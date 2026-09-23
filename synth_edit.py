"""
SynthEditMode — live sound-editing overlay for melodic voices and drum/kit
sounds.

Not a top-level mode like LooperMode/SequencerMode; it's a temporary
overlay toggled by BTN_SYNTH_EDIT, usable from SEQ mode (edits the
selected track's drum/kit sound, synth_params.DRUM_PARAM_SCHEMA) or from
LOOP mode while a melodic layer (config.NUM_KIT_LAYERS..7) is active
(edits that layer's voice, synth_params.PARAM_SCHEMA). It always resolves
its target live via _edit_target() -- never a cached copy -- so cycling
layers/tracks, or switching LOOP<->SEQ, while editing retargets it on the
fly; code.py exits the overlay automatically only if you land on the
looper's kit layer, the one context with nothing to edit (its sound is
whatever was last edited from SEQ).

UI while active:
  Pads 0-7   : select a parameter (grid depends on current target's schema)
  RECORD     : toggle page (melodic only -- the drum schema fits on one page)
  TEMPO+/-   : step the selected parameter's value (held = auto-repeat)
  RESET pad  : hold ~0.6s to restore the sound's built-in defaults
"""

import synth_params
from event_types import PAD_DOWN, PAD_UP, BTN_DOWN, BTN_UP
from config import BTN_RECORD, BTN_TEMPO_UP, BTN_TEMPO_DN, NUM_KIT_LAYERS

_LONG_PRESS_RESET = 0.6   # seconds: hold RESET pad to actually reset
_REPEAT_DELAY     = 0.4   # seconds TEMPO+/- must be held before auto-repeat starts
_REPEAT_INTERVAL  = 0.12  # seconds between auto-repeat steps
_FLASH_DURATION   = 0.5   # seconds the numeric value is shown after a tap


class SynthEditMode:
    def __init__(self, synth, display, looper, seq, get_active_mode):
        self._synth           = synth
        self._display         = display
        self._looper          = looper
        self._seq             = seq
        self._get_active_mode = get_active_mode

        self._page         = 0
        self._selected_pad = [0, 0]   # remembered cursor, one per page

        self._reset_pressed_at = 0.0

        self._held_button    = None   # BTN_TEMPO_UP / BTN_TEMPO_DN / None
        self._next_repeat_at = 0.0

        self._flash_until = 0.0

    # ── Entry / exit ──────────────────────────────────────────────────────────

    def enter(self):
        self._held_button = None
        self._flash_until = 0.0
        self._refresh_display()

    def exit(self):
        self._held_button = None

    def _edit_target(self):
        """Return (schema, index, get_fn, set_fn, reset_fn) for whatever is
        currently editable -- the selected sequencer track's drum sound, or
        the looper's active melodic voice. Resolved live off which top-level
        mode is active, so this needs no explicit "mode changed" plumbing."""
        if self._get_active_mode() is self._seq:
            return (synth_params.DRUM_PARAM_SCHEMA, self._seq.selected_track,
                    self._synth.get_drum_param, self._synth.set_drum_param,
                    self._synth.reset_drum)
        voice_idx = self._looper.active_idx - NUM_KIT_LAYERS
        return (synth_params.PARAM_SCHEMA, voice_idx,
                self._synth.get_voice_param, self._synth.set_voice_param,
                self._synth.reset_voice)

    # ── Event handling ────────────────────────────────────────────────────────

    def handle_event(self, event, now):
        etype, data = event

        if etype == PAD_DOWN:
            self._select_pad(data, now)

        elif etype == PAD_UP:
            self._release_pad(data, now)

        elif etype == BTN_DOWN and data == BTN_RECORD:
            self._page = 1 - self._page
            self._refresh_display()

        elif etype == BTN_DOWN and data in (BTN_TEMPO_UP, BTN_TEMPO_DN):
            direction = 1 if data == BTN_TEMPO_UP else -1
            self._held_button    = data
            self._next_repeat_at = now + _REPEAT_DELAY
            self._apply_step(direction, now)

        elif etype == BTN_UP and data == self._held_button:
            self._held_button = None

    def update(self, now):
        """Call once per main-loop iteration while this overlay is active."""
        if self._held_button is not None and now >= self._next_repeat_at:
            direction = 1 if self._held_button == BTN_TEMPO_UP else -1
            self._apply_step(direction, now)
            self._next_repeat_at = now + _REPEAT_INTERVAL

        if self._flash_until and now >= self._flash_until:
            self._flash_until = 0.0
            self._refresh_display()

    def refresh_display(self):
        self._refresh_display()

    # ── Private ───────────────────────────────────────────────────────────────

    def _select_pad(self, pad, now):
        self._selected_pad[self._page] = pad
        schema, _, _, _, _ = self._edit_target()
        entry = synth_params.schema_for(schema, self._page, pad)
        if entry and entry["kind"] == "action":
            self._reset_pressed_at = now
        self._refresh_display()

    def _release_pad(self, pad, now):
        schema, idx, _, _, reset = self._edit_target()
        entry = synth_params.schema_for(schema, self._page, pad)
        if (entry and entry["kind"] == "action"
                and self._selected_pad[self._page] == pad
                and now - self._reset_pressed_at >= _LONG_PRESS_RESET):
            reset(idx)
        self._refresh_display()

    def _apply_step(self, direction, now):
        schema, idx, get, set_, _ = self._edit_target()
        pad   = self._selected_pad[self._page]
        entry = synth_params.schema_for(schema, self._page, pad)
        if entry is None or entry["kind"] == "action":
            return
        current = get(idx, entry["key"])
        new_val = synth_params.step_value(entry, current, direction)
        set_(idx, entry["key"], new_val)
        self._flash_until = now + _FLASH_DURATION
        self._refresh_display()

    def _refresh_display(self):
        schema, idx, get, _, _ = self._edit_target()
        pad   = self._selected_pad[self._page]
        entry = synth_params.schema_for(schema, self._page, pad)

        self._display.set_leds_lower(1 << pad)
        self._display.set_leds_upper(1 << self._page)  # LED 9 lit on page 2

        if entry is None:
            self._display.show("    ")
            return

        if entry["kind"] == "action":
            self._display.show(entry["label"])
            return

        if self._flash_until:
            value = get(idx, entry["key"])
            self._display.show(synth_params.format_value(entry, value))
        else:
            self._display.show(entry["label"])
