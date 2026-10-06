"""
The 16-pad grid: the 16-sound kit, melodic notes rising from the bottom
left, the looper and sequencer on all 16 pads, the pad LEDs clear of the
status keys, and v1 (8-pad) grooves converted on load.
"""

import json
import os
import unittest

import fakes  # noqa: F401  (installs the CircuitPython fakes first)

import config
import groove
import keymap
import palette
import sound_presets
import synth_params
from config import BTN_MENU, BTN_INC, BTN_RECORD, BTN_MODE, BTN_PLAY_STOP, BTN_VIEW
from harness import Harness, run
from synth_engine import SynthEngine

KIT_LAYER  = 0
BASS_LAYER = 1
LOAD_ITEM  = 6   # LOAD's place in the menu's root list


def kit_note(h, layer, pad):
    return h.synth._channels[layer]["data"][pad]["note"]


def presses(h, note):
    return h.synth._synth.press_log.count(note)


def switch_mode(h):
    yield from h.hold(BTN_MODE, 0.7)


def load_slot(h, slot):
    yield from h.tap(BTN_MENU)
    yield from h.taps(BTN_INC, LOAD_ITEM)
    yield from h.tap(BTN_MENU)
    yield from h.taps(BTN_INC, slot)
    assert h.text == f"L{slot + 1:02d}*", h.text
    yield from h.tap(BTN_MENU)
    assert h.text == "DONE", h.text


class KitTest(unittest.TestCase):
    def test_sixteen_distinct_sounds(self):
        kit = sound_presets.build_kit_instance()
        names = [sound["name"] for sound in kit]
        self.assertEqual(len(kit), 16)
        self.assertEqual(len(set(names)), 16, names)
        self.assertEqual(names[:8], ["KICK", "DNBK", "CHH ", "OHH ",
                                     "SNRE", "CLAP", "COWB", "WOOD"])
        for name in names:
            self.assertEqual(len(name), 4, name)

    def test_new_sounds_start_inside_the_editor_ranges(self):
        # Otherwise a first SOUND edit would jump the value to a range end.
        ranges = {e["key"]: (e["lo"], e["hi"])
                  for e in synth_params.DRUM_PARAM_SCHEMA if e["kind"] == "continuous"}
        for sound in sound_presets.build_kit_instance()[8:]:
            for key, value in sound["params"].items():
                lo, hi = ranges[key]
                if key == "ring" and value == 0:
                    continue
                self.assertTrue(lo <= value <= hi, (sound["name"], key, value))

    def test_sequencer_keeps_eight_tracks(self):
        engine = SynthEngine()
        self.assertEqual(len(engine._sequencer_kit), config.NUM_TRACKS)
        self.assertEqual(engine.sound_name(7), "WOOD")
        self.assertEqual(len(engine.snapshot_sounds()["track_vol"]), config.NUM_TRACKS)

    def test_kit_layer_plays_all_sixteen(self):
        engine = SynthEngine()
        for pad in range(16):
            engine.trigger_layer_pad(KIT_LAYER, pad)
        notes = [s["note"] for s in engine._channels[KIT_LAYER]["data"]]
        for note in notes:
            self.assertIn(note, engine._synth.press_log)


class MelodicLayoutTest(unittest.TestCase):
    def test_notes_rise_from_bottom_left(self):
        self.assertEqual(keymap.NOTE_OF_PAD[12], 0)     # bottom left: the root
        self.assertEqual(keymap.NOTE_OF_PAD[15], 3)     # along the bottom row
        self.assertEqual(keymap.NOTE_OF_PAD[8], 4)      # then up a row
        self.assertEqual(keymap.NOTE_OF_PAD[3], 15)     # top right: the highest
        for note in range(16):
            self.assertEqual(keymap.NOTE_OF_PAD[keymap.PAD_OF_NOTE[note]], note)

    def test_three_octaves_of_pentatonic(self):
        engine = SynthEngine()
        voice = engine._channels[BASS_LAYER]["data"]    # root A1, 55 Hz
        by_note = [voice["scale"][keymap.PAD_OF_NOTE[n]] for n in range(16)]
        self.assertAlmostEqual(by_note[0], 55.0)
        self.assertAlmostEqual(by_note[5], 110.0)
        self.assertAlmostEqual(by_note[15], 440.0)
        self.assertEqual(by_note, sorted(by_note))
        engine.trigger_layer_pad(BASS_LAYER, 12)
        self.assertAlmostEqual(voice["note"].frequency, 55.0)
        engine.trigger_layer_pad(BASS_LAYER, 3)
        self.assertAlmostEqual(voice["note"].frequency, 440.0)


