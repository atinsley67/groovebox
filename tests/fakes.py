"""
Desktop stand-ins for the CircuitPython modules the groovebox imports
(board, busio, digitalio, audiobusio, synthio, adafruit_aw9523,
adafruit_ht16k33), so the real project modules run under CPython.

Importing this module installs them into sys.modules, puts the project root
on sys.path, and replaces clock.now() with a settable fake clock -- so it
must be imported before any project module.

The fakes only record what the code does to them (pressed notes, printed
text, LED currents); none of them make sound or touch hardware.
"""

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _module(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


# ── board / busio / digitalio ─────────────────────────────────────────────────

_module("board", **{f"GP{i}": f"GP{i}" for i in range(30)})


class _I2C:
    def __init__(self, scl, sda, frequency=100000, timeout=255):
        self.frequency = frequency

    def deinit(self):
        pass


_module("busio", I2C=_I2C)


class _Direction:
    INPUT  = "in"
    OUTPUT = "out"


class _Pull:
    UP   = "up"
    DOWN = "down"


class _DigitalInOut:
    def __init__(self, pin):
        self.pin       = pin
        self.direction = None
        self.pull      = None
        self.value     = True   # pull-up, not pressed

    def deinit(self):
        pass


_module("digitalio", DigitalInOut=_DigitalInOut, Direction=_Direction, Pull=_Pull)


# ── audiobusio ────────────────────────────────────────────────────────────────

class _I2SOut:
    def __init__(self, bit_clock, word_select, data):
        self.playing = None

    def play(self, sample, loop=False):
        self.playing = sample

    def deinit(self):
        pass


_module("audiobusio", I2SOut=_I2SOut)


# ── synthio ───────────────────────────────────────────────────────────────────

class FilterMode:
    LOW_PASS  = "lp"
    HIGH_PASS = "hp"
    BAND_PASS = "bp"
    NOTCH     = "notch"


class Envelope:
    def __init__(self, attack_time=0.1, decay_time=0.05, release_time=0.2,
                 attack_level=1.0, sustain_level=0.8):
        self.attack_time   = attack_time
        self.decay_time    = decay_time
        self.release_time  = release_time
        self.attack_level  = attack_level
        self.sustain_level = sustain_level


class Biquad:
    def __init__(self, mode, frequency, Q=0.7071067811865475):
        self.mode      = mode
        self.frequency = frequency
        self.Q         = Q


class LFO:
    def __init__(self, waveform=None, rate=1.0, scale=1.0, offset=0.0,
                 phase_offset=0.0, once=False, interpolate=True):
        self.waveform   = waveform
        self.rate       = rate
        self.scale      = scale
        self.offset     = offset
        self.once       = once
        self.retriggers = 0

    def retrigger(self):
        self.retriggers += 1


class Note:
    def __init__(self, frequency, panning=0.0, waveform=None, envelope=None,
                 amplitude=1.0, bend=0.0, filter=None, ring_frequency=0.0,
                 ring_bend=0.0, ring_waveform=None):
        self.frequency      = frequency
        self.panning        = panning
        self.waveform       = waveform
        self.envelope       = envelope
        self.amplitude      = amplitude
        self.bend           = bend
        self.filter         = filter
        self.ring_frequency = ring_frequency
        self.ring_bend      = ring_bend
        self.ring_waveform  = ring_waveform


def _as_list(notes):
    return list(notes) if isinstance(notes, (list, tuple)) else [notes]


class Synthesizer:
    """Records every press; `pressed` holds the notes currently down."""

    def __init__(self, sample_rate=11025, channel_count=1, waveform=None, envelope=None):
        self.pressed   = []
        self.press_log = []   # every note ever pressed, in order

    def press(self, notes):
        for note in _as_list(notes):
            self.press_log.append(note)
            if not any(n is note for n in self.pressed):
                self.pressed.append(note)

    def release(self, notes):
        for note in _as_list(notes):
            self.pressed = [n for n in self.pressed if n is not note]

    def deinit(self):
        pass


_module("synthio", FilterMode=FilterMode, Envelope=Envelope, Biquad=Biquad,
        LFO=LFO, Note=Note, Synthesizer=Synthesizer)


# ── Adafruit display / LED driver libraries ───────────────────────────────────

class _AW9523:
    def __init__(self, i2c, address=0x58):
        self.LED_modes  = 0
        self.directions = 0
        self.currents   = {}

    def set_constant_current(self, pin, value):
        self.currents[pin] = value


_module("adafruit_aw9523", AW9523=_AW9523)


class Seg14x4:
    """`text` is what the 4-char display currently shows; `history` every
    string printed to it; `writes` how many times it was sent over I2C
    (like the real library, print() also sends when auto_write is on)."""

    def __init__(self, i2c, address=0x70, auto_write=True):
        self.brightness = 1.0
        self.auto_write = auto_write
        self.text       = ""
        self.history    = []
        self.writes     = 0

    def print(self, text):
        self.text = text
        self.history.append(text)
        if self.auto_write:
            self.show()

    def show(self):
        self.writes += 1


_segments = _module("adafruit_ht16k33.segments", Seg14x4=Seg14x4)
_module("adafruit_ht16k33", segments=_segments)


# ── supervisor / keypad / neopixel (the NeoKey hardware) ──────────────────────

_TICKS_MASK = (1 << 29) - 1
TICKS_OFFSET = [0]   # shift supervisor.ticks_ms() (e.g. to just before its wrap)


def ticks_ms():
    """supervisor.ticks_ms(), following the fake clock; wraps at 2**29."""
    return (int(round(CLOCK.t * 1000)) + TICKS_OFFSET[0]) & _TICKS_MASK


_module("supervisor", ticks_ms=ticks_ms)


class Event:
    def __init__(self, key_number=0, pressed=True, timestamp=None):
        self.key_number = key_number
        self.pressed    = pressed
        self.timestamp  = ticks_ms() if timestamp is None else timestamp

    @property
    def released(self):
        return not self.pressed


class _EventQueue:
    def __init__(self):
        self._queue     = []
        self.overflowed = False

    def push(self, event):
        """Test hook: queue an event, as the background scanner would."""
        self._queue.append(event)

    def get_into(self, event):
        if not self._queue:
            return False
        queued = self._queue.pop(0)
        event.key_number = queued.key_number
        event.pressed    = queued.pressed
        event.timestamp  = queued.timestamp
        return True

    def clear(self):
        self._queue     = []
        self.overflowed = False

    def __len__(self):
        return len(self._queue)


class KeyMatrix:
    def __init__(self, row_pins, column_pins, columns_to_anodes=True,
                 interval=0.020, max_events=64, debounce_threshold=1):
        self.row_pins           = list(row_pins)
        self.column_pins        = list(column_pins)
        self.columns_to_anodes  = columns_to_anodes
        self.interval           = interval
        self.debounce_threshold = debounce_threshold
        self.key_count          = len(self.row_pins) * len(self.column_pins)
        self.events             = _EventQueue()

    def deinit(self):
        pass


_module("keypad", Event=Event, KeyMatrix=KeyMatrix)


class NeoPixel:
    """`shown` is what the strip displays (as of the last show()); `shows`
    counts sends."""

    def __init__(self, pin, n, *, bpp=3, brightness=1.0, auto_write=True,
                 pixel_order=None):
        self.pin        = pin
        self.n          = n
        self.brightness = brightness
        self.auto_write = auto_write
        self._buffer    = [(0, 0, 0)] * n
        self.shown      = [(0, 0, 0)] * n
        self.shows      = 0

    def __setitem__(self, index, color):
        self._buffer[index] = tuple(color)
        if self.auto_write:
            self.show()

    def __getitem__(self, index):
        return self._buffer[index]

    def __len__(self):
        return self.n

    def fill(self, color):
        self._buffer = [tuple(color)] * self.n
        if self.auto_write:
            self.show()

    def show(self):
        self.shown = list(self._buffer)
        self.shows += 1

    def deinit(self):
        pass


_module("neopixel", NeoPixel=NeoPixel)


# ── Fake clock ────────────────────────────────────────────────────────────────

import clock   # noqa: E402  (project module; needs the path set up above)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t


CLOCK = FakeClock()
clock.now = CLOCK.now
