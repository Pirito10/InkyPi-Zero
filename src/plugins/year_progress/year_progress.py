from plugins.base_plugin.base_plugin import BasePlugin
from utils.app_utils import get_font
from datetime import datetime
from PIL import Image, ImageDraw
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

        def draw_content(image, draw, content_box, text_color):
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

            draw.text((center_x, y), "PROGRESO", font=subtitle_font, fill=text_color, anchor="ma")
            y += subtitle_h

            bar_top = y
            bar_bottom = y + bar_height

            # Draw the bar's contents (fill + dots) onto a separate canvas,
            # then clip it with a rounded-rectangle mask so only the two
            # outer corners on each end are rounded, with a square seam
            # between the fill and the dots.
            bar_img = Image.new("RGB", (box_width, bar_height), "white")
            bar_draw = ImageDraw.Draw(bar_img)

            fill_width = round(box_width * year_percent / 100)
            if fill_width > 0:
                bar_draw.rectangle((0, 0, fill_width, bar_height), fill=text_color)

            dot_spacing = max(3, round(unit * 0.6))
            dot_radius = max(1, round(dot_spacing * 0.2))
            dy = dot_spacing / 2
            while dy < bar_height:
                dx = fill_width + dot_spacing / 2
                while dx < box_width:
                    bar_draw.ellipse((dx - dot_radius, dy - dot_radius, dx + dot_radius, dy + dot_radius), fill=text_color)
                    dx += dot_spacing
                dy += dot_spacing

            bar_radius = max(2, round(unit * 1))
            mask = Image.new("L", (box_width, bar_height), 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, box_width, bar_height), radius=bar_radius, fill=255)
            image.paste(bar_img, (round(left), round(bar_top)), mask)

            # Month tick marks, straddling the top/bottom edge of the bar
            tick_extend = max(2, round(unit * 1))
            for month in range(1, 12):
                tick_x = left + round(box_width * month / 12)
                draw.line([(tick_x, bar_top - tick_extend), (tick_x, bar_top + tick_extend)], fill=text_color, width=1)
                draw.line([(tick_x, bar_bottom - tick_extend), (tick_x, bar_bottom + tick_extend)], fill=text_color, width=1)

            y = bar_bottom + label_gap

            draw.text((left, y), f"{year_percent}% COMPLETADO", font=label_font, fill=text_color, anchor="la")
            days_left_text = f"{days_left} DÍAS RESTANTES"
            days_left_width = draw.textlength(days_left_text, font=label_font)
            draw.text((right - days_left_width, y), days_left_text, font=label_font, fill=text_color, anchor="la")

        return self.render_image_pil(dimensions, settings, draw_content)
