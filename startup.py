"""
Startup animation: a rainbow wave across every key while "GROOVEBOX"
scrolls across the 4-char display. Runs once before the main loop starts;
pressing any pad or key skips it.

The wave treats both pieces as one 7 x 5 grid, laid out as they sit side by
side: the 4x4 pads bottom left, the 2x5 function block on the right, one
empty column between. It rolls in from the bottom-left corner, reaches the
top-right one and bounces back, its colors banded along the diagonals and
drifting as it goes. Key positions come from config's layout tables
(PAD_PIXELS / FUNC_PIXELS), so it follows the wiring.
"""

import time

import clock
import config
import palette

MARQUEE_TEXT        = "GROOVEBOX"
MARQUEE_FRAME_DELAY = 0.12    # seconds per scroll step; the wave lasts as long as the scroll
WAVE_FRAME_DELAY    = 0.025   # seconds between wave frames (~40 a second)

_WAVE_WIDTH = 2.5   # diagonals lit either side of the wave front
_HUE_SPREAD = 24    # color-wheel steps between neighbouring diagonals
_HUE_SPEED  = 200   # color-wheel steps per second the colors drift


def _key_positions():
    """(strip, pixel, diagonal) for every key. The diagonal counts from the
    combined grid's bottom-left corner (0) to its top-right one (the
    highest): the pads bottom-aligned on the left, the function block
    top-aligned on the right, one empty column between."""
    pad_rows  = len(config.PAD_PIXELS)
    pad_cols  = len(config.PAD_PIXELS[0])
    func_rows = len(config.FUNC_PIXELS)
    height    = max(pad_rows, func_rows)
    keys = []
    for r, row in enumerate(config.PAD_PIXELS):
        y = height - pad_rows + r              # rows counted from the top
        for c, pixel in enumerate(row):
            keys.append(("pad", pixel, c + (height - 1 - y)))
    for r, row in enumerate(config.FUNC_PIXELS):
        for c, pixel in enumerate(row):
            keys.append(("func", pixel, pad_cols + 1 + c + (height - 1 - r)))
    return keys


def _wheel(pos):
    """A rainbow color for pos on a 256-step wheel: red, green, blue, red."""
    pos = int(pos) % 256
    if pos < 85:
        return (255 - pos * 3, pos * 3, 0)
    if pos < 170:
        pos -= 85
        return (0, 255 - pos * 3, pos * 3)
    pos -= 170
    return (pos * 3, 0, 255 - pos * 3)


def _draw_wave(pixels, keys, t, duration, last_diagonal):
    """The wave at time t of `duration`: its front starts just off the
    bottom-left corner, reaches the last diagonal halfway through, and
    comes back."""
    rise  = 1.0 - abs(2.0 * t / duration - 1.0)          # 0 -> 1 -> 0
    front = (last_diagonal + _WAVE_WIDTH) * rise - _WAVE_WIDTH
    for strip, pixel, diagonal in keys:
        level = 1.0 - abs(diagonal - front) / _WAVE_WIDTH
        if level > 0:
            color = palette.scaled(_wheel(diagonal * _HUE_SPREAD + t * _HUE_SPEED), level)
        else:
            color = palette.OFF
        pixels.set_raw(strip, pixel, color)


def _skip_requested(hw):
    return len(hw.scan()) > 0


def run(hw, disp):
    """Play the boot animation. Returns as soon as any key is pressed."""
    keys          = _key_positions()
    last_diagonal = max(diagonal for _, _, diagonal in keys)
    padded        = "    " + MARQUEE_TEXT + "    "
    duration      = (len(padded) - 3) * MARQUEE_FRAME_DELAY
    start         = clock.now()
    while True:
        t = clock.now() - start
        if t >= duration:
            break
        step = int(t / MARQUEE_FRAME_DELAY)
        disp.show(padded[step:step + 4])
        _draw_wave(disp.pixels, keys, t, duration, last_diagonal)
        disp.update()   # straight away (no `now`: not rate-limited)
        if _skip_requested(hw):
            break
        time.sleep(WAVE_FRAME_DELAY)
    disp.clear()
    disp.update()
