"""
The NeoKey hardware layer: keymap's layout lookups, hw's key scanning,
pixels' LED output, and the main loop end to end
on top of them.
"""

import importlib
import unittest

import fakes

import config
import keymap
import palette
from config import (BTN_MODE, BTN_MENU, BTN_INC, BTN_DEC, BTN_RECORD,
                    BTN_PLAY_STOP, BTN_MUTE, BTN_VIEW)
from event_types import PAD_DOWN, PAD_UP, BTN_DOWN
from harness import run
from hw import Hardware

MS = 0.001


class KeymapTest(unittest.TestCase):
    def test_function_layout_follows_tables(self):
        for r, row in enumerate(config.FUNC_LAYOUT):
            for c, button in enumerate(row):
                key = config.FUNC_KEYS[r][c]
                self.assertEqual(keymap.BUTTON_OF_KEY[key], button)
                if button is not None:
                    self.assertEqual(keymap.FUNC_PIXEL_OF_BUTTON[button],
                                     config.FUNC_PIXELS[r][c])

    def test_requested_layout(self):
        # Up/down top right, mode/menu top left.
        self.assertEqual(config.FUNC_LAYOUT[0], [BTN_MODE, BTN_INC])
        self.assertEqual(config.FUNC_LAYOUT[1], [BTN_MENU, BTN_DEC])

    def test_pads_number_row_by_row(self):
        for r in range(4):
            for c in range(4):
                key = config.PAD_KEYS[r][c]
                self.assertEqual(keymap.PAD_OF_KEY[key], r * 4 + c)
                self.assertEqual(keymap.PAD_PIXEL_OF_KEY[key], config.PAD_PIXELS[r][c])

    def check_rejected(self, name, value):
        saved = getattr(config, name)
        setattr(config, name, value)
        try:
            with self.assertRaises(ValueError) as caught:
                importlib.reload(keymap)
            self.assertIn(name, str(caught.exception))
        finally:
            setattr(config, name, saved)
            importlib.reload(keymap)

    def test_bad_tables_rejected(self):
        self.check_rejected("PAD_KEYS", [[0, 0, 1, 2]] + config.PAD_KEYS[1:])
        self.check_rejected("FUNC_PIXELS", config.FUNC_PIXELS[:4])
        self.check_rejected("FUNC_LAYOUT", [[BTN_MODE, BTN_INC], [BTN_MENU, BTN_DEC],
                                            [BTN_RECORD, BTN_PLAY_STOP],
                                            [BTN_VIEW, None], [None, None]])   # no MUTE


