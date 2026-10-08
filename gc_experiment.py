"""
One-off diagnostic, not part of the groovebox: does a long list of small
objects make CircuitPython's garbage collector re-scan the heap?

The collector's mark stack holds 64 entries. An object with more unmarked
children than that overflows it, and the collector then re-scans the whole
heap -- so one list of 256 tuples (a full loop layer's notes) could cost far
more than the same tuples spread over short lists. This measures it, three
times over: on a bare heap, with the groovebox's code imported, and with
its voices built (a SynthEngine). Each line shows a collection's time on its
own ("base") and what each shape of the same data adds to it:

  1x60 / 1x70   one list of 60 / 70 tuples: either side of 64
  1x256         one list of 256 tuples, like a full loop layer
  8x32          the same 256 tuples as eight lists of 32
  arrays        the same 256 notes as an array of floats + a bytearray

Run it from the REPL with code.py stopped (Ctrl-C, then a key for the REPL):
    import gc_experiment
Ctrl-D afterwards restarts the groovebox.
"""

import array
import gc
import time


def _collect_ms():
    """A collection's time with nothing to free: the best of three."""
    best = None
    for _ in range(3):
        gc.collect()
        start = time.monotonic_ns()
        gc.collect()
        took = (time.monotonic_ns() - start) / 1000000
        if best is None or took < best:
            best = took
    return best


def _tuples(count, offset=0):
    """`count` new (position, pad) tuples, like a loop layer's notes."""
    return [(i * 0.125 + offset, i % 16) for i in range(count)]


def _added(build, base):
    """What holding `build()`'s result adds to a collection."""
    held = build()   # noqa: F841 -- kept alive for the measurement
    return _collect_ms() - base


def _trial(label):
    base = _collect_ms()
    shapes = (
        ("1x60",   lambda: _tuples(60)),
        ("1x70",   lambda: _tuples(70)),
        ("1x256",  lambda: _tuples(256)),
        ("8x32",   lambda: [_tuples(32, k) for k in range(8)]),
        ("arrays", lambda: (array.array("f", [i * 0.125 for i in range(256)]),
                            bytearray(i % 16 for i in range(256)))),
    )
    parts = " | ".join(f"{name} +{_added(build, base):.2f}" for name, build in shapes)
    print(f"GCX {label:<12} used {gc.mem_alloc() // 1024}k base {base:.2f}ms | {parts}")


_trial("bare heap")

import arp, arranger, display, groove, hw, looper, menu   # noqa: E402,F401
import pad_views, sequencer, startup, synth_engine        # noqa: E402,F401
_trial("code")

_engine = synth_engine.SynthEngine()
_trial("voices")

print("GCX done -- Ctrl-D restarts the groovebox")
