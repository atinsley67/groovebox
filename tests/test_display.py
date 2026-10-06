"""DisplayManager: the text goes out once per change, hold_text(), and the
pad frames / key colors."""

import unittest

import fakes  # noqa: F401  (installs the CircuitPython fakes first)

import config
import keymap
import palette
from display import DisplayManager


class DisplayTextTest(unittest.TestCase):
    def setUp(self):
        self.disp = DisplayManager(object())
        self.seg  = self.disp._seg

    def test_one_write_per_change(self):
        writes = self.seg.writes
        self.disp.show("SND")
        self.assertEqual(self.seg.text, "SND ")
        self.assertEqual(self.seg.writes, writes + 1)   # not 2: auto_write is off
        self.disp.show("SND ")
        self.assertEqual(self.seg.writes, writes + 1)   # unchanged: not sent

    def test_mode_redraws_skip_unchanged_text(self):
        self.disp.show_sequencer_state(0)
        writes = self.seg.writes
        for _ in range(16):     # every step redraws: the text doesn't change
            self.disp.show_sequencer_state(0)
        self.assertEqual(self.seg.writes, writes)
        self.disp.show_sequencer_state(1)
        self.assertEqual(self.seg.text, "T2  ")
        self.assertEqual(self.seg.writes, writes + 1)

    def test_held_text_is_left_alone(self):
        self.disp.hold_text(True)
        self.disp.show("V 80")
        self.disp.show_looper_state("PLY ", layer_num=1)
        self.assertEqual(self.seg.text, "V 80")
        self.disp.hold_text(False)
        self.disp.show_looper_state("PLY ", layer_num=1)
        self.assertEqual(self.seg.text, "L1  ")

    def test_looper_text(self):
        self.disp.show_looper_state("REC ", layer_num=2)
        self.assertEqual(self.seg.text, "REC ")
        self.disp.show_looper_state("REC ", layer_num=2, synced=True)
        self.assertEqual(self.seg.text, "SREC")


class DisplayLightsTest(unittest.TestCase):
    def setUp(self):
        self.disp = DisplayManager(object())
        self.pads = self.disp.pixels._pads.pixels
        self.func = self.disp.pixels._func.pixels

    def test_frames_and_key_colors(self):
        frame = [palette.OFF] * config.NUM_PADS
        frame[15] = palette.LIVE
        self.disp.set_pad_frame(frame)
        self.disp.set_key_color(config.BTN_CLEAR, palette.ARMED_CLEAR)
        self.disp.update()
        self.assertEqual(self.pads.shown[keymap.PAD_PIXEL[15]], palette.LIVE)
        self.assertEqual(self.pads.shown[keymap.PAD_PIXEL[0]], palette.OFF)
        self.assertEqual(self.func.shown[keymap.FUNC_PIXEL_OF_BUTTON[config.BTN_CLEAR]],
                         palette.ARMED_CLEAR)
        self.disp.clear_leds()
        self.disp.update()
        self.assertEqual(set(self.pads.shown) | set(self.func.shown), {palette.OFF})


if __name__ == "__main__":
    unittest.main()
