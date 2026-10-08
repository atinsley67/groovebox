"""
LooperMode — 8-layer event-based live looper using synthio.

Each layer plays its own instance of whatever instrument it's assigned (see
synth_engine.assign_channel; by default layer 0 = the drum kit, layers 1-7 =
the melodic voices). On a kit layer each pad triggers a different drum
sound; on a melodic layer each pad plays a scale degree on that layer's own
voice (see synth_engine.trigger_layer_pad).
A recorded note-on is (loop_pos_seconds, pad); how `pad` is interpreted
depends only on which instrument the layer currently has -- reassigning a
layer re-instruments its recorded content live. Pads whose sound needs an
explicit release (a melodic voice, or a sustained kit pad) also get a
matching note-off recorded, so playback reproduces the actual hold length
instead of the sound's fixed default. A pad without a recorded release
(sound self-releases, or the hold crossed the loop seam) falls back to that
default via SynthEngine's own hold_ms timer.

Layer states:
  IDLE    — no events recorded
  PLAYING — looping events
  MUTED   — events retained but silent
  OVERDUB — recording additional events while playing (the pass itself is
            always freeform: starts/stops the instant RECORD is pressed;
            individual note starts recorded during it are still subject to
            note-start quantization below, same as any other recording)

Recording state (global, one layer at a time):
  IDLE      — not recording
  ARMED     — waiting for first pad press on active layer (freeform first
              layer only -- see below)
  COUNTDOWN — armed, waiting for a scheduled moment to start (see below)
  RECORDING — capturing events

The first layer recorded sets master_duration. Subsequent layers auto-commit
at that boundary so all layers stay locked to the same loop length.

Quantized start ("always record a full loop"):
  A layer recorded while a beat or loop reference already exists doesn't
  start on whatever pad you happen to press first -- it starts on "the 1":
    - First layer, synced (sequencer running): counts down to the
      sequencer's next bar boundary. If that boundary is too close for
      the full 3-2-1 to fit (RECORD pressed late in a short bar), the
      countdown instead waits out that bar and counts down through the
      next one, so it's never truncated.
    - Any later layer (master_duration already set, regardless of sync):
      counts down to the existing loop's own wrap-to-zero.
  Pressing a pad during the countdown just previews the sound and doesn't
  affect the countdown -- except during the final numbered step ("ARM1"),
  where a press is assumed to be aimed at the upcoming "1": it's snapped to
  loop position 0 the moment recording actually starts, whether the pad was
  tapped and released before the 1 or held through it. A pad first pressed
  earlier than "ARM1" is a plain preview and isn't captured. RECORD pressed
  during the countdown cancels the arm, same as today's ARMED cancel. RECORD pressed
  once real recording is underway stops capturing immediately; for a later
  layer this still commits at the full master_duration (silent tail) rather
  than shortening the loop.
  A first layer recorded with no beat/loop reference at all keeps today's
  original behavior unchanged: it starts on the first pad press.

Note-start quantization (synced sessions only):
  While self._synced is true, every recorded note-on (RECORDING or OVERDUB
  alike) is snapped to a grid line -- one sequencer step by default
  (_QUANT_SUBDIV; see there to go finer, e.g. 1/32), weighted toward the
  line just played past rather than a plain 50/50 nearest-neighbor split
  (_QUANT_BIAS). Only the
  recorded position moves: the pad's sound still fires the instant it's
  pressed, so this is only ever audible on loop playback, never as added
  input latency. A note-off moves with its own note-on, so the played
  length is preserved (and a recorded note-off is never before its
  note-on). On a melodic layer the join between neighbouring notes is kept
  too: overlapping (legato) notes stay overlapping and separate ones stay
  separate (see _keep_join). A freeform (unsynced) loop is unaffected --
  there's no tempo grid to snap to.

Exact presses (the arpeggiator's notes, arp.py -- handle_event(...,
exact=True)):
  Already on the grid, so the finger rules above would only damage them: a
  32nd would snap onto the 16th before it, and every note in ARM1 would
  land on position 0. An exact press is recorded at its event time as
  given -- no quantization, no _keep_join, no ARM1 snap. The one exception
  is a countdown: an exact press timed at the take's start
  (count_in_start) joins the take at position 0, like an ARM1 finger
  press; any other is a preview. The arp works out where its first note
  belongs with snap(), the same rule _quantize_pos uses, so an arp take
  starts where a finger note would have been recorded.

Loop-length edits (the menu's EXTEND / MIRROR, only while nothing is being
captured -- see can_modify_length):
  EXTEND doubles every layer's length; the new second half is silent.
  MIRROR replaces the active layer's second half with a copy of its first.

Grooves (the menu's SAVE / LOAD): snapshot() / restore() -- committed
layers only; see there.

Snap-to-bar sync:
  A synced first layer's recording (after its countdown lands on the 1)
  keeps capturing bar after bar -- get a beat going, however many bars you
  want -- until RECORD is pressed to end it. That press is a stop request,
  not an immediate cut: recording keeps running through the current bar
  and commits at the next step-0 boundary, so the loop is always a whole
  number of bars, at least one, and never shorter than what you actually
  played. (Later layers auto-commit at master_duration instead.)
"""

import array
import math

import keymap
from event_types import PAD_DOWN, PAD_UP, BTN_DOWN, TICK
from config import (BTN_RECORD, BTN_MUTE,
                    MAX_LOOP_EVENTS, NUM_LOOP_LAYERS, NUM_PADS, STEPS_PER_BAR)

_IDLE      = "IDLE"
_ARMED     = "ARM "
_COUNTDOWN = "CNT "
_RECORDING = "REC "
_PLAYING   = "PLY "
_OVERDUB   = "DUB "
_MUTED     = "MUTE"

_FLASH_DURATION  = 0.08  # seconds: how long a pad LED stays lit after firing

_COUNTDOWN_STEPS  = 3                          # numbered flashes before REC ("ARM3".."ARM1")
_COUNT_IN_SECONDS = 3.0                        # "time" kind: total lead-in when far from the wrap
_TIME_PER_STEP    = _COUNT_IN_SECONDS / _COUNTDOWN_STEPS
_STEPS_PER_BEAT   = STEPS_PER_BAR // 4          # assumes 4/4 time, like the sequencer

# Recorded-note-start quantization (synced sessions only -- see
# _quantize_pos): grid = one sequencer step divided by this. 1 = snap to
# 1/16 (the sequencer's own step grid), 2 = 1/32, etc.
_QUANT_SUBDIV = 1
# Fraction of each grid interval that rounds back to the line just played
# past; the remaining tail at the end of the interval rounds forward to the
# next line instead. 0.5 = plain nearest-neighbor; 0.75 favors keeping a
# note where it was actually played unless it's clearly reaching ahead.
_QUANT_BIAS = 0.65

# How far before the loop end a release is placed when it has to be pulled
# back inside the loop (see _fit_to_duration, mirror_active_layer). update()
# flushes any release a pass didn't reach at the wrap, so it always fires.
_SEAM_EPS = 0.001

