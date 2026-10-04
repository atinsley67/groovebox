"""
NeoKey button input (config.HARDWARE = "neokey"): the 4x4 pad grid and the
2x5 function block, each its own keypad.KeyMatrix. keypad scans them in the
background (firmware, not Python), timestamps every transition and queues
it; scan() just drains both queues into the same (event_type, payload,
event_time) events the breadboard returns, merged in time order. A pad
press is a PAD_DOWN for its pad index, a function key a BTN_DOWN for its
button id (keymap.py, from config's layout tables).

RP2350 workaround: the NeoKey's diodes call for columns_to_anodes=False,
which relies on internal pull-downs -- and those don't work on the RP2350
(erratum E9; see the keypad docs). So each matrix gets the board's row and
column lines swapped, with columns_to_anodes=True: the same diode
direction, using pull-ups. Key numbers therefore run down the board's
columns (board column * row count + board row); config's PAD_KEYS /
FUNC_KEYS tables absorb that, along with how each piece is mounted.

Timestamps: keypad stamps events in supervisor.ticks_ms (whole ms, wrapping
at 2**29); each is converted to clock.now()'s timebase by its age
(event_time = now - age), less config.KEY_TIME_ADJUST -- see there.

scan() allocates nothing when no key has changed (the common case): one
reused keypad.Event, and the clock is only read when there's an event.
"""

import busio
import keypad
import supervisor

import clock
import config
import keymap
from event_types import PAD_DOWN, PAD_UP, BTN_DOWN, BTN_UP

_TICKS_PERIOD = 1 << 29
_TICKS_MAX    = _TICKS_PERIOD - 1
_TICKS_HALF   = _TICKS_PERIOD // 2

_NO_EVENTS = ()


def _ticks_diff(ticks1, ticks2):
    """Signed ticks1 - ticks2 in ms, across the 2**29 wrap."""
    diff = (ticks1 - ticks2) & _TICKS_MAX
    return ((diff + _TICKS_HALF) & _TICKS_MAX) - _TICKS_HALF


def _event_time(event):
    return event[2]


def _matrix(board_rows, board_cols):
    """A KeyMatrix for one piece, row/column lines swapped (see above)."""
    return keypad.KeyMatrix(
        row_pins=board_cols, column_pins=board_rows, columns_to_anodes=True,
        interval=config.KEY_SCAN_INTERVAL,
        debounce_threshold=config.KEY_DEBOUNCE_THRESHOLD,
    )


class NeoKeyHardware:
    def __init__(self):
        self.i2c = busio.I2C(config.I2C_SCL, config.I2C_SDA,
                             frequency=config.I2C_FREQUENCY)
        self._pads = _matrix(config.PAD_ROW_PINS, config.PAD_COL_PINS)
        self._func = _matrix(config.FUNC_ROW_PINS, config.FUNC_COL_PINS)

        # Pads past NUM_PADS give no events until the modes handle them.
        pad_of_key = [pad if pad < config.NUM_PADS else None
                      for pad in keymap.PAD_OF_KEY]
        # (event queue, key number -> payload, press type, release type)
        self._sources = (
            (self._pads.events, pad_of_key,            PAD_DOWN, PAD_UP),
            (self._func.events, keymap.BUTTON_OF_KEY,  BTN_DOWN, BTN_UP),
        )
        self._event = keypad.Event()   # reused by get_into(): no allocation

    def scan(self):
        """(event_type, payload, event_time) for every key transition since
        the last call, oldest first. event_time is when the key actually
        changed -- see the module docstring."""
        events = None
        event  = self._event
        for queue, payload_of_key, down, up in self._sources:
            while queue.get_into(event):
                payload = payload_of_key[event.key_number]
                if payload is None:
                    continue
                if events is None:
                    events = []
                    now    = clock.now()
                    ticks  = supervisor.ticks_ms()
                age = _ticks_diff(ticks, event.timestamp) / 1000
                events.append((down if event.pressed else up, payload,
                               now - age - config.KEY_TIME_ADJUST))
        if events is None:
            return _NO_EVENTS
        if len(events) > 1:
            events.sort(key=_event_time)   # merge the two matrices in time order
        return events

    def raw_events(self):
        """For io_test.py: every transition as ("pad" | "func", key number,
        pressed), unmapped -- unassigned keys and pads past NUM_PADS too."""
        out   = []
        event = self._event
        for name, matrix in (("pad", self._pads), ("func", self._func)):
            while matrix.events.get_into(event):
                out.append((name, event.key_number, event.pressed))
        return out

    def deinit(self):
        self._pads.deinit()
        self._func.deinit()
        self.i2c.deinit()
