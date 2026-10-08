"""
Arpeggiator -- plays the pads you hold on a LOOP layer one at a time, in
time.

An input effect in front of the looper: code.py hands it the pads your
fingers press (press / release) instead of the looper, and sends what it
plays (update / stop) on to looper.handle_event(..., exact=True), exactly
as fingers would. The looper records the arp's notes as ordinary notes, so
grooves, EXT / MIRR and AUTO need nothing new -- a recorded arp is just
notes.

Settings are per layer (MODE, RATE, GATE -- the menu's ARP item, via
SCHEMA), and so is whether the arp is on (KEY MODE in LOOP's keyboard
view). One arp runs at a time, for the active layer.

  MODE  UP, DN, UPDN (no repeated ends), RAND (never the same note twice
        running), ORDR (the order pressed). UP / DN / UPDN go by pitch
        (keymap.NOTE_OF_PAD), so UP really rises.
  RATE  8TH, 16TH, 32ND.
  GATE  25-100% of a step. 100 is legato: each note starts before the last
        one's release, so the voice's GLID slides from one to the next.

Timing. Note k is due at anchor + k * step (step = one RATE), each one sent
with its due time, not the frame's, like code.py's TICKs. With the tempo
clock running, code.py hands over every TICK (sync), and the next note is
re-pinned to that tick's grid, so the arp can't drift off the sequencer or
a synced loop. Without it the arp keeps its own time at the menu BPM.

The first note sounds the moment the first pad goes down, but its place on
the grid -- the anchor, S -- is where a finger note pressed then would be
recorded:
  - in the count-in's last step (ARM1): the take's start, the 1
  - tempo clock running: the press snapped to the grid with the looper's
    own rule (looper.snap), on the recording grid or the arp's own if
    finer (so a late 32ND never leaves its next note in the past)
  - otherwise: the press itself (no grid; the looper doesn't quantize
    either)
The first note is sent timed S, so it's recorded exactly there, and every
later note follows S's grid. Live, only the first note differs: it starts
at the press, so it's a little shorter (late) or longer (early) than the
rest. S can be in the future (an early press, or ARM1).

No hardware imports, so it runs on the desktop as is.
"""

import random

import keymap
import looper
from event_types import PAD_DOWN, PAD_UP

MODE_NAMES = ["UP  ", "DN  ", "UPDN", "RAND", "ORDR"]
RATE_NAMES = ["8TH ", "16TH", "32ND"]
GATE_NAMES = ["G 25", "G 50", "G 75", "G100"]

_UP, _DN, _UPDN, _RAND, _ORDR = range(5)
_RATE_STEPS = (2.0, 1.0, 0.5)        # one RATE, in sequencer steps
_GATES      = (0.25, 0.5, 0.75, 1.0)

# The menu's ARP list, in order. Every value is an index into its names.
SCHEMA = [
    {"key": "mode", "label": "MODE", "names": MODE_NAMES},
    {"key": "rate", "label": "RATE", "names": RATE_NAMES},
    {"key": "gate", "label": "GATE", "names": GATE_NAMES},
]

_DEFAULTS = {"mode": _UP, "rate": 1, "gate": 1}   # UP, 16TH, 50%


