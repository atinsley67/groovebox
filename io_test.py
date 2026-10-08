"""
Hardware I/O test loop — confirms every key, every key's NeoPixel, the
alphanumeric display, and the I2S DAC are wired correctly, and is how
config's layout tables are filled in (see docs/HARDWARE.md). Standalone: only
touches config.py, hw.py, display.py, keymap.py and palette.py, never the
main app's modes/sequencing.

Wire it in temporarily from code.py by uncommenting the line noted there;
comment it back out to return to the real app.

  1. Pixel walk: each pixel lights white in turn while the display shows
     its index: "P  0".."P 15" on the pad grid, then "F  0".."F  9" on the
     function block. Note where each lights up -> PAD_PIXELS / FUNC_PIXELS.
  2. Then press keys. On press the display shows the key's number: "PK 5"
     (pad grid) or "FK 3" (function block) -> PAD_KEYS / FUNC_KEYS. On
     release it shows what config makes of that key: "PD 1".."PD16" for a
     pad, the button's name for a function key, "----" if unassigned.
     The pixel config puts under that key lights white while it's held,
     so a wrong light means a wrong PIXELS entry. Pad 1 plays a tone
     through the DAC.
"""

import time

import audiobusio
import synthio

import config
import keymap
import palette
from hw import Hardware
from display import DisplayManager

_TONE_PAD = 0          # PAD1 doubles as the DAC/synthio smoke test
_TONE_FREQUENCY = 440  # A4
_PIXEL_WALK_STEP = 0.6 # seconds each pixel stays lit in the pixel walk

_BTN_NAMES = {
    config.BTN_RECORD:     "REC ",
    config.BTN_PLAY_STOP:  "PLAY",
    config.BTN_MODE:       "MODE",
    config.BTN_INC:        "UP  ",
    config.BTN_DEC:        "DOWN",
    config.BTN_MUTE:       "MUTE",
    config.BTN_MENU:       "MENU",
    config.BTN_VIEW:       "VIEW",
    config.BTN_KEY_MODE:   "KMOD",
    config.BTN_CLEAR:      "CLR ",
}


def run():
    hw     = Hardware()
    disp   = DisplayManager(hw.i2c)
    pixels = disp.pixels

    audio = audiobusio.I2SOut(
        bit_clock=config.I2S_BIT_CLOCK,
        word_select=config.I2S_WORD_SELECT,
        data=config.I2S_DATA_OUT,
    )
    synth = synthio.Synthesizer(sample_rate=config.SAMPLE_RATE)
    audio.play(synth) # type: ignore # The local stub doesn't like this, but it's correct.
    tone = synthio.Note(frequency=_TONE_FREQUENCY)

    disp.show("IOTS")
    time.sleep(0.5)

    # 1. Pixel walk, in index order on each strip.
    for strip, count, prefix in (("pad", keymap.NUM_PAD_KEYS, "P"),
                                 ("func", keymap.NUM_FUNC_KEYS, "F")):
        for pixel in range(count):
            pixels.set_raw(strip, pixel, palette.PRESSED)
            disp.update()
            disp.show(f"{prefix}{pixel:3d}")
            time.sleep(_PIXEL_WALK_STEP)
            pixels.set_raw(strip, pixel, palette.OFF)
        disp.update()

    # 2. Keys: raw number on press, config's meaning on release.
    disp.show("KEYS")
    while True:
        for strip, key, pressed in hw.raw_events():
            if strip == "pad":
                pad   = keymap.PAD_OF_KEY[key]
                pixel = keymap.PAD_PIXEL_OF_KEY[key]
                name  = f"PD{pad + 1:2d}"
                if pad == _TONE_PAD:
                    (synth.press if pressed else synth.release)(tone)
            else:
                button = keymap.BUTTON_OF_KEY[key]
                pixel  = keymap.FUNC_PIXEL_OF_KEY[key]
                name   = _BTN_NAMES[button] if button is not None else "----"
            pixels.set_raw(strip, pixel, palette.PRESSED if pressed else palette.OFF)
            if pressed:
                disp.show(f"{'P' if strip == 'pad' else 'F'}K{key:2d}")
            else:
                disp.show(name)
        disp.update()