class LooperSixteenPadTest(unittest.TestCase):
    def test_record_play_and_mirror_on_the_bottom_rows(self):
        def scenario(h):
            yield from h.tap(BTN_RECORD)                  # freeform arm
            yield from h.pad_tap(15)                      # starts the take
            yield 0.2
            yield from h.pad_tap(8)
            yield 0.3
            yield from h.tap(BTN_RECORD)                  # commit: plays
            layer = h.looper._layers[KIT_LAYER]
            assert [pad for _, pad in layer.events] == [15, 8], layer.events
            crash = kit_note(h, KIT_LAYER, 15)
            before = presses(h, crash)
            seen = set()
            for _ in range(120):                          # ~2 passes
                seen.add(h.pad_color(15))
                yield 0.01
            assert presses(h, crash) >= before + 2
            assert palette.PLAYBACK in seen, "playback lights pad 16"

            yield from h.tap(BTN_MENU)
            yield from h.taps(BTN_INC, 4)
            assert h.text == "MIRR"
            yield from h.tap(BTN_MENU)
            assert h.text == "DONE"
            assert sorted(pad for _, pad in layer.events) == [8, 8, 15, 15], layer.events
        run(scenario)

    def test_melodic_layer_records_its_notes(self):
        def scenario(h):
            yield from h.tap(BTN_VIEW)                    # channel view: layer 2 (BASS)
            yield from h.pad_tap(BASS_LAYER)
            voice = h.synth._channels[BASS_LAYER]["data"]
            yield from h.tap(BTN_RECORD)
            h.pad_down(3)                                 # top right: 3 octaves up
            yield 0.05
            assert abs(voice["note"].frequency - 440.0) < 1e-6
            h.pad_up(3)
            yield 0.3
            yield from h.tap(BTN_RECORD)
            layer = h.looper._layers[BASS_LAYER]
            assert [pad for _, pad in layer.events] == [3]
            assert [pad for _, pad in layer.releases] == [3]
        run(scenario)


class SequencerSixteenStepTest(unittest.TestCase):
    def test_every_pad_is_a_step_of_the_bar(self):
        def scenario(h):
            yield from switch_mode(h)
            for pad in (0, 9, 15):
                yield from h.pad_tap(pad)
            assert [s for s, on in enumerate(h.seq._grid[0]) if on] == [0, 9, 15]
            assert h.pad_color(15) == palette.HAS_CONTENT
            assert h.pad_color(14) == palette.OFF
            assert h.text == "T1  "
            yield from h.tap(BTN_RECORD)                  # no page toggle any more
            assert [s for s, on in enumerate(h.seq._grid[0]) if on] == [0, 9, 15]
            assert h.text == "T1  "
        run(scenario)

    def test_plays_all_sixteen_steps(self):
        def scenario(h):
            yield from switch_mode(h)
            yield from h.pad_tap(15)
            kick = h.synth._sequencer_kit[0]["note"]
            fired = []
            h.synth._synth.press_log.clear()
            yield from h.tap(BTN_PLAY_STOP)
            for _ in range(250):                          # 120 BPM: a bar is 2 s
                if h.synth._synth.press_log.count(kick) > len(fired):
                    fired.append(h.seq.current_step)
                yield 0.01
            assert fired == [15], fired
            assert h.seq.playing
        run(scenario)

    def test_bottom_row_steps_leave_the_status_keys_alone(self):
        # Pads 9-11 once shared bits with RECORD / PLAY / the beat.
        def scenario(h):
            yield from switch_mode(h)
            for pad in range(8, 16):
                yield from h.pad_tap(pad)
            assert h.key_color(BTN_RECORD) == palette.OFF
            assert h.key_color(BTN_PLAY_STOP) == palette.OFF
            for pad in range(8, 16):
                assert h.pad_color(pad) == palette.HAS_CONTENT, pad
        run(scenario)


class GrooveVersionTest(unittest.TestCase):
    def write_v1(self, h, slot):
        os.makedirs(h.groove_dir, exist_ok=True)
        layer = {"dur": 0.5, "muted": False}
        data = {
            "v": 1, "bpm": 120, "sync": "freeform",
            "sounds": {"kit": [], "layers": [{"id": 0}, {"id": 1}]},
            "loop": {"master": 0.5, "layers": [
                dict(layer, on=[[0.0, 3]], off=[]),                         # kit
                dict(layer, on=[[0.0, 0], [0.1, 7]], off=[[0.05, 0]]),      # BASS
            ]},
        }
        with open(f"{h.groove_dir}/slot{slot + 1}.json", "w") as f:
            json.dump(data, f)

    def test_v1_melodic_notes_move_to_their_new_pads(self):
        h = Harness()
        self.write_v1(h, 0)

        def scenario(h):
            yield from load_slot(h, 0)
            kit, bass = h.looper._layers[0], h.looper._layers[1]
            assert kit.events == [(0.0, 3)], kit.events            # kit: unchanged
            assert bass.events == [(0.0, 12), (0.1, 11)], bass.events
            assert bass.releases == [(0.05, 12)], bass.releases
            voice = h.synth._channels[1]["data"]
            assert abs(voice["scale"][12] - 55.0) < 1e-6           # old pad 1's note
        h.run(scenario)

    def test_saves_v2_and_reloads_unchanged(self):
        h = Harness()
        self.write_v1(h, 0)

        def scenario(h):
            yield from load_slot(h, 0)
            yield 0.7
            yield from h.tap(BTN_RECORD)                  # close the menu
            groove.save(1, h.menu._capture_groove())
            with open(f"{h.groove_dir}/slot2.json") as f:
                assert json.load(f)["v"] == groove.VERSION == 2
            yield from load_slot(h, 1)
            bass = h.looper._layers[1]
            assert bass.events == [(0.0, 12), (0.1, 11)], bass.events
        h.run(scenario)


if __name__ == "__main__":
    unittest.main()
