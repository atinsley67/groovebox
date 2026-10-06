"""
AUTO, the mute arranger: varies the groove by muting and unmuting channels
on its own, on phrase boundaries -- mostly small changes, now and then a
breakdown and a drop. The menu's AUT item switches it on and off; code.py
feeds it the phrase clock (on_unit) and flashes the word it returns.

Channels are the channel view's: loop layers 0-7, then sequencer tracks as
8-15, all treated alike. Every channel with content takes part (a committed
loop layer, a track with steps -- never a layer being recorded or
overdubbed), whatever its mute when AUTO started. Mutes are read afresh at
each boundary, so a change by hand is simply where it carries on from.
Switching AUTO off leaves the mutes as they are.

At each phrase boundary:
  - Small moves: one channel changes (two, now and then, on a block line).
    Each change is an unmute with probability 3m / (3m + p) -- m muted, p
    playing -- otherwise a mute, of a channel picked at random. Muted
    channels being three times as likely to change pulls the mix back
    toward three quarters playing, however far it wanders (a weighted
    Ehrenfest urn: the share playing settles around 3 / (3 + 1)).
  - Never fewer than a third of the channels playing (at least one).
  - A breakdown, now and then on a block line: down to that floor at
    once. One or two blocks later, the drop: every channel back at once.
    The small moves carry on in between -- mostly unmuting, so they build.
Each change returns a word to flash, from the lists below.

Phrases: changes only ever land on a phrase boundary. Phrases come in
blocks that each start on a block line, so the bigger changes land on the
big downbeats:
  with the tempo clock (bars): 8-bar blocks, played as 8 (mostly), 4 + 4
    (often) or 2 + 2 + 4 (now and then)
  a freeform loop (passes): 2-pass blocks, as 2 or 1 + 1
Switched on (or the count restarted: a resume, or bars <-> passes), it
waits for the next block line before the first phrase counts.
"""

import random

from config import NUM_LOOP_LAYERS, NUM_TRACKS

_UNMUTE_WEIGHT   = 3       # a muted channel's odds of changing vs. a playing one's
_TWO_CHANGES     = 1 / 3   # chance a block line changes two channels, not one
# Chance a block line starts a breakdown, and blocks from it to its drop.
# With 8 channels: a breakdown every ~75 bars, about 14% of the time at 3 or
# fewer playing, and the full mix about 14% of the time.
_BREAKDOWN       = 1 / 8
_DROP_AFTER      = (1, 2)

# (block length, plans as ((phrase lengths), weight)) per kind of unit.
_BLOCKS = {
    "bar":  (8, (((8,), 55), ((4, 4), 35), ((2, 2, 4), 10))),
    "pass": (2, (((2,), 60), ((1, 1), 40))),
}

# Something's changing -- what, exactly, is anyone's guess.
_WORDS = ("WUBZ", "FLUX", "VYBE", "ZOOP", "WOMP", "BLIP", "SWSH", "FWIP",
          "SKRT", "DUBZ", "GLYD", "TWEK", "NUDG", "SLYD", "PHAZ", "WARP",
          "DRFT", "SPYN", "SCRT", "MIXX")
_BREAKDOWN_WORDS = ("DEEP", "SINK", "HUSH", "VOID", "MELT", "DRIP")
_DROP_WORDS      = ("BOOM", "SLAM", "BLAM", "KAPW", "BANG", "WHAM")


class Arranger:
    def __init__(self, looper, seq, rng=random):
        # Channel n -> (mode, its index there): layers, then tracks.
        self._channels = ([(looper, n) for n in range(NUM_LOOP_LAYERS)] +
                          [(seq, n) for n in range(NUM_TRACKS)])
        self._rng      = rng
        self.running   = False
        self._drop_in  = 0     # block lines until a breakdown's drop (0: none due)
        self._kind     = None  # "bar" / "pass": what on_unit counts
        self._next     = None  # unit of the next phrase boundary (None: line up)
        self._last     = None  # the last unit seen
        self._plan     = []    # the rest of this block's phrase lengths
        self._lining_up = True

    def start(self):
        self.running  = True
        self._drop_in = 0
        self._realign(None)

    def stop(self):
        self.running = False   # the mutes stay as they are

    # ── The phrase clock ──────────────────────────────────────────────────────

    def on_unit(self, n, kind):
        """Unit n (a bar or a loop pass, counted from 0 since the transport
        started) has just begun. Returns a word to flash when something
        changes, else None."""
        if not self.running:
            return None
        if kind != self._kind or (self._last is not None and n < self._last):
            self._realign(kind)   # restarted, or switched bars <-> passes
        self._last = n
        block, plans = _BLOCKS[kind]
        if self._next is None:
            self._next = -(-n // block) * block   # the next block line (n, if on one)
        if n < self._next:
            return None
        block_line = not self._plan
        if block_line:
            self._plan = list(self._pick(plans))
        self._next = n + self._plan.pop(0)
        if self._lining_up:
            self._lining_up = False
            return None
        return self._change(block_line)

    def _realign(self, kind):
        self._kind      = kind
        self._next      = None
        self._last      = None
        self._plan      = []
        self._lining_up = True

    # ── The changes ───────────────────────────────────────────────────────────

    def _change(self, block_line):
        """A phrase boundary: change some mutes. Returns the word to flash."""
        rng      = self._rng
        channels = [ch for ch in range(len(self._channels)) if self._can_arrange(ch)]
        if len(channels) < 2:
            return None   # nothing to vary
        muted   = [ch for ch in channels if self._is_muted(ch)]
        playing = [ch for ch in channels if not self._is_muted(ch)]
        floor   = max(1, len(channels) // 3)

        if block_line and self._drop_in:
            self._drop_in -= 1
            if not self._drop_in:
                for ch in muted:
                    self._set(ch, False)
                return rng.choice(_DROP_WORDS)
        elif block_line and len(playing) > floor and rng.random() < _BREAKDOWN:
            while len(playing) > floor:
                ch = rng.choice(playing)
                playing.remove(ch)
                self._set(ch, True)
            self._drop_in = rng.randint(*_DROP_AFTER)
            return rng.choice(_BREAKDOWN_WORDS)

        changes = 2 if block_line and rng.random() < _TWO_CHANGES else 1
        for _ in range(changes):
            weight = _UNMUTE_WEIGHT * len(muted)
            if muted and (len(playing) <= floor or
                          rng.random() * (weight + len(playing)) < weight):
                ch = rng.choice(muted)
                muted.remove(ch)
                playing.append(ch)
                self._set(ch, False)
            else:
                ch = rng.choice(playing)
                playing.remove(ch)
                muted.append(ch)
                self._set(ch, True)
        return rng.choice(_WORDS)

    def _can_arrange(self, channel):
        mode, n = self._channels[channel]
        return mode.can_arrange(n)

    def _is_muted(self, channel):
        mode, n = self._channels[channel]
        return mode.is_muted(n)

    def _set(self, channel, muted):
        mode, n = self._channels[channel]
        mode.set_muted(n, muted)

    def _pick(self, options):
        """A weighted random choice from ((value, weight), ...)."""
        r = self._rng.random() * sum(weight for _, weight in options)
        for value, weight in options:
            r -= weight
            if r < 0:
                return value
        return options[-1][0]