class Arpeggiator:
    def __init__(self, layer_count, step_dur):
        self._settings = [dict(_DEFAULTS) for _ in range(layer_count)]
        self._on       = 0        # bit n set = layer n's arp is on

        self._step_dur = step_dur   # a sequencer step (1/16), seconds
        self._synced   = False      # the tempo clock is running
        self._tick_at  = 0.0        # ...and its last tick was due here

        self._layer   = 0
        self._held    = []       # pads the fingers hold, in press order
        self._held_mask = 0
        self._last_released = 0  # plays a first note whose pad has already lifted
        self._running = False    # notes still to come
        self._first   = False    # the first note is waiting to go out
        self._anchor  = 0.0      # the next note is due at anchor + n * step
        self._n       = 0
        self._step    = step_dur
        self._pos     = 0        # notes played: the place in the pattern
        self._last_at = None     # when the last note started
        self._sounding = None    # the pad sounding, or None
        self._off_at   = None    # when its release is due (None: held on, legato)
        self._last_pad = None    # the last pad played (RAND won't repeat it)

        self._out = []           # update()'s events, reused

    # ── Settings (the menu's ARP item, KEY MODE) ──────────────────────────────

    def is_on(self, layer):
        return bool(self._on & (1 << layer))

    def set_on(self, layer, on):
        if on:
            self._on |= 1 << layer
        else:
            self._on &= ~(1 << layer)

    def get(self, layer, key):
        return self._settings[layer][key]

    def set(self, layer, key, value):
        self._settings[layer][key] = value
        if key == "rate" and layer == self._layer:
            self._restep()

    # ── For the lights ────────────────────────────────────────────────────────

    @property
    def held_mask(self):
        """The pads the fingers hold (bit n = pad n)."""
        return self._held_mask

    @property
    def note_pad(self):
        """The pad the arp is sounding, or None."""
        return self._sounding

    # ── The tempo clock (code.py) ─────────────────────────────────────────────

    def sync(self, tick_at, step_dur):
        """A TICK of the tempo clock, due at tick_at. Re-pins the next note
        to the grid from this tick (the finest RATE is half a step)."""
        self._synced  = True
        self._tick_at = tick_at
        if step_dur != self._step_dur:
            self.set_step_dur(step_dur)
        if self._running and not self._first:
            half = step_dur / 2
            due  = self._anchor + self._n * self._step
            self._anchor = tick_at + round((due - tick_at) / half) * half
            self._n      = 0

    def unsync(self):
        """The tempo clock stopped: keep time alone from here."""
        self._synced = False

    def set_step_dur(self, step_dur):
        """A BPM change: the next note lands one new step after the last."""
        self._step_dur = step_dur
        self._restep()

    # ── The fingers (code.py) ─────────────────────────────────────────────────

    def press(self, pad, t, layer, count_in_start=None):
        """A pad pressed at t on `layer`. count_in_start: the looper's,
        when the press is in ARM1."""
        if pad in self._held:
            return
        self._held.append(pad)
        self._held_mask |= 1 << pad
        if not self._running:
            self._start(t, layer, count_in_start)

    def release(self, pad, t):
        if pad not in self._held:
            return
        self._held.remove(pad)
        self._held_mask &= ~(1 << pad)
        self._last_released = pad

    def stop(self, now):
        """Stop dead: release the sounding note now and forget the fingers.
        Returns the events to send (the release)."""
        out = self._out
        out.clear()
        if self._sounding is not None:
            out.append((PAD_UP, self._sounding, now))
        self._held.clear()
        self._held_mask = 0
        self._running   = False
        self._first     = False
        self._sounding  = None
        self._off_at    = None
        return out

    # ── Playing ───────────────────────────────────────────────────────────────

    def update(self, now):
        """The events due by `now`, in time order, as (etype, pad, t) -- at
        most one note a frame, like the tempo clock's ticks. The list is
        reused: use it before the next call."""
        out = self._out
        out.clear()

        # Fingers all lifted: no more notes. A legato note gets its release.
        if self._running and not self._held and not self._first:
            self._running = False
            if self._sounding is not None and self._off_at is None:
                self._off_at = self._last_at + self._step

        note_at = None
        if self._first:
            note_at = self._anchor
        elif self._running:
            due = self._anchor + self._n * self._step
            if now >= due:
                note_at = due

        if (self._off_at is not None and now >= self._off_at and
                (note_at is None or self._off_at <= note_at)):
            out.append((PAD_UP, self._sounding, self._off_at))
            self._sounding = None
            self._off_at   = None

        if note_at is not None:
            pad = self._pick()
            self._note_on(pad, note_at)
            self._pos    += 1
            self._last_at = note_at
            if self._first:
                self._first = False
                self._n     = 1
            else:
                self._n += 1
        return out

    # ── Private ───────────────────────────────────────────────────────────────

    def _start(self, t, layer, count_in_start):
        """The first pad down: work out S (see the module docstring)."""
        self._layer = layer
        self._step  = self._step_dur * _RATE_STEPS[self._settings[layer]["rate"]]
        if count_in_start is not None:
            start = count_in_start
        elif self._synced:
            grid  = min(looper.quant_grid(self._step_dur), self._step)
            start = self._tick_at + looper.snap(t - self._tick_at, grid)
        else:
            start = t
        self._running = True
        self._first   = True
        self._anchor  = start
        self._n       = 0
        self._pos     = 0

    def _restep(self):
        """A new step length (RATE or BPM): carry on one new step after the
        last note."""
        self._step = self._step_dur * _RATE_STEPS[self._settings[self._layer]["rate"]]
        if self._running and not self._first and self._last_at is not None:
            self._anchor = self._last_at
            self._n      = 1

    def _gate(self):
        return _GATES[self._settings[self._layer]["gate"]]

    def _pick(self):
        """The next pad in the pattern."""
        pads = self._held or [self._last_released]
        count = len(pads)
        mode  = self._settings[self._layer]["mode"]
        if mode == _ORDR:
            return pads[self._pos % count]
        if mode == _RAND:
            i = random.randrange(count)
            if count > 1 and pads[i] == self._last_pad:
                i = (i + 1 + random.randrange(count - 1)) % count
            return pads[i]
        by_pitch = sorted(pads, key=lambda p: keymap.NOTE_OF_PAD[p])
        if mode == _UP:
            return by_pitch[self._pos % count]
        if mode == _DN:
            return by_pitch[count - 1 - self._pos % count]
        # UPDN: up, then back down without repeating either end.
        if count == 1:
            return by_pitch[0]
        i = self._pos % (2 * count - 2)
        return by_pitch[i if i < count else 2 * count - 2 - i]

    def _note_on(self, pad, t):
        """Start `pad` at t, ending whatever still sounds. Legato: the new
        note first, so the voice slides on -- unless it's the same pad,
        whose release would cut the new note off."""
        out    = self._out
        old    = self._sounding
        legato = self._gate() >= 1.0
        if old is None:
            out.append((PAD_DOWN, pad, t))
        elif legato and old != pad:
            out.append((PAD_DOWN, pad, t))
            out.append((PAD_UP, old, t))
        else:
            out.append((PAD_UP, old, t))
            out.append((PAD_DOWN, pad, t))
        self._sounding = pad
        self._last_pad = pad
        self._off_at   = None if legato else t + self._gate() * self._step
