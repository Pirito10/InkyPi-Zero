from plugins.base_plugin.base_plugin import BasePlugin
from utils.app_utils import get_font
from datetime import datetime
import logging
import pytz

logger = logging.getLogger(__name__)
class YearProgress(BasePlugin):
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
        current_time = datetime.now(tz)

        start_of_year = tz.localize(datetime(current_time.year, 1, 1))
        start_of_next_year = tz.localize(datetime(current_time.year + 1, 1, 1))

        total_days = (start_of_next_year - start_of_year).days
        days_left = (start_of_next_year - current_time).total_seconds() / (24 * 3600)
        elapsed_days = (current_time - start_of_year).total_seconds() / (24 * 3600)

        year = current_time.year
        year_percent = round((elapsed_days / total_days) * 100)
        days_left = round(days_left)

        def draw_content(draw, content_box, text_color):
            left, top, right, bottom = content_box
            box_width = right - left
            box_height = bottom - top
            unit = min(box_width, box_height) / 100
            center_x = left + box_width / 2

            year_font = get_font("Jost", max(1, round(unit * 20)), font_weight="bold")
            subtitle_font = get_font("Jost", max(1, round(unit * 10)))
            label_font = get_font("Jost", max(1, round(unit * 5)))

            bar_height = round(unit * 10)
            label_gap = round(unit * 2)

            year_h = sum(year_font.getmetrics())
            subtitle_h = sum(subtitle_font.getmetrics())
            label_h = sum(label_font.getmetrics())
            subtitle_gap = round(unit * 10)

            total_height = year_h + subtitle_gap + subtitle_h + bar_height + label_gap + label_h

            y = top + (box_height - total_height) / 2
            draw.text((center_x, y), str(year), font=year_font, fill=text_color, anchor="ma")
            y += year_h + subtitle_gap

            draw.text((center_x, y), "PROGRESS", font=subtitle_font, fill=text_color, anchor="ma")
            y += subtitle_h

            bar_top = y
            bar_bottom = y + bar_height
            fill_width = round(box_width * year_percent / 100)
            if fill_width > 0:
                draw.rectangle((left, bar_top, left + fill_width, bar_bottom), fill=text_color)

            dot_spacing = max(3, round(unit * 0.6))
            dot_radius = max(1, round(dot_spacing * 0.2))
            dy = bar_top + dot_spacing / 2
            while dy < bar_bottom:
                dx = left + fill_width + dot_spacing / 2
                while dx < right:
                    draw.ellipse((dx - dot_radius, dy - dot_radius, dx + dot_radius, dy + dot_radius), fill=text_color)
                    dx += dot_spacing
                dy += dot_spacing
            y = bar_bottom + label_gap

            draw.text((left, y), f"{year_percent}% DONE", font=label_font, fill=text_color, anchor="la")
            days_left_text = f"{days_left} DAYS LEFT"
            days_left_width = draw.textlength(days_left_text, font=label_font)
            draw.text((right - days_left_width, y), days_left_text, font=label_font, fill=text_color, anchor="la")

        return self.render_image_pil(dimensions, settings, draw_content)