class HardwareTest(unittest.TestCase):
    def setUp(self):
        fakes.CLOCK.t = 10.0
        fakes.TICKS_OFFSET[0] = 0
        self.hw = Hardware()

    def tearDown(self):
        fakes.TICKS_OFFSET[0] = 0

    def push(self, strip, key, pressed, ms_ago):
        matrix = self.hw._pads if strip == "pad" else self.hw._func
        matrix.events.push(fakes.Event(key, pressed,
                                       timestamp=fakes.ticks_ms() - ms_ago))

    def test_matrices_swapped_for_rp2350(self):
        pads, func = self.hw._pads, self.hw._func
        self.assertEqual(pads.row_pins, config.PAD_COL_PINS)
        self.assertEqual(pads.column_pins, config.PAD_ROW_PINS)
        self.assertEqual(func.row_pins, config.FUNC_COL_PINS)
        self.assertEqual(func.column_pins, config.FUNC_ROW_PINS)
        for matrix in (pads, func):
            self.assertTrue(matrix.columns_to_anodes)
            self.assertEqual(matrix.interval, config.KEY_SCAN_INTERVAL)
            self.assertEqual(matrix.debounce_threshold, config.KEY_DEBOUNCE_THRESHOLD)

    def test_idle_scan_allocates_nothing(self):
        self.assertIs(self.hw.scan(), self.hw.scan())
        self.assertEqual(len(self.hw.scan()), 0)

    def test_pad_and_button_events(self):
        pad3 = keymap.PAD_OF_KEY.index(3)
        menu = keymap.BUTTON_OF_KEY.index(BTN_MENU)
        self.push("pad", pad3, True, ms_ago=10)
        self.push("func", menu, True, ms_ago=4)
        (t1, p1, time1), (t2, p2, time2) = self.hw.scan()
        self.assertEqual((t1, p1), (PAD_DOWN, 3))
        self.assertEqual((t2, p2), (BTN_DOWN, BTN_MENU))
        self.assertAlmostEqual(time1, 10.0 - 0.010 - config.KEY_TIME_ADJUST)
        self.assertAlmostEqual(time2, 10.0 - 0.004 - config.KEY_TIME_ADJUST)

    def test_merged_in_time_order(self):
        menu = keymap.BUTTON_OF_KEY.index(BTN_MENU)
        pad0 = keymap.PAD_OF_KEY.index(0)
        self.push("pad", pad0, True, ms_ago=2)      # pads drain first, but
        self.push("func", menu, True, ms_ago=7)     # this one came earlier
        self.push("pad", pad0, False, ms_ago=1)
        types = [(e[0], e[1]) for e in self.hw.scan()]
        self.assertEqual(types, [(BTN_DOWN, BTN_MENU), (PAD_DOWN, 0), (PAD_UP, 0)])

    def test_ticks_wrap(self):
        # ticks_ms() now reads 3; the press was stamped 5 ms earlier, before the wrap.
        fakes.TICKS_OFFSET[0] = (1 << 29) - int(round(fakes.CLOCK.t * 1000)) + 3
        self.assertEqual(fakes.ticks_ms(), 3)
        self.hw._pads.events.push(fakes.Event(keymap.PAD_OF_KEY.index(0), True,
                                              timestamp=(1 << 29) - 2))
        (_, _, event_time), = self.hw.scan()
        self.assertAlmostEqual(event_time, 10.0 - 0.005 - config.KEY_TIME_ADJUST)

    def test_unused_keys_give_no_events(self):
        self.push("func", keymap.BUTTON_OF_KEY.index(None), True, ms_ago=0)
        self.assertEqual(len(self.hw.scan()), 0)

    def test_every_pad_gives_events(self):
        for key in range(keymap.NUM_PAD_KEYS):
            self.push("pad", key, True, ms_ago=0)
        pads = sorted(payload for _, payload, _ in self.hw.scan())
        self.assertEqual(pads, list(range(16)))

    def test_raw_events_are_unmapped(self):
        self.push("pad", 15, True, ms_ago=0)
        self.push("func", 9, False, ms_ago=0)
        self.assertEqual(self.hw.raw_events(), [("pad", 15, True), ("func", 9, False)])


class PixelLedsTest(unittest.TestCase):
    def setUp(self):
        import pixels
        self.leds = pixels.PixelLeds()
        self.pads = self.leds._pads.pixels
        self.func = self.leds._func.pixels

    def func_shown(self, button):
        return self.func.shown[keymap.FUNC_PIXEL_OF_BUTTON[button]]

    def test_starts_cleared_and_capped(self):
        for strip in (self.pads, self.func):
            self.assertEqual(strip.shows, 1)
            self.assertEqual(set(strip.shown), {palette.OFF})
            self.assertEqual(strip.brightness, config.PIXEL_BRIGHTNESS)
            self.assertFalse(strip.auto_write)

    def test_mask_compatibility(self):
        mask = (1 << 2) | (1 << config.LED_RECORD) | (1 << config.LED_PLAY)
        self.leds.show_mask(mask)
        self.leds.update()
        self.assertEqual(self.pads.shown[keymap.PAD_PIXEL[2]], palette.PLAYBACK)
        self.assertEqual(self.pads.shown[keymap.PAD_PIXEL[3]], palette.OFF)
        self.assertEqual(self.func_shown(BTN_RECORD), palette.RECORDING)
        self.assertEqual(self.func_shown(BTN_PLAY_STOP), palette.PLAYING)
        self.leds.show_mask(mask | (1 << config.LED_BEAT))
        self.leds.update()
        self.assertEqual(self.func_shown(BTN_PLAY_STOP), palette.BEAT)
        self.assertEqual(self.func_shown(BTN_MUTE), palette.OFF)

    def test_sends_only_changes_rate_limited(self):
        self.leds.set_pad(0, palette.PLAYBACK)
        self.leds.update(1.000)
        self.assertEqual(self.pads.shows, 2)
        self.assertEqual(self.func.shows, 1)          # unchanged strip not sent
        self.leds.set_pad(0, palette.OFF)
        self.leds.update(1.005)                       # within 1/60 s: held back
        self.assertEqual(self.pads.shows, 2)
        self.leds.update(1.020)
        self.assertEqual(self.pads.shows, 3)
        self.leds.set_pad(0, palette.OFF)             # same color: nothing to send
        self.leds.update(2.0)
        self.assertEqual(self.pads.shows, 3)
        self.leds.set_raw("func", 4, palette.PRESSED)
        self.leds.update()                            # no `now`: straight away
        self.assertEqual(self.func.shown[4], palette.PRESSED)


