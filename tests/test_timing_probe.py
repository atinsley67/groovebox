"""timing_probe: its stats, and the main loop running with it switched on."""

import contextlib
import io
import unittest

import fakes  # noqa: F401  (installs the CircuitPython fakes first)

import config
import harness
import palette
from config import BTN_MENU
from timing_probe import TimingProbe

MS = 1000000


class FakeNs:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t


class FakeHw:
    """hw.scan() that takes `scan_ns` of the fake clock."""

    def __init__(self, clock, scan_ns):
        self.i2c     = object()
        self._clock  = clock
        self.scan_ns = scan_ns

    def scan(self):
        self._clock.t += self.scan_ns
        return ["event"]


class TimingProbeTest(unittest.TestCase):
    def test_stats(self):
        ns    = FakeNs()
        probe = TimingProbe(FakeHw(ns, 1 * MS), ns=ns, report_every=1.0)
        # Passes (scan start to scan start) of 2, 2, 6 and 12 ms.
        for rest in (1, 1, 5, 11):
            self.assertEqual(probe.scan(), ["event"])
            ns.t += rest * MS
        probe.scan()
        line = probe.report_line()
        self.assertIn("passes 4 ", line)
        self.assertIn("avg 5.50ms worst 12.00ms", line)
        self.assertIn(">5ms 2 >10ms 1", line)
        self.assertIn("scan avg 1.00ms worst 1.00ms", line)
        self.assertIn("session worst 12.00ms", line)

    def test_reports_and_skips_its_own_print(self):
        ns    = FakeNs()
        probe = TimingProbe(FakeHw(ns, 0), ns=ns, report_every=1.0)
        out   = io.StringIO()
        with contextlib.redirect_stdout(out):
            for _ in range(11):        # 10 ms passes: 1.1 s, one report
                probe.scan()
                ns.t += 100 * MS
            self.assertEqual(out.getvalue().count("TIMING"), 1)
            ns.t += 50 * MS            # the reporting pass: slow, not counted
            probe.scan()
            ns.t += 100 * MS
            probe.scan()
        self.assertIn("passes 1 ", probe.report_line())
        self.assertIn("worst 100.00ms", probe.report_line())

    def test_report_times_a_collection(self):
        ns = FakeNs()

        def collect():
            ns.t += 7 * MS

        probe = TimingProbe(FakeHw(ns, 0), ns=ns, report_every=1.0,
                            collect=collect, mem_free=lambda: 182 * 1024)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            probe.scan()
            ns.t += 1000 * MS
            probe.scan()               # reports, collecting first
            ns.t += 10 * MS
            probe.scan()
        self.assertIn("| gc 7.00ms free 182k", out.getvalue())
        # The 7 ms collection was in the reporting pass, which isn't counted.
        self.assertIn("passes 0 ", probe.report_line())


class AllocAndLedTimingTest(unittest.TestCase):
    def test_alloc_per_pass_predicts_collections(self):
        ns   = FakeNs()
        free = [300 * 1024]
        probe = TimingProbe(FakeHw(ns, 0), ns=ns, report_every=1.0,
                            collect=lambda: None, mem_free=lambda: free[0])
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2000):                  # 1 ms passes, 500 B each
                probe.scan()
                ns.t += 1 * MS
                free[0] -= 500
                if ns.t == 1000 * MS:
                    free[0] = 300 * 1024           # the report's collection
        line = probe.report_line()
        self.assertIn("alloc 500B/pass", line)
        # ~1000 passes x 500 B over 300 KB free: about 2 collections.
        self.assertIn("~2gc", line)

    def test_slow_passes_split_into_gc_and_other(self):
        ns   = FakeNs()
        free = [200 * 1024]
        probe = TimingProbe(FakeHw(ns, 0), ns=ns, report_every=10.0,
                            collect=lambda: None, mem_free=lambda: free[0])
        for i in range(300):
            probe.scan()
            free[0] -= 100
            if i % 100 == 10:
                ns.t += 6 * MS              # a stall with no collection
            elif i % 100 == 60:
                ns.t += 6 * MS              # a collection
                free[0] = 200 * 1024
            ns.t += 1 * MS
        probe.scan()
        # 3 stalls and 3 collections, and only the collections free memory.
        self.assertIn(">5ms 6 (gc 3)", probe.report_line())

    def test_alloc_unknown_after_a_collection(self):
        ns   = FakeNs()
        free = [300 * 1024]
        probe = TimingProbe(FakeHw(ns, 0), ns=ns, report_every=1.0,
                            collect=lambda: None, mem_free=lambda: free[0])
        with contextlib.redirect_stdout(io.StringIO()):
            for i in range(1100):
                probe.scan()
                ns.t += 1 * MS
                free[0] += 10                      # memory going *up*: collected
        self.assertIn("alloc ?", probe.report_line())

    def test_led_work_timed(self):
        ns = FakeNs()

        class Strip:
            dirty = False

        class Pixels:
            _pads, _func = Strip(), Strip()

        class Disp:
            pixels = Pixels()

            def update(self, now=None):
                ns.t += 3 * MS
                self.pixels._pads.dirty = False

        drawn = []

        def draw(now):
            ns.t += 2 * MS
            drawn.append(now)

        disp  = Disp()
        probe = TimingProbe(FakeHw(ns, 0), disp, ns=ns, mem_free=None)
        timed = probe.timed_draw(draw)
        timed(1.5)
        timed(1.6)
        self.assertEqual(drawn, [1.5, 1.6])
        disp.update()               # nothing to send: not timed
        disp.pixels._pads.dirty = True
        disp.update()
        line = probe.report_line()
        self.assertIn("leds draw 2x 2.00ms", line)
        self.assertIn("send 1x 3.00ms", line)


class MainLoopWithProbeTest(unittest.TestCase):
    def test_main_loop_runs_with_probe_on(self):
        saved = config.TIMING_PROBE
        config.TIMING_PROBE = True
        try:
            def scenario(h):
                yield from h.tap(BTN_MENU)
                assert h.text == "SND "
                h.pad_down(2)
                yield 0.05
                assert h.pad_color(2) == palette.LIVE   # drawn through the timer
                h.pad_up(2)
                yield 0.05
            harness.run(scenario)
        finally:
            config.TIMING_PROBE = saved


if __name__ == "__main__":
    unittest.main()
