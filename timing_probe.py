"""
Main-loop timing probe (config.TIMING_PROBE) -- a baseline to compare the
button hardware against before and after a change.

Wraps the Hardware object so code.py needs only one line: every hw.scan()
call marks the start of a main-loop pass. Given the DisplayManager too, it
also times the LED work. Every REPORT_EVERY seconds it prints one line to
the serial console:

  TIMING passes 4210 avg 1.19ms worst 8.42ms >5ms 3 >10ms 0 | scan avg 0.21ms worst 0.40ms | session worst 12.80ms | gc 6.90ms free 182k | alloc 410B/pass ~9gc | leds draw 300x 0.30ms worst 0.61ms send 180x 0.52ms worst 0.95ms

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
  leds draw     code.py's draw_lights (the pad view's frame and every key's
                color, up to 60 a second), once code.py hands it over with
                timed_draw(): count, average, worst
  leds send     NeoPixel strip sends (DisplayManager.update calls that sent)

With it, every window prints what the main loop allocates, part by part --
what makes the collections come round:

  ALLOC per pass, 96 samples (3 lost to a gc): total 1720B | scan 40 | loop ev 120 | loop 610 | synth 380 | ... | rest 300

  One pass in _ALLOC_SAMPLE_EVERY is a sample: memory in use is read around
  hw.scan() and every method code.py hands to track(), and at the end of
  the pass. Each figure is the average bytes per sampled pass; "rest" is
  the total less the parts -- code.py's own loop and anything not tracked.
  Reading memory walks the heap, so a sampled pass is slow: it's left out of
  the timing stats. A sample whose pass had a collection in it can't be
  measured, and is lost.

Heap census: census() prints one HEAP line -- memory in use and a timed
collection -- at each stage of boot, and after a groove loads (code.py, with
config.TIMING_PROBE on), so the GC time can be traced to code, sound tables,
voices or recorded loops. See census().

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
_ALLOC_SAMPLE_EVERY  = 25    # one pass in this many measures its allocation by part


class TimingProbe:
    def __init__(self, hw, disp=None, ns=time.monotonic_ns, report_every=REPORT_EVERY,
                 collect=gc.collect, mem_free=getattr(gc, "mem_free", None),
                 mem_alloc=getattr(gc, "mem_alloc", None)):
        self._hw       = hw
        self._ns       = ns
        self._collect  = collect
        self._mem_free = mem_free   # CircuitPython only; None leaves "free"/"alloc" out
        self._mem_alloc = mem_alloc  # CircuitPython only; None: no ALLOC line
        # The ALLOC line's parts (bucket 0 is hw.scan; track() adds more),
        # bytes per part this window, and the pass being sampled.
        self._labels      = ["scan"]
        self._part_bytes  = [0]
        self._pass_bytes  = [0]
        self._pass_no     = 0
        self._sampling    = False
        self._sample_base = 0       # memory in use when the sampled pass began
        self._sample_lost = False   # a collection ran in it
        self._sample_done = 0       # this window's samples...
        self._sample_lost_count = 0
        self._sample_total = 0      # ...and their total bytes
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
        self._draw = [0, 0, 0]   # [count, total ns, worst ns]
        self._send = [0, 0, 0]
        for i in range(len(self._part_bytes)):
            self._part_bytes[i] = 0
        self._sample_done       = 0
        self._sample_lost_count = 0
        self._sample_total      = 0

    # ── LED timing ────────────────────────────────────────────────────────────

    def timed_draw(self, draw):
        """`draw` (code.py's draw_lights), timed on every call, and its
        allocation counted on sampled passes (as "lights")."""
        ns   = self._ns
        part = self._add_part("lights")

        def timed(now):
            sampling = self._sampling
            if sampling:
                before = self._mem_alloc()
            start = ns()
            draw(now)
            _record(self._draw, ns() - start)
            if sampling:
                self._count(part, before)

        return timed

    # ── Allocation by part ────────────────────────────────────────────────────

    def track(self, label, obj, name, arity):
        """Count what obj.<name>() allocates on sampled passes, under
        `label`, by replacing it with a wrapper. arity: how many arguments
        it takes (fixed-arity wrappers: *args would itself allocate). A
        third argument is optional and named `exact` (looper.handle_event's,
        which code.py's play_arp passes by keyword), and a lone one is
        optional too (disp.update's now)."""
        part = self._add_part(label)
        fn   = getattr(obj, name)
        if arity == 0:
            def tracked():
                if not self._sampling:
                    return fn()
                before = self._mem_alloc()
                result = fn()
                self._count(part, before)
                return result
        elif arity == 1:
            def tracked(a=None):
                if not self._sampling:
                    return fn(a)
                before = self._mem_alloc()
                result = fn(a)
                self._count(part, before)
                return result
        elif arity == 2:
            def tracked(a, b):
                if not self._sampling:
                    return fn(a, b)
                before = self._mem_alloc()
                result = fn(a, b)
                self._count(part, before)
                return result
        else:
            def tracked(a, b, exact=False):
                if not self._sampling:
                    return fn(a, b, exact)
                before = self._mem_alloc()
                result = fn(a, b, exact)
                self._count(part, before)
                return result
        setattr(obj, name, tracked)

    def _add_part(self, label):
        self._labels.append(label)
        self._part_bytes.append(0)
        self._pass_bytes.append(0)
        return len(self._labels) - 1

    def _count(self, part, before):
        grew = self._mem_alloc() - before
        if grew < 0:
            self._sample_lost = True   # a collection ran in the middle
        else:
            self._pass_bytes[part] += grew

    def _begin_sample(self):
        for i in range(len(self._pass_bytes)):
            self._pass_bytes[i] = 0
        self._sample_lost = False
        self._sampling    = True
        self._sample_base = self._mem_alloc()

    def _end_sample(self):
        """First thing in the pass after a sampled one: the whole pass's
        allocation, and its parts into the window's figures."""
        total = self._mem_alloc() - self._sample_base
        self._sampling = False
        if total < 0 or self._sample_lost:
            self._sample_lost_count += 1
            return
        self._sample_done  += 1
        self._sample_total += total
        for i in range(len(self._pass_bytes)):
            self._part_bytes[i] += self._pass_bytes[i]

    def alloc_line(self):
        if not self._sample_done:
            return f"ALLOC per pass, no samples ({self._sample_lost_count} lost to a gc)"
        n     = self._sample_done
        parts = " | ".join(f"{label} {b // n}"
                           for label, b in zip(self._labels, self._part_bytes))
        rest  = (self._sample_total - sum(self._part_bytes)) // n
        return (f"ALLOC per pass, {n} samples ({self._sample_lost_count} lost to a gc):"
                f" total {self._sample_total // n}B | {parts} | rest {rest}")

    def _wrap_leds(self, disp):
        """Time the display's sends by replacing its update() with a timed
        version. Calls with nothing to send aren't timed, so the probe adds
        no clock reads to an idle pass."""
        ns     = self._ns
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
        if self._sampling:
            self._end_sample()   # before anything else allocates
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

        self._pass_no += 1
        if (self._mem_alloc is not None and start < self._report_at and
                self._pass_no % _ALLOC_SAMPLE_EVERY == 0):
            # A sampled pass: slow (memory readings walk the heap), so it
            # stays out of the timing stats -- and so does this scan.
            self._skip_pass = True
            self._begin_sample()
            events = self._hw.scan()
            self._count(0, self._sample_base)
            return events

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
            line += " | leds draw " + _stat(self._draw)
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
        if self._mem_alloc is not None:
            print(self.alloc_line())
        if self._mem_free is not None:
            # Start the next window's allocation sample from this fresh heap.
            self._free_after_gc  = free
            self._alloc_free0    = free
            self._free_ref       = free
            self._alloc_per_pass = None
        self._reset_window()


def census(label, ns=time.monotonic_ns, collect=gc.collect,
           mem_alloc=getattr(gc, "mem_alloc", None),
           mem_free=getattr(gc, "mem_free", None), out=print):
    """One line on what's live in the heap at this point, for tracing the
    GC time back to what holds it. code.py calls it at boot milestones and
    after a groove loads:

      HEAP voices         used 142k free 251k gc 12.40ms

      used / free  memory after a full collection
      gc           how long that collection took: the second of two, so
                   it's the cost of walking what's live, not of freeing
                   garbage. The difference from the line before is what that
                   stage added to every collection from then on.
    """
    collect()
    start = ns()
    collect()
    took = ns() - start
    line = f"HEAP {label:<14}"
    if mem_alloc is not None and mem_free is not None:
        line += f" used {mem_alloc() // 1024}k free {mem_free() // 1024}k"
    out(f"{line} gc {_ms(took)}")


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
