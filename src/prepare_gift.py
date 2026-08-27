#!/usr/bin/env python3

"""
Final step before wrapping the gift up: paints the "Feliz aniversario" screen
directly on the e-paper and re-arms the startup flag, so the next real boot of
the service (when the recipient plugs it in) automatically shows the setup
screen.

Usage (on the Pi, WITHOUT --dev). Needs root - device.json and
current_image.png are owned by root (the service itself runs as root), so a
plain user hits a PermissionError. Plain `sudo python` drops the venv from
PATH, so call the venv's interpreter explicitly:
    cd /usr/local/inkypi/src
    sudo /usr/local/inkypi/venv_inkypi/bin/python prepare_gift.py

Run this only after the inkypi service is stopped (`sudo systemctl stop
inkypi`) - if it's left running, its next scheduled refresh will write its own
(stale, in-memory) config back to disk and silently undo the flag this script
just set. This script itself checks for that and refuses to run if the
service is still active.
"""

import logging.config
import os
import subprocess
import sys

logging.config.fileConfig(os.path.join(os.path.dirname(__file__), 'config', 'logging.conf'))

try:
    service_active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "inkypi"]
    ).returncode == 0
except FileNotFoundError:
    service_active = False  # no systemd here (e.g. running outside the Pi) - proceed

if service_active:
    print("The inkypi service is still running - stop it first:")
    print("  sudo systemctl stop inkypi")
    print("(otherwise its next refresh can overwrite the flag this script sets)")
    sys.exit(1)

from config import Config
from display.display_manager import DisplayManager
from utils.app_utils import generate_gift_ready_image

device_config = Config()
display_manager = DisplayManager(device_config)

img = generate_gift_ready_image(device_config.get_resolution())
display_manager.display_image(img)

device_config.update_value("startup", True, write=True)

print("Gift screen displayed and startup flag re-armed.")
print("The next time the service starts, the setup screen will show automatically.")
