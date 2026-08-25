import os
import logging
import random
import requests
import msal
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from PIL import Image, ImageDraw
from plugins.base_plugin.base_plugin import BasePlugin
from utils.app_utils import get_font, resolve_path

logger = logging.getLogger(__name__)

MONTHS_ES_ABBR = [
    "ene", "feb", "mar", "abr", "may", "jun",
    "jul", "ago", "sep", "oct", "nov", "dic"
]

# Public client (no secret) registered for this project — safe to embed,
# unlike a client secret. "common" accepts both personal and work/school
# Microsoft accounts, matching how the app was registered.
CLIENT_ID = "9ebac9a5-bb7d-4db6-9fcd-5ddd8dbf0825"
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Tasks.Read"]
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

TOKEN_CACHE_PATH = resolve_path("config/microsoft_todo_token_cache.json")

MUTED_GRAY = "#999999"


def load_token_cache():
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_PATH):
        with open(TOKEN_CACHE_PATH, "r") as f:
            cache.deserialize(f.read())
    return cache


def save_token_cache(cache):
    if cache.has_state_changed:
        os.makedirs(os.path.dirname(TOKEN_CACHE_PATH), exist_ok=True)
        with open(TOKEN_CACHE_PATH, "w") as f:
            f.write(cache.serialize())


def get_msal_app(cache):
    return msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)


