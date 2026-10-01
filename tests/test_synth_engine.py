"""SynthEngine channel / track volume, and how it survives ASSIGN and grooves."""

import unittest

import fakes  # noqa: F401  (installs the CircuitPython fakes first)

from synth_engine import SynthEngine

KIT_LAYER  = 0   # default layer 0 = KIT
BASS_LAYER = 1   # default layer 1 = BASS (melodic)


def kit_amplitudes(engine, layer):
    return [s["note"].amplitude for s in engine._channels[layer]["data"]]


def kit_expected(engine, layer, gain):
    return [s["params"]["amp"] * gain for s in engine._channels[layer]["data"]]


class ChannelVolumeTest(unittest.TestCase):
    def setUp(self):
        self.engine = SynthEngine()

    def test_defaults_to_full(self):
        for layer in range(8):
            self.assertEqual(self.engine.channel_volume(layer), 100)
        for track in range(8):
            self.assertEqual(self.engine.track_volume(track), 100)

    def test_kit_layer_scales_every_sound(self):
        self.engine.set_channel_volume(KIT_LAYER, 50)
        self.assertEqual(self.engine.channel_volume(KIT_LAYER), 50)
        for got, want in zip(kit_amplitudes(self.engine, KIT_LAYER),
                             kit_expected(self.engine, KIT_LAYER, 0.5)):
            self.assertAlmostEqual(got, want)

    def test_melodic_layer_scales_both_notes(self):
        voice = self.engine._channels[BASS_LAYER]["data"]
        self.engine.set_channel_volume(BASS_LAYER, 40)
        want = voice["params"]["amp"] * 0.4
        self.assertAlmostEqual(voice["note"].amplitude, want)
        self.assertAlmostEqual(voice["detune_note"].amplitude, want)

    def test_melodic_tremolo_range_scales(self):
        self.engine.set_channel_param(BASS_LAYER, None, "lfo_depth", 0.5)
        self.engine.set_channel_param(BASS_LAYER, None, "lfo_dest", 2)   # tremolo
        self.engine.set_channel_volume(BASS_LAYER, 50)
        voice = self.engine._channels[BASS_LAYER]["data"]
        amp   = voice["params"]["amp"] * 0.5
        lfo   = voice["lfo"]
        self.assertIs(voice["note"].amplitude, lfo)
        self.assertIs(voice["detune_note"].amplitude, lfo)
        self.assertAlmostEqual(lfo.scale, amp * 0.5 / 2)
        self.assertAlmostEqual(lfo.offset, amp * (1.0 - 0.5 / 2))

    def test_amp_edit_keeps_volume(self):
        self.engine.set_channel_volume(BASS_LAYER, 50)
        self.engine.set_channel_param(BASS_LAYER, None, "amp", 0.6)
        voice = self.engine._channels[BASS_LAYER]["data"]
        self.assertAlmostEqual(voice["note"].amplitude, 0.3)

    def test_reset_keeps_volume(self):
        self.engine.set_channel_volume(KIT_LAYER, 20)
        self.engine.set_channel_param(KIT_LAYER, 3, "amp", 0.1)
        self.engine.reset_channel(KIT_LAYER, 3)
        sound = self.engine._channels[KIT_LAYER]["data"][3]
        self.assertAlmostEqual(sound["note"].amplitude, sound["defaults"]["amp"] * 0.2)

    def test_volume_is_clamped(self):
        self.engine.set_channel_volume(KIT_LAYER, 150)
        self.assertEqual(self.engine.channel_volume(KIT_LAYER), 100)
        self.engine.set_channel_volume(KIT_LAYER, -5)
        self.assertEqual(self.engine.channel_volume(KIT_LAYER), 0)
        self.assertEqual(kit_amplitudes(self.engine, KIT_LAYER), [0.0] * 8)

    def test_layers_are_independent(self):
        self.engine.set_channel_volume(2, 30)
        self.assertEqual(self.engine.channel_volume(3), 100)
        self.assertEqual(self.engine.track_volume(2), 100)

    def test_track_volume_scales_one_sequencer_sound(self):
        kit = self.engine._sequencer_kit
        self.engine.set_track_volume(2, 40)
        self.assertAlmostEqual(kit[2]["note"].amplitude, kit[2]["params"]["amp"] * 0.4)
        self.assertAlmostEqual(kit[3]["note"].amplitude, kit[3]["params"]["amp"])
        # A loop layer's own kit copy is a different channel.
        self.assertEqual(kit_amplitudes(self.engine, KIT_LAYER),
                         kit_expected(self.engine, KIT_LAYER, 1.0))
        self.engine.set_drum_param(2, "amp", 0.5)
        self.assertAlmostEqual(kit[2]["note"].amplitude, 0.2)
        self.engine.reset_drum(2)
        self.assertAlmostEqual(kit[2]["note"].amplitude, kit[2]["defaults"]["amp"] * 0.4)


