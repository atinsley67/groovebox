"""
MenuMode — the settings overlay: sound editing, instrument assignment, and
loop-length edits.

Not a top-level mode like LooperMode/SequencerMode; it's a temporary
overlay opened by BTN_MENU, usable from either mode. It always resolves its
target live (never a cached copy), so cycling layers/tracks with MODE, or
switching LOOP<->SEQ, while it's open retargets it on the fly.

One control scheme everywhere in the menu:
  MENU       : enter / run the highlighted item; confirm inside a section
  PLAY/STOP  : back to root (cancel in ASSIGN); at root, close the menu --
               code.py routes it here via back()
  TEMPO+/-   : move the highlight / step the value (held = auto-repeat)
  Pads 0-7   : jump the highlight / select a param or instrument
  MODE       : unchanged (code.py) -- the menu follows the new layer/track
Pads and TEMPO only ever move a highlight or step a value; MENU is the only
thing that commits an action, so there are no hold-to-confirm gestures.

Root (always where the menu opens): SOUND, ASSIGN, EXTEND, MIRROR.

SOUND: edit the target's sound -- SEQ mode: the selected track's drum sound
  (synth_params.DRUM_PARAM_SCHEMA); LOOP mode: the active layer's own
  instrument (PARAM_SCHEMA for a melodic voice, DRUM_PARAM_SCHEMA for one of
  a kit layer's 8 sounds). Pads pick a param, TEMPO+/- steps it, MENU on the
  RST pad restores the sound's built-in defaults. RECORD toggles the page
  (melodic), or on a kit loop layer steps which of its 8 sounds is edited.

ASSIGN (LOOP only): pick the active layer's instrument. The name shows
  immediately; the sound swaps once the highlight has settled
  (_ASSIGN_SETTLE), so the loop re-instruments live as you browse without
  building an instance per step. MENU keeps it; PLAY/STOP reverts to the
  layer's original instance, SOUND edits intact. Changing layer keeps the
  pending choice for the old layer.

EXTEND / MIRROR (LOOP only): run in place from root -- see
  LooperMode.extend_loop / mirror_active_layer. "N/A " if they can't run.
"""

import synth_params
from event_types import PAD_DOWN, BTN_DOWN, BTN_UP
from config import BTN_RECORD, BTN_TEMPO_UP, BTN_TEMPO_DN, BTN_MENU, NUM_PADS

_REPEAT_DELAY    = 0.4   # seconds TEMPO+/- must be held before auto-repeat starts
_REPEAT_INTERVAL = 0.12  # seconds between auto-repeat steps
_FLASH_DURATION  = 0.5   # seconds a SOUND value is shown after a step
_MSG_DURATION    = 0.6   # seconds a status message ("N/A ", "DONE", a name) is shown
_ASSIGN_SETTLE   = 0.2   # seconds the ASSIGN highlight must rest before the sound swaps

_ROOT   = "root"
_SOUND  = "sound"
_ASSIGN = "assign"

# Root items, in pad order: (display label, action)
_ROOT_ITEMS = [
    ("SND ", "sound"),
    ("ASGN", "assign"),
    ("EXT ", "extend"),
    ("MIRR", "mirror"),
]


