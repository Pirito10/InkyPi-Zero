import os
import logging
import random
import requests
import msal
from concurrent.futures import ThreadPoolExecutor
from datetime import date
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
CIRCLE_COLOR = "#666666"


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

        if settings.get("randomLists") == "true":
            all_lists = self.fetch_lists(access_token)
            if not all_lists:
                raise RuntimeError("No hay ninguna lista de tareas en la cuenta conectada.")
            list_ids = [l["id"] for l in random.sample(all_lists, min(2, len(all_lists)))]
        else:
            list_ids = [id for id in [settings.get("listIdLeft"), settings.get("listIdRight")] if id]
            if not list_ids:
                raise RuntimeError("Selecciona al menos una lista de tareas en los ajustes.")

        with ThreadPoolExecutor(max_workers=len(list_ids)) as executor:
            columns = list(executor.map(lambda lid: self.fetch_list_and_tasks(access_token, lid), list_ids))

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        def draw_content(image, draw, content_box, text_color):
            self.draw_columns(draw, content_box, text_color, columns)

        return self.render_image_pil(dimensions, settings, draw_content)

    def draw_columns(self, draw, content_box, text_color, columns):
        left, top, right, bottom = content_box

        if len(columns) == 1:
            list_name, tasks = columns[0]
            self.draw_tasks(draw, (left, top, right, bottom), text_color, list_name, tasks)
            return

        gap = (right - left) * 0.04
        mid = (left + right) / 2
        draw.line((mid, top, mid, bottom), fill=MUTED_GRAY, width=1)

        (left_name, left_tasks), (right_name, right_tasks) = columns
        self.draw_tasks(draw, (left, top, mid - gap / 2, bottom), text_color, left_name, left_tasks)
        self.draw_tasks(draw, (mid + gap / 2, top, right, bottom), text_color, right_name, right_tasks)

    def get_access_token(self):
        cache = load_token_cache()
        app = get_msal_app(cache)

        accounts = app.get_accounts()
        if not accounts:
            raise RuntimeError("No hay ninguna cuenta de Microsoft conectada. Ejecuta scripts/connect_microsoft_todo.py.")

        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        save_token_cache(cache)

        if not result or "access_token" not in result:
            raise RuntimeError("No se pudo renovar el acceso a Microsoft To Do, vuelve a conectar la cuenta.")
        return result["access_token"]

    def fetch_lists(self, access_token):
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(f"{GRAPH_BASE}/me/todo/lists", headers=headers, timeout=30)
        response.raise_for_status()
        return response.json().get("value", [])

    def fetch_list_and_tasks(self, access_token, list_id):
        headers = {"Authorization": f"Bearer {access_token}"}

        list_response = requests.get(f"{GRAPH_BASE}/me/todo/lists/{list_id}", headers=headers, timeout=30)
        list_response.raise_for_status()
        list_name = list_response.json().get("displayName", "")

        params = {"$filter": "status ne 'completed'", "$orderby": "createdDateTime"}
        tasks_response = requests.get(f"{GRAPH_BASE}/me/todo/lists/{list_id}/tasks", headers=headers, params=params, timeout=30)
        tasks_response.raise_for_status()
        tasks = tasks_response.json().get("value", [])

        return list_name, tasks

    def draw_tasks(self, draw, content_box, text_color, list_name, tasks):
        left, top, right, bottom = content_box
        height = bottom - top

        title_font = get_font("Jost", round(height * 0.075), font_weight="bold")
        task_font = get_font("Jost", round(height * 0.05))
        due_font = get_font("Jost", round(height * 0.038))

        draw.text((left, top), list_name or "Tareas", font=title_font, fill=text_color, anchor="la")
        body_top = top + sum(title_font.getmetrics()) * 1.5

        if not tasks:
            draw.text(((left + right) / 2, (body_top + bottom) / 2), "Sin tareas pendientes", font=task_font, fill=MUTED_GRAY, anchor="mm")
            return

        row_h = round(height * 0.11)
        circle_r = round(height * 0.014)
        text_x = left + circle_r * 4

        y = body_top
        for task in tasks:
            if y + row_h > bottom:
                break
            row_center = y + row_h / 2
            draw.circle((left + circle_r, row_center), circle_r, outline=CIRCLE_COLOR, width=max(1, round(circle_r * 0.18)))

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

    def truncate_to_width(self, draw, text, font, max_width):
        if draw.textlength(text, font=font) <= max_width:
            return text
        while text and draw.textlength(text + "…", font=font) > max_width:
            text = text[:-1]
        return text + "…"