class VolumeAcrossAssignTest(unittest.TestCase):
    def setUp(self):
        self.engine = SynthEngine()

    def test_new_instrument_gets_slot_volume(self):
        self.engine.set_channel_volume(BASS_LAYER, 30)
        self.engine.assign_channel(BASS_LAYER, 0)   # BASS -> KIT
        self.assertEqual(self.engine.channel_volume(BASS_LAYER), 30)
        for got, want in zip(kit_amplitudes(self.engine, BASS_LAYER),
                             kit_expected(self.engine, BASS_LAYER, 0.3)):
            self.assertAlmostEqual(got, want)

    def test_restored_instrument_gets_current_volume(self):
        old = self.engine.assign_channel(BASS_LAYER, 0)
        self.engine.set_channel_volume(BASS_LAYER, 60)
        self.engine.restore_channel(BASS_LAYER, old)
        voice = self.engine._channels[BASS_LAYER]["data"]
        self.assertAlmostEqual(voice["note"].amplitude, voice["params"]["amp"] * 0.6)


class VolumeGrooveTest(unittest.TestCase):
    def test_round_trip(self):
        engine = SynthEngine()
        engine.set_channel_volume(KIT_LAYER, 45)
        engine.set_channel_volume(BASS_LAYER, 70)
        engine.set_track_volume(5, 10)
        snap = engine.snapshot_sounds()
        self.assertEqual(snap["layer_vol"][:2], [45, 70])
        self.assertEqual(snap["track_vol"][5], 10)

        fresh = SynthEngine()
        fresh.restore_sounds(snap)
        self.assertEqual(fresh.channel_volume(KIT_LAYER), 45)
        self.assertEqual(fresh.channel_volume(BASS_LAYER), 70)
        self.assertEqual(fresh.track_volume(5), 10)
        for got, want in zip(kit_amplitudes(fresh, KIT_LAYER),
                             kit_expected(fresh, KIT_LAYER, 0.45)):
            self.assertAlmostEqual(got, want)
        voice = fresh._channels[BASS_LAYER]["data"]
        self.assertAlmostEqual(voice["note"].amplitude, voice["params"]["amp"] * 0.7)
        kit = fresh._sequencer_kit
        self.assertAlmostEqual(kit[5]["note"].amplitude, kit[5]["params"]["amp"] * 0.1)

    def test_groove_without_volumes_loads_at_full(self):
        engine = SynthEngine()
        engine.set_channel_volume(KIT_LAYER, 45)
        engine.set_track_volume(0, 10)
        snap = engine.snapshot_sounds()
        del snap["layer_vol"], snap["track_vol"]
        engine.restore_sounds(snap)
        self.assertEqual(engine.channel_volume(KIT_LAYER), 100)
        self.assertEqual(engine.track_volume(0), 100)
        self.assertAlmostEqual(engine._sequencer_kit[0]["note"].amplitude,
                               engine._sequencer_kit[0]["params"]["amp"])

    def test_malformed_volumes_are_tolerated(self):
        engine = SynthEngine()
        engine.restore_sounds({"layer_vol": [250, -3, "x", None, 55.0],
                               "track_vol": "nope"})
        self.assertEqual([engine.channel_volume(i) for i in range(6)],
                         [100, 0, 100, 100, 55, 100])
        self.assertEqual(engine.track_volume(0), 100)


if __name__ == "__main__":
    unittest.main()
