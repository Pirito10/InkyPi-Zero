import logging

from display.abstract_display import AbstractDisplay
from PIL import Image

logger = logging.getLogger(__name__)


def quantize_to_4_gray(image, epd_display):
    """
    Dither image down to the 4 exact gray levels a 4Gray-capable epd driver
    expects. The driver's own getbuffer_4Gray() does no dithering itself, just
    a raw truncation of each pixel's top 2 bits, so this has to be done before
    handing the image off, using the driver's own GRAY1-4 constants.
    """
    gray_levels = [epd_display.GRAY4, epd_display.GRAY3, epd_display.GRAY2, epd_display.GRAY1]
    palette_data = []
    for gray in gray_levels:
        palette_data += [gray, gray, gray]
    palette_img = Image.new('P', (1, 1))
    palette_img.putpalette(palette_data)

    gray_rgb = image.convert('L').convert('RGB')
    indexed_img = gray_rgb.quantize(palette=palette_img, dither=Image.Dither.FLOYDSTEINBERG)
    return indexed_img.convert('L')


class WaveshareDisplay(AbstractDisplay):
    """Drives the Waveshare epd7in5_V2, the only display this project supports."""

    def initialize_display(self):
        logger.info("Initializing Waveshare display")

        # Deferred import: epdconfig.py probes for real GPIO/SPI hardware at
        # import time, which fails outside a Pi. Mock mode never reaches this
        # method, so keeping the import here (not at module level) means dev
        # machines can still import display_manager without that hardware.
        from display.waveshare_epd.epd7in5_V2 import EPD

        self.epd_display = EPD()
        self.epd_display.init()

    def display_image(self, image, image_settings=[]):
        """
        Displays an image on the Waveshare display.

        The image has been processed by adjusting orientation, resizing, and converting it
        into the buffer format required for e-paper rendering.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): Additional settings to modify image rendering.

        Raises:
            ValueError: If no image is provided.
        """

        logger.info("Displaying image to Waveshare display.")
        if not image:
            raise ValueError(f"No image provided.")

        # "bw" trades the 1-bit panel's deeper black for losing gray shading
        # entirely — some prefer that contrast over 4-gray's lighter black
        # (see TODO.md). Assume device was in sleep mode either way.
        if self.device_config.get_config("color_mode") == "bw":
            self.epd_display.init()
            self.epd_display.Clear()
            self.epd_display.display(self.epd_display.getbuffer(image))
        else:
            self.epd_display.init_4Gray()
            self.epd_display.Clear()
            gray_image = quantize_to_4_gray(image, self.epd_display)
            self.epd_display.display_4Gray(self.epd_display.getbuffer_4Gray(gray_image))

        # Put device into low power mode (EPD displays maintain image when powered off)
        logger.info("Putting Waveshare display into sleep mode for power saving.")
        self.epd_display.sleep()

    def clear_and_sleep(self):
        """
        Clears the panel to white and puts it to sleep — the manufacturer's
        recommended state before disconnecting power or long-term storage
        (leaving the panel powered on with an image displayed indefinitely
        can damage it beyond repair).
        """
        logger.info("Clearing Waveshare display and putting it to sleep.")
        # Match whichever init display_image() would use, since Clear()'s
        # actual voltage sequence depends on which init set up the panel.
        if self.device_config.get_config("color_mode") == "bw":
            self.epd_display.init()
        else:
            self.epd_display.init_4Gray()
        self.epd_display.Clear()
        self.epd_display.sleep()