class MicrosoftTodo(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        try:
            access_token = self.get_access_token()
            template_params['lists'] = self.fetch_lists(access_token)
            template_params['connected'] = True
        except Exception as e:
            logger.warning(f"No se pudo conectar con Microsoft To Do: {str(e)}")
            template_params['lists'] = []
            template_params['connected'] = False
        return template_params

    def generate_image(self, settings, device_config):
        access_token = self.get_access_token()
        # Fetched once regardless of mode: needed to pick from in random
        # mode, and reused here for display names either way instead of
        # asking the Graph API for each list's details separately.
        all_lists = self.fetch_lists(access_token)
        list_names = {l["id"]: l.get("displayName", "") for l in all_lists}

        if settings.get("randomLists") == "true":
            if not all_lists:
                raise RuntimeError("No hay ninguna lista de tareas en la cuenta conectada.")
            list_ids = [l["id"] for l in random.sample(all_lists, min(2, len(all_lists)))]
        else:
            list_ids = [id for id in [settings.get("listIdLeft"), settings.get("listIdRight")] if id]
            if not list_ids:
                raise RuntimeError("Selecciona al menos una lista de tareas en los ajustes.")

        with ThreadPoolExecutor(max_workers=len(list_ids)) as executor:
            tasks_per_list = list(executor.map(lambda lid: self.fetch_tasks(access_token, lid), list_ids))
        columns = [(list_names.get(lid, ""), tasks) for lid, tasks in zip(list_ids, tasks_per_list)]

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        def draw_content(image, draw, content_box, text_color):
            self.draw_columns(image, draw, content_box, text_color, columns)

        return self.render_image_pil(dimensions, settings, draw_content)

    def draw_columns(self, image, draw, content_box, text_color, columns):
        left, top, right, bottom = content_box

        if len(columns) == 1:
            list_name, tasks = columns[0]
            self.draw_tasks(image, draw, (left, top, right, bottom), text_color, list_name, tasks)
            return

        gap = (right - left) * 0.04
        mid = (left + right) / 2
        draw.line((mid, top, mid, bottom), fill=MUTED_GRAY, width=1)

        (left_name, left_tasks), (right_name, right_tasks) = columns
        self.draw_tasks(image, draw, (left, top, mid - gap / 2, bottom), text_color, left_name, left_tasks)
        self.draw_tasks(image, draw, (mid + gap / 2, top, right, bottom), text_color, right_name, right_tasks)

    def get_access_token(self):
        cache = load_token_cache()
        app = get_msal_app(cache)

        accounts = app.get_accounts()
        if not accounts:
            raise RuntimeError("No hay ninguna cuenta de Microsoft conectada. Ejecuta plugins/microsoft_todo/connect.py.")

        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        save_token_cache(cache)

        if not result or "access_token" not in result:
            raise RuntimeError("No se pudo renovar el acceso a Microsoft To Do, vuelve a conectar la cuenta.")
        return result["access_token"]

    def fetch_lists(self, access_token):
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = requests.get(f"{GRAPH_BASE}/me/todo/lists", headers=headers, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"No se pudieron obtener las listas de Microsoft To Do: {str(e)}")
        return response.json().get("value", [])

    def fetch_tasks(self, access_token, list_id):
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"$filter": "status ne 'completed'", "$orderby": "createdDateTime"}
        try:
            response = requests.get(f"{GRAPH_BASE}/me/todo/lists/{list_id}/tasks", headers=headers, params=params, timeout=30)
            response.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"No se pudieron obtener las tareas de Microsoft To Do (¿la lista sigue existiendo?): {str(e)}")
        return response.json().get("value", [])

    def draw_tasks(self, image, draw, content_box, text_color, list_name, tasks):
        left, top, right, bottom = content_box
        height = bottom - top

        title_font = get_font("Jost", round(height * 0.08), font_weight="bold")
        title = self.truncate_to_width(draw, list_name or "Tareas", title_font, right - left)
        draw.text(((left + right) / 2, top), title, font=title_font, fill=text_color, anchor="ma")
        body_top = top + sum(title_font.getmetrics()) * 1.6

        if not tasks:
            empty_font = get_font("Jost", round(height * 0.05))
            draw.text(((left + right) / 2, (body_top + bottom) / 2), "Sin tareas pendientes", font=empty_font, fill=MUTED_GRAY, anchor="mm")
            return

        # Row height (and every font below) scales with how many tasks there
        # are, so a short list reads big and a long one still fits without
        # being silently cut off.
        row_h = (bottom - body_top) / len(tasks)
        row_h = max(height * 0.06, min(height * 0.21, row_h))

        task_font = get_font("Jost", round(row_h * 0.4))
        due_font = get_font("Jost", round(row_h * 0.28))
        dot_r = round(row_h * 0.065)
        text_x = left + dot_r * 4.5

        y = body_top
        for task in tasks:
            if y + row_h > bottom + 1:  # small tolerance for float rounding when rows are sized to fit exactly
                break
            row_center = y + row_h / 2
            # Nudged down slightly: a geometrically centered dot reads as too
            # high next to lowercase text, whose visual weight sits below
            # the midline of the font's full ascender-to-descender box.
            self.draw_smooth_dot(image, (left + dot_r, row_center + row_h * 0.05), dot_r, text_color)

            title = task.get("title") or ""
            due = task.get("dueDateTime")
            due_label = ""
            if due and due.get("dateTime"):
                due_date = date.fromisoformat(due["dateTime"][:10])
                due_label = f"{due_date.day} {MONTHS_ES_ABBR[due_date.month - 1]}"

            if due_label:
                due_w = draw.textlength(due_label, font=due_font)
                max_title_w = right - text_x - due_w - height * 0.02
                title = self.truncate_to_width(draw, title, task_font, max_title_w)
                draw.text((text_x, row_center), title, font=task_font, fill=text_color, anchor="lm")
                draw.text((right, row_center), due_label, font=due_font, fill=MUTED_GRAY, anchor="rm")
            else:
                title = self.truncate_to_width(draw, title, task_font, right - text_x)
                draw.text((text_x, row_center), title, font=task_font, fill=text_color, anchor="lm")

            y += row_h
            draw.line((left, y, right, y), fill="#e0e0e0", width=1)

    def draw_smooth_dot(self, image, center, radius, fill):
        # PIL's own draw.circle has no anti-aliasing, so a small dot comes
        # out visibly jagged — draw it oversized on its own layer and shrink
        # it back down, which blends the edge instead of stair-stepping it.
        # (Tried using a "•" glyph instead: Jost renders it tiny and shifted
        # high, and doesn't have "●"/"○"/"‣"/"◦" at all — not usable.)
        scale = 4
        size = radius * 2 * scale
        dot = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ImageDraw.Draw(dot).ellipse((0, 0, size - 1, size - 1), fill=fill)
        dot = dot.resize((radius * 2, radius * 2), Image.LANCZOS)
        x, y = center
        image.paste(dot, (round(x - radius), round(y - radius)), dot)

    def truncate_to_width(self, draw, text, font, max_width):
        if draw.textlength(text, font=font) <= max_width:
            return text
        while text and draw.textlength(text + "…", font=font) > max_width:
            text = text[:-1]
        return text + "…"
