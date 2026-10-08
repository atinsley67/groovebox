"""
The one timebase every module shares: seconds since this code run started.

Read from supervisor.ticks_ms(), whole milliseconds since power-on that wrap
at 2**29, rather than time.monotonic_ns(), for two reasons:

  - No allocation. A nanosecond count is far past the 30 bits CircuitPython
    keeps as a plain integer, so every monotonic_ns() call -- several every
    main-loop pass -- made a new heap object, and that garbage is what
    makes the (~20 ms, audio-stalling) collections come round. A ticks_ms()
    value always fits.
  - Precision. CircuitPython floats keep only ~22 bits, and
    time.monotonic() counts from power-on, so its values lose precision the
    longer the board has been on. Counting from this run's start keeps
    every timestamp small and precise for the length of a session.

Milliseconds are fine-grained enough: keypad stamps presses in whole ms too
(hw.py), and synthio only starts and stops notes once per ~12 ms block.
The count wraps after 2**29 ms (~6.2 days), long after the floats have lost
precision anyway.

All timestamps compared against each other (hw.scan() event times, the
main loop's `now`, looper positions, synth auto-releases, the menu's
flashes) must come from now() -- never mix it with time.monotonic().
"""

import supervisor

_TICKS_MAX = (1 << 29) - 1
_EPOCH     = supervisor.ticks_ms()


def now():
    """Seconds (float) since this code run started."""
    return ((supervisor.ticks_ms() - _EPOCH) & _TICKS_MAX) / 1000