# The least a melodic note's release is kept ahead of the next note's start
# when quantization would push it past (see _keep_join). update() plays a
# frame's note-ons before its note-offs, so a release meant to come first
# has to land a frame or two earlier.
_MIN_NOTE_GAP = 0.02

# How close an exact press's time must be to count_in_start to join a take
# from its countdown (the two are computed from the same tempo clock, so
# they differ only by float rounding).
_EXACT_EPS = 0.001


def quant_grid(step_dur):
    """The recorded-note grid: one sequencer step / _QUANT_SUBDIV."""
    return step_dur / _QUANT_SUBDIV


def snap(pos, grid):
    """The grid line a note start at `pos` (seconds from any grid line)
    belongs on, by _QUANT_BIAS. The one rounding rule: recording uses it
    (_quantize_pos), and so does the arpeggiator's first note."""
    return math.floor(pos / grid + (1.0 - _QUANT_BIAS)) * grid


class NoteList:
    """A layer's note-ons, or its note-offs: (position, pad) pairs, kept as
    two flat buffers -- positions (seconds into the loop) in a float array,
    pads in a bytearray.

    Why not a list of (pos, pad) tuples: the garbage collector never looks
    inside an array, but it visits every object a list holds, and a list of
    more than about 64 of them overflows its mark stack -- after which it
    re-scans the whole heap. One full layer (256 notes) doubled the time of
    every collection, long enough to stall the audio (gc_experiment.py).

    Reads like a list of pairs (len, index, iterate, sort) where speed
    doesn't matter; update() reads .pos and .pad directly, which allocates
    nothing."""

    def __init__(self, pairs=()):
        self.pos = array.array("f")
        self.pad = bytearray()
        for pos, pad in pairs:
            self.append(pos, pad)

    def __len__(self):
        return len(self.pad)

    def __getitem__(self, i):
        return (self.pos[i], self.pad[i])

    def __iter__(self):
        for i in range(len(self.pad)):
            yield (self.pos[i], self.pad[i])

    def __repr__(self):
        return f"NoteList({list(self)})"

    def append(self, pos, pad):
        self.pos.append(pos)
        self.pad.append(pad)

    def sort(self):
        """By position; notes at the same position keep their order. Runs
        mid-playback (a take's or overdub's end), so it sorts indices -- a
        list of small ints, which the garbage collector never has to follow
        -- rather than building (pos, pad) tuples."""
        order = _order_by_pos(self.pos)
        pos, pad = self.pos, self.pad
        self.pos = array.array("f", [pos[i] for i in order])
        self.pad = bytearray(pad[i] for i in order)


def _order_by_pos(positions):
    """Indices of `positions` (a float array) in position order, ties in
    index order. MicroPython's sort isn't stable, so the ties are put back
    in order by hand; they're short runs (a chord's notes)."""
    order = sorted(range(len(positions)), key=lambda i: positions[i])
    n = len(order)
    start = 0
    while start < n:
        end = start + 1
        while end < n and positions[order[end]] == positions[order[start]]:
            end += 1
        if end - start > 1:
            run = sorted(order[start:end])
            for k in range(len(run)):
                order[start + k] = run[k]
        start = end
    return order


def _count_through(notes, pos):
    """Number of leading notes at or before `pos` -- the index update()
    should carry on from. `notes` (a NoteList) must be sorted by position."""
    n = 0
    for note_pos in notes.pos:
        if note_pos > pos:
            break
        n += 1
    return n


def _restore_entries(saved, duration, v1_notes=False):
    """Saved [pos, pad] pairs back to a sorted NoteList, dropping anything
    a playable loop couldn't hold (hand-edited files included). v1_notes: a
    melodic layer from a v1 groove, where pad n played note n -- each moves
    to the pad that plays that note now."""
    entries = [(pos, keymap.PAD_OF_NOTE[pad] if v1_notes else pad)
               for pos, pad in saved
               if 0.0 <= pos < duration and 0 <= pad < NUM_PADS]
    entries.sort(key=lambda e: e[0])
    return NoteList(entries[:MAX_LOOP_EVENTS])


class LoopLayer:
    def __init__(self):
        self.events        = NoteList()   # note-ons
        self.releases      = NoteList()   # note-offs
        self.loop_duration = 0.0
        self.play_start    = 0.0
        self.last_loop_cnt = -1
        self.next_evt_idx  = 0
        self.next_rel_idx  = 0
        self.state         = _IDLE
        # pad_index -> (real_pos, recorded_pos) of its still-open note-on,
        # while recording/overdubbing. Used to pair a PAD_UP with its onset:
        # the real position measures how long the note was actually held,
        # the recorded (possibly quantized) one is where its release is
        # anchored.
        self.open_onsets   = {}
        # The last release recorded in the current take, as (index in
        # releases, its note's recorded onset, real time released) -- see
        # LooperMode._keep_join.
        self.last_release  = None
        # Most recently pressed pad on this layer -- which kit sound the
        # menu's SOUND editor starts on for a kit layer.
        self.last_pad      = 0


