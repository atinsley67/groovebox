"""
The one timebase every module shares: seconds since this code run started.

Why not time.monotonic() directly: CircuitPython floats keep only ~22 bits
of precision, and monotonic() counts from power-on (not from this code
run), so its values -- and therefore the gap between representable times
-- keep growing for as long as the board has been on. After an hour that
gap is around a millisecond, after a few hours several. Reading the
integer monotonic_ns() and subtracting this run's start first keeps every
timestamp small and precise for the length of a session.

All timestamps compared against each other (hw.scan() event times, the
main loop's `now`, looper positions, synth auto-releases, the menu's
flashes) must come from now() -- never mix it with time.monotonic().
"""

import time

_EPOCH_NS = time.monotonic_ns()


def now():
    """Seconds (float) since this code run started."""
    return (time.monotonic_ns() - _EPOCH_NS) / 1000000000
