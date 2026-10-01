"""
Runs the real code.py main loop against scripted button presses.

A scenario is a generator function taking the Harness. It presses and
releases buttons/pads (queued as hw.scan() events, stamped with the current
fake time) and yields how many seconds to let the main loop run before it
continues. Assertions go straight in the scenario; when it returns, the
main loop is stopped.

    def scenario(h):
        yield from h.tap(BTN_MENU)
        assert h.text == "SND "

    Harness().run(scenario)

Time is fake (tests/fakes.py): every main-loop pass is one FRAME of it, so
runs are deterministic and much faster than real time. The instances
code.py builds (synth, looper, seq, menu, disp) are captured for
inspection.
"""

import importlib.util
import os
import sys
import tempfile
import time

import fakes

import config
import display
import groove
import looper
import menu
import sequencer
import startup
import synth_engine
from event_types import BTN_DOWN, BTN_UP, PAD_DOWN, PAD_UP

FRAME = 0.001   # seconds of fake time per main-loop pass


class _StopHarness(BaseException):
    """Ends main()'s `while True`. A BaseException, so code.py's own
    `except Exception` crash handler doesn't catch it."""


class Harness:
    def __init__(self):
        self.synth  = None
        self.looper = None
        self.seq    = None
        self.menu   = None
        self.disp   = None
        self.i2c    = object()
        self._queue    = []
        self._scenario = None
        self._wake_at  = 0.0
        self._error    = None
        self.groove_dir = tempfile.mkdtemp(prefix="grooves-").replace("\\", "/")

    # ── Driving ───────────────────────────────────────────────────────────────

    @property
    def t(self):
        return fakes.CLOCK.t

    def down(self, button):
        self._queue.append((BTN_DOWN, button, self.t))

    def up(self, button):
        self._queue.append((BTN_UP, button, self.t))

    def pad_down(self, pad):
        self._queue.append((PAD_DOWN, pad, self.t))

    def pad_up(self, pad):
        self._queue.append((PAD_UP, pad, self.t))

    def tap(self, button, hold=0.03, after=0.03):
        self.down(button)
        yield hold
        self.up(button)
        yield after

    def taps(self, button, count):
        for _ in range(count):
            yield from self.tap(button)

    def hold(self, button, seconds):
        self.down(button)
        yield seconds
        self.up(button)
        yield 0.03

    def pad_tap(self, pad, hold=0.03, after=0.03):
        self.pad_down(pad)
        yield hold
        self.pad_up(pad)
        yield after

    # ── What code.py's instances show ─────────────────────────────────────────

    @property
    def text(self):
        """What the 4-char display shows right now."""
        return self.disp._seg.text

    @property
    def bpm(self):
        return round(60.0 / (self.seq.step_dur * 4))

    def led(self, index):
        return bool(self.disp._led_state & (1 << index))

    # ── Running ───────────────────────────────────────────────────────────────

    def scan(self):
        """hw.scan(): resume the scenario when its wait is up, hand back what
        it queued, then advance fake time by one frame."""
        if self.t >= self._wake_at:
            try:
                self._wake_at = self.t + next(self._scenario)
            except StopIteration:
                raise _StopHarness()
            except BaseException as e:   # an assertion, most likely
                self._error = e
                raise _StopHarness()
        events, self._queue = self._queue, []
        fakes.CLOCK.t += FRAME
        return events

    def run(self, scenario):
        self._scenario = scenario(self)
        fakes.CLOCK.t  = 0.0
        harness = self

        class FakeHardware:
            def __init__(self):
                self.i2c = harness.i2c

            def scan(self):
                return harness.scan()

        def recording(cls, attr):
            class Recorded(cls):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    setattr(harness, attr, self)
            return Recorded

        def crashed(_seconds):
            # code.py's crash handler prints the traceback then sleeps
            # forever; surface the exception it caught instead.
            harness._error = sys.exc_info()[1]
            raise _StopHarness()

        patches = [
            (synth_engine, "SynthEngine", recording(synth_engine.SynthEngine, "synth")),
            (looper, "LooperMode", recording(looper.LooperMode, "looper")),
            (sequencer, "SequencerMode", recording(sequencer.SequencerMode, "seq")),
            (menu, "MenuMode", recording(menu.MenuMode, "menu")),
            (display, "DisplayManager", recording(display.DisplayManager, "disp")),
            (startup, "run", lambda hw, disp: None),
            (groove, "_DIR", self.groove_dir),
            (time, "sleep", crashed),
        ]
        import hw
        patches.append((hw, "Hardware", FakeHardware))

        saved = [(mod, name, getattr(mod, name)) for mod, name, _ in patches]
        for mod, name, value in patches:
            setattr(mod, name, value)
        try:
            path = os.path.join(fakes.ROOT, "code.py")
            spec = importlib.util.spec_from_file_location("groovebox_code", path)
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
            except _StopHarness:
                pass
        finally:
            for mod, name, value in saved:
                setattr(mod, name, value)
        if self._error is not None:
            raise self._error


def run(scenario):
    """Run a scenario; returns the Harness for any after-the-fact checks."""
    h = Harness()
    h.run(scenario)
    return h


__all__ = ["Harness", "run", "config", "FRAME"]
