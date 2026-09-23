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
  note-on). A freeform (unsynced) loop is unaffected -- there's no tempo
  grid to snap to.

Loop-length edits (the menu's EXTEND / MIRROR, only while nothing is being
captured -- see can_modify_length):
  EXTEND doubles every layer's length; the new second half is silent.
  MIRROR replaces the active layer's second half with a copy of its first.

Snap-to-bar sync:
  A synced first layer's recording (after its countdown lands on the 1)
  keeps capturing bar after bar -- get a beat going, however many bars you
  want -- until RECORD is pressed to end it. That press is a stop request,
  not an immediate cut: recording keeps running through the current bar
  and commits at the next step-0 boundary, so the loop is always a whole
  number of bars, at least one, and never shorter than what you actually
  played. (Later layers auto-commit at master_duration instead.)
"""

from event_types import PAD_DOWN, PAD_UP, BTN_DOWN, BTN_UP, TICK
from config import (BTN_RECORD, BTN_MUTE,
                    MAX_LOOP_EVENTS, NUM_LOOP_LAYERS, STEPS_PER_BAR)

_IDLE      = "IDLE"
_ARMED     = "ARM "
_COUNTDOWN = "CNT "
_RECORDING = "REC "
_PLAYING   = "PLY "
_OVERDUB   = "DUB "
_MUTED     = "MUTE"

_LONG_PRESS_MUTE = 0.6   # seconds: clear active layer
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


def _count_through(entries, pos):
    """Number of leading (pos, pad) entries at or before `pos` -- the index
    update() should carry on from. `entries` must be sorted by position."""
    n = 0
    for entry_pos, _ in entries:
        if entry_pos > pos:
            break
        n += 1
    return n


class LoopLayer:
    def __init__(self):
        self.events        = []    # list of (loop_pos_seconds, pad_index) -- note-on
        self.releases      = []    # list of (loop_pos_seconds, pad_index) -- note-off
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
        self._master_dur = 0.0   # loop length; set by first layer recorded

        # Pad LEDs, active layer only. Two independent sources, combined at
        # display time (see _refresh_display): _held_mask mirrors a pad's
        # live physical down/up state exactly, no timer involved; _flash_mask
        # is a timed pulse for a note auto-triggered by loop playback, which
        # has no physical press to key off of.
        self._held_mask   = 0
        self._flash_mask  = 0
        self._flash_until = 0.0

        # Recording state (applies to whichever layer is being recorded)
        self._rec_state = _IDLE
        self._loop_start = 0.0
        self._bar_count  = 0

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

        # Global transport pause (driven externally by code.py's PLAY/STOP;
        # freezes every wall-clock-anchored timestamp rather than the loop
        # quietly continuing in the background while paused). Starts
        # stopped, so a layer committed before the transport is ever
        # started just sits there until PLAY is pressed. _paused_at stays
        # None until the first real pause; set_playing() treats "never
        # played before" differently from an actual resume (see there).
        self._transport_playing = False
        self._paused_at         = None

        # Long-press timestamps
        self._mute_at = 0.0

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
        return (self._rec_state == _IDLE and
                all(l.state == _IDLE for l in self._layers))

    @property
    def is_playing(self):
        return any(l.state in (_PLAYING, _OVERDUB) for l in self._layers)

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

    # ── Channel navigation (called by code.py MODE gesture handler) ───────────

    def cycle_channel(self):
        if self._rec_state == _RECORDING:
            return   # don't switch layers mid-recording
        self._active_idx = (self._active_idx + 1) % NUM_LOOP_LAYERS
        self._flash_mask = 0
        self._refresh_display()

    def select_channel(self, n):
        if self._rec_state == _RECORDING:
            return
        if 0 <= n < NUM_LOOP_LAYERS:
            self._active_idx = n
            self._flash_mask = 0
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

    def handle_event(self, event, now):
        etype, data = event
        layer = self._layers[self._active_idx]

        if etype == PAD_DOWN:
            pad = data
            self._synth.trigger_layer_pad(self._active_idx, pad)
            self._held_mask |= (1 << pad)
            layer.last_pad = pad

            needs_release = self._needs_release(self._active_idx, pad)

            if self._rec_state == _ARMED:
                self._loop_start    = now
                self._rec_state     = _RECORDING
                layer.events        = [(0.0, pad)]
                layer.releases      = []
                layer.open_onsets   = {pad: (0.0, 0.0)} if needs_release else {}
                if self._synced:
                    self._snap_active    = True
                    self._snap_bar_count = 0

            elif self._rec_state == _COUNTDOWN:
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
                    evt_pos = self._quantize_pos(pos) if self._synced else pos
                    layer.events.append((evt_pos, pad))
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
                    evt_pos = (self._quantize_pos(loop_pos, layer.loop_duration)
                               if self._synced else loop_pos)
                    layer.events.append((evt_pos, pad))
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
                        layer.releases.append((rel_pos, data))

        elif etype == TICK:
            if self._rec_state == _COUNTDOWN and self._countdown_kind == "beat":
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
                self._mute_at = now

        elif etype == BTN_UP:
            if data == BTN_MUTE:
                if now - self._mute_at >= _LONG_PRESS_MUTE:
                    self._clear_layer(self._active_idx)
                else:
                    self._toggle_mute(layer)

        self._refresh_display()

    def update(self, now):
        """
        Tick all playing layers. Auto-commits a recording when master_duration
        elapses (used for layers 2-8 to lock them to the master loop length).
        Returns list of pad indices triggered this frame.
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

        triggered = []
        released  = []
        flushed   = []
        wrapped   = False

        for idx, layer in enumerate(self._layers):
            if layer.state not in (_PLAYING, _OVERDUB):
                continue
            if not layer.events or layer.loop_duration <= 0:
                continue

            elapsed    = now - layer.play_start
            loop_count = int(elapsed / layer.loop_duration)
            loop_pos   = elapsed - loop_count * layer.loop_duration

            if loop_count != layer.last_loop_cnt:
                if layer.last_loop_cnt != -1:
                    # Releases the previous pass never reached (no frame
                    # landed between them and the loop end -- e.g. one
                    # pulled back to just before the seam) still fire,
                    # instead of being skipped when the indices reset.
                    for _, pad in layer.releases[layer.next_rel_idx:]:
                        flushed.append((idx, pad))
                layer.last_loop_cnt = loop_count
                layer.next_evt_idx  = 0
                layer.next_rel_idx  = 0
                wrapped = True

            while layer.next_evt_idx < len(layer.events):
                evt_pos, pad = layer.events[layer.next_evt_idx]
                if evt_pos <= loop_pos:
                    triggered.append((idx, pad))
                    layer.next_evt_idx += 1
                else:
                    break

            while layer.next_rel_idx < len(layer.releases):
                rel_pos, pad = layer.releases[layer.next_rel_idx]
                if rel_pos <= loop_pos:
                    released.append((idx, pad))
                    layer.next_rel_idx += 1
                else:
                    break

        if wrapped:
            self._bar_count += 1

        # Previous-pass releases go first, so they can't cut off a note this
        # pass just started. Then note-ons before note-offs so a note
        # recorded with a very short hold (onset and release landing in the
        # same frame) still audibly re-triggers rather than being
        # immediately silenced.
        for idx, pad in flushed:
            self._release_pad(idx, pad)
        for idx, pad in triggered:
            self._synth.trigger_layer_pad(idx, pad)
        for idx, pad in released:
            self._release_pad(idx, pad)

        active_mask = 0
        for idx, pad in triggered:
            if idx == self._active_idx:
                active_mask |= (1 << pad)

        display_changed = wrapped
        if active_mask:
            self._flash_mask  |= active_mask
            self._flash_until  = now + _FLASH_DURATION
            display_changed = True
        elif self._flash_mask and now >= self._flash_until:
            self._flash_mask = 0
            display_changed = True

        if display_changed:
            self._refresh_display()

        return [pad for _, pad in triggered]

    # ── Private ───────────────────────────────────────────────────────────────

    def _handle_record(self, now):
        layer = self._layers[self._active_idx]

        if self._rec_state == _IDLE:
            if layer.state == _IDLE:
                layer.events      = []
                layer.releases    = []
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
            elif layer.state == _OVERDUB:
                layer.events.sort(key=lambda e: e[0])
                layer.releases.sort(key=lambda e: e[0])
                layer.open_onsets = {}
                layer.state = _PLAYING
            # MUTED: RECORD is a no-op; use MUTE button to toggle

        elif self._rec_state in (_ARMED, _COUNTDOWN):
            self._rec_state           = _IDLE
            self._countdown_kind      = None
            self._countdown_snap_pads = set()
            self._countdown_down_pads = set()
            self._was_cleared         = True   # signal coordinator: snap intent cancelled

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
        layer.events       = []
        layer.releases     = []
        layer.open_onsets  = {}
        for pad in self._countdown_snap_pads:
            if len(layer.events) >= MAX_LOOP_EVENTS:
                break
            layer.events.append((0.0, pad))
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
        flush guarantees it still fires)."""
        merged = sorted([(p, 0, pad) for p, pad in layer.events] +
                        [(p, 1, pad) for p, pad in layer.releases])
        events, releases = [], []
        onset_wrapped = {}   # pad -> whether that pad's latest onset wrapped
        for pos, kind, pad in merged:
            if kind == 0:
                wrapped = pos >= duration
                onset_wrapped[pad] = wrapped
                events.append((max(0.0, pos - duration) if wrapped else pos, pad))
            else:
                if pos >= duration:
                    if onset_wrapped.get(pad):
                        pos = min(pos - duration, duration - _SEAM_EPS)
                    else:
                        pos = duration - _SEAM_EPS
                releases.append((pos, pad))
        events.sort(key=lambda e: e[0])
        releases.sort(key=lambda e: e[0])
        layer.events, layer.releases = events, releases

    def _commit_snap_recording(self, now):
        # Duration is derived from the exact tempo grid (bar_count whole
        # bars of step_dur each), not measured as a wall-clock delta
        # between the start/end TICKs -- those real `now` reads each carry
        # a little scheduling jitter, and a wall-clock-measured period
        # would very slightly mismatch the sequencer's own step_dur-based
        # clock, causing the two to drift apart over long sessions even
        # though each is individually steady. Tempo can't have changed
        # mid-recording: code.py blocks the tempo buttons for the whole
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
        time.monotonic() doesn't drift, so anchoring play_start there is
        all that's needed to keep this layer in phase with every other
        layer -- no re-derivation from another layer's current position."""
        layer.play_start    = self._loop_start
        layer.last_loop_cnt = -1
        layer.next_evt_idx  = 0
        layer.next_rel_idx  = 0
        layer.state         = _PLAYING

    def _toggle_mute(self, layer):
        if layer.state == _PLAYING or layer.state == _OVERDUB:
            layer.state = _MUTED
        elif layer.state == _MUTED:
            # play_start/loop_duration already fix this layer's phase
            # forever (pure now-based modulo, no drift) -- muting only
            # skips the trigger pass in update(), so unmuting needs no
            # realignment; the next update() call resyncs next_evt_idx
            # from the (possibly stale) last_loop_cnt on its own.
            layer.state = _PLAYING
        # IDLE: nothing to mute

    def _clear_layer(self, idx):
        layer               = self._layers[idx]
        layer.events        = []
        layer.releases      = []
        layer.open_onsets   = {}
        layer.loop_duration = 0.0
        layer.state         = _IDLE
        if self._active_idx == idx:
            self._flash_mask = 0
            if self._rec_state != _IDLE:
                self._rec_state = _IDLE
        if all(l.state == _IDLE for l in self._layers):
            self._master_dur  = 0.0
            self._bar_count   = 0
            self._was_cleared = True

    def clear_all(self):
        """Called externally by code.py on a long PLAY/STOP press."""
        for layer in self._layers:
            layer.events        = []
            layer.releases      = []
            layer.open_onsets   = {}
            layer.loop_duration = 0.0
            layer.state         = _IDLE
        self._master_dur  = 0.0
        self._rec_state   = _IDLE
        self._bar_count   = 0
        self._flash_mask  = 0
        self._was_cleared = True
        self._refresh_display()

    def set_playing(self, playing, now):
        """Called externally by code.py on a short PLAY/STOP press (and kept
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
        # invariant that a release is never before its own onset.
        merged = sorted([(p, 0, pad, i) for i, (p, pad) in enumerate(layer.events)] +
                        [(p, 1, pad, 0) for p, pad in layer.releases])
        open_by_pad = {}
        release_of  = {}   # onset index -> its release position
        for pos, kind, pad, i in merged:
            if kind == 0:
                open_by_pad.setdefault(pad, []).append(i)
            else:
                stack = open_by_pad.get(pad)
                if stack:
                    release_of[stack.pop()] = pos

        events, releases = [], []
        for i, (pos, pad) in enumerate(layer.events):
            if pos >= half:
                continue
            events.append((pos, pad))
            events.append((pos + half, pad))
            rel = release_of.get(i)
            if rel is not None:
                releases.append((rel, pad))
                releases.append((min(rel + half, seam), pad))
            elif self._needs_release(idx, pad):
                releases.append((seam, pad))

        if len(events) > MAX_LOOP_EVENTS or len(releases) > MAX_LOOP_EVENTS:
            return False
        events.sort(key=lambda e: e[0])
        releases.sort(key=lambda e: e[0])
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
        grid = self._seq.step_dur / _QUANT_SUBDIV
        q = int(pos / grid + (1.0 - _QUANT_BIAS)) * grid
        if loop_duration is not None and q >= loop_duration:
            q = 0.0   # rounded up into the next bar -- wrap to the loop's top
        return max(0.0, q)

    def _needs_release(self, layer_idx, pad):
        """True if this pad's note doesn't self-release and needs an
        explicit release -- a melodic layer's voice, or a sustained
        (hold_ms > 0) kit pad on that layer's own kit."""
        return self._synth.layer_pad_needs_release(layer_idx, pad)

    def _release_pad(self, layer_idx, pad):
        self._synth.release_layer_pad(layer_idx, pad)

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

        bar = self._snap_bar_count if self._snap_active else self._bar_count
        self._display.show_looper_state(
            self._held_mask | self._flash_mask,
            disp_state,
            bar,
            layer_num=self._active_idx + 1,
            synced=self._synced and self._snap_active,
            transport_playing=self._transport_playing,
        )
