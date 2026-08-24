from plugins.base_plugin.base_plugin import BasePlugin
from plugins.calendar.constants import FONT_SIZES
from utils.app_utils import get_font, resolve_path
from PIL import Image
import icalendar
import recurring_ical_events
import logging
import requests
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)

WEEKDAYS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]
MUTED_GRAY = "#999999"
DAY_BAR_COLORS = ["#3c8b64", "#2f6fce", "#5b6b7a"]

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={long}&daily=weathercode,temperature_2m_max,temperature_2m_min&current=temperature,weather_code&timezone=auto&forecast_days=3&temperature_unit=celsius"

class Agenda(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        calendar_urls = settings.get('calendarURLs[]')
        calendar_colors = settings.get('calendarColors[]')
        lat_str = settings.get('latitude')
        long_str = settings.get('longitude')

        if not calendar_urls:
            raise RuntimeError("Se requiere al menos una URL de calendario.")
        for url in calendar_urls:
            if not url.strip():
                raise RuntimeError("URL de calendario no válida.")
        if not lat_str or not long_str:
            raise RuntimeError("La latitud y la longitud son obligatorias.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone)
        current_dt = datetime.now(tz)

        today = tz.localize(datetime(current_dt.year, current_dt.month, current_dt.day))
        days = [self.fetch_agenda_day(today + timedelta(days=i), current_dt) for i in range(3)]

        start = today
        end = tz.normalize(today + timedelta(days=3))
        events = self.fetch_ics_events(calendar_urls, calendar_colors, tz, start, end)
        for event in events:
            self.assign_event_to_day(event, days, current_dt, tz)

        try:
            weather_data = self.get_open_meteo_data(float(lat_str), float(long_str))
            weather = self.parse_weather(weather_data, days)
        except Exception as e:
            logger.error(f"Open-Meteo request failed: {str(e)}")
            raise RuntimeError("Fallo en la petición a Open-Meteo, revisa los registros.")

        def draw_content(image, draw, content_box, text_color):
            self.draw_agenda(image, draw, content_box, text_color, days, weather, settings, time_format)

        return self.render_image_pil(dimensions, settings, draw_content)

    def fetch_agenda_day(self, day_start, current_dt):
        if day_start.date() == current_dt.date():
            label = "Hoy"
        elif day_start.date() == (current_dt.date() + timedelta(days=1)):
            label = "Mañana"
        else:
            label = WEEKDAYS_ES[day_start.weekday()].capitalize()
        return {"date": day_start, "label": label, "events": []}

    def assign_event_to_day(self, event, days, current_dt, tz):
        event_start = datetime.fromisoformat(event["start"])
        event_end = datetime.fromisoformat(event["end"]) if event.get("end") else None

        if event_end and event_end <= current_dt:
            return  # Already over — don't show it on any day.

        for day in days:
            day_date = day["date"].date()
            if event_end:
                # All-day end dates are exclusive per the iCalendar spec
                # (DTSTART=27 DTEND=30 covers the 27th-29th, not the 30th),
                # timed ones are inclusive of the end day.
                last_day = event_end.date() - timedelta(days=1) if event["allDay"] else event_end.date()
                covers = event_start.date() <= day_date <= last_day
            else:
                covers = event_start.date() == day_date
            if covers:
                day["events"].append(event)

    def fetch_ics_events(self, calendar_urls, colors, tz, start_range, end_range):
        parsed_events = []

        with ThreadPoolExecutor(max_workers=len(calendar_urls)) as executor:
            calendars = executor.map(self.fetch_calendar, calendar_urls)

        for cal, color in zip(calendars, colors):
            events = recurring_ical_events.of(cal).between(start_range, end_range)

            for event in events:
                all_day = False
                dtstart = event.decoded("dtstart")
                if isinstance(dtstart, datetime):
                    start = dtstart.astimezone(tz).isoformat()
                else:
                    start = tz.localize(datetime(dtstart.year, dtstart.month, dtstart.day)).isoformat()
                    all_day = True

                end = None
                if "dtend" in event:
                    dtend = event.decoded("dtend")
                    if isinstance(dtend, datetime):
                        end = dtend.astimezone(tz).isoformat()
                    else:
                        end = tz.localize(datetime(dtend.year, dtend.month, dtend.day)).isoformat()

                parsed_events.append({
                    "title": str(event.get("summary") or ""),
                    "start": start,
                    "end": end,
                    "allDay": all_day,
                    "color": color,
                })

        return parsed_events

    def fetch_calendar(self, calendar_url):
        if calendar_url.startswith("webcal://"):
            calendar_url = calendar_url.replace("webcal://", "https://")
        try:
            response = requests.get(calendar_url, timeout=30)
            response.raise_for_status()
            return icalendar.Calendar.from_ical(response.content)
        except Exception as e:
            raise RuntimeError(f"No se pudo obtener el calendario: {str(e)}")

    def get_open_meteo_data(self, lat, long):
        url = OPEN_METEO_URL.format(lat=lat, long=long)
        response = requests.get(url, timeout=30)
        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to retrieve Open-Meteo weather data: {response.content}")
            raise RuntimeError("No se han podido obtener los datos meteorológicos de Open-Meteo.")
        return response.json()

    def parse_weather(self, data, days):
        current = data.get("current", {})
        daily = data.get("daily", {})
        weather_codes = daily.get("weathercode", [])
        temp_max = daily.get("temperature_2m_max", [])
        temp_min = daily.get("temperature_2m_min", [])

        forecast = []
        for i in range(len(days)):
            code = weather_codes[i] if i < len(weather_codes) else 0
            forecast.append({
                "label": days[i]["label"],
                "icon": self.weather_icon_path(code),
                "high": round(temp_max[i]) if i < len(temp_max) else None,
                "low": round(temp_min[i]) if i < len(temp_min) else None,
            })

        return {
            "current_temperature": round(current.get("temperature", 0)),
            "current_icon": self.weather_icon_path(current.get("weather_code", 0)),
            "forecast": forecast,
        }

    def weather_icon_path(self, weather_code):
        # Reuses the built-in weather plugin's icon set instead of
        # shipping a second copy of the same PNGs.
        icon = "01d"
        if weather_code in [0]:
            icon = "01d"
        elif weather_code in [1]:
            icon = "022d"
        elif weather_code in [2]:
            icon = "02d"
        elif weather_code in [3]:
            icon = "04d"
        elif weather_code in [51, 61, 80]:
            icon = "51d"
        elif weather_code in [53, 63, 81]:
            icon = "53d"
        elif weather_code in [55, 65, 82]:
            icon = "09d"
        elif weather_code in [45]:
            icon = "50d"
        elif weather_code in [48]:
            icon = "48d"
        elif weather_code in [56, 66]:
            icon = "56d"
        elif weather_code in [57, 67]:
            icon = "57d"
        elif weather_code in [71, 85]:
            icon = "71d"
        elif weather_code in [73]:
            icon = "73d"
        elif weather_code in [75, 86]:
            icon = "13d"
        elif weather_code in [77]:
            icon = "77d"
        elif weather_code in [95, 96, 99]:
            icon = "11d"
        return resolve_path(os.path.join("plugins", "weather", "icons", f"{icon}.png"))

    def draw_agenda(self, image, draw, content_box, text_color, days, weather, settings, time_format):
        left, top, right, bottom = content_box
        height = bottom - top
        font_scale = FONT_SIZES.get(settings.get("fontSize", "normal"))

        title_font = get_font("Jost", round(height * 0.075), font_weight="bold")
        today = days[0]["date"]
        title = f"{WEEKDAYS_ES[today.weekday()].capitalize()}, {today.day} de {MONTHS_ES[today.month - 1]} de {today.year}"
        draw.text(((left + right) / 2, top), title, font=title_font, fill=text_color, anchor="ma")

        body_top = top + sum(title_font.getmetrics()) * 1.4
        body_height = bottom - body_top

        weather_width = (right - left) * 0.24
        divider_x = right - weather_width
        list_right = divider_x - body_height * 0.03

        draw.line((divider_x, body_top, divider_x, bottom), fill=MUTED_GRAY, width=1)

        self.draw_calendar_list(draw, (left, body_top, list_right, bottom), text_color, days, body_height, font_scale, time_format)
        self.draw_weather_panel(image, draw, (divider_x + body_height * 0.03, body_top, right, bottom), text_color, weather, body_height)

    def draw_calendar_list(self, draw, box, text_color, days, height, font_scale, time_format):
        left, top, right, bottom = box
        bar_font = get_font("Jost", round(height * 0.045 * font_scale), font_weight="bold")
        time_font = get_font("Jost", round(height * 0.038 * font_scale), font_weight="bold")
        title_font = get_font("Jost", round(height * 0.04 * font_scale))
        empty_font = get_font("Jost", round(height * 0.038 * font_scale))

        bar_h = round(height * 0.075 * font_scale)
        row_h = bar_h
        sample_time = "00:00 - 00:00" if time_format == "24h" else "00:00 AM - 00:00 PM"
        time_col_w = draw.textlength(sample_time, font=time_font) + height * 0.02

        y = top
        for i, day in enumerate(days):
            bar_color = DAY_BAR_COLORS[i % len(DAY_BAR_COLORS)]
            draw.rectangle((left, y, right, y + bar_h), fill=bar_color)
            draw.text(((left + right) / 2, y + bar_h / 2), self.day_bar_label(day), font=bar_font, fill="#ffffff", anchor="mm")
            y += bar_h

            if not day["events"]:
                empty_row_h = row_h * 0.9
                draw.text(((left + right) / 2, y + empty_row_h / 2), "Sin eventos", font=empty_font, fill=MUTED_GRAY, anchor="mm")
                y += empty_row_h
                continue

            for event in day["events"]:
                row_top = y
                row_center = row_top + row_h / 2

                if event["allDay"]:
                    time_label = "Todo el día"
                else:
                    start_dt = datetime.fromisoformat(event["start"])
                    time_label = self.format_time(start_dt, time_format)
                    if event.get("end"):
                        end_dt = datetime.fromisoformat(event["end"])
                        time_label += f" - {self.format_time(end_dt, time_format)}"

                draw.text((left, row_center), time_label, font=time_font, fill=text_color, anchor="lm")

                title_x = left + time_col_w
                max_title_w = right - title_x
                title = self.truncate_to_width(draw, event["title"], title_font, max_title_w)
                draw.text((title_x, row_center), title, font=title_font, fill=text_color, anchor="lm")

                y += row_h
                draw.line((left, y, right, y), fill="#e0e0e0", width=1)

    def day_bar_label(self, day):
        date = day["date"]
        date_str = f"{WEEKDAYS_ES[date.weekday()]}, {date.day} de {MONTHS_ES[date.month - 1]}"
        if day["label"] in ("Hoy", "Mañana"):
            return f"{day['label']}: {date_str}"
        return date_str.capitalize()

    def truncate_to_width(self, draw, text, font, max_width):
        if draw.textlength(text, font=font) <= max_width:
            return text
        while text and draw.textlength(text + "…", font=font) > max_width:
            text = text[:-1]
        return text + "…"

    def format_time(self, dt, time_format):
        if time_format == "24h":
            return dt.strftime("%H:%M")
        return dt.strftime("%I:%M %p").lstrip("0")

    def draw_weather_panel(self, image, draw, box, text_color, weather, height):
        left, top, right, bottom = box
        width = right - left

        temp_font = get_font("Jost", round(height * 0.09), font_weight="bold")
        icon_size = round(width * 0.5)
        temp_h = sum(temp_font.getmetrics())
        current_gap = height * 0.02
        section_gap = height * 0.06

        forecast = weather["forecast"][1:]
        label_font = get_font("Jost", round(height * 0.032), font_weight="bold")
        hilo_font = get_font("Jost", round(height * 0.03))
        row_h = height * 0.11
        small_icon_size = round(min(row_h * 0.55, width * 0.32))

        current_h = icon_size + current_gap + temp_h
        forecast_h = len(forecast) * row_h
        total_h = current_h + (section_gap + forecast_h if forecast else 0)
        block_top = top + (bottom - top - total_h) / 2

        icon_img = Image.open(weather["current_icon"]).convert("RGBA").resize((icon_size, icon_size))
        icon_x = left + (width - icon_size) / 2
        image.paste(icon_img, (round(icon_x), round(block_top)), icon_img)

        temp_y = block_top + icon_size + current_gap
        draw.text((left + width / 2, temp_y), f"{weather['current_temperature']}°", font=temp_font, fill=text_color, anchor="ma")

        if not forecast:
            return
        forecast_top = block_top + current_h + section_gap

        for i, day in enumerate(forecast):
            row_top = forecast_top + i * row_h
            row_center = row_top + row_h / 2

            icon_img = Image.open(day["icon"]).convert("RGBA").resize((small_icon_size, small_icon_size))
            image.paste(icon_img, (round(left), round(row_center - small_icon_size / 2)), icon_img)

            text_x = left + small_icon_size + width * 0.06
            line_gap = height * 0.005
            label_h = sum(label_font.getmetrics())
            hilo_h = sum(hilo_font.getmetrics())
            text_top = row_center - (label_h + line_gap + hilo_h) / 2

            draw.text((text_x, text_top), day["label"], font=label_font, fill=text_color, anchor="la")
            hilo = f"{day['high']}° / {day['low']}°"
            draw.text((text_x, text_top + label_h + line_gap), hilo, font=hilo_font, fill=MUTED_GRAY, anchor="la")
