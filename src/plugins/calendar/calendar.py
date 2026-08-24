from plugins.base_plugin.base_plugin import BasePlugin
from plugins.calendar.constants import FONT_SIZES
from utils.app_utils import get_font
from PIL import ImageColor
import icalendar
import recurring_ical_events
import logging
import requests
import calendar as cal
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)

WEEKDAY_INITIALS_ES = ["L", "M", "X", "J", "V", "S", "D"]
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]
MUTED_GRAY = "#999999"
DEFAULT_TODAY_COLOR = "#c0392b"

class Calendar(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        timezone = device_config.get_config("timezone", default="America/New_York")
        tz = pytz.timezone(timezone)
        current_dt = datetime.now(tz)

        if settings.get("mode") == "simple":
            def draw_content(image, draw, content_box, text_color):
                self.draw_simple_calendar(draw, content_box, text_color, current_dt, settings)
            return self.render_image_pil(dimensions, settings, draw_content)

        calendar_urls = settings.get('calendarURLs[]')
        calendar_colors = settings.get('calendarColors[]')
        view = settings.get("viewMode")

        if not view:
            raise RuntimeError("La vista es obligatoria.")
        elif view not in ["timeGridDay", "timeGridWeek", "dayGrid", "dayGridMonth", "listMonth"]:
            raise RuntimeError("Vista no válida.")

        if not calendar_urls:
            raise RuntimeError("Se requiere al menos una URL de calendario.")
        for url in calendar_urls:
            if not url.strip():
                raise RuntimeError("URL de calendario no válida.")

        time_format = device_config.get_config("time_format", default="12h")

        start, end = self.get_view_range(view, current_dt, settings, tz)
        logger.debug(f"Fetching events for {start} --> [{current_dt}] --> {end}")
        events = self.fetch_ics_events(calendar_urls, calendar_colors, tz, start, end)
        if not events:
            logger.warning("No events found for ics url")

        if view == 'timeGridWeek' and settings.get("displayPreviousDays") != "true":
            view = 'timeGrid'

        # FullCalendar's own contentHeight/height:'100%' measures its
        # container via JS at render time to compute row heights — this
        # works in Chromium but not in WebKitGTK (used as a fallback on
        # boards Chromium can't run on), where it reads a stale/wrong value
        # and lets content overflow uncapped. Passing a plain pixel number
        # sidesteps that measurement entirely. Matches base_plugin.html's
        # `padding: 1.5vw` on <body>, which eats into both dimensions.
        body_padding = round(dimensions[0] * 0.015)
        fc_height = dimensions[1] - 2 * body_padding

        template_params = {
            "view": view,
            "events": events,
            "current_dt": current_dt.isoformat(),
            "timezone": timezone,
            "plugin_settings": settings,
            "time_format": time_format,
            "font_scale": FONT_SIZES.get(settings.get("fontSize", "normal")),
            "fc_height": fc_height
        }

        image = self.render_image(dimensions, "calendar.html", "calendar.css", template_params)

        if not image:
            raise RuntimeError("No se pudo generar la captura, revisa los registros.")
        return image

    def fetch_ics_events(self, calendar_urls, colors, tz, start_range, end_range):
        parsed_events = []

        # Calendars are fetched over the network, not computed, so fetching
        # them concurrently avoids waiting on each one's request/timeout in turn.
        with ThreadPoolExecutor(max_workers=len(calendar_urls)) as executor:
            calendars = executor.map(self.fetch_calendar, calendar_urls)

        for cal, color in zip(calendars, colors):
            events = recurring_ical_events.of(cal).between(start_range, end_range)
            contrast_color = self.get_contrast_color(color)

            for event in events:
                start, end, all_day = self.parse_data_points(event, tz)
                parsed_event = {
                    "title": str(event.get("summary") or ""),
                    "start": start,
                    "backgroundColor": color,
                    "textColor": contrast_color,
                    "allDay": all_day
                }
                if end:
                    parsed_event['end'] = end

                parsed_events.append(parsed_event)

        return parsed_events

    def get_view_range(self, view, current_dt, settings, tz):
        # Arithmetic on a pytz-aware datetime keeps its original UTC offset
        # even if it crosses a DST change, so every date built here goes
        # through tz.localize()/tz.normalize() to stay correct year-round.
        today = tz.localize(datetime(current_dt.year, current_dt.month, current_dt.day))
        start = today
        if view == "timeGridDay":
            end = tz.normalize(start + timedelta(days=1))
        elif view == "timeGridWeek":
            if settings.get("displayPreviousDays") == "true":
                # Weeks always start on Monday.
                start = tz.normalize(today - timedelta(days=current_dt.weekday()))
            end = tz.normalize(start + timedelta(days=7))
        elif view == "dayGrid":
            start = tz.normalize(today - timedelta(weeks=1))
            end = tz.normalize(today + timedelta(weeks=int(settings.get("displayWeeks") or 4)))
        elif view == "dayGridMonth":
            month_start = tz.localize(datetime(current_dt.year, current_dt.month, 1))
            start = tz.normalize(month_start - timedelta(weeks=1))
            end = tz.normalize(month_start + timedelta(weeks=6))
        elif view == "listMonth":
            end = tz.normalize(start + timedelta(days=int(settings.get("displayDays") or 7)))
        return start, end

    def parse_data_points(self, event, tz):
        all_day = False
        dtstart = event.decoded("dtstart")
        if isinstance(dtstart, datetime):
            start = dtstart.astimezone(tz).isoformat()
        else:
            start = dtstart.isoformat()
            all_day = True

        end = None
        if "dtend" in event:
            dtend = event.decoded("dtend")
            if isinstance(dtend, datetime):
                end = dtend.astimezone(tz).isoformat()
            else:
                end = dtend.isoformat()
        elif "duration" in event:
            duration = event.decoded("duration")
            end = (dtstart + duration).isoformat()
        return start, end, all_day

    def fetch_calendar(self, calendar_url):
        # workaround for webcal urls
        if calendar_url.startswith("webcal://"):
            calendar_url = calendar_url.replace("webcal://", "https://")
        try:
            response = requests.get(calendar_url, timeout=30)
            response.raise_for_status()
            # Pass raw bytes rather than response.text: without an explicit
            # charset header, requests guesses ISO-8859-1 for text/* content,
            # mangling accents even though the iCalendar spec mandates UTF-8.
            return icalendar.Calendar.from_ical(response.content)
        except Exception as e:
            raise RuntimeError(f"No se pudo obtener el calendario: {str(e)}")

    def get_contrast_color(self, color):
        """
        Returns '#000000' (black) or '#ffffff' (white) depending on the contrast
        against the given color.
        """
        r, g, b = ImageColor.getrgb(color)
        # YIQ formula to estimate brightness
        yiq = (r * 299 + g * 587 + b * 114) / 1000

        return '#000000' if yiq >= 150 else '#ffffff'

    def draw_simple_calendar(self, draw, content_box, text_color, current_dt, settings):
        left, top, right, bottom = content_box
        width = right - left
        height = bottom - top
        font_scale = FONT_SIZES.get(settings.get("fontSize", "normal"))
        today_color = settings.get("nowIndicatorColor") or DEFAULT_TODAY_COLOR

        month_font = get_font("Jost", round(height * 0.11 * font_scale), font_weight="bold")
        year_font = get_font("Jost", round(height * 0.075 * font_scale))
        weekday_font = get_font("Jost", round(height * 0.04 * font_scale))
        day_font = get_font("Jost", round(height * 0.06 * font_scale))

        # Header: month name and year share one baseline, side by side.
        month_name = MONTHS_ES[current_dt.month - 1].upper()
        year_str = str(current_dt.year)
        _, month_top, _, month_bottom = draw.textbbox((0, 0), month_name, font=month_font)
        header_baseline = top + (month_bottom - month_top)
        draw.text((left, header_baseline), month_name, font=month_font, fill=text_color, anchor="ls")
        month_width = draw.textlength(month_name, font=month_font)
        draw.text((left + month_width + width * 0.02, header_baseline), year_str, font=year_font, fill=MUTED_GRAY, anchor="ls")

        # Weekday initials row, evenly spaced across the 7 columns.
        col_width = width / 7
        weekday_y = header_baseline + height * 0.06
        for col, label in enumerate(WEEKDAY_INITIALS_ES):
            x = left + col * col_width + col_width / 2
            draw.text((x, weekday_y), label, font=weekday_font, fill=MUTED_GRAY, anchor="ma")

        # Day grid, one row per calendar week (Monday-first, matching the
        # rest of the plugin), blank cells for days outside the month.
        weeks = cal.Calendar(firstweekday=cal.MONDAY).monthdayscalendar(current_dt.year, current_dt.month)
        grid_top = weekday_y + height * 0.07
        row_height = (bottom - grid_top) / len(weeks)
        circle_radius = min(col_width, row_height) * 0.38

        for row, week in enumerate(weeks):
            y = grid_top + row * row_height + row_height / 2
            for col, day in enumerate(week):
                if day == 0:
                    continue
                x = left + col * col_width + col_width / 2
                if day == current_dt.day:
                    draw.circle((x, y), circle_radius, fill=today_color)
                    draw.text((x, y), str(day), font=day_font, fill="#ffffff", anchor="mm")
                else:
                    draw.text((x, y), str(day), font=day_font, fill=text_color, anchor="mm")
