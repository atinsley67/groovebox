"""
Main-loop timing probe (config.TIMING_PROBE) -- a baseline to compare the
button hardware against before and after a change.

Wraps the Hardware object so code.py needs only one line: every hw.scan()
call marks the start of a main-loop pass. Given the DisplayManager too, it
also times the LED work. Every REPORT_EVERY seconds it prints one line to
the serial console:

  TIMING passes 4210 avg 1.19ms worst 8.42ms >5ms 3 >10ms 0 | scan avg 0.21ms worst 0.40ms | session worst 12.80ms | gc 6.90ms free 182k | alloc 410B/pass ~9gc | leds map 212x 0.09ms worst 0.31ms send 180x 0.52ms worst 0.95ms

  passes        main-loop passes in the window
  avg / worst   time per pass (one scan to the next, everything included)
  >5ms / >10ms  passes that took longer than that. "(gc 9)": how many of
                the >5ms passes had a garbage collection in them -- the
                probe reads free memory after every slow pass, and more
                free than at its last reading means a collection ran
  scan          time spent inside hw.scan() itself
  session worst the slowest pass since boot
  gc            how long one garbage collection takes: the probe runs one
                itself, timed, when it reports. Python collects on its own
                whenever memory runs low, pausing whatever pass it lands in,
                so if this matches the worst idle passes, those are GC.
  free          free memory right after that collection
  alloc         memory the main loop allocates per pass (probe included),
                measured over _ALLOC_SAMPLE_PASSES passes at the start of the
                window; "~9gc" is how many collections that rate predicts in
                the window (alloc x passes / free). If it matches >5ms, the
                slow passes are GC. "?" if a collection got in the way.
  leds map      LED changes turned into LED output (DisplayManager's
                _flush_leds, only calls where something changed): count,
                average, worst
  leds send     NeoPixel strip sends (DisplayManager.update calls that sent)

Uses integer time.monotonic_ns(), not clock.now(): float seconds lose
sub-millisecond resolution after an hour or so of uptime. The pass that
reports (print and collection included) and the one that samples memory
are left out of the stats, so the probe doesn't measure itself.
"""

import gc
import time

REPORT_EVERY = 5.0   # seconds between report lines

_NS_PER_MS = 1000000
_ALLOC_SAMPLE_PASSES = 100   # passes between the two memory readings


