"""game_intro.py: ECHO's startup -- the call, its fading echoes, the rings,
and skipping."""

import unittest

import fakes

import config
from core import display
from echo import game_intro
from core import keymap, palette
from core.display import DisplayManager
from core.event_types import BTN_DOWN, BTN_UP, PAD_DOWN

LAYER, VOLUME = 5, 80


class FakeHw:
    """scan() returns `events` on call number `on` (never, by default)."""

    def __init__(self, on=None, events=()):
        self.calls  = 0
        self.on     = on
        self.events = list(events)

    def scan(self):
        self.calls += 1
        return self.events if self.calls == self.on else ()


class FakeSound:
    def __init__(self):
        self.volume = None
        self.log    = []   # (time, "on" / "off", pad, volume then)

    def set_channel_volume(self, layer, pct):
        assert layer == LAYER
        self.volume = pct

    def trigger_layer_pad(self, layer, pad):
        assert layer == LAYER
        self.log.append((fakes.CLOCK.t, "on", pad, self.volume))

    def release_layer_pad(self, layer, pad):
        self.log.append((fakes.CLOCK.t, "off", pad, self.volume))

    def update(self, now):
        pass


class IntroTest(unittest.TestCase):
    def setUp(self):
        fakes.CLOCK.t = 0.0
        self._sleep = game_intro.time.sleep
        game_intro.time.sleep = self.fake_sleep
        self.disp  = DisplayManager(object())
        self.sound = FakeSound()
        self.pads  = self.disp.pixels._pads.pixels
        self.func  = self.disp.pixels._func.pixels
        self.frames = []        # (pad colors, function colors) per frame sent
        self.levels = []        # every display brightness set
        update, set_brightness = self.disp.update, self.disp.set_brightness

        def recording_update(now=None):
            update(now)
            self.frames.append((list(self.pads.shown), list(self.func.shown)))

        def recording_brightness(level):
            set_brightness(level)
            self.levels.append(level)

        self.disp.update = recording_update
        self.disp.set_brightness = recording_brightness

    def tearDown(self):
        game_intro.time.sleep = self._sleep

    def fake_sleep(self, seconds):
        fakes.CLOCK.t += seconds

    def run_intro(self, hw=None):
        game_intro.run(hw or FakeHw(), self.disp, self.sound, LAYER, VOLUME)

    def ons(self):
        return [(t, pad, volume) for t, kind, pad, volume in self.sound.log if kind == "on"]

    def test_the_call_and_three_fainter_echoes(self):
        self.run_intro()
        ons = self.ons()
        pads = [keymap.PAD_OF_NOTE[note] for note in game_intro.MOTIF]
        self.assertEqual([pad for _, pad, _ in ons], pads * 4)
        volumes = [volume for _, _, volume in ons]
        self.assertEqual(volumes, [round(VOLUME * level) for level in game_intro.LEVELS
                                   for _ in pads])
        self.assertEqual(sorted(set(volumes), reverse=True), [80, 40, 20, 10])
        for (t, _, _), (due, _, _) in zip(ons, game_intro.schedule()):
            self.assertAlmostEqual(t, due, delta=game_intro.FRAME_DELAY + 0.001)

    def test_it_types_the_name_then_dims_with_the_echoes(self):
        self.run_intro()
        history = self.disp._seg.history
        for text in game_intro.TEXT:
            self.assertIn(text, history)
        self.assertLess(history.index("E   "), history.index("ECHO"))
        want = [display.BRIGHTNESS * level for level in game_intro.LEVELS]
        self.assertEqual(self.levels, want + [display.BRIGHTNESS])

    def test_rings_reach_every_key_in_both_colours(self):
        self.run_intro()
        for strip in (0, 1):
            for pixel in range(len(self.frames[0][strip])):
                seen = {frame[strip][pixel] for frame in self.frames} - {palette.OFF}
                self.assertGreater(len(seen), 3, (strip, pixel))
        # A ring starts at its pad: the root's pad lights before the far
        # corner of the function block.
        root = keymap.PAD_PIXEL[keymap.PAD_OF_NOTE[0]]
        far  = config.FUNC_PIXELS[0][1]
        first_root = next(i for i, (pads, _) in enumerate(self.frames) if pads[root] != palette.OFF)
        first_far  = next(i for i, (_, func) in enumerate(self.frames) if func[far] != palette.OFF)
        self.assertLess(first_root, first_far)
        # The call's rings are cyan-ish (more blue than red).
        pads, _ = self.frames[first_root]
        self.assertGreater(pads[root][2], pads[root][0])

    def test_it_ends_dark_blank_and_put_back(self):
        self.run_intro()
        pads, func = self.frames[-1]
        self.assertEqual(set(pads) | set(func), {palette.OFF})
        self.assertEqual(self.disp._seg.text, "    ")
        self.assertEqual(self.sound.volume, VOLUME)
        self.assertEqual(self.sound.log[-1][1], "off")   # the last note let go
        last = game_intro.schedule()[-1][0]
        self.assertGreater(fakes.CLOCK.t, last + 0.5)    # the rings faded out
        self.assertLess(fakes.CLOCK.t, 5.0)

    def test_a_press_skips_it(self):
        for event in ((PAD_DOWN, 3, 0.0), (BTN_DOWN, config.BTN_PLAY_STOP, 0.0)):
            fakes.CLOCK.t = 0.0
            self.sound.log.clear()
            self.run_intro(FakeHw(on=5, events=[event]))
            self.assertLess(fakes.CLOCK.t, 0.2)
            pads, func = self.frames[-1]
            self.assertEqual(set(pads) | set(func), {palette.OFF})
            self.assertEqual(self.sound.volume, VOLUME)
            self.assertEqual(self.levels[-1], display.BRIGHTNESS)

    def test_letting_go_of_menu_doesnt_skip_it(self):
        self.run_intro(FakeHw(on=5, events=[(BTN_UP, config.BTN_MENU, 0.0)]))
        self.assertEqual(len(self.ons()), 16)


if __name__ == "__main__":
    unittest.main()
