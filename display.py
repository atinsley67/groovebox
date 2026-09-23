"""
DisplayManager wraps:
  - Adafruit AW9523 (16-channel GPIO/LED driver) — LEDs 0-15
  - Adafruit Quad Alphanumeric Display (HT16K33 14-segment, 4 chars)

AW9523 LED layout:
  LEDs  0-7  : primary row  (step on/off, pad-in-loop state)
  LEDs  8-15 : status row   (record, play, beat pulse, sequencer position)
"""

import adafruit_aw9523
from adafruit_ht16k33 import segments

import config


class DisplayManager:
    def __init__(self, i2c):
        self._aw = adafruit_aw9523.AW9523(i2c, address=config.LED_DRIVER_ADDR)
        # All 16 pins in constant-current LED mode (driven via set_constant_current,
        # not the GPIO output register)
        self._aw.LED_modes = 0xFFFF
        self._aw.directions = 0xFFFF
        self._led_state = 0x0000     # bitmask, bit N = LED N, desired state
        self._led_hw_state = 0x0000  # bitmask reflecting what's currently on the wire

        self._seg = segments.Seg14x4(i2c, address=config.ALPHANUM_ADDR)
        self._seg.brightness = 0.5

        self.clear()

    # ── LED helpers ───────────────────────────────────────────────────────────

    def set_led(self, index, on):
        if on:
            self._led_state |= (1 << index)
        else:
            self._led_state &= ~(1 << index)
        self._flush_leds()

    def set_leds_lower(self, bitmask8):
        """Set LEDs 0-7 from the low 8 bits of bitmask8."""
        self._led_state = (self._led_state & 0xFF00) | (bitmask8 & 0x00FF)
        self._flush_leds()

    def set_leds_upper(self, bitmask8):
        """Set LEDs 8-15 from the low 8 bits of bitmask8."""
        self._led_state = (self._led_state & 0x00FF) | ((bitmask8 & 0xFF) << 8)
        self._flush_leds()

    def clear_leds(self):
        self._led_state = 0x0000
        self._flush_leds()

    def _flush_leds(self):
        """AW9523 has no bulk register for constant-current mode (the `outputs`
        register only drives pins in plain GPIO mode), so each LED has to be
        pushed individually via set_constant_current. Only push the ones whose
        on/off state actually changed since the last flush."""
        changed = self._led_state ^ self._led_hw_state
        if not changed:
            return
        for i in range(16):
            if changed & (1 << i):
                self._aw.set_constant_current(i, 100 if self._led_state & (1 << i) else 0)
        self._led_hw_state = self._led_state

    # ── Alphanumeric display helpers ──────────────────────────────────────────

    def show(self, text):
        """Display up to 4 characters, left-aligned."""
        self._seg.print(f"{text:<4}"[:4])
        self._seg.show()

    def show_bpm(self, bpm):
        self._seg.print(f"b{bpm:3d}")
        self._seg.show()

    def show_mode(self, mode_name):
        self.show(mode_name)

    # ── Composite helpers used by modes ──────────────────────────────────────

    def show_sequencer_state(self, steps_bitmask8, current_step_in_page,
                             is_playing, selected_track, page):
        """
        steps_bitmask8 : which of the 8 displayed steps are on
        current_step_in_page : 0-7, which step the playhead is on (or -1)
        """
        # Lower LEDs: step on/off, with playhead blink handled by caller
        display_mask = steps_bitmask8
        if is_playing and current_step_in_page >= 0:
            # Playhead LED overrides: always lit regardless of step value
            display_mask |= (1 << current_step_in_page)
        self.set_leds_lower(display_mask)

        # Upper LEDs: record/play status
        upper = 0
        if is_playing:
            upper |= (1 << (config.LED_PLAY - 8))
        self.set_leds_upper(upper)

        # Display: track number and page
        self._seg.print(f"T{selected_track + 1}P{page + 1}")
        self._seg.show()

    def show_looper_state(self, active_pads_mask, state_name, bar_count,
                          layer_num=None, synced=False, transport_playing=True):
        """active_pads_mask: pads currently/just-now sounding on the active layer.
        transport_playing: whether the global transport is actually running --
        a layer can be in PLAYING/OVERDUB content-state while paused, and the
        LED should reflect audible reality, not just that content exists."""
        self.set_leds_lower(active_pads_mask)

        upper = 0
        if "REC" in state_name:
            upper |= (1 << (config.LED_RECORD - 8))
        if transport_playing and ("PLY" in state_name or "DUB" in state_name):
            upper |= (1 << (config.LED_PLAY - 8))
        self.set_leds_upper(upper)

        if synced:
            self._seg.print("SREC")   # snap-recording in progress
        elif state_name in ("IDLE", "PLY ") and layer_num is not None:
            # The play LED already shows PLY (and IDLE has nothing to add),
            # so show which layer the pads preview instead.
            self._seg.print(f"{'L' + str(layer_num):<4}"[:4])
        else:
            self._seg.print(f"{state_name:<4}"[:4])
        self._seg.show()

    def clear(self):
        self.clear_leds()
        self.show("    ")
