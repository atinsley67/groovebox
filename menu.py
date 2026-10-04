"""
MenuMode — the settings overlay: sound editing, instrument assignment,
tempo, loop-length edits, and groove save/load.

Not a top-level mode like LooperMode/SequencerMode; it's a temporary
overlay opened by BTN_MENU, usable from either mode. It always resolves its
target live (never a cached copy), so choosing a layer/track in the channel
view, or
switching LOOP<->SEQ, while it's open retargets it on the fly.

It owns only the 4-char text and these keys:
  MENU       : select -- enter the highlighted item / edit the value / run
               the action
  RECORD     : back (cancel in ASSIGN); at root, close the menu -- code.py
               routes it here via back()
  UP/DOWN    : move the highlight, or step the value while editing (held =
               auto-repeat)
Everything else stays with code.py and the active mode: LOOP/SEQ and a
channel-view select retarget the menu, PLAY/STOP stays the transport, the
pads keep playing the active mode (which keeps the LEDs), and MUTE / CLEAR
do nothing while the menu is open.

Every level is a list: the display shows the highlighted item's label, and
UP/DOWN wrap around it.

Root (always where the menu opens): SOUND, ASSIGN, BPM, EXTEND, MIRROR,
SAVE, LOAD.

SOUND: edit the target's sound -- SEQ mode: the selected track's drum sound
  (synth_params.DRUM_PARAM_SCHEMA); LOOP mode: the active layer's own
  instrument (PARAM_SCHEMA for a melodic voice; DRUM_PARAM_SCHEMA for a kit
  layer, editing the sound on the last pad played on that layer -- play
  another pad to switch). The list is the schema's params in order, ending
  in RST. MENU on a param edits it (UP/DOWN step it, the value shows) until
  MENU or RECORD returns to the list. MENU on RST shows SURE, and a
  second MENU restores the sound's built-in defaults. The highlight is
  remembered per schema. The target's name flashes on entry and whenever
  the target changes.

ASSIGN (LOOP only): pick the active layer's instrument. The name shows
  immediately; the sound swaps once the highlight has settled
  (_ASSIGN_SETTLE), so the loop re-instruments live as you browse without
  building an instance per step. MENU keeps it; RECORD reverts to the
  layer's original instance, SOUND edits intact. Changing layer keeps the
  pending choice for the old layer.

BPM: MENU edits the tempo, shown as "b120" (code.py's set_bpm, so the clock
  re-anchors without a jump). While code.py's tempo_locked() holds, it
  flashes LOCK and the value can't change. MENU or RECORD returns.

EXTEND / MIRROR (LOOP only): run in place from root -- see
  LooperMode.extend_loop / mirror_active_layer. "N/A " if they can't run.

SAVE / LOAD (either mode): pick one of groove.NUM_SLOTS slots. The label is
  S or L, the two-digit slot number, and "*" if the slot holds a groove:
  "S03*" saves over slot 3, "S03 " saves to an empty slot 3, "L03*" loads
  slot 3. MENU saves / loads and returns to root, flashing DONE or the
  failure ("RO  ", "FULL", "ERR "); MENU on an empty LOAD slot just flashes
  "N/A ". Loading replaces the whole session and stops the transport.
"""

import clock
import groove
import synth_params
from event_types import BTN_DOWN, BTN_UP
from config import BTN_INC, BTN_DEC, BTN_MENU

_REPEAT_DELAY    = 0.4   # seconds UP/DOWN must be held before auto-repeat starts
_REPEAT_INTERVAL = 0.12  # seconds between auto-repeat steps
_MSG_DURATION    = 0.6   # seconds a status message ("N/A ", "DONE", a name) is shown
_ASSIGN_SETTLE   = 0.2   # seconds the ASSIGN highlight must rest before the sound swaps

_ROOT   = "root"
_SOUND  = "sound"
_ASSIGN = "assign"
_BPM    = "bpm"
_SAVE   = "save"
_LOAD   = "load"

# Root items, in list order: (display label, action)
_ROOT_ITEMS = [
    ("SND ", _SOUND),
    ("ASGN", _ASSIGN),
    ("BPM ", _BPM),
    ("EXT ", "extend"),
    ("MIRR", "mirror"),
    ("SAVE", _SAVE),
    ("LOAD", _LOAD),
]


