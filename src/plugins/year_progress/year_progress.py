from plugins.base_plugin.base_plugin import BasePlugin
from utils.app_utils import get_font
from datetime import datetime, timedelta
from PIL import Image, ImageDraw
import logging
import pytz

logger = logging.getLogger(__name__)


def draw_letter_spaced_text(draw, text, font, x, y, fill, spacing, align="left"):
    """PIL has no built-in letter-spacing, so draw each character separately."""
    widths = [draw.textlength(ch, font=font) for ch in text]
    total_width = sum(widths) + spacing * (len(text) - 1)
    if align == "center":
        x -= total_width / 2
    elif align == "right":
        x -= total_width
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=font, fill=fill, anchor="la")
        x += w + spacing
    return total_width


def draw_dot_bar(draw, x, y, width, height, percent, color, num_dots=48):
    """A row of dots, filled up to `percent`, matching the InkyPi-Flow-Progress look."""
    spacing = width / num_dots
    radius = min(height, spacing) * 0.3
    filled_dots = round(num_dots * percent / 100)
    cy = y + height / 2
    for i in range(num_dots):
        cx = x + spacing * i + spacing / 2
        if i < filled_dots:
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
        else:
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=color, width=1)


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

        mode = settings.get('mode', 'simple')

        if mode == 'advanced':
            day_start = tz.localize(datetime(current_time.year, current_time.month, current_time.day))
            day_end = day_start + timedelta(days=1)
            day_percent = (current_time - day_start).total_seconds() / (day_end - day_start).total_seconds() * 100

            week_start_date = current_time.date() - timedelta(days=current_time.weekday())
            week_start = tz.localize(datetime(week_start_date.year, week_start_date.month, week_start_date.day))
            week_end = week_start + timedelta(days=7)
            week_percent = (current_time - week_start).total_seconds() / (week_end - week_start).total_seconds() * 100

            month_start = tz.localize(datetime(current_time.year, current_time.month, 1))
            if current_time.month == 12:
                month_end = tz.localize(datetime(current_time.year + 1, 1, 1))
            else:
                month_end = tz.localize(datetime(current_time.year, current_time.month + 1, 1))
            month_percent = (current_time - month_start).total_seconds() / (month_end - month_start).total_seconds() * 100

            periods = [
                ("DÍA", day_percent),
                ("SEMANA", week_percent),
                ("MES", month_percent),
                ("AÑO", year_percent),
            ]

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

            subtitle_letter_spacing = round(unit * 1.6)
            draw_letter_spaced_text(draw, "PROGRESO", subtitle_font, center_x, y, text_color, subtitle_letter_spacing, align="center")
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

            bar_radius = round(bar_height / 3)
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

            label_letter_spacing = round(unit * 0.8)
            draw_letter_spaced_text(draw, f"{year_percent}% COMPLETADO", label_font, left, y, text_color, label_letter_spacing, align="left")
            draw_letter_spaced_text(draw, f"{days_left} DÍAS RESTANTES", label_font, right, y, text_color, label_letter_spacing, align="right")

        def draw_advanced_content(image, draw, content_box, text_color):
            left, top, right, bottom = content_box
            box_width = right - left
            box_height = bottom - top
            unit = min(box_width, box_height) / 100

            label_font = get_font("Jost", max(1, round(unit * 7)), font_weight="bold")
            percent_font = get_font("Jost", max(1, round(unit * 7)))
            label_letter_spacing = round(unit * 0.8)

            label_h = sum(label_font.getmetrics())
            dots_height = round(unit * 6)
            label_gap = round(unit * 2)
            row_gap = round(unit * 8)

            block_height = label_h + label_gap + dots_height
            total_height = block_height * len(periods) + row_gap * (len(periods) - 1)

            y = top + (box_height - total_height) / 2
            for label, percent in periods:
                draw_letter_spaced_text(draw, label, label_font, left, y, text_color, label_letter_spacing, align="left")
                draw_letter_spaced_text(draw, f"{round(percent)}%", percent_font, right, y, text_color, label_letter_spacing, align="right")

                dots_y = y + label_h + label_gap
                draw_dot_bar(draw, left, dots_y, box_width, dots_height, percent, text_color)

                y += block_height + row_gap

        if mode == 'advanced':
            return self.render_image_pil(dimensions, settings, draw_advanced_content)
        return self.render_image_pil(dimensions, settings, draw_content)
