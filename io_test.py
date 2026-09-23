"""
Hardware I/O test loop — confirms every pad, button, LED, the alphanumeric
display, and the I2S DAC are wired correctly. Standalone: only touches
config.py, hw.py, and display.py, never the main app's modes/sequencing.

Wire it in temporarily from code.py by uncommenting the two lines noted
there; comment them back out to return to the real app.

Press any pad or button: its name shows on the display and its LED lights
while held. PAD1 also plays a short tone through the DAC so you can confirm
I2C and I2S in one pass.
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

_BTN_INFO = {
    config.BTN_RECORD:     ("REC ", config.LED_RECORD),
    config.BTN_PLAY_STOP:  ("PLAY", config.LED_PLAY),
    config.BTN_MODE:       ("MODE", 10),
    config.BTN_TEMPO_UP:   ("TMP+", 11),
    config.BTN_TEMPO_DN:   ("TMP-", 12),
    config.BTN_MUTE:       ("MUTE", 13),
    config.BTN_MENU:       ("MENU", 14),
}


def run():
    hw   = Hardware()
    disp = DisplayManager(hw.i2c)

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
