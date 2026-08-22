from plugins.base_plugin.base_plugin import BasePlugin
from utils.app_utils import get_font
from datetime import datetime
import logging
import pytz

logger = logging.getLogger(__name__)

MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]

class Countdown(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        title = settings.get('title')
        countdown_date_str = settings.get('date')

        if not countdown_date_str:
            raise RuntimeError("La fecha es obligatoria.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        timezone = device_config.get_config("timezone", default="America/New_York")
        tz = pytz.timezone(timezone)
        current_time = datetime.now(tz)

        countdown_date = datetime.strptime(countdown_date_str, "%Y-%m-%d")
        countdown_date = tz.localize(countdown_date)

        day_count = (countdown_date.date() - current_time.date()).days
        label = "Días restantes" if day_count >= 0 else "Días transcurridos"
        date_str = f"{countdown_date.day} de {MONTHS_ES[countdown_date.month - 1]} de {countdown_date.year}"

        def draw_content(draw, content_box, text_color):
            left, top, right, bottom = content_box
            box_width = right - left
            box_height = bottom - top
            unit = min(box_width, box_height) / 100

            lines = []
            if title:
                title_font = get_font("Jost", max(1, round(unit * 11)), font_weight="bold")
                lines.append((title, title_font, 0))

            subtitle_font = get_font("Jost", max(1, round(unit * 5)))
            lines.append((date_str, subtitle_font, round(unit * 4)))

            count_font = get_font("Jost", max(1, round(unit * 32)))
            lines.append((str(abs(day_count)), count_font, 0))

            label_font = get_font("Jost", max(1, round(unit * 8)))
            lines.append((label.upper(), label_font, 0))

            heights = [sum(font.getmetrics()) for _, font, _ in lines]
            total_height = sum(heights) + sum(gap for _, _, gap in lines)

            y = top + (box_height - total_height) / 2
            center_x = left + box_width / 2
            for (text, font, gap_after), h in zip(lines, heights):
                draw.text((center_x, y), text, font=font, fill=text_color, anchor="ma")
                y += h + gap_after

        return self.render_image_pil(dimensions, settings, draw_content)
