from utils.app_utils import get_font
from plugins.base_plugin.base_plugin import BasePlugin
from plugins.calendar.constants import FONT_SIZES
from PIL import Image, ImageColor
import icalendar
import recurring_ical_events
import logging
import re
import requests
from datetime import datetime, timedelta, date
import pytz

logger = logging.getLogger(__name__)

WEEKDAYS_ES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
WEEKDAYS_ES_LONG = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MONTHS_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"
]

TODAY_OUTLINE_WIDTH = 2

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U0001F900-\U0001F9FF"  # supplemental symbols & pictographs
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs extended-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "\U0000FE0F"             # variation selector-16 (emoji presentation)
    "\U0000200D"             # zero-width joiner (compound emoji)
    "]+", flags=re.UNICODE
)


def strip_emoji(text):
    """Jost has no emoji glyphs, and PIL doesn't fall back to another font
    for characters missing from the current one — draw.text() just skips
    them, leaving an odd gap in the middle of the title. Strip them instead
    so the remaining text spaces out normally.
    """
    text = EMOJI_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def truncate_text(draw, text, font, max_width):
    """Truncate text with an ellipsis so it fits within max_width."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text + "…" if text else ""


def format_event_time(dt, time_format):
    if time_format == "12h":
        hour = dt.hour % 12 or 12
        suffix = "am" if dt.hour < 12 else "pm"
        return f"{hour}:{dt.minute:02d}{suffix}"
    return dt.strftime("%H:%M")


class Calendar(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config) -> Image:
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

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        timezone = device_config.get_config("timezone", default="America/New_York")
        time_format = device_config.get_config("time_format", default="12h")
        tz = pytz.timezone(timezone)

        current_dt = datetime.now(tz)
        fetch_start, fetch_end = self.get_fetch_range(view, current_dt, settings)
        logger.debug(f"Fetching events for {fetch_start} --> [{current_dt}] --> {fetch_end}")
        events = self.fetch_ics_events(calendar_urls, calendar_colors, tz, fetch_start, fetch_end)
        if not events:
            logger.warning("No se encontraron eventos para las URLs de calendario configuradas.")

        def draw_content(image, draw, content_box, text_color):
            self.draw_calendar(image, draw, content_box, text_color, view, events, current_dt, settings, time_format)

        return self.render_image_pil(dimensions, settings, draw_content)

    def fetch_ics_events(self, calendar_urls, colors, tz, start_range, end_range):
        parsed_events = []

        for calendar_url, color in zip(calendar_urls, colors):
            cal = self.fetch_calendar(calendar_url)
            events = recurring_ical_events.of(cal).between(start_range, end_range)
            contrast_color = self.get_contrast_color(color)

            for event in events:
                start, end, all_day = self.parse_data_points(event, tz)
                parsed_event = {
                    "title": strip_emoji(str(event.get("summary"))),
                    "start": start,
                    "backgroundColor": color,
                    "textColor": contrast_color,
                    "allDay": all_day
                }
                if end:
                    parsed_event['end'] = end

                parsed_events.append(parsed_event)

        parsed_events.sort(key=lambda e: e["start"])
        return parsed_events

    def get_fetch_range(self, view, current_dt, settings):
        """A safe (possibly oversized) range to fetch events for; the actual
        displayed grid range is computed separately by each view's drawer."""
        start = datetime(current_dt.year, current_dt.month, current_dt.day)
        if view == "timeGridDay":
            end = start + timedelta(days=1)
        elif view == "timeGridWeek":
            if settings.get("displayPreviousDays") == "true":
                # Weeks always start on Monday.
                offset = current_dt.weekday()
                start = current_dt - timedelta(days=offset)
                start = datetime(start.year, start.month, start.day)
            end = start + timedelta(days=7)
        elif view == "dayGrid":
            end = start + timedelta(weeks=int(settings.get("displayWeeks") or 4))
        elif view == "dayGridMonth":
            start = datetime(current_dt.year, current_dt.month, 1) - timedelta(weeks=1)
            end = datetime(current_dt.year, current_dt.month, 1) + timedelta(weeks=6)
        elif view == "listMonth":
            end = start + timedelta(weeks=5)
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

    # ---- Drawing ----------------------------------------------------------

    def draw_calendar(self, image, draw, box, text_color, view, events, current_dt, settings, time_format):
        left, top, right, bottom = box
        width = right - left
        height = bottom - top
        font_scale = FONT_SIZES.get(settings.get("fontSize", "normal"), 1)
        show_weekends = settings.get("displayWeekends") != "false"

        if settings.get("displayTitle") != "false":
            title_h = round(height * 0.09 * font_scale)
            title_font = get_font("Jost", max(1, round(title_h * 0.6)), font_weight="bold")
            draw.text(
                (left + width / 2, top + title_h / 2),
                self.get_title(view, current_dt, settings, show_weekends),
                font=title_font, fill=text_color, anchor="mm"
            )
            top += title_h

        grid_box = (left, top, right, bottom)

        if view in ("dayGridMonth", "dayGrid"):
            self.draw_day_grid(draw, grid_box, text_color, events, current_dt, settings, show_weekends, font_scale, time_format, month_view=(view == "dayGridMonth"))
        elif view in ("timeGridDay", "timeGridWeek", "timeGrid"):
            self.draw_time_grid(draw, grid_box, text_color, events, current_dt, settings, show_weekends, font_scale, time_format, single_day=(view == "timeGridDay"))
        elif view == "listMonth":
            self.draw_list_view(draw, grid_box, text_color, events, current_dt, settings, font_scale, time_format)

    def get_title(self, view, current_dt, settings, show_weekends=True):
        if view == "timeGridDay":
            return f"{WEEKDAYS_ES_LONG[current_dt.weekday()]}, {current_dt.day} de {MONTHS_ES[current_dt.month - 1]}"
        if view in ("dayGridMonth",):
            return f"{MONTHS_ES[current_dt.month - 1].capitalize()} {current_dt.year}"
        if view in ("timeGridWeek", "timeGrid", "dayGrid"):
            if view == "timeGridWeek" and settings.get("displayPreviousDays") != "true":
                view = "timeGrid"
            days = self.get_grid_days(view, current_dt, settings, show_weekends)
            first, last = days[0], days[-1]
            if first.month == last.month:
                return f"{first.day} - {last.day} de {MONTHS_ES[first.month - 1]}"
            return f"{first.day} de {MONTHS_ES[first.month - 1]} - {last.day} de {MONTHS_ES[last.month - 1]}"
        if view == "listMonth":
            return f"{MONTHS_ES[current_dt.month - 1].capitalize()} {current_dt.year}"
        return ""

    def get_grid_days(self, view, current_dt, settings, show_weekends=True):
        """The list of calendar dates a grid/time-grid view should display."""
        today = current_dt.date()

        if view == "timeGridDay":
            # A single day is always shown as-is, even if it falls on a
            # weekend and weekends are otherwise hidden — filtering it out
            # would leave the view with nothing to display.
            return [today]
        elif view == "timeGrid":
            days = [today + timedelta(days=i) for i in range(7)]
        elif view == "timeGridWeek":
            week_start = today - timedelta(days=today.weekday())
            days = [week_start + timedelta(days=i) for i in range(7)]
        elif view == "dayGrid":
            week_start = today - timedelta(days=today.weekday())
            weeks = int(settings.get("displayWeeks") or 4)
            days = [week_start + timedelta(days=i) for i in range(weeks * 7)]
        elif view == "dayGridMonth":
            month_start = date(current_dt.year, current_dt.month, 1)
            grid_start = month_start - timedelta(days=month_start.weekday())
            if current_dt.month == 12:
                next_month = date(current_dt.year + 1, 1, 1)
            else:
                next_month = date(current_dt.year, current_dt.month + 1, 1)
            month_end = next_month - timedelta(days=1)
            grid_end = month_end + timedelta(days=(6 - month_end.weekday()))
            days = [grid_start + timedelta(days=i) for i in range((grid_end - grid_start).days + 1)]
        else:
            days = [today]

        if not show_weekends:
            days = [d for d in days if d.weekday() < 5]
        return days

    def dim_color(self, color):
        """A muted version of `color`, blended toward mid-gray."""
        r, g, b = ImageColor.getrgb(color)
        factor = 0.55
        return (
            round(r + (128 - r) * factor),
            round(g + (128 - g) * factor),
            round(b + (128 - b) * factor)
        )

    def draw_day_grid(self, draw, box, text_color, events, current_dt, settings, show_weekends, font_scale, time_format, month_view):
        left, top, right, bottom = box
        width = right - left
        height = bottom - top
        today = current_dt.date()
        view = "dayGridMonth" if month_view else "dayGrid"
        days = self.get_grid_days(view, current_dt, settings, show_weekends)

        num_cols = 7 if show_weekends else 5
        num_rows = len(days) // num_cols
        weekday_indices = [d for d in range(7) if show_weekends or d < 5]

        header_h = round(height * 0.05 * font_scale)
        header_font = get_font("Jost", max(1, round(header_h * 0.55)), font_weight="bold")
        col_w = width / num_cols
        for col, wd in enumerate(weekday_indices):
            draw.text((left + col * col_w + col_w / 2, top + header_h / 2), WEEKDAYS_ES[wd], font=header_font, fill=text_color, anchor="mm")

        grid_top = top + header_h
        row_h = (bottom - grid_top) / num_rows

        day_font = get_font("Jost", max(1, round(row_h * 0.16)), font_weight="bold")
        event_font = get_font("Jost", max(1, round(row_h * 0.13)))
        line_color = self.dim_color(text_color)

        events_by_date = {}
        for event in events:
            d = datetime.fromisoformat(event["start"]).date()
            events_by_date.setdefault(d, []).append(event)

        pad = round(col_w * 0.06)
        vpad = round(row_h * 0.06)
        day_line_h = sum(day_font.getmetrics())
        event_line_h = sum(event_font.getmetrics())
        chip_h = event_line_h + round(vpad * 0.4)

        for i, day in enumerate(days):
            row = i // num_cols
            col = i % num_cols
            cell_left = left + col * col_w
            cell_top = grid_top + row * row_h
            cell_right = cell_left + col_w
            cell_bottom = cell_top + row_h

            is_current_month = (not month_view) or day.month == current_dt.month
            num_color = text_color if is_current_month else line_color

            if day == today:
                draw.rectangle(
                    (cell_left + 1, cell_top + 1, cell_right - 1, cell_bottom - 1),
                    outline=text_color, width=TODAY_OUTLINE_WIDTH
                )

            draw.text((cell_left + pad, cell_top + vpad), str(day.day), font=day_font, fill=num_color, anchor="la")

            chip_top = cell_top + vpad + day_line_h + round(vpad * 0.5)
            max_chips = max(0, int((cell_bottom - vpad - chip_top) // chip_h))
            day_events = events_by_date.get(day, [])

            if len(day_events) > max_chips:
                shown = day_events[:max(0, max_chips - 1)]
                remaining = len(day_events) - len(shown)
            else:
                shown = day_events
                remaining = 0

            chip_y = chip_top
            chip_w = col_w - pad * 2
            for event in shown:
                label = event["title"]
                if settings.get("displayEventTime") == "true" and not event["allDay"]:
                    dt = datetime.fromisoformat(event["start"])
                    label = f"{format_event_time(dt, time_format)} {label}"
                chip_bottom = chip_y + chip_h - round(vpad * 0.3)
                radius = max(1, min(4, round((chip_bottom - chip_y) * 0.25), round(chip_w * 0.15)))
                draw.rounded_rectangle(
                    (cell_left + pad, chip_y, cell_left + pad + chip_w, chip_bottom),
                    radius=radius, fill=event["backgroundColor"], outline=text_color, width=1
                )
                label = truncate_text(draw, label, event_font, chip_w - pad)
                draw.text((cell_left + pad * 1.5, (chip_y + chip_bottom) / 2), label, font=event_font, fill=event["textColor"], anchor="lm")
                chip_y += chip_h

            if remaining > 0:
                draw.text((cell_left + pad, chip_y + chip_h / 2), f"+{remaining} más", font=event_font, fill=line_color, anchor="lm")

        for col in range(num_cols + 1):
            x = left + col * col_w
            draw.line((x, grid_top, x, bottom), fill=line_color, width=1)
        for row in range(num_rows + 1):
            y = grid_top + row * row_h
            draw.line((left, y, right, y), fill=line_color, width=1)

    def draw_time_grid(self, draw, box, text_color, events, current_dt, settings, show_weekends, font_scale, time_format, single_day):
        left, top, right, bottom = box
        width = right - left
        height = bottom - top
        today = current_dt.date()

        view = "timeGridDay" if single_day else ("timeGridWeek" if settings.get("displayPreviousDays") == "true" else "timeGrid")
        days = self.get_grid_days(view, current_dt, settings, show_weekends)

        start_hour = int(settings.get("startTimeInterval") or 0)
        end_hour = int(settings.get("endTimeInterval") or 24)
        if end_hour <= start_hour:
            end_hour = start_hour + 1
        num_hours = end_hour - start_hour

        header_h = round(height * 0.06 * font_scale)
        header_font = get_font("Jost", max(1, round(header_h * 0.45)), font_weight="bold")

        all_day_events_by_date = {}
        for event in events:
            if event["allDay"]:
                d = datetime.fromisoformat(event["start"]).date()
                all_day_events_by_date.setdefault(d, []).append(event)
        has_all_day = any(d in all_day_events_by_date for d in days)
        all_day_h = round(height * 0.05 * font_scale) if has_all_day else 0

        gutter_w = round(width * 0.06)
        grid_left = left + gutter_w
        grid_top = top + header_h + all_day_h
        col_w = (right - grid_left) / len(days)
        hour_h = (bottom - grid_top) / num_hours

        hour_font = get_font("Jost", max(1, round(hour_h * 0.5)))
        # Events can be as short as a few minutes tall, so size their text off
        # the hour row height (not column width, which is huge in day view).
        event_font = get_font("Jost", max(1, round(min(hour_h * 0.42, col_w * 0.09))))
        line_color = self.dim_color(text_color)

        for i, day in enumerate(days):
            cx = grid_left + i * col_w + col_w / 2
            label = f"{WEEKDAYS_ES[day.weekday()]} {day.day}" if not single_day else WEEKDAYS_ES_LONG[day.weekday()]
            draw.text((cx, top + header_h / 2), label, font=header_font, fill=text_color, anchor="mm")

        if has_all_day:
            chip_font = get_font("Jost", max(1, round(all_day_h * 0.5)))
            radius = max(2, round(all_day_h * 0.2))

            all_day_label_font = get_font("Jost", max(1, round(all_day_h * 0.32)))
            all_day_label = truncate_text(draw, "Todo el día", all_day_label_font, gutter_w - 4)
            draw.text((left + 2, top + header_h + all_day_h / 2), all_day_label, font=all_day_label_font, fill=text_color, anchor="lm")

            for i, day in enumerate(days):
                day_events = all_day_events_by_date.get(day, [])
                if not day_events:
                    continue
                cell_left = grid_left + i * col_w
                event = day_events[0]
                label = truncate_text(draw, event["title"], chip_font, col_w - 4)
                draw.rounded_rectangle(
                    (cell_left + 2, top + header_h + 2, cell_left + col_w - 2, top + header_h + all_day_h - 2),
                    radius=radius, fill=event["backgroundColor"], outline=text_color, width=1
                )
                draw.text((cell_left + col_w / 2, top + header_h + all_day_h / 2), label, font=chip_font, fill=event["textColor"], anchor="mm")

        for h in range(num_hours + 1):
            y = grid_top + h * hour_h
            if h == 0 and has_all_day:
                # Double line to set the all-day row apart from the hour grid.
                draw.line((left, y - 2, right, y - 2), fill=line_color, width=1)
                draw.line((left, y, right, y), fill=line_color, width=1)
            else:
                draw.line((left, y, right, y), fill=line_color, width=1)
            if h < num_hours:
                hour_dt = current_dt.replace(hour=(start_hour + h) % 24, minute=0)
                label = format_event_time(hour_dt, time_format)
                draw.text((grid_left - 4, y + 2), label, font=hour_font, fill=text_color, anchor="ra")

        for i in range(len(days) + 1):
            x = grid_left + i * col_w
            draw.line((x, grid_top, x, bottom), fill=line_color, width=1)

        for i, day in enumerate(days):
            cell_left = grid_left + i * col_w
            day_events = [e for e in events if not e["allDay"] and datetime.fromisoformat(e["start"]).date() == day]
            for event in day_events:
                ev_start = datetime.fromisoformat(event["start"])
                ev_end = datetime.fromisoformat(event["end"]) if event.get("end") else ev_start + timedelta(hours=1)

                start_frac = max(0, min(1, (ev_start.hour + ev_start.minute / 60 - start_hour) / num_hours))
                if ev_end.date() > ev_start.date():
                    # Spans past midnight: clip to the bottom of today's column
                    # instead of wrapping to a small hour value on the same day.
                    end_frac = 1
                else:
                    end_frac = max(0, min(1, (ev_end.hour + ev_end.minute / 60 - start_hour) / num_hours))
                if end_frac <= start_frac:
                    continue

                y1 = grid_top + start_frac * (bottom - grid_top)
                y2 = max(grid_top + end_frac * (bottom - grid_top), y1 + 2)

                radius = max(1, min(4, round((y2 - y1) * 0.25), round((col_w - 4) * 0.25)))
                draw.rounded_rectangle(
                    (cell_left + 2, y1, cell_left + col_w - 2, y2),
                    radius=radius, fill=event["backgroundColor"], outline=text_color, width=1
                )

                label = event["title"]
                if settings.get("displayEventTime") == "true":
                    label = f"{format_event_time(ev_start, time_format)} {label}"
                label = truncate_text(draw, label, event_font, col_w - 6)
                draw.text((cell_left + 4, y1 + 2), label, font=event_font, fill=event["textColor"], anchor="la")

        if settings.get("displayNowIndicator") == "true" and today in days:
            now_hour = current_dt.hour + current_dt.minute / 60
            if start_hour <= now_hour <= end_hour:
                frac = (now_hour - start_hour) / num_hours
                y = grid_top + frac * (bottom - grid_top)
                color = settings.get("nowIndicatorColor") or "#ff0000"
                idx = days.index(today)
                x1 = grid_left + idx * col_w
                x2 = x1 + col_w
                draw.line((x1, y, x2, y), fill=color, width=3)

    def draw_list_view(self, draw, box, text_color, events, current_dt, settings, font_scale, time_format):
        left, top, right, bottom = box
        width = right - left
        today = current_dt.date()

        upcoming = [e for e in events if datetime.fromisoformat(e["start"]).date() >= today]
        if not upcoming:
            empty_font = get_font("Jost", max(1, round((bottom - top) * 0.05)))
            draw.text((left + width / 2, top + (bottom - top) / 2), "No hay eventos próximos", font=empty_font, fill=self.dim_color(text_color), anchor="mm")
            return

        events_by_date = {}
        for event in upcoming:
            d = datetime.fromisoformat(event["start"]).date()
            events_by_date.setdefault(d, []).append(event)

        date_font = get_font("Jost", max(1, round(width * 0.022 * font_scale)), font_weight="bold")
        event_font = get_font("Jost", max(1, round(width * 0.020 * font_scale)))
        row_h = sum(event_font.getmetrics()) + round(width * 0.012)
        date_h = sum(date_font.getmetrics()) + round(width * 0.01)
        dot_size = round(row_h * 0.35)

        y = top
        for day in sorted(events_by_date):
            if y + date_h > bottom:
                break

            label = f"{WEEKDAYS_ES_LONG[day.weekday()]}, {day.day} de {MONTHS_ES[day.month - 1]}"
            if day == today:
                label = f"Hoy · {label}"
            draw.text((left, y), label, font=date_font, fill=text_color, anchor="la")
            y += date_h

            for event in events_by_date[day]:
                if y + row_h > bottom:
                    break
                cy = y + row_h / 2
                draw.ellipse((left, cy - dot_size / 2, left + dot_size, cy + dot_size / 2), fill=event["backgroundColor"])

                text_x = left + dot_size + round(width * 0.015)
                label = event["title"]
                if settings.get("displayEventTime") == "true" and not event["allDay"]:
                    dt = datetime.fromisoformat(event["start"])
                    label = f"{format_event_time(dt, time_format)} — {label}"
                label = truncate_text(draw, label, event_font, right - text_x)
                draw.text((text_x, cy), label, font=event_font, fill=text_color, anchor="lm")
                y += row_h

            y += round(width * 0.008)