class TimingProbe:
    def __init__(self, hw, disp=None, ns=time.monotonic_ns, report_every=REPORT_EVERY,
                 collect=gc.collect, mem_free=getattr(gc, "mem_free", None)):
        self._hw       = hw
        self._ns       = ns
        self._collect  = collect
        self._mem_free = mem_free   # CircuitPython only; None leaves "free"/"alloc" out
        self._every_ns = int(report_every * 1000000000)
        self.i2c       = hw.i2c
        self._last_start    = None
        self._report_at     = ns() + self._every_ns
        self._skip_pass     = False
        self._session_worst = 0
        self._free_after_gc = None   # mem_free() after the last report's collection
        self._free_ref      = None   # last mem_free() reading, to spot collections
        self._alloc_free0   = None   # ...pending the second reading of an alloc sample
        self._alloc_per_pass = None  # bytes, from this window's sample (None = no sample)
        self._has_leds  = disp is not None
        self._has_sends = False
        self._reset_window()
        if disp is not None:
            self._wrap_leds(disp)

    def _reset_window(self):
        self._passes     = 0
        self._pass_total = 0
        self._pass_worst = 0
        self._over_5ms   = 0
        self._slow_gc    = 0   # >5ms passes that had a collection in them
        self._over_10ms  = 0
        self._scans      = 0
        self._scan_total = 0
        self._scan_worst = 0
        self._map  = [0, 0, 0]   # [count, total ns, worst ns]
        self._send = [0, 0, 0]

    # ── LED timing ────────────────────────────────────────────────────────────

    def _wrap_leds(self, disp):
        """Time the display's LED work by replacing two of its methods with
        timed versions. Calls with nothing to do aren't timed, so the probe
        adds no clock reads to an idle pass."""
        ns    = self._ns
        flush = disp._flush_leds

        def timed_flush():
            if disp._led_state == disp._led_shown:
                return flush()
            start = ns()
            flush()
            _record(self._map, ns() - start)

        disp._flush_leds = timed_flush

        pixels = disp.pixels
        if pixels is None:
            return
        self._has_sends = True
        update = disp.update
        pads, func = pixels._pads, pixels._func

        def timed_update(now=None):
            if not (pads.dirty or func.dirty):
                return update(now)
            start = ns()
            update(now)
            if not (pads.dirty or func.dirty):   # it sent (not held back by the rate cap)
                _record(self._send, ns() - start)

        disp.update = timed_update

    # ── Per pass ──────────────────────────────────────────────────────────────

    def scan(self):
        start = self._ns()
        skip  = False
        if self._last_start is not None and not self._skip_pass:
            took = start - self._last_start
            self._record_pass(took)
            if took > 5 * _NS_PER_MS and self._mem_free is not None:
                self._check_for_collection()
                skip = True   # this pass includes the heap walk
        self._skip_pass  = skip
        self._last_start = start

        events = self._hw.scan()

        took = self._ns() - start
        self._scans      += 1
        self._scan_total += took
        if took > self._scan_worst:
            self._scan_worst = took

        if start >= self._report_at:
            self._report()
            self._report_at = start + self._every_ns
            self._skip_pass = True   # this pass includes the print
        elif self._alloc_free0 is not None and self._scans >= _ALLOC_SAMPLE_PASSES:
            self._sample_alloc()
            self._skip_pass = True   # mem_free() walks the heap: not a normal pass
        return events

    def deinit(self):
        self._hw.deinit()

    def _record_pass(self, took):
        self._passes     += 1
        self._pass_total += took
        if took > self._pass_worst:
            self._pass_worst = took
        if took > self._session_worst:
            self._session_worst = took
        if took > 5 * _NS_PER_MS:
            self._over_5ms += 1
        if took > 10 * _NS_PER_MS:
            self._over_10ms += 1

    def _check_for_collection(self):
        """After a >5ms pass: more free memory than at the last reading
        means a collection ran since -- and every slow pass gets a reading,
        while a collection always makes its pass slow, so it ran in this
        one."""
        free = self._mem_free()
        if self._free_ref is not None and free > self._free_ref:
            self._slow_gc += 1
        self._free_ref = free

    def _sample_alloc(self):
        """Second memory reading, _ALLOC_SAMPLE_PASSES passes after the
        report's collection. More free memory than at the first reading
        means a collection happened in between: no sample."""
        free = self._mem_free()
        if free <= self._alloc_free0:
            self._alloc_per_pass = (self._alloc_free0 - free) / self._scans
        self._alloc_free0 = None
        self._free_ref    = free

    # ── Reporting ─────────────────────────────────────────────────────────────

    def report_line(self, gc_suffix=""):
        passes = max(1, self._passes)
        scans  = max(1, self._scans)
        gc_count = f" (gc {self._slow_gc})" if self._mem_free is not None else ""
        line = (f"TIMING passes {self._passes}"
                f" avg {_ms(self._pass_total / passes)} worst {_ms(self._pass_worst)}"
                f" >5ms {self._over_5ms}{gc_count} >10ms {self._over_10ms}"
                f" | scan avg {_ms(self._scan_total / scans)} worst {_ms(self._scan_worst)}"
                f" | session worst {_ms(self._session_worst)}{gc_suffix}")
        if self._free_after_gc is not None:
            if self._alloc_per_pass is None:
                line += " | alloc ?"
            else:
                gcs = self._alloc_per_pass * self._passes / max(1, self._free_after_gc)
                line += f" | alloc {int(self._alloc_per_pass)}B/pass ~{gcs:.0f}gc"
        if self._has_leds:
            line += " | leds map " + _stat(self._map)
            if self._has_sends:
                line += " send " + _stat(self._send)
        return line

    def _report(self):
        start = self._ns()
        self._collect()
        suffix = f" | gc {_ms(self._ns() - start)}"
        if self._mem_free is not None:
            free = self._mem_free()
            suffix += f" free {free // 1024}k"
        print(self.report_line(suffix))
        if self._mem_free is not None:
            # Start the next window's allocation sample from this fresh heap.
            self._free_after_gc  = free
            self._alloc_free0    = free
            self._free_ref       = free
            self._alloc_per_pass = None
        self._reset_window()


def _record(stat, took):
    stat[0] += 1
    stat[1] += took
    if took > stat[2]:
        stat[2] = took


def _stat(stat):
    count, total, worst = stat
    return f"{count}x {_ms(total / max(1, count))} worst {_ms(worst)}"


def _ms(ns):
    return f"{ns / _NS_PER_MS:.2f}ms"
