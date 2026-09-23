import busio
import digitalio
import time
import board

import config
from event_types import PAD_DOWN, PAD_UP, BTN_DOWN, BTN_UP

# Debounce window in seconds
_DEBOUNCE = 0.020

_FUNC_BUTTONS = [
    (config.BTN_MODE_PIN,      config.BTN_MODE),
    (config.BTN_RECORD_PIN,    config.BTN_RECORD),
    (config.BTN_PLAY_STOP_PIN, config.BTN_PLAY_STOP),
    (config.BTN_TEMPO_UP_PIN,  config.BTN_TEMPO_UP),
    (config.BTN_TEMPO_DN_PIN,  config.BTN_TEMPO_DN),
    (config.BTN_MUTE_PIN,      config.BTN_MUTE),
    (config.BTN_SYNTH_EDIT_PIN, config.BTN_SYNTH_EDIT),
]


class Hardware:
    def __init__(self):
        self.i2c = busio.I2C(config.I2C_SCL, config.I2C_SDA)

        # Pad buttons
        self._pads = []
        for pin in config.PAD_PINS:
            btn = digitalio.DigitalInOut(pin)
            btn.direction = digitalio.Direction.INPUT
            btn.pull = digitalio.Pull.UP
            self._pads.append(btn)

        # Function buttons
        self._func = []
        for pin, btn_id in _FUNC_BUTTONS:
            btn = digitalio.DigitalInOut(pin)
            btn.direction = digitalio.Direction.INPUT
            btn.pull = digitalio.Pull.UP
            self._func.append((btn, btn_id))

        # Debounce state: (last_raw_value, stable_value, last_change_time)
        n_pads = len(self._pads)
        n_func = len(self._func)
        now = time.monotonic()
        self._pad_state  = [(True, True, now)] * n_pads
        self._func_state = [(True, True, now)] * n_func

    def scan(self):
        """Return a list of (event_type, payload, event_time) events since
        the last call. event_time is when the pin actually transitioned
        (last_t), not when the debounce window confirmed it (now) -- so
        callers doing precise timing (e.g. recording loop position) get the
        real press moment instead of one _DEBOUNCE (20ms) late, every time."""
        events = []
        now = time.monotonic()

        for i, btn in enumerate(self._pads):
            raw, stable, last_t = self._pad_state[i]
            current = btn.value  # True = not pressed (pull-up, active-low)
            if current != raw:
                self._pad_state[i] = (current, stable, now)
            elif current != stable and (now - last_t) >= _DEBOUNCE:
                self._pad_state[i] = (current, current, now)
                events.append((PAD_DOWN if not current else PAD_UP, i, last_t))

        for i, (btn, btn_id) in enumerate(self._func):
            raw, stable, last_t = self._func_state[i]
            current = btn.value
            if current != raw:
                self._func_state[i] = (current, stable, now)
            elif current != stable and (now - last_t) >= _DEBOUNCE:
                self._func_state[i] = (current, current, now)
                events.append((BTN_DOWN if not current else BTN_UP, btn_id, last_t))

        return events

    def deinit(self):
        for btn in self._pads:
            btn.deinit()
        for btn, _ in self._func:
            btn.deinit()
        self.i2c.deinit()
