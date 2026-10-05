"""
DisplayManager wraps:
  - the keys' NeoPixels (pixels.py): a color per pad, set a frame at a
    time (pad_views.py draws them; code.py sends the active view's), and a
    color per function key (code.py's key lights)
  - Adafruit Quad Alphanumeric Display (HT16K33 14-segment, 4 chars)

The modes write the 4-char text (show_looper_state / show_sequencer_state);
an overlay can hold it (the menu, or code.py's volume / LOCK / CLEAR
flash) -- see hold_text().

Call update(now) once per main-loop pass: the NeoPixels are sent from
there, rate-limited.
"""

from adafruit_ht16k33 import segments

import config
import palette
import pixels


class DisplayManager:
    def __init__(self, i2c):
        self._leds = pixels.PixelLeds()

        # auto_write off: with it on, print() already sends the text and the
        # explicit show() sent it a second time. _write_text() is the one
        # place text goes out, and only when it changed.
        self._seg = segments.Seg14x4(i2c, address=config.ALPHANUM_ADDR,
                                     auto_write=False)
        self._seg.brightness = 0.5
        self._text      = None   # what the display shows now (None = unknown)
        self._text_held = False

        self.clear()

    # ── LEDs ──────────────────────────────────────────────────────────────────

    def set_pad_frame(self, frame):
        """Color the pads from `frame`, a color per pad (pad n = frame[n])."""
        for pad in range(len(frame)):
            self._leds.set_pad(pad, frame[pad])

    def set_key_color(self, button, color):
        """Color a function key by button id."""
        self._leds.set_button(button, color)

    def clear_leds(self):
        for pad in range(config.NUM_PADS):
            self._leds.set_pad(pad, palette.OFF)
        for row in config.FUNC_LAYOUT:
            for button in row:
                self._leds.set_button(button, palette.OFF)

    def update(self, now=None):
        """Send pending LED changes. Pass the main loop's `now` (sends are
        then rate-limited); without it they go out right away."""
        self._leds.update(now)

    @property
    def pixels(self):
        """The keys' pixels.PixelLeds, for direct access (io_test.py)."""
        return self._leds

    # ── Alphanumeric display helpers ──────────────────────────────────────────

    def hold_text(self, held):
        """While held, the modes' state readouts (show_looper_state /
        show_sequencer_state) write nothing, leaving the text to whoever
        holds it. show() always writes."""
        self._text_held = held

    def show(self, text):
        """Display up to 4 characters, left-aligned."""
        self._write_text(f"{text:<4}"[:4])

    def _write_text(self, text):
        """Send exactly 4 characters to the display, skipping the I2C write
        (~1.7 ms at 100 kHz) if it already shows them -- the modes redraw
        on every pad press and loop wrap, mostly with unchanged text."""
        if text == self._text:
            return
        self._text = text
        self._seg.print(text)
        self._seg.show()

    def show_mode(self, mode_name):
        self.show(mode_name)

    # ── Composite helpers used by modes ──────────────────────────────────────

    def show_sequencer_state(self, selected_track):
        if self._text_held:
            return
        self._write_text(f"{'T' + str(selected_track + 1):<4}")

    def show_looper_state(self, state_name, layer_num=None, synced=False):
        if self._text_held:
            return
        if synced:
            self._write_text("SREC")   # snap-recording in progress
        elif state_name in ("IDLE", "PLY ") and layer_num is not None:
            # The PLAY/STOP light already shows playing (and IDLE has
            # nothing to add), so show which layer the pads play instead.
            self._write_text(f"{'L' + str(layer_num):<4}"[:4])
        else:
            self._write_text(f"{state_name:<4}"[:4])

    def clear(self):
        self.clear_leds()
        self.show("    ")