class NeoKeyMainLoopTest(unittest.TestCase):
    def test_function_keys_drive_the_menu(self):
        def scenario(h):
            yield from h.tap(BTN_MENU)
            assert h.text == "SND ", h.text
            yield from h.tap(BTN_INC)
            assert h.text == "ASGN"
            yield from h.tap(BTN_PLAY_STOP)
            yield from h.tap(BTN_PLAY_STOP)
            assert h.text == "L1  ", h.text
        run(scenario)

    def test_pads_play_and_light(self):
        def scenario(h):
            note = h.synth._channels[0]["data"][5]["note"]
            h.pad_down(5)
            yield 0.03
            assert note in h.synth._synth.press_log
            assert h.pad_color(5) == palette.PLAYBACK
            h.pad_up(5)
            yield 0.03
            assert h.pad_color(5) == palette.OFF
        run(scenario)

    def test_volume_keys(self):
        def scenario(h):
            yield from h.tap(BTN_DEC)
            assert h.synth.channel_volume(0) == 95
            assert h.text == "V 95"
        run(scenario)

    def test_unused_keys_are_harmless(self):
        def scenario(h):
            h.raw_key("func", keymap.BUTTON_OF_KEY.index(None), True)
            yield 0.05
            yield from h.tap(BTN_VIEW)
            assert h.text == "L1  "
        run(scenario)

    def test_status_keys(self):
        def scenario(h):
            yield from h.tap(BTN_RECORD)                  # freeform arm
            yield from h.pad_tap(0)                       # recording starts
            assert h.key_color(BTN_RECORD) == palette.RECORDING
            yield 0.5
            yield from h.tap(BTN_RECORD)                  # commit: plays
            yield 0.05
            assert h.key_color(BTN_RECORD) == palette.OFF
            assert h.key_color(BTN_PLAY_STOP) == palette.PLAYING
        run(scenario)

    def test_beat_flashes_play_key(self):
        def scenario(h):
            yield from h.hold(BTN_MODE, 0.7)              # SEQ
            yield from h.tap(BTN_PLAY_STOP)
            seen = set()
            for _ in range(200):                          # 2 s: four beats
                seen.add(h.key_color(BTN_PLAY_STOP))
                yield 0.01
            assert {palette.PLAYING, palette.BEAT} <= seen, seen
        run(scenario)

    def test_pixel_sends_are_capped(self):
        def scenario(h):
            yield from h.hold(BTN_MODE, 0.7)              # SEQ: steps light every 1/16
            for pad in range(16):
                yield from h.pad_tap(pad)
            yield from h.tap(BTN_PLAY_STOP)
            strip = h.disp.pixels._pads.pixels
            before = strip.shows
            for pad in range(40):                         # and drum on pads too
                yield from h.pad_tap(pad % 16, hold=0.01, after=0.01)
            yield 1.2
            sends = strip.shows - before
            assert sends <= 2.0 * 61, sends
        run(scenario)


if __name__ == "__main__":
    unittest.main()
