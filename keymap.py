"""
NeoKey lookups, derived once from config.py's layout tables (PAD_KEYS,
PAD_PIXELS, FUNC_LAYOUT, FUNC_KEYS, FUNC_PIXELS) and checked, so a
mistyped table stops at startup with a message naming it instead of
quietly misrouting keys.

Positions are read row by row from the top left of each piece as it's
mounted; a pad's index is its position (so pads 0-7 are the top two rows).

  PAD_OF_KEY[key]            pad index of a pad-matrix key number
  PAD_PIXEL[pad]             NeoPixel index under a pad
  PAD_PIXEL_OF_KEY[key]      NeoPixel index under a pad-matrix key
  BUTTON_OF_KEY[key]         button id of a function-matrix key (None = unassigned)
  FUNC_PIXEL_OF_KEY[key]     NeoPixel index under a function-matrix key
  FUNC_PIXEL_OF_BUTTON[id]   NeoPixel index under a button's key
"""

import config

NUM_PAD_KEYS  = len(config.PAD_ROW_PINS) * len(config.PAD_COL_PINS)
NUM_FUNC_KEYS = len(config.FUNC_ROW_PINS) * len(config.FUNC_COL_PINS)

# Buttons the app can't work without: each must be somewhere in FUNC_LAYOUT.
_REQUIRED_BUTTONS = (config.BTN_MODE, config.BTN_RECORD, config.BTN_PLAY_STOP,
                     config.BTN_INC, config.BTN_DEC, config.BTN_MUTE, config.BTN_MENU)


def _flat(name, rows, count):
    values = [value for row in rows for value in row]
    if len(values) != count:
        raise ValueError(f"config.{name} needs {count} entries, has {len(values)}")
    return values


def _check_numbering(name, values):
    if sorted(values) != list(range(len(values))):
        raise ValueError(f"config.{name} must hold each of 0-{len(values) - 1} exactly once")


def _invert(values):
    inverse = [0] * len(values)
    for position, value in enumerate(values):
        inverse[value] = position
    return inverse


# ── Pads ──────────────────────────────────────────────────────────────────────

_pad_keys = _flat("PAD_KEYS", config.PAD_KEYS, NUM_PAD_KEYS)
_check_numbering("PAD_KEYS", _pad_keys)
PAD_PIXEL = _flat("PAD_PIXELS", config.PAD_PIXELS, NUM_PAD_KEYS)
_check_numbering("PAD_PIXELS", PAD_PIXEL)

PAD_OF_KEY       = _invert(_pad_keys)
PAD_PIXEL_OF_KEY = [PAD_PIXEL[PAD_OF_KEY[key]] for key in range(NUM_PAD_KEYS)]

# ── Function block ────────────────────────────────────────────────────────────

_func_keys = _flat("FUNC_KEYS", config.FUNC_KEYS, NUM_FUNC_KEYS)
_check_numbering("FUNC_KEYS", _func_keys)
_func_pixels = _flat("FUNC_PIXELS", config.FUNC_PIXELS, NUM_FUNC_KEYS)
_check_numbering("FUNC_PIXELS", _func_pixels)
_layout = _flat("FUNC_LAYOUT", config.FUNC_LAYOUT, NUM_FUNC_KEYS)

for _button in _REQUIRED_BUTTONS:
    if _layout.count(_button) != 1:
        raise ValueError(f"config.FUNC_LAYOUT must hold {_button!r} exactly once")

BUTTON_OF_KEY        = [None] * NUM_FUNC_KEYS
FUNC_PIXEL_OF_KEY    = [0] * NUM_FUNC_KEYS
FUNC_PIXEL_OF_BUTTON = {}
for _position, _key in enumerate(_func_keys):
    BUTTON_OF_KEY[_key]     = _layout[_position]
    FUNC_PIXEL_OF_KEY[_key] = _func_pixels[_position]
    if _layout[_position] is not None:
        FUNC_PIXEL_OF_BUTTON[_layout[_position]] = _func_pixels[_position]
