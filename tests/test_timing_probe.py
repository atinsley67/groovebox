"""timing_probe: its stats, and the main loop running with it switched on."""

import contextlib
import io
import unittest

import fakes  # noqa: F401  (installs the CircuitPython fakes first)

import config
import harness
import palette
import timing_probe
from config import BTN_MENU, BTN_KEY_MODE
from timing_probe import TimingProbe, census

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


class AllocByPartTest(unittest.TestCase):
    """The ALLOC line: one pass in _ALLOC_SAMPLE_EVERY measured part by
    part, against a fake count of memory in use."""

    def setUp(self):
        self.ns    = FakeNs()
        self.mem   = [1000]
        self.probe = TimingProbe(FakeHw(self.ns, MS), ns=self.ns, report_every=100.0,
                                 mem_free=lambda: 0, mem_alloc=lambda: self.mem[0])

        class Part:
            grows = 40

            def update(part, now):
                self.mem[0] += part.grows
                return now * 2

        self.part = Part()
        self.probe.track("part", self.part, "update", 1)

    def run_passes(self, count):
        for _ in range(count):
            self.probe.scan()
            self.assertEqual(self.part.update(1.5), 3.0)   # passed through
            self.mem[0] += 10                              # the rest of the pass
            self.ns.t += MS

    def test_parts_and_the_rest(self):
        self.run_passes(2 * timing_probe._ALLOC_SAMPLE_EVERY)
        self.probe.scan()                                  # ends the second sample
        self.assertEqual(self.probe.alloc_line(),
                         "ALLOC per pass, 2 samples (0 lost to a gc):"
                         " total 50B | scan 0 | part 40 | rest 10")

    def test_a_collection_loses_the_sample(self):
        self.part.grows = -500                             # memory went down: a gc
        self.run_passes(timing_probe._ALLOC_SAMPLE_EVERY)
        self.probe.scan()
        self.assertEqual(self.probe.alloc_line(),
                         "ALLOC per pass, no samples (1 lost to a gc)")

    def test_sampled_passes_stay_out_of_the_timing(self):
        scans = timing_probe._ALLOC_SAMPLE_EVERY + 5
        self.run_passes(scans)
        line = self.probe.report_line()
        # scans - 1 passes end between them; the sampled one isn't counted
        self.assertIn(f"passes {scans - 2} ", line)


class CensusTest(unittest.TestCase):
    def test_times_the_second_of_two_collections(self):
        ns, lines = FakeNs(), []
        calls = []

        def collect():
            calls.append(ns.t)
            ns.t += (30 if len(calls) == 1 else 12) * MS   # garbage, then live data only

        census("voices", ns=ns, collect=collect, mem_alloc=lambda: 145 * 1024,
               mem_free=lambda: 251 * 1024, out=lines.append)
        self.assertEqual(len(calls), 2)
        self.assertEqual(lines, ["HEAP voices         used 145k free 251k gc 12.00ms"])

    def test_without_memory_readings(self):
        lines = []
        census("boot", ns=FakeNs(), collect=lambda: None, mem_alloc=None,
               mem_free=None, out=lines.append)
        self.assertEqual(lines, ["HEAP boot           gc 0.00ms"])


class MainLoopWithProbeTest(unittest.TestCase):
    def test_main_loop_runs_with_probe_on(self):
        saved = config.TIMING_PROBE
        config.TIMING_PROBE = True
        out = io.StringIO()
        try:
            def scenario(h):
                yield from h.tap(BTN_MENU)
                assert h.text == "SND "
                h.pad_down(2)
                yield 0.05
                assert h.pad_color(2) == palette.LIVE   # drawn through the timer
                h.pad_up(2)
                yield 0.05
            with contextlib.redirect_stdout(out):
                harness.run(scenario)
        finally:
            config.TIMING_PROBE = saved
        stages = [line.split()[1] for line in out.getvalue().splitlines()
                  if line.startswith("HEAP")]
        self.assertEqual(stages, ["boot", "sound", "imports", "hardware", "voices", "ready"])

    def test_the_arp_plays_through_the_probe(self):
        """play_arp passes looper.handle_event exact=True by keyword: the
        probe's wrapper has to take it (it crashed the device once)."""
        saved = config.TIMING_PROBE
        config.TIMING_PROBE = True
        try:
            def scenario(h):
                yield from h.tap(BTN_KEY_MODE)          # the layer's arp on
                h.pad_down(12)
                h.pad_down(13)
                yield 0.6                               # several arp notes, each
                h.pad_up(12)                            # through play_arp
                h.pad_up(13)
                yield 0.05
            with contextlib.redirect_stdout(io.StringIO()):
                harness.run(scenario)
        finally:
            config.TIMING_PROBE = saved


if __name__ == "__main__":
    unittest.main()