class MenuMode:
    def __init__(self, synth, display, looper, seq, get_active_mode,
                 capture_groove, apply_groove, get_bpm, set_bpm, tempo_locked):
        self._synth           = synth
        self._display         = display
        self._looper          = looper
        self._seq             = seq
        self._get_active_mode = get_active_mode
        # code.py callbacks: capture_groove() -> dict; apply_groove(dict, now);
        # get_bpm() -> int; set_bpm(int); tempo_locked() -> bool
        self._capture_groove  = capture_groove
        self._apply_groove    = apply_groove
        self._get_bpm         = get_bpm
        self._set_bpm         = set_bpm
        self._tempo_locked    = tempo_locked

        self._section  = _ROOT
        self._root_idx = 0

        # SOUND
        self._sound_idx = {"voice": 0, "drum": 0}   # remembered highlight, per schema
        self._editing   = False   # MENU pressed on a param: UP/DOWN step its value
        self._confirm   = False   # MENU pressed once on RST: showing SURE
        self._target    = None    # _target_ident() last seen, to flash a change

        # ASSIGN
        self._assign_layer       = 0
        self._assign_original    = None   # original channel, once swapped away from
        self._assign_original_id = 0
        self._assign_highlight   = 0
        self._assign_swap_at     = 0.0    # 0 = no swap pending

        # SAVE / LOAD
        self._slot       = 0   # remembered across visits: re-saving goes to the same slot
        self._used_slots = 0   # groove.used_slots() bitmask, read on entry

        self._held_button    = None   # BTN_INC / BTN_DEC / None
        self._next_repeat_at = 0.0

        self._msg       = ""
        self._msg_until = 0.0

    # ── Entry / exit ──────────────────────────────────────────────────────────

    def enter(self):
        self._section     = _ROOT
        self._root_idx    = 0
        self._editing     = False
        self._confirm     = False
        self._held_button = None
        self._msg_until   = 0.0
        self._refresh_display()

    def exit(self):
        if self._section == _ASSIGN:
            self._assign_commit()
        self._section     = _ROOT
        self._editing     = False
        self._confirm     = False
        self._held_button = None

    def back(self, now):
        """RECORD pressed. Returns True if the menu should close (pressed
        at root); otherwise steps back one level, cancelling ASSIGN."""
        self._held_button = None
        self._msg_until   = 0.0
        if self._section == _ROOT:
            return True
        if self._section == _SOUND and (self._editing or self._confirm):
            self._editing = False   # back to the param list
            self._confirm = False
        else:
            if self._section == _ASSIGN:
                self._assign_cancel()
            self._section = _ROOT
        self._refresh_display()
        return False

    # ── Event handling ────────────────────────────────────────────────────────

    def handle_event(self, event, now):
        etype, data = event

        if etype == BTN_DOWN and data == BTN_MENU:
            self._select(now)

        elif etype == BTN_DOWN and data in (BTN_INC, BTN_DEC):
            direction = 1 if data == BTN_INC else -1
            self._held_button    = data
            self._next_repeat_at = now + _REPEAT_DELAY
            self._step(direction, now)

        elif etype == BTN_UP and data == self._held_button:
            self._held_button = None

    def update(self, now):
        """Call once per main-loop iteration while this overlay is active."""
        self._sync_assign_target()
        if self._section == _SOUND:
            self._sync_sound_target(now)

        if self._held_button is not None and now >= self._next_repeat_at:
            direction = 1 if self._held_button == BTN_INC else -1
            self._step(direction, now)
            self._next_repeat_at = now + _REPEAT_INTERVAL

        if self._assign_swap_at and now >= self._assign_swap_at:
            self._assign_apply()

        if self._msg_until and now >= self._msg_until:
            self._msg_until = 0.0
            self._refresh_display()

    def refresh_display(self):
        """Called by code.py after anything that may have retargeted the
        menu (layer/track changes, LOOP<->SEQ switches)."""
        self._sync_assign_target()
        self._refresh_display()

    # ── Dispatch per section ──────────────────────────────────────────────────

    def _step(self, direction, now):
        if self._section == _ROOT:
            self._root_idx = (self._root_idx + direction) % len(_ROOT_ITEMS)
        elif self._section == _SOUND:
            self._sound_step(direction)
        elif self._section == _ASSIGN:
            count = len(self._synth.list_instrument_names())
            self._assign_move((self._assign_highlight + direction) % count, now)
        elif self._section == _BPM:
            if self._tempo_locked():
                self._flash("LOCK", now)
            else:
                self._set_bpm(self._get_bpm() + direction)
        elif self._section in (_SAVE, _LOAD):
            self._slot = (self._slot + direction) % groove.NUM_SLOTS
        self._refresh_display()

    def _select(self, now):
        if self._section == _ROOT:
            action = _ROOT_ITEMS[self._root_idx][1]
            if action == _SOUND:
                self._enter_sound(now)
            elif action == _BPM:
                self._section = _BPM
                if self._tempo_locked():
                    self._flash("LOCK", now)
            elif action in (_SAVE, _LOAD):
                self._section    = action
                self._used_slots = groove.used_slots()
            elif not self._loop_active():
                self._flash("N/A ", now)   # ASSIGN/EXTEND/MIRROR are loop-only
            elif action == _ASSIGN:
                self._enter_assign()
            elif action == "extend":
                self._flash("DONE" if self._looper.extend_loop(now) else "N/A ", now)
            elif action == "mirror":
                self._flash("DONE" if self._looper.mirror_active_layer(now) else "N/A ", now)

        elif self._section == _SOUND:
            schema, key, _, _, reset, _ = self._edit_target()
            entry = schema[self._sound_idx[key]]
            if self._editing:
                self._editing = False
            elif entry["kind"] != "action":
                self._editing = True
            elif self._confirm:
                reset()
                self._confirm = False
                self._flash("DONE", now)
            else:
                self._confirm = True

        elif self._section == _ASSIGN:
            self._assign_commit()
            self._section = _ROOT

        elif self._section == _BPM:
            self._section = _ROOT

        elif self._section == _SAVE:
            self._flash(self._save(), clock.now())
            self._section = _ROOT

        elif self._section == _LOAD:
            if not self._used_slots & (1 << self._slot):
                self._flash("N/A ", now)
            else:
                self._flash(self._load(now), clock.now())
                self._section = _ROOT

        self._held_button = None
        self._refresh_display()

    # ── SOUND ─────────────────────────────────────────────────────────────────

    def _enter_sound(self, now):
        self._section = _SOUND
        self._editing = False
        self._confirm = False
        self._target  = None   # flash the target's name straight away
        self._sync_sound_target(now)

    def _target_ident(self):
        """What SOUND is editing, cheaply enough to poll every frame:
        (schema key, ...where). Changes on a layer/track change, LOOP<->SEQ, or a pad played
        on a kit layer."""
        if not self._loop_active():
            return ("drum", "track", self._seq.selected_track)
        layer = self._looper.active_idx
        if self._synth.layer_is_melodic(layer):
            return ("voice", "layer", layer)
        return ("drum", "layer", layer, self._looper.active_layer_last_pad)

    def _sync_sound_target(self, now):
        ident = self._target_ident()
        if ident == self._target:
            return
        if self._target is not None and ident[0] != self._target[0]:
            self._editing = False   # a different schema: its own params and highlight
        self._target  = ident
        self._confirm = False
        self._flash(self._edit_target()[5], now)
        self._refresh_display()

    def _edit_target(self):
        """Return (schema, schema key, get(key), set(key, value), reset(),
        name) for whatever is currently editable. schema key picks the
        remembered highlight; name is the edited sound's (or voice's) name.
        Resolved live off which top-level mode is active, so this needs no
        explicit "mode changed" plumbing."""
        synth = self._synth
        if not self._loop_active():
            track = self._seq.selected_track
            return (synth_params.DRUM_PARAM_SCHEMA, "drum",
                    lambda k: synth.get_drum_param(track, k),
                    lambda k, value: synth.set_drum_param(track, k, value),
                    lambda: synth.reset_drum(track),
                    synth.sound_name(track))
        layer = self._looper.active_idx
        if synth.layer_is_melodic(layer):
            pad, schema, key = None, synth_params.PARAM_SCHEMA, "voice"
        else:
            pad, schema, key = (self._looper.active_layer_last_pad,
                                synth_params.DRUM_PARAM_SCHEMA, "drum")
        return (schema, key,
                lambda k: synth.get_channel_param(layer, pad, k),
                lambda k, value: synth.set_channel_param(layer, pad, k, value),
                lambda: synth.reset_channel(layer, pad),
                synth.channel_sound_name(layer, pad))

    def _sound_step(self, direction):
        schema, key, get, set_, _, _ = self._edit_target()
        if self._editing:
            entry = schema[self._sound_idx[key]]
            set_(entry["key"], synth_params.step_value(entry, get(entry["key"]), direction))
        else:
            self._sound_idx[key] = (self._sound_idx[key] + direction) % len(schema)
            self._confirm = False

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
        """ASSIGN follows the active layer: a layer change (the channel view, handled by
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

    # ── SAVE / LOAD ───────────────────────────────────────────────────────────
    # Both return the status to flash. Flashed from clock.now() rather
    # than the press time: a flash write can take long enough to use up the
    # whole message window before it's ever drawn.

    def _save(self):
        try:
            groove.save(self._slot, self._capture_groove())
        except OSError as e:
            return groove.error_label(e)
        return "DONE"

    def _load(self, now):
        try:
            data = groove.load(self._slot)
        except (OSError, ValueError) as e:
            return groove.error_label(e)
        self._apply_groove(data, now)
        return "DONE"

    # ── Display ───────────────────────────────────────────────────────────────

    def _loop_active(self):
        return self._get_active_mode() is self._looper

    def _flash(self, text, now):
        self._msg       = text
        self._msg_until = now + _MSG_DURATION

    def _refresh_display(self):
        """The menu draws only the 4-char text -- the LEDs stay with the
        active mode."""
        if self._msg_until:
            text = self._msg

        elif self._section == _ROOT:
            text = _ROOT_ITEMS[self._root_idx][0]

        elif self._section == _SOUND:
            schema, key, get, _, _, _ = self._edit_target()
            entry = schema[self._sound_idx[key]]
            if self._editing:
                text = synth_params.format_value(entry, get(entry["key"]))
            elif self._confirm:
                text = "SURE"
            else:
                text = entry["label"]

        elif self._section == _ASSIGN:
            text = self._synth.list_instrument_names()[self._assign_highlight]

        elif self._section == _BPM:
            text = f"b{self._get_bpm():3d}"

        else:   # SAVE / LOAD
            prefix = "S" if self._section == _SAVE else "L"
            used   = "*" if self._used_slots & (1 << self._slot) else " "
            text   = f"{prefix}{self._slot + 1:02d}{used}"

        self._display.show(text)
