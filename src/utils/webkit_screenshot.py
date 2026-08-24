#!/usr/bin/env python3
"""Standalone HTML-to-PNG screenshot helper using WebKitGTK.

Runs under the system Python (needs PyGObject/gi, not the project venv) and
a virtual display (Xvfb), since neither GTK nor WebKitGTK can render without
some display server, even for an off-screen capture. Used as a fallback for
take_screenshot() in image_utils.py on hardware where no Chromium-based
browser is available (e.g. ARMv6 boards, which Chromium has dropped support
for since it requires NEON).

Usage: webkit_screenshot.py <html_file> <out_png> <width> <height> [timeout_ms]
"""
import sys
import time

import cairo
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gtk, WebKit2, GLib


def main():
    if len(sys.argv) < 5:
        print("Usage: webkit_screenshot.py <html_file> <out_png> <width> <height> [timeout_ms]", file=sys.stderr)
        return 2

    html_path = sys.argv[1]
    out_path = sys.argv[2]
    width = int(sys.argv[3])
    height = int(sys.argv[4])
    timeout_ms = int(sys.argv[5]) if len(sys.argv) > 5 else 90000

    win = Gtk.Window()
    win.set_default_size(width, height)
    webview = WebKit2.WebView()
    webview.set_size_request(width, height)
    win.add(webview)
    win.show_all()

    loop = GLib.MainLoop()
    result = {}

    def on_load_changed(webview, event):
        if event == WebKit2.LoadEvent.FINISHED:
            # Let layout/JS settle (e.g. FullCalendar rendering) before capturing.
            GLib.timeout_add(500, take_snapshot)

    def take_snapshot():
        webview.get_snapshot(WebKit2.SnapshotRegion.VISIBLE, WebKit2.SnapshotOptions.NONE, None, on_snapshot_ready, None)
        return False

    def on_snapshot_ready(webview, res, data):
        try:
            surface = webview.get_snapshot_finish(res)
            surface.write_to_png(out_path)
            result['ok'] = True
        except Exception as e:
            result['error'] = str(e)
        loop.quit()

    def on_load_failed(webview, event, failing_uri, error):
        result['error'] = f"load failed: {error}"
        loop.quit()
        return True

    webview.connect('load-changed', on_load_changed)
    webview.connect('load-failed', on_load_failed)
    webview.load_uri(f"file://{html_path}")

    GLib.timeout_add(timeout_ms, loop.quit)
    loop.run()

    if not result.get('ok'):
        print(f"Screenshot failed: {result.get('error', 'timed out')}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
