"""
Hardware I/O test loop — confirms every pad, button, LED, the alphanumeric
display, and the I2S DAC are wired correctly. Standalone: only touches
config.py, hw.py, and display.py (plus keymap.py / palette.py on the
NeoKey), never the main app's modes/sequencing.

Wire it in temporarily from code.py by uncommenting the two lines noted
there; comment them back out to return to the real app.

Breadboard (config.HARDWARE = "breadboard"): press any pad or button; its
name shows on the display and its LED lights while held. PAD1 also plays a
short tone through the DAC so you can confirm I2C and I2S in one pass.

NeoKey ("neokey") -- also how to fill in config's layout tables:
  1. Pixel walk: each pixel lights white in turn while the display shows
     its index: "P  0".."P 15" on the pad grid, then "F  0".."F  9" on the
     function block. Note where each lights up -> PAD_PIXELS / FUNC_PIXELS.
  2. Then press keys. On press the display shows the key's number: "PK 5"
     (pad grid) or "FK 3" (function block) -> PAD_KEYS / FUNC_KEYS. On
     release it shows what config makes of that key: "PD 1".."PD16" for a
     pad, the button's name for a function key, "----" if unassigned.
     The pixel config puts under that key lights white while it's held,
     so a wrong light means a wrong PIXELS entry. Pad 1 plays the tone.
"""

import time

import audiobusio
import synthio

import config
from hw import Hardware
from display import DisplayManager
from event_types import PAD_DOWN, PAD_UP, BTN_DOWN, BTN_UP

_TONE_PAD = 0          # PAD1 doubles as the DAC/synthio smoke test
_TONE_FREQUENCY = 440  # A4
_PIXEL_WALK_STEP = 0.6 # seconds each pixel stays lit in the NeoKey pixel walk

_BTN_INFO = {
    config.BTN_RECORD:     ("REC ", config.LED_RECORD),
    config.BTN_PLAY_STOP:  ("PLAY", config.LED_PLAY),
    config.BTN_MODE:       ("MODE", 10),
    config.BTN_INC:        ("UP  ", 11),
    config.BTN_DEC:        ("DOWN", 12),
    config.BTN_MUTE:       ("MUTE", 13),
    config.BTN_MENU:       ("MENU", 14),
    config.BTN_VIEW:       ("VIEW", 15),
}


def _tone_synth():
    audio = audiobusio.I2SOut(
        bit_clock=config.I2S_BIT_CLOCK,
        word_select=config.I2S_WORD_SELECT,
        data=config.I2S_DATA_OUT,
    )
    synth = synthio.Synthesizer(sample_rate=config.SAMPLE_RATE)
    audio.play(synth) # type: ignore # The local stub doesn't like this, but it's correct.
    return audio, synth, synthio.Note(frequency=_TONE_FREQUENCY)


def run():
    if config.HARDWARE == "neokey":
        _run_neokey()
    else:
        _run_breadboard()


def _run_breadboard():
    hw   = Hardware()
    disp = DisplayManager(hw.i2c)
    _audio, synth, tone = _tone_synth()

    disp.show("IOTS")
    time.sleep(0.5)
    disp.clear()

    while True:
        for etype, data, _event_time in hw.scan():
            if etype == PAD_DOWN:
                disp.show(f"PAD{data + 1}")
                disp.set_led(data, True)
                if data == _TONE_PAD:
                    synth.press(tone)

            elif etype == PAD_UP:
                disp.set_led(data, False)
                if data == _TONE_PAD:
                    synth.release(tone)

            elif etype == BTN_DOWN:
                label, led = _BTN_INFO[data]
                disp.show(label)
                disp.set_led(led, True)

            elif etype == BTN_UP:
                _, led = _BTN_INFO[data]
                disp.set_led(led, False)


def _run_neokey():
    import keymap
    import palette

    hw     = Hardware()
    disp   = DisplayManager(hw.i2c)
    pixels = disp.pixels
    _audio, synth, tone = _tone_synth()

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
                name   = _BTN_INFO[button][0] if button is not None else "----"
            pixels.set_raw(strip, pixel, palette.PRESSED if pressed else palette.OFF)
            if pressed:
                disp.show(f"{'P' if strip == 'pad' else 'F'}K{key:2d}")
            else:
                disp.show(name)
        disp.update()
