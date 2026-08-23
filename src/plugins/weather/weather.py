from plugins.base_plugin.base_plugin import BasePlugin
from utils.app_utils import get_font
from PIL import Image
import requests
import logging
from datetime import datetime, timedelta, date
from astral import moon
import pytz
import math

logger = logging.getLogger(__name__)
        
def get_moon_phase_name(phase_age: float) -> str:
    """Determines the name of the lunar phase based on the age of the moon."""
    PHASES_THRESHOLDS = [
        (1.0, "newmoon"),
        (7.0, "waxingcrescent"),
        (8.5, "firstquarter"),
        (14.0, "waxinggibbous"),
        (15.5, "fullmoon"),
        (22.0, "waninggibbous"),
        (23.5, "lastquarter"),
        (29.0, "waningcrescent"),
    ]

    for threshold, phase_name in PHASES_THRESHOLDS:
        if phase_age <= threshold:
            return phase_name  
    return "newmoon"

def parse_open_meteo_dt(time_str, tz):
    """Open-Meteo (with timezone=auto) returns naive local-time strings for the
    queried location — already in `tz`, not the server's own clock — so they
    must be localized directly rather than converted with .astimezone(tz),
    which would misinterpret them if the server's system timezone differs
    from the configured display timezone.
    """
    return tz.localize(datetime.fromisoformat(time_str))

WEEKDAYS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
WEEKDAYS_ES_LONG = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]

TEMPERATURE_UNIT = "°C"
SPEED_UNIT = "m/s"
DISTANCE_UNIT = "km"

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={long}&hourly=weather_code,temperature_2m,precipitation,precipitation_probability,relative_humidity_2m,surface_pressure,visibility&daily=weathercode,temperature_2m_max,temperature_2m_min,sunrise,sunset&current=temperature,windspeed,winddirection,is_day,precipitation,weather_code,apparent_temperature&timezone=auto&models=best_match&forecast_days={forecast_days}&temperature_unit=celsius&wind_speed_unit=ms&precipitation_unit=mm"
OPEN_METEO_AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={long}&hourly=european_aqi,uv_index,uv_index_clear_sky&timezone=auto"

