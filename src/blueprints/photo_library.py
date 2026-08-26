from flask import Blueprint, request, jsonify, current_app, render_template
from utils.app_utils import resolve_path
from PIL import Image, ImageOps
from urllib.parse import quote
import os
import logging

logger = logging.getLogger(__name__)
photo_library_bp = Blueprint("photo_library", __name__)

ALLOWED_EXTENSIONS = {'pdf', 'png', 'avif', 'jpg', 'jpeg', 'gif', 'webp', 'heif', 'heic'}


def get_library_dir():
    library_dir = resolve_path(os.path.join("static", "images", "saved"))
    os.makedirs(library_dir, exist_ok=True)
    return library_dir


def unique_file_path(library_dir, file_name):
    """Avoid silently overwriting an existing library photo of the same name."""
    file_path = os.path.join(library_dir, file_name)
    if not os.path.exists(file_path):
        return file_path

    base, extension = os.path.splitext(file_name)
    counter = 1
    while os.path.exists(file_path):
        file_path = os.path.join(library_dir, f"{base} ({counter}){extension}")
        counter += 1
    return file_path


def build_photo_usage_map():
    """Map each photo path in use to the list of 'instance (playlist)' names using it."""
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    usage_map = {}
    for playlist in playlist_manager.playlists:
        for plugin_instance in playlist.plugins:
            if plugin_instance.plugin_id != "image_upload":
                continue
            label = f"{plugin_instance.name} ({playlist.name})"
            for file_path in (plugin_instance.settings.get("imageFiles[]") or []):
                usage_map.setdefault(file_path, []).append(label)
    return usage_map


def photo_info(file_path, used_by=None):
    return {
        "filename": os.path.basename(file_path),
        "path": file_path,
        "url": f"/static/images/saved/{quote(os.path.basename(file_path))}",
        "mtime": os.path.getmtime(file_path),
        "used_by": used_by or []
    }


def list_library_photos():
    library_dir = get_library_dir()
    usage_map = build_photo_usage_map()
    photos = []
    for file_name in os.listdir(library_dir):
        extension = os.path.splitext(file_name)[1].replace('.', '').lower()
        if extension not in ALLOWED_EXTENSIONS:
            continue
        file_path = os.path.join(library_dir, file_name)
        photos.append(photo_info(file_path, usage_map.get(file_path)))
    photos.sort(key=lambda p: p["mtime"], reverse=True)
    return photos


@photo_library_bp.route('/photo-library')
def photo_library_page():
    return render_template('photo_library.html', photos=list_library_photos())


@photo_library_bp.route('/photo-library/upload', methods=['POST'])
def photo_library_upload():
    library_dir = get_library_dir()
    saved = []

    for file in request.files.getlist('photos[]'):
        file_name = file.filename
        if not file_name:
            continue

        extension = os.path.splitext(file_name)[1].replace('.', '')
        if not extension or extension.lower() not in ALLOWED_EXTENSIONS:
            continue

        file_name = os.path.basename(file_name)
        file_path = unique_file_path(library_dir, file_name)
        file_name = os.path.basename(file_path)

        if extension.lower() in {'jpg', 'jpeg'}:
            try:
                with Image.open(file) as img:
                    img = ImageOps.exif_transpose(img)
                    img.save(file_path)
            except Exception as e:
                logger.warning(f"EXIF processing error for {file_name}: {e}")
                file.save(file_path)
        else:
            file.save(file_path)

        saved.append(photo_info(file_path))

    return jsonify({"success": True, "saved": saved})


@photo_library_bp.route('/photo-library/delete', methods=['POST'])
def photo_library_delete():
    data = request.get_json() or {}
    file_name = os.path.basename(data.get("filename", ""))
    if not file_name:
        return jsonify({"error": "Falta el nombre del archivo"}), 400

    library_dir = get_library_dir()
    file_path = os.path.join(library_dir, file_name)

    if not os.path.isfile(file_path):
        return jsonify({"error": "La foto no existe"}), 404

    users = build_photo_usage_map().get(file_path, [])
    if users:
        return jsonify({
            "error": f"Esta foto está en uso en: {', '.join(users)}. Quítala de ahí antes de borrarla."
        }), 400

    try:
        os.remove(file_path)
    except Exception as e:
        logger.warning(f"Failed to delete photo {file_path}: {e}")
        return jsonify({"error": "No se pudo borrar la foto"}), 500

    return jsonify({"success": True})
