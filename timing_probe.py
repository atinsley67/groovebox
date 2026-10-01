"""
Main-loop timing probe (config.TIMING_PROBE) -- a baseline to compare the
button hardware against before and after a change.

Wraps the Hardware object so code.py needs only one line: every hw.scan()
call marks the start of a main-loop pass. Every REPORT_EVERY seconds it
prints one line to the serial console:

  TIMING passes 4210 avg 1.19ms worst 8.42ms >5ms 3 >10ms 0 | scan avg 0.21ms worst 0.40ms | session worst 12.80ms | gc 6.90ms free 182k

  passes        main-loop passes in the window
  avg / worst   time per pass (one scan to the next, everything included)
  >5ms / >10ms  passes that took longer than that
  scan          time spent inside hw.scan() itself
  session worst the slowest pass since boot
  gc            how long one garbage collection takes: the probe runs one
                itself, timed, when it reports. Python collects on its own
                whenever memory runs low, pausing whatever pass it lands in,
                so if this matches the worst idle passes, those are GC.
  free          free memory right after that collection

Uses integer time.monotonic_ns(), not clock.now(): float seconds lose
sub-millisecond resolution after an hour or so of uptime. The pass that
reports (print and collection included) is left out of the stats, so the
probe doesn't measure itself.
"""

import gc
import time

REPORT_EVERY = 5.0   # seconds between report lines

_NS_PER_MS = 1000000


class TimingProbe:
    def __init__(self, hw, ns=time.monotonic_ns, report_every=REPORT_EVERY,
                 collect=gc.collect, mem_free=getattr(gc, "mem_free", None)):
        self._hw       = hw
        self._ns       = ns
        self._collect  = collect
        self._mem_free = mem_free   # CircuitPython only; None leaves "free" out
        self._every_ns = int(report_every * 1000000000)
        self.i2c       = hw.i2c
        self._last_start   = None
        self._report_at    = ns() + self._every_ns
        self._skip_pass    = False
        self._session_worst = 0
        self._reset_window()

    def _reset_window(self):
        self._passes     = 0
        self._pass_total = 0
        self._pass_worst = 0
        self._over_5ms   = 0
        self._over_10ms  = 0
        self._scans      = 0
        self._scan_total = 0
        self._scan_worst = 0

    def scan(self):
        start = self._ns()
        if self._last_start is not None and not self._skip_pass:
            self._record_pass(start - self._last_start)
        self._skip_pass  = False
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

    def report_line(self, gc_suffix=""):
        passes = max(1, self._passes)
        scans  = max(1, self._scans)
        return (f"TIMING passes {self._passes}"
                f" avg {_ms(self._pass_total / passes)} worst {_ms(self._pass_worst)}"
                f" >5ms {self._over_5ms} >10ms {self._over_10ms}"
                f" | scan avg {_ms(self._scan_total / scans)} worst {_ms(self._scan_worst)}"
                f" | session worst {_ms(self._session_worst)}{gc_suffix}")

    def _report(self):
        start = self._ns()
        self._collect()
        suffix = f" | gc {_ms(self._ns() - start)}"
        if self._mem_free is not None:
            suffix += f" free {self._mem_free() // 1024}k"
        print(self.report_line(suffix))
        self._reset_window()


def _ms(ns):
    return f"{ns / _NS_PER_MS:.2f}ms"