class MenuMode:
    def __init__(self, synth, display, looper, seq, get_active_mode):
        self._synth           = synth
        self._display         = display
        self._looper          = looper
        self._seq             = seq
        self._get_active_mode = get_active_mode

        self._section  = _ROOT
        self._root_idx = 0

        # SOUND
        self._page         = 0
        self._selected_pad = [0, 0]   # remembered cursor, one per page
        self._kit_pad      = 0        # kit loop layer: which of its sounds is edited
        self._kit_layer    = None     # layer _kit_pad was seeded for (None = reseed)
        self._flash_until  = 0.0      # value readout after a step

        # ASSIGN
        self._assign_layer       = 0
        self._assign_original    = None   # original channel, once swapped away from
        self._assign_original_id = 0
        self._assign_highlight   = 0
        self._assign_swap_at     = 0.0    # 0 = no swap pending

        self._held_button    = None   # BTN_TEMPO_UP / BTN_TEMPO_DN / None
        self._next_repeat_at = 0.0

        self._msg       = ""
        self._msg_until = 0.0

    # ── Entry / exit ──────────────────────────────────────────────────────────

    def enter(self):
        self._section     = _ROOT
        self._root_idx    = 0
        self._held_button = None
        self._flash_until = 0.0
        self._msg_until   = 0.0
        self._refresh_display()

    def exit(self):
        if self._section == _ASSIGN:
            self._assign_commit()
        self._section     = _ROOT
        self._held_button = None

    def back(self, now):
        """PLAY/STOP pressed. Returns True if the menu should close (pressed
        at root); otherwise steps back to root, cancelling ASSIGN."""
        self._held_button = None
        if self._section == _ROOT:
            return True
        if self._section == _ASSIGN:
            self._assign_cancel()
        self._section     = _ROOT
        self._flash_until = 0.0
        self._msg_until   = 0.0
        self._refresh_display()
        return False

    # ── Event handling ────────────────────────────────────────────────────────

    def handle_event(self, event, now):
        etype, data = event

        if etype == PAD_DOWN:
            self._pad(data, now)

        elif etype == BTN_DOWN and data == BTN_MENU:
            self._select(now)

        elif etype == BTN_DOWN and data == BTN_RECORD:
            self._record(now)

        elif etype == BTN_DOWN and data in (BTN_TEMPO_UP, BTN_TEMPO_DN):
            direction = 1 if data == BTN_TEMPO_UP else -1
            self._held_button    = data
            self._next_repeat_at = now + _REPEAT_DELAY
            self._step(direction, now)

        elif etype == BTN_UP and data == self._held_button:
            self._held_button = None

    def update(self, now):
        """Call once per main-loop iteration while this overlay is active."""
        self._sync_assign_target()

        if self._held_button is not None and now >= self._next_repeat_at:
            direction = 1 if self._held_button == BTN_TEMPO_UP else -1
            self._step(direction, now)
            self._next_repeat_at = now + _REPEAT_INTERVAL

        if self._assign_swap_at and now >= self._assign_swap_at:
            self._assign_apply()

        refresh = False
        if self._flash_until and now >= self._flash_until:
            self._flash_until = 0.0
            refresh = True
        if self._msg_until and now >= self._msg_until:
            self._msg_until = 0.0
            refresh = True
        if refresh:
            self._refresh_display()

    def refresh_display(self):
        """Called by code.py after anything that may have retargeted the
        menu (MODE layer/track changes, LOOP<->SEQ switches)."""
        self._sync_assign_target()
        self._refresh_display()

    # ── Dispatch per section ──────────────────────────────────────────────────

    def _pad(self, pad, now):
        if self._section == _ROOT:
            if pad < len(_ROOT_ITEMS):
                self._root_idx = pad
        elif self._section == _SOUND:
            self._selected_pad[self._page] = pad
            self._flash_until = 0.0
        elif self._section == _ASSIGN:
            if pad < len(self._synth.list_instrument_names()):
                self._assign_move(pad, now)
        self._refresh_display()

    def _step(self, direction, now):
        if self._section == _ROOT:
            self._root_idx = (self._root_idx + direction) % len(_ROOT_ITEMS)
        elif self._section == _SOUND:
            self._sound_step(direction, now)
        elif self._section == _ASSIGN:
            count = len(self._synth.list_instrument_names())
            self._assign_move((self._assign_highlight + direction) % count, now)
        self._refresh_display()

    def _select(self, now):
        if self._section == _ROOT:
            action = _ROOT_ITEMS[self._root_idx][1]
            if action == "sound":
                self._enter_sound(now)
            elif not self._loop_active():
                self._flash("N/A ", now)   # ASSIGN/EXTEND/MIRROR are loop-only
            elif action == "assign":
                self._enter_assign()
            elif action == "extend":
                self._flash("DONE" if self._looper.extend_loop(now) else "N/A ", now)
            elif action == "mirror":
                self._flash("DONE" if self._looper.mirror_active_layer(now) else "N/A ", now)

        elif self._section == _SOUND:
            schema, _, _, reset, _ = self._edit_target()
            entry = synth_params.schema_for(schema, self._page,
                                            self._selected_pad[self._page])
            if entry and entry["kind"] == "action":
                reset()
                self._flash("DONE", now)

        elif self._section == _ASSIGN:
            self._assign_commit()
            self._section = _ROOT

        self._held_button = None
        self._refresh_display()

    def _record(self, now):
        if self._section != _SOUND:
            return
        schema, _, _, _, kit_name = self._edit_target()
        if _num_pages(schema) > 1:
            self._page = 1 - self._page
            self._flash_until = 0.0
        elif self._loop_active() and kit_name is not None:
            self._kit_pad = (self._kit_pad + 1) % NUM_PADS
            self._flash(self._synth.channel_sound_name(self._looper.active_idx,
                                                       self._kit_pad), now)
        self._refresh_display()

    # ── SOUND ─────────────────────────────────────────────────────────────────

    def _enter_sound(self, now):
        self._section     = _SOUND
        self._kit_layer   = None   # reseed the kit cursor from the layer's last pad
        self._flash_until = 0.0
        _, _, _, _, kit_name = self._edit_target()
        if kit_name is not None:
            self._flash(kit_name, now)   # make clear which kit sound is being edited

    def _edit_target(self):
        """Return (schema, get(key), set(key, value), reset(), kit_name) for
        whatever is currently editable. kit_name is the edited kit sound's
        name, or None for a melodic voice. Resolved live off which top-level
        mode is active, so this needs no explicit "mode changed" plumbing."""
        synth = self._synth
        if not self._loop_active():
            track  = self._seq.selected_track
            schema = synth_params.DRUM_PARAM_SCHEMA
            get    = lambda key: synth.get_drum_param(track, key)
            set_   = lambda key, value: synth.set_drum_param(track, key, value)
            reset  = lambda: synth.reset_drum(track)
            name   = synth.sound_name(track)
        else:
            layer = self._looper.active_idx
            if synth.layer_is_melodic(layer):
                pad, schema, name = None, synth_params.PARAM_SCHEMA, None
            else:
                if self._kit_layer != layer:
                    self._kit_layer = layer
                    self._kit_pad   = self._looper.active_layer_last_pad
                pad, schema = self._kit_pad, synth_params.DRUM_PARAM_SCHEMA
                name = synth.channel_sound_name(layer, pad)
            get   = lambda key: synth.get_channel_param(layer, pad, key)
            set_  = lambda key, value: synth.set_channel_param(layer, pad, key, value)
            reset = lambda: synth.reset_channel(layer, pad)
        # A single-page schema (drum) can't be on page 2 -- e.g. after
        # switching from a melodic layer's page 2 to a kit layer.
        if self._page >= _num_pages(schema):
            self._page = 0
        return schema, get, set_, reset, name

    def _sound_step(self, direction, now):
        schema, get, set_, _, _ = self._edit_target()
        entry = synth_params.schema_for(schema, self._page,
                                        self._selected_pad[self._page])
        if entry is None or entry["kind"] == "action":
            return
        set_(entry["key"], synth_params.step_value(entry, get(entry["key"]), direction))
        self._flash_until = now + _FLASH_DURATION

    # ── ASSIGN ────────────────────────────────────────────────────────────────

    def _enter_assign(self):
        layer = self._looper.active_idx
        self._section            = _ASSIGN
        self._assign_layer       = layer
        self._assign_original    = None
        self._assign_original_id = self._synth.channel_instrument_id(layer)
        self._assign_highlight   = self._assign_original_id
        self._assign_swap_at     = 0.0

    def _assign_move(self, instrument_id, now):
        if instrument_id != self._assign_highlight:
            self._assign_highlight = instrument_id
            self._assign_swap_at   = now + _ASSIGN_SETTLE

    def _assign_apply(self):
        """Make the layer's slot hold the highlighted instrument."""
        self._assign_swap_at = 0.0
        layer  = self._assign_layer
        target = self._assign_highlight
        if target == self._assign_original_id:
            # Back to where we started: put the original instance (and its
            # edits) back, if it was swapped out at all.
            if self._assign_original is not None:
                self._synth.restore_channel(layer, self._assign_original)
                self._assign_original = None
            return
        if target == self._synth.channel_instrument_id(layer):
            return   # already holds a fresh instance of it
        old = self._synth.assign_channel(layer, target)
        if self._assign_original is None:
            self._assign_original = old   # keep aside for cancel

    def _assign_commit(self):
        if self._assign_swap_at:
            self._assign_apply()
        self._assign_original = None

    def _assign_cancel(self):
        self._assign_swap_at = 0.0
        if self._assign_original is not None:
            self._synth.restore_channel(self._assign_layer, self._assign_original)
            self._assign_original = None

    def _sync_assign_target(self):
        """ASSIGN follows the active layer: a layer change (MODE, handled by
        code.py) keeps the old layer's pending choice and starts over on the
        new one; leaving LOOP mode keeps it and returns to root."""
        if self._section != _ASSIGN:
            return
        if not self._loop_active():
            self._assign_commit()
            self._section = _ROOT
        elif self._looper.active_idx != self._assign_layer:
            self._assign_commit()
            self._enter_assign()

    # ── Display ───────────────────────────────────────────────────────────────

    def _loop_active(self):
        return self._get_active_mode() is self._looper

    def _flash(self, text, now):
        self._msg       = text
        self._msg_until = now + _MSG_DURATION

    def _refresh_display(self):
        upper = 0
        if self._section == _ROOT:
            lower = 1 << self._root_idx
            text  = _ROOT_ITEMS[self._root_idx][0]

        elif self._section == _ASSIGN:
            lower = 1 << self._assign_highlight
            text  = self._synth.list_instrument_names()[self._assign_highlight]

        else:
            schema, get, _, _, _ = self._edit_target()
            pad   = self._selected_pad[self._page]
            entry = synth_params.schema_for(schema, self._page, pad)
            lower = 1 << pad
            upper = 1 << self._page   # LED 8 page 1, LED 9 page 2
            if entry is None:
                text = "    "
            elif entry["kind"] != "action" and self._flash_until:
                text = synth_params.format_value(entry, get(entry["key"]))
            else:
                text = entry["label"]

        if self._msg_until:
            text = self._msg

        self._display.set_leds_lower(lower)
        self._display.set_leds_upper(upper)
        self._display.show(text)


def _num_pages(schema):
    return max(entry["page"] for entry in schema) + 1
