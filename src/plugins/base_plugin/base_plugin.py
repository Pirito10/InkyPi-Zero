import logging
import os
from utils.app_utils import resolve_path, get_fonts
from utils.image_utils import take_screenshot_html
from utils.image_loader import AdaptiveImageLoader
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pathlib import Path
from PIL import Image, ImageDraw
import asyncio
import base64

logger = logging.getLogger(__name__)

STATIC_DIR = resolve_path("static")
PLUGINS_DIR = resolve_path("plugins")
BASE_PLUGIN_DIR =  os.path.join(PLUGINS_DIR, "base_plugin")
BASE_PLUGIN_RENDER_DIR = os.path.join(BASE_PLUGIN_DIR, "render")

FRAME_STYLES = [
    {
        "name": "None",
        "icon": "frames/blank.png"
    },
    {
        "name": "Corner",
        "icon": "frames/corner.png"
    },
    {
        "name": "Top and Bottom",
        "icon": "frames/top_and_bottom.png"
    },
    {
        "name": "Rectangle",
        "icon": "frames/rectangle.png"
    }
]

class BasePlugin:
    """Base class for all plugins."""
    def __init__(self, config, **dependencies):
        self.config = config

        # Initialize adaptive image loader for device-aware image processing
        self.image_loader = AdaptiveImageLoader()

        self.render_dir = self.get_plugin_dir("render")
        if os.path.exists(self.render_dir):
            # instantiate jinja2 env with base plugin and current plugin render directories
            loader = FileSystemLoader([self.render_dir, BASE_PLUGIN_RENDER_DIR])
            self.env = Environment(
                loader=loader,
                autoescape=select_autoescape(['html', 'xml'])
            )

    def generate_image(self, settings, device_config):
        raise NotImplementedError("generate_image must be implemented by subclasses")

    def cleanup(self, settings):
        """Optional cleanup method that plugins can override to delete associated resources.

        Called when a plugin instance is deleted. Plugins should override this to clean up
        any files, external resources, or other data associated with the plugin instance.

        Args:
            settings: The plugin instance's settings dict, which may contain file paths or other resources
        """
        pass  # Default implementation does nothing

    def get_plugin_id(self):
        return self.config.get("id")

    def get_plugin_dir(self, path=None):
        plugin_dir = os.path.join(PLUGINS_DIR, self.get_plugin_id())
        if path:
            plugin_dir = os.path.join(plugin_dir, path)
        return plugin_dir

    def generate_settings_template(self):
        template_params = {"settings_template": "base_plugin/settings.html"}

        settings_path = self.get_plugin_dir("settings.html")
        if Path(settings_path).is_file():
            template_params["settings_template"] = f"{self.get_plugin_id()}/settings.html"

        template_params['frame_styles'] = FRAME_STYLES
        return template_params

    def render_image(self, dimensions, html_file, css_file=None, template_params={}):
        # load the base plugin and current plugin css files
        css_files = [os.path.join(BASE_PLUGIN_RENDER_DIR, "plugin.css")]
        if css_file:
            plugin_css = os.path.join(self.render_dir, css_file)
            css_files.append(plugin_css)

        template_params["style_sheets"] = css_files
        template_params["width"] = dimensions[0]
        template_params["height"] = dimensions[1]
        template_params["font_faces"] = get_fonts()
        template_params["static_dir"] = STATIC_DIR

        # load and render the given html template
        template = self.env.get_template(html_file)
        rendered_html = template.render(template_params)

        return take_screenshot_html(rendered_html, dimensions)

    def render_image_pil(self, dimensions, settings, draw_content):
        """
        PIL-based alternative to render_image(), for plugins that draw
        directly instead of rendering HTML/CSS through a browser. Applies
        the same Style options (frame, margin, background, text color) that
        render/plugin.html applies for the browser-rendered plugins, then
        calls draw_content(draw, content_box, text_color) to draw the
        plugin-specific content, where content_box = (left, top, right,
        bottom) is the drawable area inside the frame/margins/padding.
        """
        width, height = dimensions
        text_color = settings.get("textColor") or "#000000"

        if settings.get("backgroundOption") == "image" and settings.get("backgroundImageFile"):
            image = Image.open(settings["backgroundImageFile"]).convert("RGB")
            image = image.resize((width, height))
        else:
            background_color = settings.get("backgroundColor") or "#ffffff"
            image = Image.new("RGB", (width, height), background_color)

        draw = ImageDraw.Draw(image)

        default_margin = 5
        top = int(settings.get("topMargin") or settings.get("margin") or default_margin)
        bottom = int(settings.get("bottomMargin") or settings.get("margin") or default_margin)
        left = int(settings.get("leftMargin") or settings.get("margin") or default_margin)
        right = int(settings.get("rightMargin") or settings.get("margin") or default_margin)
        outer_box = (left, top, width - right, height - bottom)

        frame = settings.get("selectedFrame")
        frame_width = max(2, round(width * 0.007))
        l, t, r, b = outer_box
        if frame == "Rectangle":
            draw.rectangle(outer_box, outline=text_color, width=frame_width)
        elif frame == "Top and Bottom":
            draw.line([(l, t), (r, t)], fill=text_color, width=frame_width)
            draw.line([(l, b), (r, b)], fill=text_color, width=frame_width)
        elif frame == "Corner":
            corner_size = round(width * 0.10)
            draw.line([(l, t), (l + corner_size, t)], fill=text_color, width=frame_width)
            draw.line([(l, t), (l, t + corner_size)], fill=text_color, width=frame_width)
            draw.line([(r - corner_size, b), (r, b)], fill=text_color, width=frame_width)
            draw.line([(r, b - corner_size), (r, b)], fill=text_color, width=frame_width)

        padding = round(width * 0.015)
        content_box = (l + padding, t + padding, r - padding, b - padding)

        draw_content(draw, content_box, text_color)

        return image