class LooperMode:
    def __init__(self, synth, display, seq):
        self._synth   = synth
        self._display = display
        self._seq     = seq

        self._layers     = [LoopLayer() for _ in range(NUM_LOOP_LAYERS)]
        self._active_idx = 0
        # update()'s per-layer scratch, reused every pass: whether the
        # layer is playing back, and where in its loop it is.
        self._layer_live = [False] * NUM_LOOP_LAYERS
        self._layer_pos  = [0.0] * NUM_LOOP_LAYERS
        self._master_dur = 0.0   # loop length; set by first layer recorded

        # Pad lights, active layer only. Two independent sources, combined by
        # pad_views.KeyboardView: _held_mask mirrors a pad's
        # live physical down/up state exactly, no timer involved; _flash_mask
        # is a timed pulse for a note auto-triggered by loop playback, which
        # has no physical press to key off of.
        self._held_mask   = 0
        self._flash_mask  = 0
        self._flash_until = 0.0
        # When each layer last played a note (live or playback), for the
        # channel view's activity flash.
        self._played_at = [-1.0] * NUM_LOOP_LAYERS

        # Loop passes since the transport started (see pass_index), and
        # when the current one began.
        self._pass_index = -1
        self._pass_at    = 0.0

        # Recording state (applies to whichever layer is being recorded)
        self._rec_state = _IDLE
        self._loop_start = 0.0

        # Snap-to-bar sync
        self._synced         = False
        self._snap_active    = False
        self._snap_bar_count = 0
        # RECORD pressed during snap_active: commit at the next bar
        # boundary instead of right away (see TICK handling below).
        self._snap_stop_requested = False
        self._was_cleared         = False

        # Quantized-start countdown (COUNTDOWN rec_state only)
        self._countdown_kind   = None  # "beat" (first layer, synced) | "time" (later layer)
        self._countdown_number = 0     # 0 = blank "ARM ", else counts down to 1
        self._countdown_target = 0.0   # "time" kind: wall-clock moment to start recording
        # "beat" kind: armed too close to the upcoming bar wrap for a full
        # 3-2-1 to fit -- skip that wrap and count down through the one
        # after it instead (see _begin_countdown).
        self._countdown_extra_bar = False
        # Pads first pressed during the final "ARM1" step: snapped to
        # position 0 once recording actually starts (see PAD_DOWN/PAD_UP
        # handling below and _start_countdown_recording). _down tracks
        # which of those are still held (vs. already tapped and released)
        # so we know whether to also seed an open onset for their release.
        self._countdown_snap_pads = set()
        self._countdown_down_pads = set()
        # "beat" kind: (time, step) of the last TICK seen, to work out when
        # the bar -- and so the take -- starts (count_in_start).
        self._countdown_tick = (0.0, 0)

        # Global transport pause (driven externally by code.py's PLAY/STOP;
        # freezes every wall-clock-anchored timestamp rather than the loop
        # quietly continuing in the background while paused). Starts
        # stopped, so a layer committed before the transport is ever
        # started just sits there until PLAY is pressed. _paused_at stays
        # None until the first real pause; set_playing() treats "never
        # played before" differently from an actual resume (see there).
        self._transport_playing = False
        self._paused_at         = None

        # Ownership must be explicitly claimed via enter()/set_display_owner
        # -- never assumed at construction, since code.py only ever hands
        # it off explicitly and a mode that's never had focus should never
        # be able to paint over the shared display on a background event
        # (e.g. a TICK dispatched to it while another mode has focus).
        self._is_display_owner = False

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def clock_needed(self):
        return self._snap_active or (self._rec_state == _COUNTDOWN and
                                      self._countdown_kind == "beat")

    @property
    def is_idle(self):
        """True only when no recording is in progress and no layers have events."""
        if self._rec_state != _IDLE:
            return False
        for layer in self._layers:   # not all(): a generator allocates
            if layer.state != _IDLE:
                return False
        return True

    @property
    def is_playing(self):
        """Read by the lights every frame, so a plain loop (any() over a
        generator would allocate)."""
        for layer in self._layers:
            if layer.state == _PLAYING or layer.state == _OVERDUB:
                return True
        return False

    @property
    def active_idx(self):
        return self._active_idx

    @property
    def active_layer_last_pad(self):
        return self._layers[self._active_idx].last_pad

    @property
    def snap_active(self):
        return self._snap_active

    @property
    def count_in_start(self):
        """When the take starts, while the countdown is on its final step
        ("ARM1", where a press is aimed at the 1); else None."""
        if self._rec_state != _COUNTDOWN or self._countdown_number != 1:
            return None
        if self._countdown_kind == "time":
            return self._countdown_target
        tick_at, step = self._countdown_tick
        return tick_at + (STEPS_PER_BAR - step) * self._seq.step_dur

    # ── For the lights (pad_views.KeyboardView, code.py's key lights) ─────────

    @property
    def held_mask(self):
        """Pads held down right now on the active layer (bit n = pad n)."""
        return self._held_mask

    @property
    def flash_mask(self):
        """Pads the active layer's playback just played (bit n = pad n)."""
        return self._flash_mask

    @property
    def capturing(self):
        """True while a press on the active layer is being recorded:
        recording it, or overdubbing it."""
        return (self._rec_state == _RECORDING or
                self._layers[self._active_idx].state == _OVERDUB)

    @property
    def record_status(self):
        """"rec" (recording, or any layer overdubbing), "armed" (armed or
        counting in), or None."""
        if self._rec_state == _RECORDING:
            return "rec"
        if self._rec_state == _ARMED or self._rec_state == _COUNTDOWN:
            return "armed"
        for layer in self._layers:
            if layer.state == _OVERDUB:
                return "rec"
        return None

    @property
    def transport_playing(self):
        return self._transport_playing

    @property
    def was_cleared(self):
        v = self._was_cleared
        self._was_cleared = False
        return v

    # ── Entry / exit ──────────────────────────────────────────────────────────

    def enter(self):
        self._is_display_owner = True
        self._refresh_display()

    def exit(self):
        self._is_display_owner = False

    def refresh_display(self):
        self._refresh_display()

    # ── Channels (called by code.py for the channel view and CLEAR) ───────────

    def can_select(self, n):
        """False while recording on another layer: you can't change layer
        mid-recording."""
        return self._rec_state != _RECORDING or n == self._active_idx

    def select_channel(self, n):
        if not self.can_select(n):
            return
        if 0 <= n < NUM_LOOP_LAYERS:
            self._active_idx = n
            self._flash_mask = 0
            self._refresh_display()

    def channel_status(self, idx):
        """Layer `idx` for the channel view: "rec" (recording or
        overdubbing), "armed" (armed or counting in), "muted", "content" or
        "empty"."""
        layer = self._layers[idx]
        if idx == self._active_idx:
            if self._rec_state == _RECORDING:
                return "rec"
            if self._rec_state == _ARMED or self._rec_state == _COUNTDOWN:
                return "armed"
        if layer.state == _OVERDUB:
            return "rec"
        if layer.state == _MUTED:
            return "muted"
        if layer.state == _IDLE:
            return "empty"
        return "content"

    def played_at(self, idx):
        """When layer `idx` last played a note."""
        return self._played_at[idx]

    def toggle_mute(self, idx):
        self._toggle_mute(idx)
        self._refresh_display()

    # ── For AUTO (arranger.py) ────────────────────────────────────────────────

    def can_arrange(self, idx):
        """True for a layer AUTO may mute / unmute: one with a committed
        loop that's playing or muted (not idle, not being recorded or
        overdubbed)."""
        state = self._layers[idx].state
        return state == _PLAYING or state == _MUTED

    def is_muted(self, idx):
        return self._layers[idx].state == _MUTED

    def set_muted(self, idx, muted):
        layer = self._layers[idx]
        if muted and layer.state == _PLAYING:
            layer.state = _MUTED
            self._release_playback(idx)
        elif not muted and layer.state == _MUTED:
            layer.state = _PLAYING
        self._refresh_display()

    @property
    def pass_index(self):
        """Which pass of the loop is playing, counted from 0 since the
        loop was first recorded or loaded (-1 before the first). A resume
        starts a new pass. AUTO's phrase clock for a freeform loop -- which
        has no bar lines, so the count needn't restart with the transport."""
        return self._pass_index

    def clear_layer(self, idx):
        self._clear_layer(idx)
        self._refresh_display()

    # ── Sync coordinator interface ────────────────────────────────────────────

    def set_snap_mode(self, enabled):
        self._synced              = enabled
        self._snap_active         = False
        self._snap_bar_count      = 0
        self._snap_stop_requested = False

    def set_display_owner(self, is_owner):
        self._is_display_owner = is_owner
        if is_owner:
            self._refresh_display()

    # ── Event handling ────────────────────────────────────────────────────────

    def handle_event(self, event, now, exact=False):
        """exact: a press already on the grid, recorded at `now` as given
        (see "Exact presses" above)."""
        etype, data = event
        layer = self._layers[self._active_idx]

        if etype == PAD_DOWN:
            pad = data
            self._synth.trigger_layer_pad(self._active_idx, pad)
            self._held_mask |= (1 << pad)
            self._played_at[self._active_idx] = now
            layer.last_pad = pad

            needs_release = self._needs_release(self._active_idx, pad)

            if self._rec_state == _ARMED:
                self._loop_start    = now
                self._rec_state     = _RECORDING
                layer.events        = NoteList(((0.0, pad),))
                layer.releases      = NoteList()
                layer.open_onsets   = {pad: (0.0, 0.0)} if needs_release else {}
                layer.last_release  = None
                if self._synced:
                    self._snap_active    = True
                    self._snap_bar_count = 0

            elif self._rec_state == _COUNTDOWN:
                if exact:
                    # Only a press timed at the take's start joins it.
                    start = self.count_in_start
                    if start is not None and abs(now - start) < _EXACT_EPS:
                        self._countdown_snap_pads.add(pad)
                        self._countdown_down_pads.add(pad)
                else:
                    if self._countdown_number == 1:
                        self._countdown_snap_pads.add(pad)
                    self._countdown_down_pads.add(pad)

            elif self._rec_state == _RECORDING:
                # Clamp rather than let a negative pos through: `now` is the
                # pad's true (debounce-corrected) press time, which can
                # occasionally predate self._loop_start by a few ms if the
                # press physically happened right at the COUNTDOWN->RECORDING
                # boundary but wasn't debounce-confirmed until just after --
                # such a press belongs at the very start of the loop anyway.
                pos = max(0.0, now - self._loop_start)
                if len(layer.events) < MAX_LOOP_EVENTS:
                    quantize = self._synced and not exact
                    evt_pos = self._quantize_pos(pos) if quantize else pos
                    if quantize and self._synth.layer_is_melodic(self._active_idx):
                        self._keep_join(layer, evt_pos, now)
                    layer.events.append(evt_pos, pad)
                    if needs_release:
                        # Keep both: the real onset measures the held
                        # length, the recorded (possibly snapped) one
                        # anchors where the release goes -- see PAD_UP
                        # handling below.
                        layer.open_onsets[pad] = (pos, evt_pos)

            elif layer.state == _OVERDUB:
                elapsed  = now - layer.play_start
                loop_pos = elapsed % layer.loop_duration
                if len(layer.events) < MAX_LOOP_EVENTS:
                    quantize = self._synced and not exact
                    evt_pos = (self._quantize_pos(loop_pos, layer.loop_duration)
                               if quantize else loop_pos)
                    if exact:
                        # Timed on the seam (an arp note rounded forward
                        # onto the 1) but a hair short of it after the
                        # modulo: it belongs at the top.
                        if layer.loop_duration - evt_pos < _EXACT_EPS:
                            evt_pos = 0.0
                        loop_pos = evt_pos
                    if quantize and self._synth.layer_is_melodic(self._active_idx):
                        self._keep_join(layer, evt_pos, now, layer.loop_duration)
                    layer.events.append(evt_pos, pad)
                    if needs_release:
                        layer.open_onsets[pad] = (loop_pos, evt_pos)

        elif etype == PAD_UP:
            self._release_pad(self._active_idx, data)
            self._held_mask &= ~(1 << data)

            if self._rec_state == _COUNTDOWN:
                self._countdown_down_pads.discard(data)

            recording = self._rec_state == _RECORDING
            if recording or layer.state == _OVERDUB:
                onset = layer.open_onsets.pop(data, None)
                if onset is not None:
                    real_onset, recorded_onset = onset
                    rel_pos = (max(0.0, now - self._loop_start) if recording else
                               (now - layer.play_start) % layer.loop_duration)
                    # A release position before its onset means the hold
                    # crossed the loop seam (only possible in OVERDUB) --
                    # too ambiguous to place on the grid, so skip it and
                    # let the voice's hold_ms fallback release it instead.
                    if rel_pos >= real_onset and len(layer.releases) < MAX_LOOP_EVENTS:
                        # Preserve the played length: the release moves
                        # with its (possibly quantized) onset -- which also
                        # covers an OVERDUB onset that snapped past the end
                        # and wrapped to 0. Anything that lands past the
                        # loop end is pulled back inside it: here for
                        # OVERDUB, at commit time (_fit_to_duration) for a
                        # recording, whose final length isn't known yet.
                        rel_pos = recorded_onset + (rel_pos - real_onset)
                        if not recording:
                            rel_pos = min(rel_pos, layer.loop_duration - _SEAM_EPS)
                        layer.releases.append(rel_pos, data)
                        layer.last_release = (len(layer.releases) - 1,
                                              recorded_onset, now)

        elif etype == TICK:
            if self._rec_state == _COUNTDOWN and self._countdown_kind == "beat":
                self._countdown_tick = (now, data)
                if data == 0:
                    if self._countdown_extra_bar:
                        # Consume the skipped wrap: the bar starting now is
                        # long enough for the full countdown, so start
                        # counting down through it instead of recording.
                        self._countdown_extra_bar = False
                        self._countdown_number    = _COUNTDOWN_STEPS
                    else:
                        self._start_countdown_recording(now)
                elif not self._countdown_extra_bar and data % _STEPS_PER_BEAT == 0:
                    remaining_steps = STEPS_PER_BAR - data
                    self._countdown_number = max(1, min(_COUNTDOWN_STEPS,
                                                         remaining_steps // _STEPS_PER_BEAT))

            elif self._rec_state == _RECORDING and self._snap_active:
                if data == 0:
                    self._snap_bar_count += 1
                    if self._snap_stop_requested:
                        self._commit_snap_recording(now)

        elif etype == BTN_DOWN:
            if data == BTN_RECORD:
                self._handle_record(now)
            elif data == BTN_MUTE:
                self._toggle_mute(self._active_idx)

        self._refresh_display()

    def update(self, now):
        """
        Tick all playing layers. Auto-commits a recording when master_duration
        elapses (used for layers 2-8 to lock them to the master loop length).
        Called every main-loop pass while the transport runs, so it
        allocates nothing in the common case.
        """
        if (self._rec_state == _RECORDING
                and self._master_dur > 0
                and not self._snap_active):
            if now - self._loop_start >= self._master_dur:
                self._commit_recording(self._master_dur)

        if self._rec_state == _COUNTDOWN and self._countdown_kind == "time":
            if now >= self._countdown_target:
                self._start_countdown_recording(now)
                self._refresh_display()
            else:
                # Fixed time per number, not proportional to the total wait:
                # a loop that just wrapped shows blank "ARM " (0) until the
                # final _COUNT_IN_SECONDS, then counts down 3-2-1 at a
                # steady pace. A short wait just starts wherever that pace
                # lands (e.g. straight into "ARM1"), never inventing time
                # that isn't there.
                remaining  = self._countdown_target - now
                steps_left = int(-(-remaining // _TIME_PER_STEP))  # ceil
                number     = steps_left if steps_left <= _COUNTDOWN_STEPS else 0
                if number != self._countdown_number:
                    self._countdown_number = number
                    self._refresh_display()

        # Three rounds over the layers, firing as they go: the previous
        # pass's leftover releases first, so they can't cut off a note this
        # pass just started; then note-ons; then note-offs, so a note
        # recorded with a very short hold (onset and release landing in the
        # same frame) still audibly re-triggers rather than being
        # immediately silenced. Nothing is collected into lists on the way:
        # this runs every main-loop pass, and anything it allocated would
        # bring the next (audio-stalling) garbage collection closer.
        live    = self._layer_live
        pos     = self._layer_pos
        wrapped = False

        # States are compared with ==, never `in (_PLAYING, _OVERDUB)`: a
        # tuple of names is built afresh on every test (16 bytes on the
        # device), and at 8 layers a pass that was most of the main loop's
        # garbage.
        for idx in range(NUM_LOOP_LAYERS):
            layer = self._layers[idx]
            state = layer.state
            live[idx] = ((state == _PLAYING or state == _OVERDUB) and
                         len(layer.events.pad) > 0 and layer.loop_duration > 0)
            if not live[idx]:
                continue

            elapsed    = now - layer.play_start
            loop_count = int(elapsed / layer.loop_duration)
            pos[idx]   = elapsed - loop_count * layer.loop_duration

            if loop_count != layer.last_loop_cnt:
                if layer.last_loop_cnt != -1:
                    # Releases the previous pass never reached (no frame
                    # landed between them and the loop end -- e.g. one
                    # pulled back to just before the seam) still fire,
                    # instead of being skipped when the indices reset.
                    pads = layer.releases.pad
                    for i in range(layer.next_rel_idx, len(pads)):
                        self._release_pad(idx, pads[i])
                layer.last_loop_cnt = loop_count
                layer.next_evt_idx  = 0
                layer.next_rel_idx  = 0
                wrapped = True

        active_mask = 0
        for idx in range(NUM_LOOP_LAYERS):
            if not live[idx]:
                continue
            layer     = self._layers[idx]
            positions = layer.events.pos
            pads      = layer.events.pad
            while layer.next_evt_idx < len(pads):
                if positions[layer.next_evt_idx] > pos[idx]:
                    break
                pad = pads[layer.next_evt_idx]
                self._synth.trigger_layer_pad(idx, pad)
                self._played_at[idx] = now
                if idx == self._active_idx:
                    active_mask |= (1 << pad)
                layer.next_evt_idx += 1

        for idx in range(NUM_LOOP_LAYERS):
            if not live[idx]:
                continue
            layer     = self._layers[idx]
            positions = layer.releases.pos
            pads      = layer.releases.pad
            while layer.next_rel_idx < len(pads):
                if positions[layer.next_rel_idx] > pos[idx]:
                    break
                self._release_pad(idx, pads[layer.next_rel_idx])
                layer.next_rel_idx += 1

        if active_mask:
            self._flash_mask  |= active_mask
            self._flash_until  = now + _FLASH_DURATION
        elif self._flash_mask and now >= self._flash_until:
            self._flash_mask = 0

        # Every layer shares the loop's length and phase, so a wrap is a new
        # pass -- but a layer committed at the wrap can report its own wrap
        # a moment after the others: one count per half-loop at most.
        if wrapped and (self._pass_index < 0 or
                        now - self._pass_at > self._master_dur / 2):
            self._pass_index += 1
            self._pass_at     = now

        if wrapped:
            # The text: a wrap is where an auto-committed take shows as
            # playing. (The pad lights are drawn from flash_mask.)
            self._refresh_display()

    # ── Private ───────────────────────────────────────────────────────────────

    def _handle_record(self, now):
        layer = self._layers[self._active_idx]

        if self._rec_state == _IDLE:
            if layer.state == _IDLE:
                layer.events      = NoteList()
                layer.releases    = NoteList()
                layer.open_onsets = {}
                if self._master_dur > 0:
                    # A later layer: always quantized to the existing
                    # loop's own wrap-to-zero, regardless of sync mode.
                    self._begin_countdown("time", now)
                elif self._synced:
                    # First layer, synced: quantized to the sequencer's
                    # next bar boundary.
                    self._begin_countdown("beat", now)
                else:
                    # First layer, no reference at all: original
                    # behavior -- starts on the first pad press.
                    self._rec_state = _ARMED
            elif layer.state == _PLAYING:
                layer.state = _OVERDUB
                layer.last_release = None
            elif layer.state == _OVERDUB:
                layer.events.sort()
                layer.releases.sort()
                layer.open_onsets = {}
                layer.state = _PLAYING
            # MUTED: RECORD is a no-op; use MUTE button to toggle

        elif self._rec_state == _ARMED or self._rec_state == _COUNTDOWN:
            self._rec_state           = _IDLE
            self._countdown_kind      = None
            self._countdown_snap_pads = set()
            self._countdown_down_pads = set()
            # Only a first layer's arm carries the session's sync intent
            # (code.py picks snap/freeform when it's armed) -- cancelling
            # that resets it. Cancelling a later layer's countdown must
            # leave an existing session's sync alone, or a synced loop
            # would lose its PLAY/STOP link and BPM lock.
            if self._master_dur == 0:
                self._was_cleared = True

        elif self._rec_state == _RECORDING:
            if self._snap_active:
                # Request to stop, not an immediate cut: keep capturing
                # through the current bar and commit at the next step-0
                # boundary, so the loop always lands on a whole bar count.
                self._snap_stop_requested = True
            elif self._master_dur > 0:
                # A later layer: stop capturing now, but still commit the
                # full master_duration -- the untouched remainder just
                # plays back silent, same as if you'd never overdubbed it.
                self._commit_recording(self._master_dur)
            else:
                dur = now - self._loop_start
                if dur > 0.05 and layer.events:
                    self._commit_recording(dur)
                else:
                    self._rec_state = _IDLE
                    layer.state     = _IDLE

    def _begin_countdown(self, kind, now):
        """Arm a quantized-start recording. "beat" waits for the sequencer's
        next bar boundary (driven by TICK, see handle_event); "time" waits
        for the existing reference layer's own loop wrap (driven by
        update())."""
        self._rec_state           = _COUNTDOWN
        self._countdown_kind      = kind
        self._countdown_number    = 0   # blank "ARM " until inside the final stretch
        self._countdown_extra_bar = False
        self._countdown_snap_pads = set()
        self._countdown_down_pads = set()
        if kind == "beat":
            # If the upcoming wrap is too close for a full 3-2-1 to play
            # out (e.g. REC pressed late in a short bar), skip it and
            # count down through the bar after instead -- see the TICK
            # handler in handle_event.
            remaining_steps = STEPS_PER_BAR - self._seq.current_step
            remaining_beats = remaining_steps // _STEPS_PER_BEAT
            if remaining_beats < _COUNTDOWN_STEPS:
                self._countdown_extra_bar = True
        elif kind == "time":
            ref      = self._find_reference_layer()
            elapsed  = now - ref.play_start
            loop_pos = elapsed % ref.loop_duration
            remaining = ref.loop_duration - loop_pos
            self._countdown_target = now + remaining

    def _start_countdown_recording(self, now):
        """Countdown reached its target: begin capturing events for real.
        Pads pressed during the final "ARM1" step (self._countdown_snap_pads)
        are captured retroactively as onsets at position 0 -- whether they
        were tapped and released before this moment or are still held (in
        which case an open onset is seeded so the eventual real PAD_UP
        produces a proper recorded release, same as any other note).

        A "time" countdown (later layer) is polled from update(), which only
        runs once per main-loop iteration -- by the time it notices
        now >= self._countdown_target, `now` has already overshot the target
        by however long that iteration took. Anchoring loop_start to the
        exact target instead of `now` drops that scheduling jitter, so the
        new layer lands exactly on the reference layer's wrap instead of a
        few ms late (later layers otherwise pick up their own independent
        jitter, and since _find_reference_layer can reference any non-idle
        layer, that error could propagate into the next layer recorded too).
        A "beat" countdown (first layer) is already exact -- it's driven
        directly from the TICK handler at the instant TICK(0) fires, so
        `now` there already is the precise instant."""
        layer = self._layers[self._active_idx]
        self._loop_start   = (self._countdown_target if self._countdown_kind == "time"
                               else now)
        self._rec_state    = _RECORDING
        layer.events       = NoteList()
        layer.releases     = NoteList()
        layer.open_onsets  = {}
        layer.last_release = None
        for pad in self._countdown_snap_pads:
            if len(layer.events) >= MAX_LOOP_EVENTS:
                break
            layer.events.append(0.0, pad)
            if pad in self._countdown_down_pads and self._needs_release(self._active_idx, pad):
                layer.open_onsets[pad] = (0.0, 0.0)
        self._countdown_snap_pads = set()
        self._countdown_down_pads = set()
        if self._countdown_kind == "beat":
            self._snap_active         = True
            self._snap_bar_count      = 0
            self._snap_stop_requested = False
        self._countdown_kind = None

    def _find_reference_layer(self):
        """Any non-idle layer -- muted layers still keep a valid, undrifted
        play_start/loop_duration -- to use as a wrap-to-zero reference for
        _begin_countdown("time", ...). Guaranteed to find one whenever
        master_dur > 0, since that's only ever set by committing a layer."""
        for l in self._layers:
            if l.state != _IDLE and l.loop_duration > 0:
                return l
        return None

    def _commit_recording(self, duration):
        layer = self._layers[self._active_idx]
        self._fit_to_duration(layer, duration)
        layer.open_onsets = {}
        layer.loop_duration = duration
        if self._master_dur == 0.0:
            self._master_dur = duration
            # First layer ever committed: start playing immediately, like
            # a real looper pedal, instead of making you press PLAY
            # separately. A synced first layer already has the transport
            # running by the time it can commit, so this only actually
            # does anything for a freeform session.
            self._transport_playing = True
        self._rec_state = _IDLE
        self._start_layer_playback(layer)

    def _fit_to_duration(self, layer, duration):
        """Fold anything recorded at or past the loop end back inside it,
        then sort both lists. Only reachable with quantization on: a note
        played in the last fraction of a step can snap to exactly
        `duration` (which would never fire -- playback positions are always
        < loop_duration), and a length-preserving release can land past
        the end. An onset past the end wraps to the loop top, and so does
        its own release, keeping the pair together; any other release past
        the end is pulled back to just before the seam (update()'s wrap
        flush guarantees it still fires).

        Runs as a take commits, mid-playback, so it works in place on the
        flat arrays: building a few hundred (pos, pad) tuples here once
        stalled the audio for a third of a second. Only the handful of
        notes past the end are touched; the sorts are by index."""
        on_pos, on_pad   = layer.events.pos, layer.events.pad
        rel_pos, rel_pad = layer.releases.pos, layer.releases.pad
        # Releases first, while the onsets still hold their recorded
        # positions: one past the end wraps with its note if that pad's
        # latest onset at or before it (an onset sorts ahead of a release
        # at the same position) wrapped too.
        for j in range(len(rel_pos)):
            pos = rel_pos[j]
            if pos < duration:
                continue
            pad    = rel_pad[j]
            latest = -1.0
            for i in range(len(on_pos)):
                if on_pad[i] == pad and latest < on_pos[i] <= pos:
                    latest = on_pos[i]
            if latest >= duration:
                rel_pos[j] = min(pos - duration, duration - _SEAM_EPS)
            else:
                rel_pos[j] = duration - _SEAM_EPS
        for i in range(len(on_pos)):
            if on_pos[i] >= duration:
                on_pos[i] = max(0.0, on_pos[i] - duration)
        layer.events.sort()
        layer.releases.sort()

    def _commit_snap_recording(self, now):
        # Duration is derived from the exact tempo grid (bar_count whole
        # bars of step_dur each), not measured as a wall-clock delta
        # between the start/end TICKs -- those real `now` reads each carry
        # a little scheduling jitter, and a wall-clock-measured period
        # would very slightly mismatch the sequencer's own step_dur-based
        # clock, causing the two to drift apart over long sessions even
        # though each is individually steady. Tempo can't have changed
        # mid-recording: code.py blocks the menu's BPM edit for the whole
        # "snap" session.
        bar_count = self._snap_bar_count
        self._snap_active         = False
        self._snap_bar_count      = 0
        self._snap_stop_requested = False
        layer = self._layers[self._active_idx]
        dur   = bar_count * STEPS_PER_BAR * self._seq.step_dur
        if dur > 0.05 and layer.events:
            self._commit_recording(dur)
        else:
            self._rec_state = _IDLE
            layer.state     = _IDLE

    def _start_layer_playback(self, layer):
        """Begin playback. Recorded event positions are already relative to
        the real moment this recording started (self._loop_start), and
        clock.now() doesn't drift, so anchoring play_start there is
        all that's needed to keep this layer in phase with every other
        layer -- no re-derivation from another layer's current position."""
        layer.play_start    = self._loop_start
        layer.last_loop_cnt = -1
        layer.next_evt_idx  = 0
        layer.next_rel_idx  = 0
        layer.state         = _PLAYING

    def _toggle_mute(self, idx):
        layer = self._layers[idx]
        if layer.state == _PLAYING or layer.state == _OVERDUB:
            layer.state = _MUTED
            self._release_playback(idx)
        elif layer.state == _MUTED:
            # play_start/loop_duration already fix this layer's phase
            # forever (pure now-based modulo, no drift) -- muting only
            # skips the trigger pass in update(), so unmuting needs no
            # realignment; the next update() call resyncs next_evt_idx
            # from the (possibly stale) last_loop_cnt on its own.
            layer.state = _PLAYING
        # IDLE: nothing to mute

    def _clear_layer(self, idx):
        # Its recorded note-offs go with it: let go of what it left sounding.
        self._release_playback(idx)
        layer               = self._layers[idx]
        layer.events        = NoteList()
        layer.releases      = NoteList()
        layer.open_onsets   = {}
        layer.loop_duration = 0.0
        layer.state         = _IDLE
        if self._active_idx == idx:
            self._flash_mask = 0
            if self._rec_state != _IDLE:
                self._rec_state = _IDLE
        if all(l.state == _IDLE for l in self._layers):
            self._master_dur  = 0.0
            self._pass_index  = -1
            self._was_cleared = True

    def clear_all(self):
        """Called externally by code.py: CLEAR's "every layer" scope."""
        for idx in range(NUM_LOOP_LAYERS):
            self._release_playback(idx)   # see _clear_layer
        for layer in self._layers:
            layer.events        = NoteList()
            layer.releases      = NoteList()
            layer.open_onsets   = {}
            layer.loop_duration = 0.0
            layer.state         = _IDLE
        self._master_dur  = 0.0
        self._rec_state   = _IDLE
        self._flash_mask  = 0
        self._pass_index  = -1
        self._was_cleared = True
        self._refresh_display()

    def set_playing(self, playing, now):
        """Called externally by code.py on a PLAY/STOP press (and kept
        in sync with the sequencer's own transport, except in a freeform
        session -- see code.py). Pausing doesn't stop code.py from calling
        handle_event for non-clock events (previewing a pad still works),
        but code.py stops calling update() while paused, so nothing
        advances or triggers. On resume, every already-committed layer
        restarts at position 0 rather than resuming its exact pre-pause
        phase -- simpler, and it means every layer (and the sequencer, in a
        synced session -- code.py resets its own step clock to 0 the same
        way on resume) comes back trivially lockstepped from one shared
        instant instead of each independently reconstructing fractional
        phase across the pause."""
        if playing == self._transport_playing:
            return
        self._transport_playing = playing
        if playing:
            for layer in self._layers:
                if layer.state != _IDLE:
                    layer.play_start    = now
                    layer.last_loop_cnt = -1
                    layer.next_evt_idx  = 0
                    layer.next_rel_idx  = 0
            # An in-progress (not yet committed) recording has no "start of
            # loop" to snap back to -- it still just shifts forward by the
            # exact pause duration, preserving what's already been captured.
            if self._paused_at is not None:
                paused_for = now - self._paused_at
                if self._rec_state == _RECORDING:
                    self._loop_start += paused_for
                elif self._rec_state == _COUNTDOWN and self._countdown_kind == "time":
                    self._countdown_target += paused_for
        else:
            self._paused_at = now
            # update() stops here, so the recorded note-offs would never
            # come: let go of whatever playback left sounding.
            for idx in range(NUM_LOOP_LAYERS):
                self._release_playback(idx)
        self._refresh_display()

    # ── Grooves (called by code.py for the menu's SAVE / LOAD) ────────────────

    def snapshot(self):
        """Every committed layer as plain data. A layer mid-overdub is saved
        as playing (sorted copies -- overdub appends out of order); one
        still being recorded for the first time is IDLE until it commits,
        so it's left out along with the rest of the in-progress take."""
        layers = []
        for layer in self._layers:
            if layer.state == _IDLE or layer.loop_duration <= 0:
                layers.append(None)
                continue
            layers.append({
                "dur":   layer.loop_duration,
                "muted": layer.state == _MUTED,
                "on":    sorted(layer.events, key=lambda e: e[0]),
                "off":   sorted(layer.releases, key=lambda e: e[0]),
            })
        return {"master": self._master_dur, "layers": layers}

    def restore(self, data, v1_notes=False):
        """Replace everything with a snapshot(). Expects the transport
        already stopped (code.py does that first), so the next PLAY starts
        every layer from the top via set_playing(). Unlike clear_all() this
        never flags was_cleared -- code.py sets the loaded groove's sync
        mode itself, and that flag would reset it to "none" at frame end.
        v1_notes: the snapshot is from a v1 groove (see groove.py), so the
        notes on melodic layers move to today's layout -- which needs the
        layers' instruments already restored."""
        self._rec_state           = _IDLE
        self._countdown_kind      = None
        self._countdown_number    = 0
        self._countdown_snap_pads = set()
        self._countdown_down_pads = set()
        self._snap_active         = False
        self._snap_bar_count      = 0
        self._snap_stop_requested = False
        self._flash_mask          = 0
        self._pass_index          = -1
        self._was_cleared         = False

        saved = data.get("layers", [])
        for idx, layer in enumerate(self._layers):
            entry = saved[idx] if idx < len(saved) else None
            dur   = entry.get("dur", 0.0) if entry else 0.0
            layer.open_onsets   = {}
            layer.last_loop_cnt = -1
            layer.next_evt_idx  = 0
            layer.next_rel_idx  = 0
            if dur <= 0:
                layer.events, layer.releases = NoteList(), NoteList()
                layer.loop_duration = 0.0
                layer.state         = _IDLE
                continue
            remap = v1_notes and self._synth.layer_is_melodic(idx)
            layer.events        = _restore_entries(entry.get("on", []), dur, remap)
            layer.releases      = _restore_entries(entry.get("off", []), dur, remap)
            layer.loop_duration = dur
            layer.state         = _MUTED if entry.get("muted") else _PLAYING

        live = [l for l in self._layers if l.state != _IDLE]
        self._master_dur = (data.get("master") or live[0].loop_duration) if live else 0.0
        self._refresh_display()

    # ── Loop-length edits (called by the menu's EXTEND / MIRROR) ──────────────

    def can_modify_length(self):
        """True when a loop exists and nothing is being captured: no
        recording/countdown, and no layer mid-overdub (overdub toggling
        happens entirely within _rec_state == _IDLE, so it needs its own
        check)."""
        return (self._rec_state == _IDLE and self._master_dur > 0 and
                all(l.state != _OVERDUB for l in self._layers))

    def extend_loop(self, now):
        """Double the loop length for every layer (they all share one
        master_duration); content is untouched, so the new second half is
        silent everywhere. Each layer is re-anchored so its current pass
        plays out before the silent half starts -- just doubling
        loop_duration would remap the position to elapsed % 2L, dropping
        into silence mid-pass on every odd pass. The re-anchor moves
        play_start by a whole number of old loop lengths, so layers stay
        phase-aligned and a synced loop stays bar-aligned. Returns False
        (no-op) unless can_modify_length()."""
        if not self.can_modify_length():
            return False
        for layer in self._layers:
            if layer.state == _IDLE or layer.loop_duration <= 0:
                continue
            old_pos = (now - layer.play_start) % layer.loop_duration
            layer.play_start     = now - old_pos
            layer.loop_duration *= 2
            self._resync_layer(layer, now)
        self._master_dur *= 2
        return True

    def mirror_active_layer(self, now):
        """Replace the active layer's second half with a copy of its first
        half (anything already in the second half is dropped). Every copied
        note that needs a release gets one: its original's release shifted
        by half the loop, pulled back to just before the seam if that would
        land past the end (not wrapped into the next pass, where on a
        melodic layer it would cut off the first half's notes), or at the
        seam if the original had none. Returns False with nothing changed if
        the layer is idle, can_modify_length() fails, or the result would
        exceed MAX_LOOP_EVENTS."""
        if not self.can_modify_length():
            return False
        idx   = self._active_idx
        layer = self._layers[idx]
        if layer.state == _IDLE or layer.loop_duration <= 0:
            return False
        dur  = layer.loop_duration
        half = dur / 2
        seam = dur - _SEAM_EPS

        # Pair every onset with its release: a release belongs to the latest
        # still-unpaired onset of the same pad at or before it (onsets sort
        # ahead of releases at equal positions). Exact, given the recording
        # invariant that a release is never before its own onset. Like
        # _fit_to_duration this runs mid-playback, so it walks the two
        # lists in position order by index -- no (pos, pad) tuples.
        on_pos, on_pad   = layer.events.pos, layer.events.pad
        rel_pos, rel_pad = layer.releases.pos, layer.releases.pad
        on_order  = _order_by_pos(on_pos)
        rel_order = _order_by_pos(rel_pos)
        open_by_pad = [[] for _ in range(NUM_PADS)]   # unpaired onset indices
        release_of  = array.array("f", [-1.0] * len(on_pos))   # -1: none
        a = 0
        for j in rel_order:
            pos = rel_pos[j]
            while a < len(on_order) and on_pos[on_order[a]] <= pos:
                i = on_order[a]
                open_by_pad[on_pad[i]].append(i)
                a += 1
            stack = open_by_pad[rel_pad[j]]
            if stack:
                release_of[stack.pop()] = pos

        # Count before building, so a result that won't fit changes nothing.
        n_events = n_releases = 0
        for i in range(len(on_pos)):
            if on_pos[i] < half:
                n_events += 2
                if release_of[i] >= 0:
                    n_releases += 2
                elif self._needs_release(idx, on_pad[i]):
                    n_releases += 1
        if n_events > MAX_LOOP_EVENTS or n_releases > MAX_LOOP_EVENTS:
            return False

        events, releases = NoteList(), NoteList()
        for i in range(len(on_pos)):
            pos, pad = on_pos[i], on_pad[i]
            if pos >= half:
                continue
            events.append(pos, pad)
            events.append(pos + half, pad)
            rel = release_of[i]
            if rel >= 0:
                releases.append(rel, pad)
                releases.append(min(rel + half, seam), pad)
            elif self._needs_release(idx, pad):
                releases.append(seam, pad)
        events.sort()
        releases.sort()
        layer.events, layer.releases = events, releases
        layer.open_onsets = {}
        self._resync_layer(layer, now)
        return True

    def _resync_layer(self, layer, now):
        """Re-derive a layer's pass/position bookkeeping after its timing or
        content changed mid-playback, so update() carries on from the
        current position. (Not last_loop_cnt = -1 / indices = 0: that would
        replay every event before the current position in one burst and
        count a spurious wrap.)"""
        elapsed    = now - layer.play_start
        loop_count = int(elapsed / layer.loop_duration)
        loop_pos   = elapsed - loop_count * layer.loop_duration
        layer.last_loop_cnt = loop_count
        layer.next_evt_idx  = _count_through(layer.events, loop_pos)
        layer.next_rel_idx  = _count_through(layer.releases, loop_pos)

    def _quantize_pos(self, pos, loop_duration=None):
        """Snap a just-recorded note-on position to a grid line (see
        _QUANT_SUBDIV, _QUANT_BIAS). Audio has already fired by the time
        this runs (see PAD_DOWN handling) -- only the recorded position
        moves, so quantization is only ever audible on loop playback."""
        q = snap(pos, quant_grid(self._seq.step_dur))
        if loop_duration is not None and q >= loop_duration:
            q = 0.0   # rounded up into the next bar -- wrap to the loop's top
        return max(0.0, q)

    def _keep_join(self, layer, evt_pos, now, dur=None):
        """Keep the join between a melodic layer's notes as played, despite
        quantization. Only note starts snap to the grid -- each release
        moves with its own note -- so on a one-voice layer a release and
        the next note's start can swap places: an overlapping (legato) pair
        would play back as separate notes, and separate notes a hair apart
        as legato (tied, or gliding). Called with a new note's recorded
        start, before it's added:
          - Legato (a pad still held): the held note's release isn't
            recorded at all. Live it's ignored anyway -- the voice has moved
            on to the new note -- so with no release to move, playback
            can't pull the two apart.
          - Separate: if the previous note's recorded release now lands
            after this start (or too close before it), it's pulled back to
            the real gap before it, at least _MIN_NOTE_GAP -- never before
            its own note's start.
        dur: the loop length while overdubbing (positions wrap); None while
        recording a take (positions run on)."""
        last, layer.last_release = layer.last_release, None
        if layer.open_onsets:
            layer.open_onsets.clear()
            return
        if last is None:
            return
        idx, onset, released_at = last
        gap = now - released_at
        if gap >= 2 * self._seq.step_dur / _QUANT_SUBDIV:
            return   # snapping moves a start under one grid step: no swap possible
        rel_pos = layer.releases.pos[idx]
        ahead = rel_pos - evt_pos   # > 0: the release lands after this start
        if dur:
            ahead = (ahead + dur / 2) % dur - dur / 2
        lead = max(gap, _MIN_NOTE_GAP)
        if ahead > -lead:
            layer.releases.pos[idx] = max(onset, rel_pos - ahead - lead)

    def _needs_release(self, layer_idx, pad):
        """True if this pad's note doesn't self-release and needs an
        explicit release -- a melodic layer's voice, or a sustained
        (hold_ms > 0) kit pad on that layer's own kit."""
        return self._synth.layer_pad_needs_release(layer_idx, pad)

    def _release_pad(self, layer_idx, pad):
        self._synth.release_layer_pad(layer_idx, pad)

    def _release_playback(self, idx):
        """Let go of what layer idx's playback left sounding (pause, mute,
        clear): its recorded note-offs stop coming with update(). The
        player's own held pads on the active layer are theirs to release."""
        keep = self._held_mask if idx == self._active_idx else 0
        self._synth.release_layer_notes(idx, keep)

    def _refresh_display(self):
        if not self._is_display_owner:
            return
        layer = self._layers[self._active_idx]
        if self._rec_state == _ARMED:
            disp_state = _ARMED
        elif self._rec_state == _COUNTDOWN:
            disp_state = _ARMED if self._countdown_number == 0 else f"ARM{self._countdown_number}"
        elif self._rec_state == _RECORDING:
            disp_state = _RECORDING
        else:
            disp_state = layer.state

        self._display.show_looper_state(
            disp_state,
            layer_num=self._active_idx + 1,
            synced=self._synced and self._snap_active,
        )
