"""
Image Loader for InkyPi

Loads a local image file and resizes it for display, using PIL's draft
mode to keep memory usage low while decoding on the Pi Zero W's 512MB RAM.
"""

from PIL import Image, ImageOps
import logging
import gc
import os

logger = logging.getLogger(__name__)


class ImageLoader:
    """
    Usage:
        loader = ImageLoader()
        image = loader.from_file("/path/to/image.jpg", (800, 480))
    """

    def from_file(self, path, dimensions, resize=True):
        """
        Load an image from a local file and optionally resize it.

        Args:
            path: Path to local image file
            dimensions: Target dimensions as (width, height)
            resize: Whether to resize the image (default True)

        Returns:
            PIL Image object resized to dimensions, or None on error
        """
        logger.debug(f"Loading image from file: {path}")

        if not os.path.exists(path):
            logger.error(f"File not found: {path}")
            return None

        try:
            img = Image.open(path)
            original_size = img.size
            original_pixels = original_size[0] * original_size[1]
            logger.info(f"Loaded image: {original_size[0]}x{original_size[1]} ({img.mode} mode, {original_pixels/1_000_000:.1f}MP)")

            if resize:
                # Apply draft mode for massive memory savings during decode
                img.draft('RGB', (dimensions[0] * 2, dimensions[1] * 2))
                img.load()
                logger.debug(f"Image decoded: {img.size[0]}x{img.size[1]} (draft mode reduced from {original_size[0]}x{original_size[1]})")

                img = self._process_and_resize(img, dimensions, original_size)
            else:
                # Even without resizing, apply EXIF orientation correction
                img = ImageOps.exif_transpose(img)
                if img.size != original_size:
                    logger.debug(f"EXIF orientation applied: {original_size[0]}x{original_size[1]} -> {img.size[0]}x{img.size[1]}")

            return img

        except MemoryError as e:
            logger.error(f"Out of memory while loading {path}: {e}")
            logger.error("Try using a smaller image or enabling more swap space")
            gc.collect()
            return None
        except Exception as e:
            logger.error(f"Error loading image from {path}: {e}")
            return None

    def _process_and_resize(self, img, dimensions, original_size):
        """
        Process and resize image.

        Args:
            img: PIL Image object
            dimensions: Target dimensions (width, height)
            original_size: Original image size for logging

        Returns:
            Processed and resized PIL Image
        """
        # Apply EXIF orientation correction first (before any processing)
        # This handles images from cameras/phones that store rotation in EXIF metadata
        # Safe to call on any image - returns unchanged if no EXIF data present
        img = ImageOps.exif_transpose(img)
        if img.size != original_size:
            logger.debug(f"EXIF orientation applied: {original_size[0]}x{original_size[1]} -> {img.size[0]}x{img.size[1]}")

        # Convert to RGB if necessary (removes alpha channel, saves memory)
        # E-ink displays don't need alpha channel anyway
        if img.mode in ('RGBA', 'LA', 'P'):
            logger.debug(f"Converting image from {img.mode} to RGB")
            img = img.convert('RGB')

        # For very large images, use two-stage resize
        if img.size[0] > dimensions[0] * 2 or img.size[1] > dimensions[1] * 2:
            logger.debug(f"Image is {img.size[0]}x{img.size[1]}, using two-stage resize")

            # Stage 1: Aggressive downsample using thumbnail (in-place, very memory efficient)
            aspect = img.size[0] / img.size[1]
            if aspect > 1:  # Landscape
                intermediate_size = (dimensions[0] * 2, int(dimensions[0] * 2 / aspect))
            else:  # Portrait
                intermediate_size = (int(dimensions[1] * 2 * aspect), dimensions[1] * 2)

            logger.debug(f"Stage 1: Downsampling to ~{intermediate_size[0]}x{intermediate_size[1]} using NEAREST")
            img.thumbnail(intermediate_size, Image.NEAREST)
            logger.debug(f"Stage 1 complete: {img.size[0]}x{img.size[1]}")
            gc.collect()

            # Stage 2: High-quality resize to exact dimensions
            logger.debug(f"Stage 2: Final resize to {dimensions[0]}x{dimensions[1]} using LANCZOS")
            img = ImageOps.fit(img, dimensions, method=Image.LANCZOS)
            logger.debug(f"Stage 2 complete: {dimensions[0]}x{dimensions[1]}")
        else:
            # Direct resize with BICUBIC (fast, sufficient quality for e-ink)
            logger.debug(f"Resizing directly from {img.size[0]}x{img.size[1]} to {dimensions[0]}x{dimensions[1]}")
            img = ImageOps.fit(img, dimensions, method=Image.BICUBIC)

        # Explicit garbage collection
        gc.collect()
        logger.debug("Garbage collection completed")
        logger.info(f"Image processing complete: {dimensions[0]}x{dimensions[1]}")

        return img
