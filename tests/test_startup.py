"""startup.py: the boot wave's grid, its bounce, the marquee, and skipping."""

import unittest

import fakes

import config
import palette
import startup
from display import DisplayManager


class FakeHw:
    """scan() returns a press on call `press_on` (never, by default)."""

    def __init__(self, press_on=None):
        self.calls    = 0
        self.press_on = press_on

    def scan(self):
        self.calls += 1
        return ["press"] if self.calls == self.press_on else ()


class StartupTest(unittest.TestCase):
    def setUp(self):
        fakes.CLOCK.t = 0.0
        self._sleep = startup.time.sleep
        startup.time.sleep = self.fake_sleep
        self.disp = DisplayManager(object())
        self.pads = self.disp.pixels._pads.pixels
        self.func = self.disp.pixels._func.pixels
        # Every frame the animation sends: (pad colors, function colors).
        self.frames = []
        update = self.disp.update

        def recording_update(now=None):
            update(now)
            self.frames.append((list(self.pads.shown), list(self.func.shown)))

        self.disp.update = recording_update

    def tearDown(self):
        startup.time.sleep = self._sleep

    def fake_sleep(self, seconds):
        fakes.CLOCK.t += seconds

    def test_grid_runs_bottom_left_to_top_right(self):
        keys = {(strip, pixel): d for strip, pixel, d in startup._key_positions()}
        self.assertEqual(len(keys), 26)
        self.assertEqual(keys[("pad", config.PAD_PIXELS[3][0])], 0)    # bottom-left pad
        self.assertEqual(keys[("pad", config.PAD_PIXELS[0][3])], 6)    # top-right pad
        self.assertEqual(keys[("func", config.FUNC_PIXELS[4][0])], 5)  # after the gap
        self.assertEqual(keys[("func", config.FUNC_PIXELS[0][1])], 10)  # top-right key

    def test_wave_bounces_across_every_key(self):
        startup.run(FakeHw(), self.disp)
        corner, far = config.PAD_PIXELS[3][0], config.FUNC_PIXELS[0][1]
        lit_corner = [i for i, (pads, _) in enumerate(self.frames)
                      if pads[corner] != palette.OFF]
        lit_far    = [i for i, (_, func) in enumerate(self.frames)
                      if func[far] != palette.OFF]
        assert lit_corner and lit_far
        # Out from the corner, to the far key, and back to the corner.
        self.assertLess(lit_corner[0], lit_far[0])
        self.assertGreater(lit_corner[-1], lit_far[-1])
        # Every key lit at some point, in more than one color.
        for strip in (0, 1):
            for pixel in range(len(self.frames[0][strip])):
                seen = {frame[strip][pixel] for frame in self.frames} - {palette.OFF}
                self.assertGreater(len(seen), 1, (strip, pixel))
        # Ends dark and blank, having scrolled the name.
        pads, func = self.frames[-1]
        self.assertEqual(set(pads) | set(func), {palette.OFF})
        self.assertEqual(self.disp._seg.text, "    ")
        self.assertIn("GROO", self.disp._seg.history)
        self.assertIn("VEBO", self.disp._seg.history)

    def test_lasts_as_long_as_the_scroll(self):
        startup.run(FakeHw(), self.disp)
        scroll = (len(startup.MARQUEE_TEXT) + 5) * startup.MARQUEE_FRAME_DELAY
        self.assertAlmostEqual(fakes.CLOCK.t, scroll, delta=0.05)

    def test_a_press_skips_it(self):
        startup.run(FakeHw(press_on=3), self.disp)
        self.assertLess(fakes.CLOCK.t, 0.1)
        pads, func = self.frames[-1]
        self.assertEqual(set(pads) | set(func), {palette.OFF})
        self.assertEqual(self.disp._seg.text, "    ")


if __name__ == "__main__":
    unittest.main()
