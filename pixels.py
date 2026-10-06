"""
The keys' NeoPixels: one strip under the pad grid, one under the
function block, each on its own data pin (config.PAD_PIXEL_PIN /
FUNC_PIXEL_PIN), capped at config.PIXEL_BRIGHTNESS.

Colors are buffered and pushed by update(): a strip is only sent when one
of its pixels changed, at most every _PUSH_INTERVAL -- each send briefly
blocks the main loop, and LED changes can come many times a frame.
"""

import neopixel

import config
import keymap
import palette

_PUSH_INTERVAL = 1 / 60   # seconds: at most ~60 sends per second per strip


class _Strip:
    """One NeoPixel strip, plus the last color set per pixel (to skip sends
    that would change nothing) and whether it needs sending."""

    def __init__(self, pin, count):
        self.pixels = neopixel.NeoPixel(pin, count, brightness=config.PIXEL_BRIGHTNESS,
                                        auto_write=False)
        self.colors = [palette.OFF] * count
        self.dirty  = False
        # Pixels keep whatever they last showed (or power up random): clear.
        self.pixels.fill(palette.OFF)
        self.pixels.show()

    def set(self, pixel, color):
        if self.colors[pixel] != color:
            self.colors[pixel] = color
            self.pixels[pixel] = color
            self.dirty = True

    def send(self):
        if self.dirty:
            self.pixels.show()
            self.dirty = False


class PixelLeds:
    def __init__(self):
        self._pads = _Strip(config.PAD_PIXEL_PIN, keymap.NUM_PAD_KEYS)
        self._func = _Strip(config.FUNC_PIXEL_PIN, keymap.NUM_FUNC_KEYS)
        self._next_push = 0.0

    # ── Setting colors (buffered until update()) ──────────────────────────────

    def set_pad(self, pad, color):
        """Color the key of pad `pad` (its position, see keymap.py)."""
        self._pads.set(keymap.PAD_PIXEL[pad], color)

    def set_button(self, button, color):
        """Color a function key by button id; unassigned ids are ignored."""
        pixel = keymap.FUNC_PIXEL_OF_BUTTON.get(button)
        if pixel is not None:
            self._func.set(pixel, color)

    def set_raw(self, strip_name, pixel, color):
        """For io_test.py: color a pixel by its index on "pad" or "func"."""
        (self._pads if strip_name == "pad" else self._func).set(pixel, color)

    # ── Sending ───────────────────────────────────────────────────────────────

    def update(self, now=None):
        """Send any strip whose colors changed. With `now` (the main loop),
        at most every _PUSH_INTERVAL -- the rest waits for a later call;
        without (startup, io_test), right away."""
        if not (self._pads.dirty or self._func.dirty):
            return
        if now is not None:
            if now < self._next_push:
                return
            self._next_push = now + _PUSH_INTERVAL
        self._pads.send()
        self._func.send()
