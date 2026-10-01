"""DisplayManager: the text goes out once per change, and hold_text()."""

import unittest

import fakes  # noqa: F401  (installs the CircuitPython fakes first)

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
        state = dict(steps_bitmask8=0, current_step_in_page=-1, is_playing=True,
                     selected_track=0, page=0)
        self.disp.show_sequencer_state(**state)
        writes = self.seg.writes
        for step in range(8):   # playhead moving: LEDs change, text doesn't
            self.disp.show_sequencer_state(**dict(state, current_step_in_page=step))
        self.assertEqual(self.seg.writes, writes)
        self.disp.show_sequencer_state(**dict(state, selected_track=1))
        self.assertEqual(self.seg.text, "T2P1")
        self.assertEqual(self.seg.writes, writes + 1)

    def test_held_text_only_updates_leds(self):
        self.disp.hold_text(True)
        self.disp.show("V 80")
        self.disp.show_looper_state(0b101, "PLY ", 0, layer_num=1)
        self.assertEqual(self.seg.text, "V 80")
        self.assertTrue(self.disp._led_state & 0b101)
        self.disp.hold_text(False)
        self.disp.show_looper_state(0b101, "PLY ", 0, layer_num=1)
        self.assertEqual(self.seg.text, "L1  ")


if __name__ == "__main__":
    unittest.main()