class Weather(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        lat_str = settings.get('latitude')
        long_str = settings.get('longitude')
        if not lat_str or not long_str:
            raise RuntimeError("La latitud y la longitud son obligatorias.")
        lat = float(lat_str)
        long = float(long_str)

        title = settings.get('customTitle', '')

        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone)

        try:
            forecast_days = 7
            weather_data = self.get_open_meteo_data(lat, long, forecast_days + 1)
            aqi_data = self.get_open_meteo_air_quality(lat, long)
            data = self.parse_open_meteo_data(weather_data, aqi_data, tz, time_format, lat)
        except Exception as e:
            logger.error(f"Open-Meteo request failed: {str(e)}")
            raise RuntimeError("Fallo en la petición a Open-Meteo, revisa los registros.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        now = datetime.now(tz)
        if time_format == "24h":
            last_refresh_time = now.strftime("%Y-%m-%d %H:%M")
        else:
            last_refresh_time = now.strftime("%Y-%m-%d %I:%M %p")

        def draw_content(image, draw, content_box, text_color):
            self.draw_weather_dashboard(image, draw, content_box, text_color, title, data, settings, last_refresh_time)

        return self.render_image_pil(dimensions, settings, draw_content)

    def draw_weather_dashboard(self, image, draw, content_box, text_color, title, data, settings, last_refresh_time):
        left, top, right, bottom = content_box
        width = right - left
        height = bottom - top

        show_refresh = settings.get('displayRefreshTime') == 'true'
        show_metrics = settings.get('displayMetrics') == 'true'
        show_graph = settings.get('displayGraph') == 'true'
        show_forecast = settings.get('displayForecast') == 'true'
        show_rain = settings.get('displayRain') == 'true'
        show_graph_icons = settings.get('displayGraphIcons') == 'true'
        show_moon = settings.get('moonPhase') == 'true'
        forecast_days = int(settings.get('forecastDays') or 7)
        icon_step = int(settings.get('graphIconStep') or 2)

        if show_refresh:
            refresh_font = get_font("Jost", max(1, round(height * 0.03)), font_weight="bold")
            draw.text((right, top), f"Última actualización: {last_refresh_time}", font=refresh_font, fill=text_color, anchor="ra")

        gap = round(height * 0.02)
        chart_h = round(height * 0.24) if show_graph else 0
        forecast_h = round(height * 0.24) if show_forecast else 0
        header_h = round(height * 0.15)

        today_h = height - header_h - gap
        if show_graph:
            today_h -= chart_h + gap
        if show_forecast:
            today_h -= forecast_h + gap

        y = top
        self.draw_weather_header(draw, (left, y, right, y + header_h), text_color, title, data['current_date'])
        y += header_h + gap

        self.draw_today_row(image, draw, (left, y, right, y + today_h), text_color, data, show_metrics)
        y += today_h

        if show_graph:
            y += gap
            self.draw_hourly_chart(image, draw, (left, y, right, y + chart_h), text_color, data['hourly_forecast'], show_rain, show_graph_icons, icon_step)
            y += chart_h

        if show_forecast:
            y += gap
            self.draw_forecast_row(image, draw, (left, y, right, y + forecast_h), text_color, data['forecast'][1:forecast_days + 1], show_moon)

    def draw_weather_header(self, draw, box, text_color, title, current_date):
        left, top, right, bottom = box
        width = right - left
        height = bottom - top
        center_x = left + width / 2

        title_font = get_font("Jost", max(1, round(height * 0.5)), font_weight="bold")
        date_font = get_font("Jost", max(1, round(height * 0.3)))

        if title:
            title_h = sum(title_font.getmetrics())
            date_h = sum(date_font.getmetrics())
            y = bottom - title_h - date_h
            draw.text((center_x, y), title, font=title_font, fill=text_color, anchor="ma")
            y += title_h
            draw.text((center_x, y), current_date, font=date_font, fill=text_color, anchor="ma")
        else:
            date_h = sum(date_font.getmetrics())
            draw.text((center_x, bottom - date_h), current_date, font=date_font, fill=text_color, anchor="ma")

    def draw_today_row(self, image, draw, box, text_color, data, show_metrics):
        left, top, right, bottom = box
        width = right - left
        height = bottom - top

        if show_metrics:
            icon_col_w = round(width * 0.22)
            temp_col_w = round(width * 0.28)
        else:
            icon_col_w = round(width * 0.35)
            temp_col_w = width - icon_col_w

        description_font = get_font("Jost", max(1, round(height * 0.12)), font_weight="bold")
        description_h = sum(description_font.getmetrics())

        icon_size = round(min(icon_col_w, height - description_h) * 0.9)
        icon_center_x = left + icon_col_w / 2
        icon_x = round(icon_center_x - icon_size / 2)
        icon_y = round(top + (height - description_h - icon_size) / 2)
        icon_img = Image.open(data['current_day_icon']).convert("RGBA").resize((icon_size, icon_size))
        image.paste(icon_img, (icon_x, icon_y), icon_img)
        draw.text((icon_center_x, icon_y + icon_size), data['current_description'], font=description_font, fill=text_color, anchor="ma")

        temp_center_x = left + icon_col_w + temp_col_w / 2
        temp_font = get_font("Jost", max(1, round(height * 0.42)))
        unit_font = get_font("Jost", max(1, round(height * 0.17)))
        feels_font = get_font("Jost", max(1, round(height * 0.11)))
        minmax_font = get_font("Jost", max(1, round(height * 0.13)))

        temp_h = sum(temp_font.getmetrics())
        feels_h = sum(feels_font.getmetrics())
        minmax_h = sum(minmax_font.getmetrics())
        block_h = temp_h + feels_h + minmax_h
        y = top + (height - block_h) / 2

        temp_text = data['current_temperature']
        unit_text = data['temperature_unit']
        temp_w = draw.textlength(temp_text, font=temp_font)
        unit_w = draw.textlength(unit_text, font=unit_font)
        x = temp_center_x - (temp_w + unit_w) / 2
        draw.text((x, y), temp_text, font=temp_font, fill=text_color, anchor="la")
        draw.text((x + temp_w, y), unit_text, font=unit_font, fill=text_color, anchor="la")
        y += temp_h

        draw.text((temp_center_x, y), f"Sensación {data['feels_like']}°", font=feels_font, fill=text_color, anchor="ma")
        y += feels_h

        today_forecast = data['forecast'][0] if data['forecast'] else {"high": "-", "low": "-"}
        draw.text((temp_center_x, y), f"{today_forecast['high']}° / {today_forecast['low']}°", font=minmax_font, fill=text_color, anchor="ma")

        if show_metrics:
            metrics_box = (left + icon_col_w + temp_col_w, top, right, bottom)
            self.draw_data_points_grid(image, draw, metrics_box, text_color, data['data_points'])

    def draw_data_points_grid(self, image, draw, box, text_color, data_points):
        left, top, right, bottom = box
        width = right - left
        height = bottom - top
        cols = 2
        rows = math.ceil(len(data_points) / cols)
        cell_w = width / cols
        cell_h = height / rows

        label_font = get_font("Jost", max(1, round(cell_h * 0.26)))
        measure_font = get_font("Jost", max(1, round(cell_h * 0.42)), font_weight="bold")
        unit_font = get_font("Jost", max(1, round(cell_h * 0.26)))

        for i, dp in enumerate(data_points):
            col, row = i % cols, i // cols
            cell_left = left + col * cell_w
            cell_top = top + row * cell_h

            icon_size = round(min(cell_w * 0.22, cell_h * 0.75))
            icon_img = Image.open(dp['icon']).convert("RGBA").resize((icon_size, icon_size))
            icon_x = round(cell_left + cell_w * 0.05)
            icon_y = round(cell_top + (cell_h - icon_size) / 2)
            image.paste(icon_img, (icon_x, icon_y), icon_img)

            text_left = icon_x + icon_size + round(cell_w * 0.060)

            label_h = sum(label_font.getmetrics())
            measure_h = sum(measure_font.getmetrics())
            y = cell_top + (cell_h - label_h - measure_h) / 2

            draw.text((text_left, y), dp['label'], font=label_font, fill=text_color, anchor="la")
            y += label_h

            unit_gap = round(cell_w * 0.015)
            measure_text = str(dp['measurement'])
            unit_text = dp.get('unit') or ''
            arrow_text = dp.get('arrow') or ''
            baseline_y = y + measure_font.getmetrics()[0]
            x = text_left
            draw.text((x, y), measure_text, font=measure_font, fill=text_color, anchor="la")
            measure_w = draw.textlength(measure_text, font=measure_font)
            x += measure_w
            if unit_text:
                x += unit_gap
                draw.text((x, baseline_y), unit_text, font=unit_font, fill=text_color, anchor="ls")
                x += draw.textlength(unit_text, font=unit_font)
            if arrow_text:
                x += unit_gap
                draw.text((x, baseline_y), arrow_text, font=measure_font, fill=text_color, anchor="ls")

    def draw_hourly_chart(self, image, draw, box, text_color, hourly_forecast, show_rain, show_graph_icons, icon_step):
        left, top, right, bottom = box
        width = right - left
        height = bottom - top
        n = len(hourly_forecast)
        if n == 0:
            return

        unit = min(width, height) / 100
        label_font = get_font("Jost", max(1, round(height * 0.09)))

        temps = [h['temperature'] for h in hourly_forecast]
        min_temp, max_temp = min(temps), max(temps)
        if min_temp == max_temp:
            max_temp = min_temp + 1

        left_margin = round(draw.textlength(f"{max_temp}°", font=label_font)) + round(unit * 3)
        right_margin = round(draw.textlength("100%", font=label_font)) + round(unit * 3)

        label_h = sum(label_font.getmetrics())
        top_margin = label_h + round(unit * 1.5)
        axis_bottom_h = label_h + round(unit * 0.5)
        hour_label_h = label_h + round(unit * 1.5)
        bottom_margin = axis_bottom_h + hour_label_h
        icon_margin = round(height * 0.22) if show_graph_icons else 0

        plot_left = left + left_margin
        plot_right = right - right_margin
        plot_top = top + top_margin
        plot_bottom = bottom - bottom_margin - icon_margin
        plot_width = plot_right - plot_left
        plot_height = plot_bottom - plot_top
        if plot_width <= 0 or plot_height <= 0:
            return

        def x_for(i):
            return plot_left + plot_width * i / max(1, n - 1)

        def y_for_temp(t):
            return plot_bottom - (t - min_temp) / (max_temp - min_temp) * plot_height

        # Precipitation probability bars
        bar_color = (26, 111, 176, 200)
        bar_width = max(1, plot_width / n * 0.9)
        for i, h in enumerate(hourly_forecast):
            pct = h.get('precipitation') or 0
            bar_h = pct * plot_height
            if bar_h <= 0:
                continue
            x = x_for(i)
            bar_top_y = plot_bottom - bar_h
            draw.rectangle((x - bar_width / 2, bar_top_y, x + bar_width / 2, plot_bottom), fill=bar_color)

        # Temperature line (envelope only, no fill, so it doesn't compete
        # visually with the precipitation bars underneath it)
        points = [(x_for(i), y_for_temp(h['temperature'])) for i, h in enumerate(hourly_forecast)]
        draw.line(points, fill=(241, 122, 36, 255), width=max(2, round(unit * 0.4)), joint="curve")

        # Axis labels live in their own reserved margins, above/below the
        # plot area, so bars/line never cover them.
        axis_gap = round(unit * 0.5)
        draw.text((left, top), f"{max_temp}°", font=label_font, fill=text_color, anchor="la")
        draw.text((left, plot_bottom + axis_gap), f"{min_temp}°", font=label_font, fill=text_color, anchor="la")
        draw.text((right, top), "100%", font=label_font, fill=text_color, anchor="ra")
        draw.text((right, plot_bottom + axis_gap), "0%", font=label_font, fill=text_color, anchor="ra")

        # Hour labels, skipping enough to avoid overlap
        label_w = draw.textlength("00:00", font=label_font)
        max_labels = max(1, int(plot_width / (label_w * 2.2)))
        label_step = max(1, round(n / max_labels))
        hour_label_y = plot_bottom + axis_bottom_h + axis_gap
        for i in range(0, n, label_step):
            draw.text((x_for(i), hour_label_y), hourly_forecast[i]['time'], font=label_font, fill=text_color, anchor="ma")

        if show_rain:
            rain_font = get_font("Jost", max(1, round(height * 0.07)))
            threshold = 0.09
            for i, h in enumerate(hourly_forecast):
                rain_mm = h.get('rain') or 0
                if rain_mm > threshold:
                    pct = h.get('precipitation') or 0
                    bar_top_y = plot_bottom - pct * plot_height
                    draw.text((x_for(i), bar_top_y - round(unit)), f"{rain_mm:.2f}mm", font=rain_font, fill=text_color, anchor="ms")

        if show_graph_icons:
            icon_size = round(icon_margin * 0.8)
            if icon_size > 0:
                icon_cache = {}
                icon_y = round(plot_bottom + bottom_margin + round(unit))
                for i in range(0, n, max(1, icon_step)):
                    icon_path = hourly_forecast[i]['icon']
                    icon_img = icon_cache.get(icon_path)
                    if icon_img is None:
                        icon_img = Image.open(icon_path).convert("RGBA").resize((icon_size, icon_size))
                        icon_cache[icon_path] = icon_img
                    icon_x = round(x_for(i) - icon_size / 2)
                    image.paste(icon_img, (icon_x, icon_y), icon_img)

    def draw_forecast_row(self, image, draw, box, text_color, forecast, show_moon):
        left, top, right, bottom = box
        width = right - left
        height = bottom - top
        n = len(forecast)
        if n == 0:
            return

        gap = round(width * 0.015)
        card_w = (width - gap * (n - 1)) / n
        border_radius = round(min(card_w, height) * 0.08)
        border_width = max(1, round(width * 0.0015))

        day_font = get_font("Jost", max(1, round(height * 0.13)), font_weight="bold")
        temp_font = get_font("Jost", max(1, round(height * 0.1)))
        moon_font = get_font("Jost", max(1, round(height * 0.09)))

        for i, day in enumerate(forecast):
            card_left = left + i * (card_w + gap)
            card_right = card_left + card_w
            center_x = card_left + card_w / 2
            draw.rounded_rectangle((card_left, top, card_right, bottom), radius=border_radius, outline=text_color, width=border_width)

            pad = round(card_w * 0.08)
            inner_left = card_left + pad
            inner_right = card_right - pad
            inner_w = inner_right - inner_left

            y = top + pad
            draw.text((center_x, y), day['day'], font=day_font, fill=text_color, anchor="ma")
            y += sum(day_font.getmetrics())

            icon_size = round(min(inner_w, height * 0.32))
            icon_img = Image.open(day['icon']).convert("RGBA").resize((icon_size, icon_size))
            image.paste(icon_img, (round(center_x - icon_size / 2), round(y)), icon_img)
            y += icon_size

            draw.text((center_x, y), f"{day['high']}° / {day['low']}°", font=temp_font, fill=text_color, anchor="ma")
            y += sum(temp_font.getmetrics())

            if show_moon:
                y += round(height * 0.02)
                draw.line((inner_left, y, inner_right, y), fill=text_color, width=1)
                y += round(height * 0.03)
                moon_icon_size = round(height * 0.14)
                moon_icon = Image.open(day['moon_phase_icon']).convert("RGBA").resize((moon_icon_size, moon_icon_size))
                moon_text = f"{day['moon_phase_pct']} %"
                moon_text_w = draw.textlength(moon_text, font=moon_font)
                total_w = moon_icon_size + round(card_w * 0.03) + moon_text_w
                x = center_x - total_w / 2
                image.paste(moon_icon, (round(x), round(y)), moon_icon)
                draw.text((x + moon_icon_size + round(card_w * 0.03), y + moon_icon_size / 2), moon_text, font=moon_font, fill=text_color, anchor="lm")

    def parse_open_meteo_data(self, weather_data, aqi_data, tz, time_format, lat):
        current = weather_data.get("current", {})
        daily = weather_data.get('daily', {})
        dt = parse_open_meteo_dt(current.get('time'), tz) if current.get('time') else datetime.now(tz)
        weather_code = current.get("weather_code", 0)
        is_day = current.get("is_day", 1)
        current_icon = self.map_weather_code_to_icon(weather_code, is_day)

        data = {
            "current_date": f"{WEEKDAYS_ES_LONG[dt.weekday()]}, {dt.day} de {MONTHS_ES[dt.month - 1]}",
            "current_day_icon": self.get_plugin_dir(f'icons/{current_icon}.png'),
            "current_description": self.map_weather_code_to_description(weather_code),
            "current_temperature": str(round(current.get("temperature", 0))),
            "feels_like": str(round(current.get("apparent_temperature", current.get("temperature", 0)))),
            "temperature_unit": TEMPERATURE_UNIT,
            "time_format": time_format
        }

        data['forecast'] = self.parse_open_meteo_forecast(weather_data.get('daily', {}), tz, is_day, lat)
        data['data_points'] = self.parse_open_meteo_data_points(weather_data, aqi_data, tz, time_format)

        data['hourly_forecast'] = self.parse_open_meteo_hourly(weather_data.get('hourly', {}), tz, time_format, daily.get('sunrise', []), daily.get('sunset', []))
        return data

    def map_weather_code_to_icon(self, weather_code, is_day):

        icon = "01d" # Default to clear day icon
        
        if weather_code in [0]:   # Clear sky
            icon = "01d"
        elif weather_code in [1]: # Mainly clear
            icon = "022d"
        elif weather_code in [2]: # Partly cloudy
            icon = "02d"
        elif weather_code in [3]: # Overcast
            icon = "04d"
        elif weather_code in [51, 61, 80]: # Drizzle, showers, rain: Light
            icon = "51d"          
        elif weather_code in [53, 63, 81]: # Drizzle, showers, rain: Moderatr
            icon = "53d"
        elif weather_code in [55, 65, 82]: # Drizzle, showers, rain: Heavy
            icon = "09d"
        elif weather_code in [45]: # Fog
            icon = "50d"                       
        elif weather_code in [48]: # Icy fog
            icon = "48d"
        elif weather_code in [56, 66]: # Light freezing Drizzle
            icon = "56d"            
        elif weather_code in [57, 67]: # Freezing Drizzle
            icon = "57d"            
        elif weather_code in [71, 85]: # Snow fall: Slight
            icon = "71d"
        elif weather_code in [73]:     # Snow fall: Moderate
            icon = "73d"
        elif weather_code in [75, 86]: # Snow fall: Heavy
            icon = "13d"
        elif weather_code in [77]:     # Snow grain
            icon = "77d"
        elif weather_code in [95]: # Thunderstorm
            icon = "11d"
        elif weather_code in [96, 99]: # Thunderstorm with slight and heavy hail
            icon = "11d"

        if is_day == 0:
            if icon == "01d":
                icon = "01n"      # Clear sky night
            elif icon == "022d":
                icon = "022n"     # Mainly clear night
            elif icon == "02d":
                icon = "02n"      # Partly cloudy night                
            elif icon == "10d":
                icon = "10n"      # Rain night

        return icon

    def map_weather_code_to_description(self, weather_code):
        if weather_code in [0]:   # Clear sky
            return "Cielo despejado"
        elif weather_code in [1]: # Mainly clear
            return "Mayormente despejado"
        elif weather_code in [2]: # Partly cloudy
            return "Parcialmente nublado"
        elif weather_code in [3]: # Overcast
            return "Nublado"
        elif weather_code in [51, 61, 80]: # Drizzle, showers, rain: Light
            return "Lluvia ligera"
        elif weather_code in [53, 63, 81]: # Drizzle, showers, rain: Moderate
            return "Lluvia moderada"
        elif weather_code in [55, 65, 82]: # Drizzle, showers, rain: Heavy
            return "Lluvia intensa"
        elif weather_code in [45]: # Fog
            return "Niebla"
        elif weather_code in [48]: # Icy fog
            return "Niebla helada"
        elif weather_code in [56, 66]: # Light freezing drizzle
            return "Llovizna helada ligera"
        elif weather_code in [57, 67]: # Freezing drizzle
            return "Llovizna helada"
        elif weather_code in [71, 85]: # Snow fall: Slight
            return "Nieve ligera"
        elif weather_code in [73]:     # Snow fall: Moderate
            return "Nieve moderada"
        elif weather_code in [75, 86]: # Snow fall: Heavy
            return "Nieve intensa"
        elif weather_code in [77]:     # Snow grain
            return "Granos de nieve"
        elif weather_code in [95]: # Thunderstorm
            return "Tormenta"
        elif weather_code in [96, 99]: # Thunderstorm with slight and heavy hail
            return "Tormenta con granizo"
        return "Cielo despejado"

    def get_moon_phase_icon_path(self, phase_name: str, lat: float) -> str:
        """Determines the path to the moon icon, inverting it if the location is in the Southern Hemisphere."""
        # Waxing, Waning, First and Last quarter phases are inverted between hemispheres.
        if lat < 0: # Southern Hemisphere
            if phase_name == "waxingcrescent":
                phase_name = "waningcrescent"
            elif phase_name == "waxinggibbous":
                phase_name = "waninggibbous"
            elif phase_name == "waningcrescent":
                phase_name = "waxingcrescent"
            elif phase_name == "waninggibbous":
                phase_name = "waxinggibbous"
            elif phase_name == "firstquarter":
                phase_name = "lastquarter"
            elif phase_name == "lastquarter":
                phase_name = "firstquarter"
        
        return self.get_plugin_dir(f"icons/{phase_name}.png")

    def parse_open_meteo_forecast(self, daily_data, tz, is_day, lat):
        """
        Parse the daily forecast from Open-Meteo API and calculate moon phase and illumination using the local 'astral' library.
        """
        times = daily_data.get('time', [])
        weather_codes = daily_data.get('weathercode', [])
        temp_max = daily_data.get('temperature_2m_max', [])
        temp_min = daily_data.get('temperature_2m_min', [])

        forecast = []

        for i in range(0, len(times)): 
            dt = parse_open_meteo_dt(times[i], tz)
            day_label = WEEKDAYS_ES[dt.weekday()]

            code = weather_codes[i] if i < len(weather_codes) else 0
            weather_icon = self.map_weather_code_to_icon(code, is_day=1)
            weather_icon_path = self.get_plugin_dir(f"icons/{weather_icon}.png")

            timestamp = int(dt.replace(hour=12, minute=0, second=0).timestamp())
            target_date: date = dt.date() + timedelta(days=1)

            try:
                phase_age = moon.phase(target_date)
                phase_name_north_hemi = get_moon_phase_name(phase_age)
                LUNAR_CYCLE_DAYS = 29.530588853
                phase_fraction = phase_age / LUNAR_CYCLE_DAYS
                illum_pct = (1 - math.cos(2 * math.pi * phase_fraction)) / 2 * 100
            except Exception as e:
                logger.error(f"Error calculating moon phase for {target_date}: {e}")
                illum_pct = 0
                phase_name_north_hemi = "newmoon"
            moon_icon_path = self.get_moon_phase_icon_path(phase_name_north_hemi, lat)

            forecast.append({
                "day": day_label,
                "high": int(temp_max[i]) if i < len(temp_max) else 0,
                "low": int(temp_min[i]) if i < len(temp_min) else 0,
                "icon": weather_icon_path,
                "moon_phase_pct": f"{illum_pct:.0f}",
                "moon_phase_icon": moon_icon_path
            })

        return forecast

    def parse_open_meteo_hourly(self, hourly_data, tz, time_format, sunrises, sunsets):
        hourly = []
        times = hourly_data.get('time', [])
        temperatures = hourly_data.get('temperature_2m', [])
        precipitation_probabilities = hourly_data.get('precipitation_probability', [])
        rain = hourly_data.get('precipitation', [])
        codes = hourly_data.get('weather_code', [])
        
        sun_map = {}
        for sr_s, ss_s in zip(sunrises, sunsets):
            sr_dt = parse_open_meteo_dt(sr_s, tz)
            ss_dt = parse_open_meteo_dt(ss_s, tz)
            sun_map[sr_dt.date()] = (sr_dt, ss_dt)
        
        current_time_in_tz = datetime.now(tz)
        start_index = 0
        for i, time_str in enumerate(times):
            try:
                dt_hourly = parse_open_meteo_dt(time_str, tz)
                if dt_hourly.date() == current_time_in_tz.date() and dt_hourly.hour >= current_time_in_tz.hour:
                    start_index = i
                    break
                if dt_hourly.date() > current_time_in_tz.date():
                    break
            except ValueError:
                logger.warning(f"Could not parse time string {time_str} in hourly data.")
                continue

        sliced_times = times[start_index:]
        sliced_temperatures = temperatures[start_index:]
        sliced_precipitation_probabilities = precipitation_probabilities[start_index:]
        sliced_rain = rain[start_index:]
        sliced_codes = codes[start_index:]

        for i in range(min(24, len(sliced_times))):
            dt = parse_open_meteo_dt(sliced_times[i], tz)
            sunrise, sunset = sun_map.get(dt.date(), (None, None))
            is_day = 0
            if sunrise and sunset:
                is_day = 1 if sunrise <= dt < sunset else 0
            code = sliced_codes[i] if i < len(sliced_codes) else 0
            icon_name = self.map_weather_code_to_icon(code, is_day)
            hour_forecast = {
                "time": self.format_time(dt, time_format, True),
                "temperature": int(sliced_temperatures[i]) if i < len(sliced_temperatures) else 0,
                "precipitation": (sliced_precipitation_probabilities[i] / 100) if i < len(sliced_precipitation_probabilities) else 0,
                "rain": (sliced_rain[i]) if i < len(sliced_rain) else 0,
                "icon": self.get_plugin_dir(f"icons/{icon_name}.png")
            }
            hourly.append(hour_forecast)
        return hourly

    def parse_open_meteo_data_points(self, weather_data, aqi_data, tz, time_format):
        """Parses current data points from Open-Meteo API response."""
        data_points = []
        daily_data = weather_data.get('daily', {})
        current_data = weather_data.get('current', {})
        hourly_data = weather_data.get('hourly', {})

        current_time = datetime.now(tz)

        # Sunrise
        sunrise_times = daily_data.get('sunrise', [])
        if sunrise_times:
            sunrise_dt = parse_open_meteo_dt(sunrise_times[0], tz)
            data_points.append({
                "label": "Amanecer",
                "measurement": self.format_time(sunrise_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunrise_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunrise.png')
            })
        else:
            logger.error(f"Sunrise not found in Open-Meteo response, this is expected for polar areas in midnight sun and polar night periods.")

        # Sunset
        sunset_times = daily_data.get('sunset', [])
        if sunset_times:
            sunset_dt = parse_open_meteo_dt(sunset_times[0], tz)
            data_points.append({
                "label": "Atardecer",
                "measurement": self.format_time(sunset_dt, time_format, include_am_pm=False),
                "unit": "" if time_format == "24h" else sunset_dt.strftime('%p'),
                "icon": self.get_plugin_dir('icons/sunset.png')
            })
        else:
            logger.error(f"Sunset not found in Open-Meteo response, this is expected for polar areas in midnight sun and polar night periods.")

        # Wind
        wind_speed = current_data.get("windspeed", 0)
        wind_deg = current_data.get("winddirection", 0)
        wind_arrow = self.get_wind_arrow(wind_deg)
        wind_unit = SPEED_UNIT
        data_points.append({
            "label": "Viento", "measurement": wind_speed, "unit": wind_unit,
            "icon": self.get_plugin_dir('icons/wind.png'), "arrow": wind_arrow
        })

        # humidity, pressure and visibility all share weather_data's hourly
        # time array, and UV index/AQI both share aqi_data's \u2014 find each
        # array's "current hour" index once instead of re-parsing it per field.
        weather_hour_index = self.find_current_hour_index(hourly_data.get('time', []), tz, current_time)
        aqi_hour_index = self.find_current_hour_index(aqi_data.get('hourly', {}).get('time', []), tz, current_time)

        # Humidity
        humidity_values = hourly_data.get('relative_humidity_2m', [])
        current_humidity = int(humidity_values[weather_hour_index]) if weather_hour_index is not None else "N/A"
        data_points.append({
            "label": "Humedad", "measurement": current_humidity, "unit": '%',
            "icon": self.get_plugin_dir('icons/humidity.png')
        })

        # Pressure
        pressure_values = hourly_data.get('surface_pressure', [])
        current_pressure = int(pressure_values[weather_hour_index]) if weather_hour_index is not None else "N/A"
        data_points.append({
            "label": "Presión", "measurement": current_pressure, "unit": 'hPa',
            "icon": self.get_plugin_dir('icons/pressure.png')
        })

        # UV Index
        uv_index_values = aqi_data.get('hourly', {}).get('uv_index', [])
        current_uv_index = uv_index_values[aqi_hour_index] if aqi_hour_index is not None else "N/A"
        data_points.append({
            "label": "Índice UV", "measurement": current_uv_index, "unit": '',
            "icon": self.get_plugin_dir('icons/uvi.png')
        })

        # Visibility
        visibility_values = hourly_data.get('visibility', [])
        visibility_conversion = 0.001  # m to km
        visibility_max = 10.  # km
        if weather_hour_index is None:
            visibility_str = "N/A"
        else:
            current_visibility = visibility_values[weather_hour_index] * visibility_conversion
            visibility_str = f"{current_visibility:.1f}"
            if current_visibility >= visibility_max:
                visibility_str = u"\u2265" + visibility_str
        data_points.append({
            "label": "Visibilidad",
            "measurement": visibility_str,
            "unit": DISTANCE_UNIT,
            "icon": self.get_plugin_dir('icons/visibility.png')
        })

        # Air Quality
        aqi_values = aqi_data.get('hourly', {}).get('european_aqi', [])
        current_aqi = round(aqi_values[aqi_hour_index], 1) if aqi_hour_index is not None else "N/A"
        scale = ""
        if current_aqi and current_aqi != "N/A":
            scale = ["Buena","Aceptable","Moderada","Mala","Muy mala","Pésima"][min(int(current_aqi//20), 5)]
        data_points.append({
            "label": "Calidad del aire", "measurement": current_aqi,
            "unit": scale, "icon": self.get_plugin_dir('icons/aqi.png')
        })

        return data_points

    def find_current_hour_index(self, times, tz, current_time):
        for i, time_str in enumerate(times):
            try:
                if parse_open_meteo_dt(time_str, tz).hour == current_time.hour:
                    return i
            except ValueError:
                logger.warning(f"Could not parse time string {time_str}.")
                continue
        return None

    def get_wind_arrow(self, wind_deg: float) -> str:
        DIRECTIONS = [
            ("↓", 22.5),    # North (N)
            ("↙", 67.5),    # North-East (NE)
            ("←", 112.5),   # East (E)
            ("↖", 157.5),   # South-East (SE)
            ("↑", 202.5),   # South (S)
            ("↗", 247.5),   # South-West (SW)
            ("→", 292.5),   # West (W)
            ("↘", 337.5),   # North-West (NW)
            ("↓", 360.0)    # Wrap back to North
        ]
        wind_deg = wind_deg % 360
        for arrow, upper_bound in DIRECTIONS:
            if wind_deg < upper_bound:
                return arrow

        return "↑"

    def get_open_meteo_data(self, lat, long, forecast_days):
        url = OPEN_METEO_FORECAST_URL.format(lat=lat, long=long, forecast_days=forecast_days)
        response = requests.get(url, timeout=30)

        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to retrieve Open-Meteo weather data: {response.content}")
            raise RuntimeError("No se han podido obtener los datos meteorológicos de Open-Meteo.")
        
        return response.json()

    def get_open_meteo_air_quality(self, lat, long):
        url = OPEN_METEO_AIR_QUALITY_URL.format(lat=lat, long=long)
        response = requests.get(url, timeout=30)
        if not 200 <= response.status_code < 300:
            logger.error(f"Failed to retrieve Open-Meteo air quality data: {response.content}")
            raise RuntimeError("No se han podido obtener los datos de calidad del aire de Open-Meteo.")
        
        return response.json()
    
    def format_time(self, dt, time_format, hour_only=False, include_am_pm=True):
        """Format datetime based on 12h or 24h preference"""
        if time_format == "24h":
            return dt.strftime("%H:00" if hour_only else "%H:%M")
        
        if include_am_pm:
            fmt = "%I %p" if hour_only else "%I:%M %p"
        else:
            fmt = "%I" if hour_only else "%I:%M"

        return dt.strftime(fmt).lstrip("0")
