import logging
import os
import socket

from functools import lru_cache
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger(__name__)

FONT_FAMILIES = {
    "Jost": [{
        "font-weight": "normal",
        "file": "Jost.ttf"
    },{
        "font-weight": "bold",
        "file": "Jost-SemiBold.ttf"
    }],
    "Napoli": [{
        "font-weight": "normal",
        "file": "Napoli.ttf"
    }],
    "DS-Digital": [{
        "font-weight": "normal",
        "file": os.path.join("DS-DIGI", "DS-DIGI.TTF")
    }]
}

def resolve_path(file_path):
    src_dir = os.getenv("SRC_DIR")
    if src_dir is None:
        # Default to the src directory
        src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    src_path = Path(src_dir)
    return str(src_path / file_path)

def get_ip_address():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("8.8.8.8", 80))
        ip_address = s.getsockname()[0]
    return ip_address

@lru_cache(maxsize=None)
def get_font(font_name, font_size=50, font_weight="normal"):
    if font_name in FONT_FAMILIES:
        font_variants = FONT_FAMILIES[font_name]

        font_entry = next((entry for entry in font_variants if entry["font-weight"] == font_weight), None)
        if font_entry is None:
            font_entry = font_variants[0]  # Default to first available variant

        if font_entry:
            font_path = resolve_path(os.path.join("static", "fonts", font_entry["file"]))
            return ImageFont.truetype(font_path, font_size)
        else:
            logger.warning(f"Requested font weight not found: font_name={font_name}, font_weight={font_weight}")
    else:
        logger.warning(f"Requested font not found: font_name={font_name}")

    return None

def get_fonts():
    fonts_list = []
    for font_family, variants in FONT_FAMILIES.items():
        for variant in variants:
            fonts_list.append({
                "font_family": font_family,
                "url": resolve_path(os.path.join("static", "fonts", variant["file"])),
                "font_weight": variant.get("font-weight", "normal"),
                "font_style": variant.get("font-style", "normal"),
            })
    return fonts_list

def _draw_centered_message(dimensions, title, subtitle_lines, title_font_size_ratio=0.11):
    bg_color = (255, 255, 255)
    text_color = (0, 0, 0)
    width, height = dimensions

    image = Image.new("RGBA", dimensions, bg_color)
    image_draw = ImageDraw.Draw(image)

    title_font = get_font("Jost", width * title_font_size_ratio, "bold")
    subtitle_font_size = width * 0.032
    subtitle_font = get_font("Jost", subtitle_font_size)

    title_bbox = image_draw.textbbox((0, 0), title, font=title_font)
    title_height = title_bbox[3] - title_bbox[1]
    line_height = subtitle_font_size * 1.35
    subtitle_block_height = line_height * len(subtitle_lines)
    gap = height * 0.06

    # Center title + gap + subtitle block as one unit, instead of anchoring
    # the title to height/2 and the subtitle to height*3/4 independently -
    # that left the whole block visually shifted toward the bottom.
    total_height = title_height + gap + subtitle_block_height
    top = (height - total_height) / 2

    title_center_y = top + title_height / 2
    image_draw.text((width/2, title_center_y), title, anchor="mm", fill=text_color, font=title_font)

    subtitle_top = top + title_height + gap
    for i, line in enumerate(subtitle_lines):
        line_center_y = subtitle_top + line_height * i + line_height / 2
        image_draw.text((width/2, line_center_y), line, anchor="mm", fill=text_color, font=subtitle_font)

    return image

def generate_gift_ready_image(dimensions=(800, 480)):
    """First screen: kept on the display while unplugged, before the gift is wrapped up."""
    return _draw_centered_message(dimensions, "Feliz aniversario", ["Enchúfame y espera instrucciones"])

def generate_startup_image(dimensions=(800, 480)):
    """Second screen: shown automatically on the recipient's first real boot (see the
    'startup' config flag in inkypi.py) - tells them how to reach the web UI."""
    hostname = socket.gethostname()
    return _draw_centered_message(dimensions, "¡Ya casi está!",
                                   [f"Entra a http://{hostname}.local", "desde el navegador de tu ordenador y configúrame"],
                                   title_font_size_ratio=0.09)

def parse_form(request_form):
    request_dict = request_form.to_dict()
    for key in request_form.keys():
        if key.endswith('[]'):
            request_dict[key] = request_form.getlist(key)
    return request_dict

def handle_request_files(request_files, form_data=None):
    form_data = form_data or {}
    allowed_file_extensions = {'png', 'avif', 'jpg', 'jpeg', 'gif', 'webp', 'heif', 'heic'}
    file_location_map = {}
    # handle existing file locations being provided as part of the form data
    for key in set(request_files.keys()):
        is_list = key.endswith('[]')
        if key in form_data:
            file_location_map[key] = form_data.getlist(key) if is_list else form_data.get(key)
    # add new files in the request
    for key, file in request_files.items(multi=True):
        is_list = key.endswith('[]')
        file_name = file.filename
        if not file_name:
            continue

        extension = os.path.splitext(file_name)[1].replace('.', '')
        if not extension or extension.lower() not in allowed_file_extensions:
            continue

        file_name = os.path.basename(file_name)

        file_save_dir = resolve_path(os.path.join("static", "images", "saved"))
        file_path = os.path.join(file_save_dir, file_name)

        # Open the image and apply EXIF transformation before saving
        if extension in {'jpg', 'jpeg'}:
            try:
                with Image.open(file) as img:
                    img = ImageOps.exif_transpose(img)
                    img.save(file_path)
            except Exception as e:
                logger.warning(f"EXIF processing error for {file_name}: {e}")
                file.save(file_path)
        else:
            # Directly save non-JPEG files
            file.save(file_path)

        if is_list:
            file_location_map.setdefault(key, [])
            file_location_map[key].append(file_path)
        else:
            file_location_map[key] = file_path
    return file_location_map
