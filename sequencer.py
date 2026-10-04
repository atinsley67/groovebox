"""
SequencerMode — 8-track × 16-step step sequencer.

UI interaction:
  - Pads 0-15  : toggle steps 0-15 of the bar on the selected track (row
                 by row from the top left). Toggling also previews the sound.
  - MODE button : short = advance selected track; long = switch to looper;
                  hold + pad = jump to that track. (All handled by code.py.)
  - RECORD      : nothing (free for a later use)
  - PLAY/STOP   : global transport, handled by code.py -- short press calls
                  set_playing(), long press calls clear_all().
  - MUTE short  : mute / unmute selected track
  - MUTE long   : clear all steps on selected track (also unmutes it)
  - UP/DOWN     : selected track's volume -- handled by code.py

Display (4 chars): T<track+1>  e.g. "T1  "
Pad LEDs         : step on/off for the selected track; the step being
                   played is always lit.
"""

from event_types import PAD_DOWN, PAD_UP, BTN_DOWN, BTN_UP, TICK
from config import BTN_MUTE, STEPS_PER_BAR, NUM_TRACKS, DEFAULT_BPM

_LONG_PRESS_CLEAR_TRACK = 0.6


class SequencerMode:
    def __init__(self, synth, display):
        self._synth   = synth
        self._display = display

        # grid[track][step] = True/False
        self._grid = [[False] * STEPS_PER_BAR for _ in range(NUM_TRACKS)]

        self._selected_track = 0
        self._playing        = False
        self._current_step   = 0

        self._muted_tracks = 0   # bitmask: bit n set = track n is muted
        self._mute_at      = 0.0

        # 16th-note duration in seconds. code.py owns tempo (BPM) and keeps
        # this in sync whenever it changes; kept here (rather than a
        # standalone clock object) since it's already the step-grid
        # authority other modes read (see current_step). Default matches
        # code.py's own initial step_dur so it's sane even before the first
        # explicit sync.
        self._step_dur = 60.0 / (DEFAULT_BPM * 4)

        # Ownership must be explicitly claimed via enter()/set_display_owner
        # -- never assumed at construction, since code.py only ever hands it
        # off explicitly and a mode that's never had focus should never be
        # able to paint over the shared display on a background event (e.g.
        # a TICK dispatched to it while the other mode has focus).
        self._is_display_owner = False

    # ── Entry / exit ──────────────────────────────────────────────────────────

    def enter(self):
        self._is_display_owner = True
        self._refresh_display()

    def exit(self):
        self._is_display_owner = False

    def set_display_owner(self, is_owner):
        self._is_display_owner = is_owner
        if is_owner:
            self._refresh_display()

    @property
    def playing(self):
        return self._playing

    @property
    def current_step(self):
        return self._current_step

    @property
    def step_dur(self):
        return self._step_dur

    @step_dur.setter
    def step_dur(self, value):
        self._step_dur = value

    @property
    def selected_track(self):
        return self._selected_track

    def update(self, now):
        pass

    def refresh_display(self):
        self._refresh_display()

    # ── Channel navigation (called by code.py MODE gesture handler) ───────────

    def cycle_channel(self):
        self._selected_track = (self._selected_track + 1) % NUM_TRACKS
        self._refresh_display()

    def select_channel(self, n):
        if 0 <= n < NUM_TRACKS:
            self._selected_track = n
            self._refresh_display()

    # ── Global transport (called externally by code.py's PLAY/STOP) ───────────

    def set_playing(self, playing):
        """Doesn't touch current_step itself -- code.py's own clock resets
        its step counter to 0 on resume (see its "Drive tempo clock"
        section) and that reaches current_step via the next TICK, same as
        any other step."""
        self._playing = playing
        self._refresh_display()

    def clear_all(self):
        for track in range(NUM_TRACKS):
            for s in range(STEPS_PER_BAR):
                self._grid[track][s] = False
        self._muted_tracks = 0
        self._refresh_display()

    # ── Grooves (called by code.py for the menu's SAVE / LOAD) ────────────────

    def snapshot(self):
        """Pattern and mutes as plain data: one step bitmask per track."""
        grid = []
        for track in self._grid:
            mask = 0
            for s, on in enumerate(track):
                if on:
                    mask |= 1 << s
            grid.append(mask)
        return {"grid": grid, "muted": self._muted_tracks}

    def restore(self, data):
        grid = data.get("grid", [])
        for track in range(NUM_TRACKS):
            mask = grid[track] if track < len(grid) else 0
            for s in range(STEPS_PER_BAR):
                self._grid[track][s] = bool(mask & (1 << s))
        self._muted_tracks = data.get("muted", 0)
        self._refresh_display()

    # ── Event handling ────────────────────────────────────────────────────────

    def handle_event(self, event, now):
        etype, data = event

        if etype == PAD_DOWN:
            step  = data   # pad n = step n
            track = self._selected_track
            if step < STEPS_PER_BAR:
                self._grid[track][step] = not self._grid[track][step]
            self._synth.trigger(track)

        elif etype == PAD_UP:
            # The press previewed the track's sound, not the pad's.
            track = self._selected_track
            if self._synth.is_melodic(track):
                self._synth.note_off(track)

        elif etype == BTN_DOWN:
            if data == BTN_MUTE:
                self._mute_at = now

        elif etype == BTN_UP:
            if data == BTN_MUTE:
                if now - self._mute_at >= _LONG_PRESS_CLEAR_TRACK:
                    track = self._selected_track
                    for s in range(STEPS_PER_BAR):
                        self._grid[track][s] = False
                    self._muted_tracks &= ~(1 << track)   # also unmute
                else:
                    self._muted_tracks ^= (1 << self._selected_track)

        elif etype == TICK:
            self._current_step = data
            self._fire_step(data)

        self._refresh_display()

    # ── Private ───────────────────────────────────────────────────────────────

    def _fire_step(self, step):
        for track in range(NUM_TRACKS):
            if self._muted_tracks & (1 << track):
                continue
            if self._grid[track][step]:
                self._synth.trigger(track)

    def _steps_bitmask(self):
        mask = 0
        for step, on in enumerate(self._grid[self._selected_track]):
            if on:
                mask |= (1 << step)
        return mask

    def _refresh_display(self):
        if not self._is_display_owner:
            return
        self._display.show_sequencer_state(
            steps_mask=self._steps_bitmask(),
            playhead_step=self._current_step if self._playing else -1,
            is_playing=self._playing,
            selected_track=self._selected_track,
        )
