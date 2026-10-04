"""
DisplayManager wraps:
  - the status LEDs, a bitmask the modes set, shown on the keys'
    NeoPixels (pixels.py)
  - Adafruit Quad Alphanumeric Display (HT16K33 14-segment, 4 chars)

LED layout:
  bits 0..NUM_PADS-1 : the pads (step on/off, pad sounding)
  LED_RECORD, LED_PLAY, LED_BEAT (config) : the status keys, above the pads

The focused mode always owns the LEDs, except that a pad frame (the channel
view's colors, set_pad_frame()) overrides the bitmask's pad bits while it's
up. The 4-char text can be held by an overlay (the menu, or code.py's
volume / LOCK / CLEAR flash) -- see hold_text().

Call update(now) once per main-loop pass: the NeoPixels are sent from
there, rate-limited.
"""

from adafruit_ht16k33 import segments

import config
import pixels

_PAD_BITS  = (1 << config.NUM_PADS) - 1
_MODE_BITS = _PAD_BITS | (1 << config.LED_RECORD) | (1 << config.LED_PLAY)   # what the modes' state readouts set


class DisplayManager:
    def __init__(self, i2c):
        self._leds = pixels.PixelLeds()
        self._led_state = 0          # bitmask, bit N = LED N, desired state
        self._led_shown = 0          # bitmask last handed to the LEDs (all off at start)
        self._pad_frame = False      # True while set_pad_frame() owns the pads

        # auto_write off: with it on, print() already sends the text and the
        # explicit show() sent it a second time. _write_text() is the one
        # place text goes out, and only when it changed.
        self._seg = segments.Seg14x4(i2c, address=config.ALPHANUM_ADDR,
                                     auto_write=False)
        self._seg.brightness = 0.5
        self._text      = None   # what the display shows now (None = unknown)
        self._text_held = False

        self.clear()

    # ── LED helpers ───────────────────────────────────────────────────────────

    def set_led(self, index, on):
        if on:
            self._led_state |= (1 << index)
        else:
            self._led_state &= ~(1 << index)
        self._flush_leds()

    def _set_leds(self, bits, values):
        """Set the LEDs in mask `bits` from `values`, leaving the rest."""
        self._led_state = (self._led_state & ~bits) | (values & bits)
        self._flush_leds()

    def _show_mode_leds(self, pad_mask, recording, playing):
        """The pads, RECORD and PLAY in one go (not the beat pulse, which
        code.py drives)."""
        status = 0
        if recording:
            status |= 1 << config.LED_RECORD
        if playing:
            status |= 1 << config.LED_PLAY
        self._set_leds(_MODE_BITS, (pad_mask & _PAD_BITS) | status)

    def clear_leds(self):
        self._led_state = 0
        self._flush_leds()

    def _flush_leds(self):
        if self._led_state == self._led_shown:
            return
        self._leds.show_mask(self._led_state, pads=not self._pad_frame)
        self._led_shown = self._led_state

    def set_pad_frame(self, frame):
        """Color every pad from `frame` (a color per pad), overriding the
        bitmask's pad bits until set_pad_frame(None) hands them back."""
        if frame is None:
            if self._pad_frame:
                self._pad_frame = False
                self._leds.show_mask(self._led_state)
                self._led_shown = self._led_state
            return
        self._pad_frame = True
        for pad in range(len(frame)):
            self._leds.set_pad(pad, frame[pad])

    def set_key_color(self, button, color):
        """Color a function key the bitmask doesn't drive (KEY MODE, CLEAR)."""
        self._leds.set_button(button, color)

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
        show_sequencer_state) only update the LEDs, leaving the text to
        whoever holds it. show() always writes."""
        self._text_held = held

    def show(self, text):
        """Display up to 4 characters, left-aligned."""
        self._write_text(f"{text:<4}"[:4])

    def _write_text(self, text):
        """Send exactly 4 characters to the display, skipping the I2C write
        (~1.7 ms at 100 kHz) if it already shows them -- the modes redraw
        on every pad flash and loop wrap, mostly with unchanged text."""
        if text == self._text:
            return
        self._text = text
        self._seg.print(text)
        self._seg.show()

    def show_mode(self, mode_name):
        self.show(mode_name)

    # ── Composite helpers used by modes ──────────────────────────────────────

    def show_sequencer_state(self, steps_mask, playhead_step, is_playing,
                             selected_track):
        """
        steps_mask    : which steps of the bar are on (bit n = step n = pad n)
        playhead_step : the step being played, or -1
        """
        pad_mask = steps_mask
        if is_playing and playhead_step >= 0:
            # The playhead is always lit, whatever the step's value
            pad_mask |= (1 << playhead_step)
        self._show_mode_leds(pad_mask, False, is_playing)

        if self._text_held:
            return
        self._write_text(f"{'T' + str(selected_track + 1):<4}")

    def show_looper_state(self, active_pads_mask, state_name, bar_count,
                          layer_num=None, synced=False, transport_playing=True):
        """active_pads_mask: pads currently/just-now sounding on the active layer.
        transport_playing: whether the global transport is actually running --
        a layer can be in PLAYING/OVERDUB content-state while paused, and the
        LED should reflect audible reality, not just that content exists."""
        self._show_mode_leds(
            active_pads_mask,
            "REC" in state_name,
            transport_playing and ("PLY" in state_name or "DUB" in state_name))

        if self._text_held:
            return
        if synced:
            self._write_text("SREC")   # snap-recording in progress
        elif state_name in ("IDLE", "PLY ") and layer_num is not None:
            # The play LED already shows PLY (and IDLE has nothing to add),
            # so show which layer the pads preview instead.
            self._write_text(f"{'L' + str(layer_num):<4}"[:4])
        else:
            self._write_text(f"{state_name:<4}"[:4])

    def clear(self):
        self.clear_leds()
        self.show("    ")
