from PIL import Image, ImageEnhance, ImageOps, ImageFilter
import os
import logging
import hashlib
import tempfile
import subprocess
import shutil

logger = logging.getLogger(__name__)

def change_orientation(image, orientation, inverted=False):
    if orientation == 'horizontal':
        angle = 0
    elif orientation == 'vertical':
        angle = 90

    if inverted:
        angle = (angle + 180) % 360

    return image.rotate(angle, expand=1)

def resize_image(image, desired_size, image_settings=[]):
    img_width, img_height = image.size
    desired_width, desired_height = desired_size
    desired_width, desired_height = int(desired_width), int(desired_height)

    img_ratio = img_width / img_height
    desired_ratio = desired_width / desired_height

    keep_width = "keep-width" in image_settings

    x_offset, y_offset = 0,0
    new_width, new_height = img_width,img_height
    # Step 1: Determine crop dimensions
    desired_ratio = desired_width / desired_height
    if img_ratio > desired_ratio:
        # Image is wider than desired aspect ratio
        new_width = int(img_height * desired_ratio)
        if not keep_width:
            x_offset = (img_width - new_width) // 2
    else:
        # Image is taller than desired aspect ratio
        new_height = int(img_width / desired_ratio)
        if not keep_width:
            y_offset = (img_height - new_height) // 2

    # Step 2: Crop the image
    image = image.crop((x_offset, y_offset, x_offset + new_width, y_offset + new_height))

    # Step 3: Resize to the exact desired dimensions (if necessary)
    return image.resize((desired_width, desired_height), Image.LANCZOS)

def apply_image_enhancement(img, image_settings={}):
    # Convert image to RGB mode if necessary for enhancement operations
    # ImageEnhance requires RGB mode for operations like blend
    if img.mode not in ('RGB', 'L'):
        img = img.convert('RGB')
        

    # Apply Brightness
    img = ImageEnhance.Brightness(img).enhance(image_settings.get("brightness", 1.0))

    # Apply Contrast
    img = ImageEnhance.Contrast(img).enhance(image_settings.get("contrast", 1.0))

    # Apply Sharpness
    img = ImageEnhance.Sharpness(img).enhance(image_settings.get("sharpness", 1.0))

    return img

def compute_image_hash(image):
    """Compute SHA-256 hash of an image."""
    image = image.convert("RGB")
    img_bytes = image.tobytes()
    return hashlib.sha256(img_bytes).hexdigest()

def take_screenshot_html(html_str, dimensions, timeout_ms=None):
    image = None
    try:
        # Create a temporary HTML file
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as html_file:
            html_file.write(html_str.encode("utf-8"))
            html_file_path = html_file.name

        image = take_screenshot(html_file_path, dimensions, timeout_ms)

        # Remove html file
        os.remove(html_file_path)

    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")

    return image

def _find_system_python():
    """The webkit_screenshot.py helper needs PyGObject (gi), which is a
    system package tied to the OS's own Python, not something the project's
    venv has (or should have)."""
    for candidate in ("/usr/bin/python3", "python3"):
        path = shutil.which(candidate) if not os.path.isabs(candidate) else (candidate if os.path.exists(candidate) else None)
        if path:
            return path
    return None


def take_screenshot(target, dimensions, timeout_ms=None):
    """Renders via WebKitGTK, since this board's CPU (ARMv6) lacks the NEON
    instructions Chromium requires. WebKitGTK runs fine here, with JIT
    disabled, via an interpreter-only JS engine — slower than Chromium but
    functional. Needs system Python (see _find_system_python) plus
    python3-gi, python3-gi-cairo, gir1.2-webkit2-4.1 and xvfb installed.
    """
    try:
        python_bin = _find_system_python()
        xvfb_run = shutil.which("xvfb-run")
        if not python_bin or not xvfb_run:
            logger.error("WebKitGTK unavailable: need system python3 and xvfb-run installed.")
            return None

        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webkit_screenshot.py")

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
            img_file_path = img_file.name

        command = [xvfb_run, "-a", python_bin, helper, target, img_file_path, str(dimensions[0]), str(dimensions[1])]
        if timeout_ms:
            command.append(str(timeout_ms))

        env = dict(os.environ, WEBKIT_DISABLE_COMPOSITING_MODE="1", LIBGL_ALWAYS_SOFTWARE="1")
        # WebKitGTK is much slower than Chromium here (interpreter-only JS), so
        # give it a generous ceiling regardless of the caller's timeout_ms.
        result = subprocess.run(command, capture_output=True, check=False, env=env, timeout=120)

        if result.returncode != 0 or not os.path.exists(img_file_path):
            logger.error(f"Failed to take screenshot via WebKitGTK (return code: {result.returncode}): {result.stderr.decode(errors='replace')}")
            return None

        with Image.open(img_file_path) as img:
            image = img.copy()
        os.remove(img_file_path)
        return image

    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")
        return None

def pad_image_blur(img: Image, dimensions: tuple[int, int]) -> Image:
    bkg = ImageOps.fit(img, dimensions)
    bkg = bkg.filter(ImageFilter.BoxBlur(8))
    img = ImageOps.contain(img, dimensions)

    img_size = img.size
    bkg.paste(img, ((dimensions[0] - img_size[0]) // 2, (dimensions[1] - img_size[1]) // 2))
    return bkg
