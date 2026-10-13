"""
ECHO's startup: a call and its echoes. Runs once before the game's title;
pressing any pad or key skips it.

The box plays a 4-note call, one note per letter as ECHO types itself onto
the display, and it comes back three times, each fainter, like an echo off
a far wall: the notes quieter, the display dimmer. Every note sends a ring
out across all the keys from the pad it plays: cyan for the call, then
yellow and cyan in turn for the echoes (the game's ME / YOU colours), so
each pass's rings ripple through the fading ones before.

Where the groovebox's startup (startup.py) is a silent rainbow wave rolling
corner to corner, this one is a sound and its rings, dying away.

The rings treat both pieces as one 7 x 5 grid, as startup.py does: the 4x4
pads bottom left, the 2x5 function block on the right, one empty column
between. Positions come from the pad order and config.FUNC_LAYOUT, so they
follow the wiring.
"""

import math
import time

from core import clock
import config
from core import display, keymap, palette
from core.event_types import BTN_DOWN, PAD_DOWN

MOTIF       = (0, 2, 3, 5)       # scale notes, one a letter: root, 4th, 5th, octave
TEXT        = ("E   ", "EC  ", "ECH ", "ECHO")
LEVELS      = (1.0, 0.5, 0.25, 0.12)   # the call, then each echo
NOTE_GAP    = 0.16    # seconds between a pass's notes
PASS_GAP    = 0.8     # seconds from one pass to the next
FRAME_DELAY = 0.025   # seconds between frames (~40 a second)

_RING_SPEED  = 10.0   # keys a second
_RING_WIDTH  = 1.2    # keys lit either side of a ring's front
_RING_SPREAD = 0.35   # how fast a ring fades as it grows
_PASS_COLORS = (palette.CYAN, palette.YELLOW)


def _key_positions():
    """(pad, button, x, y) for every key -- pad index or None, button id or
    None -- on the combined grid, y counted from the top."""
    pad_rows = len(config.PAD_KEYS)
    pad_cols = len(config.PAD_KEYS[0])
    height   = max(pad_rows, len(config.FUNC_LAYOUT))
    keys = []
    for pad in range(config.NUM_PADS):
        row, col = divmod(pad, pad_cols)
        keys.append((pad, None, col, height - pad_rows + row))
    for row, buttons in enumerate(config.FUNC_LAYOUT):
        for col, button in enumerate(buttons):
            if button is not None:
                keys.append((None, button, pad_cols + 1 + col, row))
    return keys


def schedule():
    """(time, pass, note) for every note, in order: the call is pass 0."""
    return [(k * PASS_GAP + i * NOTE_GAP, k, i)
            for k in range(len(LEVELS)) for i in range(len(MOTIF))]


def _skip_requested(hw):
    """A press, not a release: MENU, held to get here, comes up during it."""
    for etype, _, _ in hw.scan():
        if etype == PAD_DOWN or etype == BTN_DOWN:
            return True
    return False


def _draw(leds, keys, dist, notes, fired, t, life, rgb):
    """Every key's light at time t: the sum of the rings still crossing
    the keys (rgb: three lists, a sum per key, reused frame to frame)."""
    red, green, blue = rgb
    count = len(keys)
    for n in range(count):
        red[n] = green[n] = blue[n] = 0.0
    for e in range(fired):
        start, k, i = notes[e]
        age = t - start
        if age >= life:
            continue   # it's gone past every key
        front = age * _RING_SPEED
        fade  = LEVELS[k] / (1.0 + _RING_SPREAD * front)
        color = _PASS_COLORS[k % 2]
        for n in range(count):
            level = 1.0 - abs(dist[n][i] - front) / _RING_WIDTH
            if level > 0:
                level *= fade
                red[n]   += color[0] * level
                green[n] += color[1] * level
                blue[n]  += color[2] * level
    for n in range(count):
        color = (min(255, int(red[n])), min(255, int(green[n])), min(255, int(blue[n])))
        pad, button, _, _ = keys[n]
        if pad is not None:
            leds.set_pad(pad, color)
        else:
            leds.set_button(button, color)


def run(hw, disp, sound, layer, volume):
    """Play the intro on loop layer `layer` of `sound` (a
    synth_engine.SynthEngine), whose volume it leaves at `volume`. Returns
    when it's over, or as soon as a key is pressed."""
    keys  = _key_positions()
    pads  = [keymap.PAD_OF_NOTE[note] for note in MOTIF]
    where = {}
    for pad, _, x, y in keys:
        if pad is not None:
            where[pad] = (x, y)
    dist  = [[math.sqrt((x - where[p][0]) ** 2 + (y - where[p][1]) ** 2) for p in pads]
             for _, _, x, y in keys]
    notes = schedule()
    # The last ring has crossed the farthest key.
    life  = (max(max(row) for row in dist) + _RING_WIDTH) / _RING_SPEED
    end   = notes[-1][0] + life

    leds  = disp.pixels
    rgb   = ([0.0] * len(keys), [0.0] * len(keys), [0.0] * len(keys))
    fired = 0
    sounding = None
    start = clock.now()
    while True:
        now = clock.now()
        t = now - start
        if t >= end:
            break
        while fired < len(notes) and notes[fired][0] <= t:
            _, k, i = notes[fired]
            if sounding is not None:
                sound.release_layer_pad(layer, sounding)
            sound.set_channel_volume(layer, round(volume * LEVELS[k]))
            sound.trigger_layer_pad(layer, pads[i])
            sounding = pads[i]
            if k == 0:
                disp.show(TEXT[i])
            if i == 0:
                disp.set_brightness(display.BRIGHTNESS * LEVELS[k])
            fired += 1
        _draw(leds, keys, dist, notes, fired, t, life, rgb)
        disp.update()   # straight away (no `now`: not rate-limited)
        sound.update(now)
        if _skip_requested(hw):
            break
        time.sleep(FRAME_DELAY)

    if sounding is not None:
        sound.release_layer_pad(layer, sounding)
    sound.set_channel_volume(layer, volume)
    disp.set_brightness(display.BRIGHTNESS)
    disp.clear()
    disp.update()
