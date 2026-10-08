"""
The melodic key and scale (scales.py, the menu's KEY / SCAL): each pad's
pitch in every key and scale, the root guide lights, live re-voicing of
recorded loops, and grooves saving them (older grooves load in A minor
pentatonic).
"""

import json
import unittest

import fakes  # installs the CircuitPython fakes first

import config
import groove
import keymap
import palette
import scales
import sound_presets
from config import BTN_MENU, BTN_INC, BTN_DEC, BTN_RECORD, BTN_VIEW
from harness import Harness, run
from synth_engine import SynthEngine

BASS_LAYER = 1
KEY_ITEM   = 4   # KEY's place in the menu's root list; SCAL follows it
SAVE_ITEM  = 8
LOAD_ITEM  = 9


def expected(key, scale, pad):
    """A pad's pitch at octave 0, worked out the long way."""
    steps = scales.SCALES[scale][1]
    note  = keymap.NOTE_OF_PAD[pad]
    semis = (scales.root_offset(key) + steps[note % len(steps)]
             + 12 * (note // len(steps)))
    return 55.0 * 2 ** (semis / 12)


class PitchTableTest(unittest.TestCase):
    def test_every_key_and_scale(self):
        engine = SynthEngine()
        pitches = engine._pad_pitch
        for key in range(12):
            for scale in range(len(scales.SCALES)):
                engine.set_tuning(key, scale)
                self.assertIs(engine._pad_pitch, pitches)   # rewritten in place
                for pad in range(16):
                    self.assertAlmostEqual(engine.pad_frequency(BASS_LAYER, pad),
                                           expected(key, scale, pad), places=2)
                by_note = [pitches[keymap.PAD_OF_NOTE[n]] for n in range(16)]
                self.assertEqual(by_note, sorted(by_note))

    def test_default_is_a_minor_pentatonic(self):
        engine = SynthEngine()
        self.assertEqual(scales.KEY_NAMES[engine.key], "A   ")
        self.assertEqual(scales.SCALES[engine.scale][0], "MINP")
        self.assertAlmostEqual(engine.pad_frequency(BASS_LAYER, 12), 55.0)

    def test_keys_stay_nearest_a(self):
        offsets = [scales.root_offset(key) for key in range(12)]
        self.assertEqual(sorted(offsets), list(range(-5, 7)))
        self.assertEqual(scales.root_offset(scales.DEFAULT_KEY), 0)

    def test_every_voice_stays_under_nyquist(self):
        ceiling = config.SAMPLE_RATE / 2
        top = max(spec[2] for spec in sound_presets.MELODIC_VOICE_SPECS)
        for key in range(12):
            for scale in range(len(scales.SCALES)):
                highest = max(expected(key, scale, pad) for pad in range(16))
                self.assertLess(highest * 2 ** top, ceiling,
                                (scales.KEY_NAMES[key], scales.SCALES[scale][0]))

    def test_seven_note_modes_span_two_octaves_and_a_bit(self):
        engine = SynthEngine()
        engine.set_tuning(scales.DEFAULT_KEY, 3)          # DOR
        low  = engine.pad_frequency(BASS_LAYER, keymap.PAD_OF_NOTE[0])
        high = engine.pad_frequency(BASS_LAYER, keymap.PAD_OF_NOTE[14])
        self.assertAlmostEqual(high / low, 4.0, places=3)  # degree 14: two octaves up


class RootMaskTest(unittest.TestCase):
    def test_pentatonic_roots_are_a_diagonal(self):
        self.assertEqual(scales.root_mask(0), sum(1 << p for p in (12, 9, 6, 3)))

    def test_seven_note_roots(self):
        pads = [keymap.PAD_OF_NOTE[n] for n in (0, 7, 14)]
        self.assertEqual(scales.root_mask(3), sum(1 << p for p in pads))

    def test_engine_follows_the_scale(self):
        engine = SynthEngine()
        engine.set_tuning(0, 6)
        self.assertEqual(engine.root_mask, scales.root_mask(6))


ROOT_LABELS = ["SND ", "ASGN", "ARP ", "BPM ", "KEY ", "SCAL", "EXT ", "MIRR",
               "SAVE", "LOAD", "AUT "]


def open_item(h, index):
    yield from h.open_menu_at(ROOT_LABELS[index])
    yield from h.tap(BTN_MENU)


class MenuTest(unittest.TestCase):
    def test_key_steps_and_wraps(self):
        def scenario(h):
            yield from h.tap(BTN_MENU)
            yield from h.taps(BTN_INC, KEY_ITEM)
            assert h.text == "KEY ", h.text
            yield from h.tap(BTN_MENU)
            assert h.text == "A   ", h.text
            yield from h.tap(BTN_INC)
            assert h.text == "A#  " and h.synth.key == 10, h.text
            yield from h.taps(BTN_INC, 2)
            assert h.text == "C   " and h.synth.key == 0, h.text   # wrapped
            yield from h.tap(BTN_RECORD)
            assert h.text == "KEY ", h.text                        # back to root
        run(scenario)

    def test_scale_steps_and_wraps(self):
        def scenario(h):
            yield from h.tap(BTN_MENU)
            yield from h.taps(BTN_INC, KEY_ITEM + 1)
            assert h.text == "SCAL", h.text
            yield from h.tap(BTN_MENU)
            assert h.text == "MINP", h.text
            yield from h.tap(BTN_DEC)
            assert h.text == "HMIN", h.text                        # wrapped
            assert h.synth.scale == len(scales.SCALES) - 1
            yield from h.tap(BTN_MENU)
            assert h.text == "SCAL", h.text                        # MENU returns too
        run(scenario)

    def test_root_lights_follow_the_scale(self):
        def scenario(h):
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(BASS_LAYER)
            yield from open_item(h, KEY_ITEM + 1)
            yield from h.taps(BTN_INC, 3)                          # DOR
            yield 0.05
            roots = {pad for pad in range(16) if h.pad_color(pad) == palette.ROOT_NOTE}
            assert roots == {keymap.PAD_OF_NOTE[n] for n in (0, 7, 14)}, roots
        run(scenario)

    def test_a_recorded_loop_follows_a_key_change(self):
        def scenario(h):
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(BASS_LAYER)
            yield from h.tap(BTN_RECORD)
            yield from h.pad_tap(12)                               # the root
            yield 0.4
            yield from h.tap(BTN_RECORD)                           # commit: playing
            before = list(h.looper._layers[BASS_LAYER].events.pad)
            yield from open_item(h, KEY_ITEM)
            yield from h.tap(BTN_INC)                              # A -> A#
            yield 1.0                                              # a pass or two
            voice = h.synth._channels[BASS_LAYER]["data"]
            wave  = voice["params"]["wave"]
            freq  = (fakes.live_pair(voice)["note"].frequency
                     * sound_presets.WAVEFORM_DIVISORS[wave])
            assert abs(freq - 55.0 * 2 ** (1 / 12)) < 0.01, freq
            assert list(h.looper._layers[BASS_LAYER].events.pad) == before
        run(scenario)


class GrooveTest(unittest.TestCase):
    def test_saved_and_loaded(self):
        def scenario(h):
            yield from open_item(h, KEY_ITEM)
            yield from h.taps(BTN_DEC, 2)                          # G
            yield from h.tap(BTN_RECORD)
            yield from h.tap(BTN_INC)                              # SCAL
            yield from h.tap(BTN_MENU)
            yield from h.taps(BTN_INC, 5)                          # PHRY
            yield from h.tap(BTN_RECORD)
            yield from h.tap(BTN_RECORD)                           # close
            yield from open_item(h, SAVE_ITEM)
            yield from h.tap(BTN_MENU)
            yield 0.1                                     # the fade before the file work
            assert h.text == "DONE", h.text
            with open(f"{h.groove_dir}/slot1.json") as f:
                saved = json.load(f)
            assert saved["v"] == groove.VERSION == 4
            assert (saved["sounds"]["key"], saved["sounds"]["scale"]) == (7, 5)
            h.synth.set_tuning(scales.DEFAULT_KEY, scales.DEFAULT_SCALE)
            yield 1.0                                              # the menu closed itself
            yield from open_item(h, LOAD_ITEM)
            yield from h.tap(BTN_MENU)
            yield 0.1                                     # the fade before the file work
            assert h.text == "DONE", h.text
            assert (h.synth.key, h.synth.scale) == (7, 5)
        run(scenario)

    def test_older_grooves_load_in_a_minor_pentatonic(self):
        h = Harness()
        with open(f"{h.groove_dir}/slot1.json", "w") as f:
            json.dump({"v": 3, "bpm": 120, "sync": "none", "sounds": {}}, f)

        def scenario(h):
            h.synth.set_tuning(2, 4)                               # D aeolian
            yield from open_item(h, LOAD_ITEM)
            yield from h.tap(BTN_MENU)
            yield 0.1                                     # the fade before the file work
            assert h.text == "DONE", h.text
            assert (h.synth.key, h.synth.scale) == (scales.DEFAULT_KEY,
                                                    scales.DEFAULT_SCALE)
        h.run(scenario)

    def test_a_bad_value_loads_the_default(self):
        engine = SynthEngine()
        engine.restore_sounds({"key": 40, "scale": "DOR"})
        self.assertEqual((engine.key, engine.scale),
                         (scales.DEFAULT_KEY, scales.DEFAULT_SCALE))


if __name__ == "__main__":
    unittest.main()
