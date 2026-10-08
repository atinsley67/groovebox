"""Kit sound lengths, retriggers, chokes and amplitude shapes, the v2 groove upgrade,
the melodic voices' wave divisors, pitch envelope, glide and retriggers."""

import math
import unittest

import fakes

import config
import sound_presets
import synth_engine
import synth_params
from sound_presets import voice_notes
from synth_engine import SynthEngine

KIT_LAYER = 0
CHH, OHH, CLAP, RIDE, CRSH = 2, 3, 5, 14, 15

# What each kit sound always really played at before v3 (its release time),
# for the sounds that weren't rebuilt.
_V2_LENGTHS = {0: 0.03, 1: 0.015, 4: 0.02, 6: 0.05, 7: 0.01, 8: 0.03,
               9: 0.03, 10: 0.03, 11: 0.005, 13: 0.02}


def instrument_id(name):
    return sound_presets.INSTRUMENT_NAMES.index(name)


def lfo_block_values(lfo, blocks):
    """What synthio's LFO tick (shared-module/synthio/LFO.c) yields for a
    retriggered one-shot LFO over its first `blocks` blocks."""
    almost_one = 32767 / 32768
    per_block  = lfo.rate * 256 / config.SAMPLE_RATE
    table      = lfo.waveform
    accum, out = 0.0, []
    for _ in range(blocks):
        accum = min(accum + per_block, almost_one)
        idx = int(math.floor(accum * (len(table) - 1)))
        out.append(round(table[idx] / 32767, 2))
    return out


def live(sound):
    """The Note a kit sound's last hit played on (or will next fade)."""
    return sound["notes"][sound["live"]]


class KitLengthTest(unittest.TestCase):
    def setUp(self):
        self.engine = SynthEngine()
        self.kit = self.engine._channels[KIT_LAYER]["data"]

    def test_untouched_sounds_keep_their_real_length(self):
        for pad, length in _V2_LENGTHS.items():
            sound = self.kit[pad]
            self.assertAlmostEqual(sound["params"]["decay"], length, msg=pad)
            for note in sound["notes"]:
                self.assertAlmostEqual(note.envelope.release_time, length, msg=pad)

    def test_dec_sets_the_release(self):
        self.engine.set_channel_param(KIT_LAYER, 0, "decay", 0.4)
        env = live(self.kit[0]).envelope
        self.assertAlmostEqual(env.release_time, 0.4)
        self.assertAlmostEqual(env.decay_time, 0.4)
        self.engine.trigger_layer_pad(KIT_LAYER, 0)            # the next hit has it
        self.assertAlmostEqual(live(self.kit[0]).envelope.release_time, 0.4)
        self.engine.set_drum_param(0, "decay", 0.25)          # sequencer kit too
        self.assertAlmostEqual(live(self.engine._sequencer_kit[0]).envelope.release_time, 0.25)

    def test_dec_range_reaches_the_crash(self):
        dec = next(e for e in synth_params.DRUM_PARAM_SCHEMA if e["key"] == "decay")
        for sound in self.kit:
            self.assertGreaterEqual(sound["params"]["decay"], dec["lo"], sound["name"])
            self.assertLessEqual(sound["params"]["decay"], dec["hi"], sound["name"])
        self.assertGreaterEqual(self.kit[CRSH]["params"]["decay"], 2.0)

    def test_long_noise_plays_one_sample_per_sample(self):
        for pad in (CHH, OHH, CLAP, 12, RIDE, CRSH):
            for note in self.kit[pad]["notes"]:
                self.assertGreaterEqual(len(note.waveform), 4096, pad)
                self.assertAlmostEqual(note.frequency * len(note.waveform),
                                       config.SAMPLE_RATE, msg=pad)

    def test_edits_reach_both_notes(self):
        self.engine.set_channel_param(KIT_LAYER, 0, "tune", 70.0)
        self.engine.set_channel_param(KIT_LAYER, 0, "cutoff", 900.0)
        for note in self.kit[0]["notes"]:
            self.assertEqual(note.frequency, 70.0)
            self.assertEqual(note.filter.frequency, 900.0)


class RetriggerTest(unittest.TestCase):
    """A hit while the last is still ringing starts fresh, on the other Note."""

    def setUp(self):
        self.engine = SynthEngine()
        self.kit = self.engine._channels[KIT_LAYER]["data"]
        self.log = self.engine._synth.press_log

    def test_hits_alternate_notes(self):
        crash = self.kit[CRSH]
        a, b = crash["notes"]
        for _ in range(3):
            self.engine.trigger_layer_pad(KIT_LAYER, CRSH)
        self.assertEqual(self.log, [a, b, a])

    def test_last_hit_fades_new_hit_is_full(self):
        crash = self.kit[CRSH]
        a, b = crash["notes"]
        self.engine.trigger_layer_pad(KIT_LAYER, CRSH)
        self.engine.trigger_layer_pad(KIT_LAYER, CRSH)
        self.assertIs(a.envelope, synth_engine._CHOKE_ENVELOPE)
        self.assertIs(b.envelope, crash["envelope"])
        self.engine.trigger_layer_pad(KIT_LAYER, CRSH)
        self.assertIs(a.envelope, crash["envelope"])
        self.assertIs(b.envelope, synth_engine._CHOKE_ENVELOPE)

    def test_each_note_has_its_own_lfos(self):
        kick = self.kit[0]
        for note, lfo in zip(kick["notes"], kick["bend_lfos"]):
            self.assertIs(note.bend, lfo)
        self.assertIsNot(*kick["bend_lfos"])
        self.engine.trigger_layer_pad(KIT_LAYER, 0)
        self.assertEqual([l.retriggers for l in kick["bend_lfos"]], [1, 0])
        self.engine.trigger_layer_pad(KIT_LAYER, 0)
        self.assertEqual([l.retriggers for l in kick["bend_lfos"]], [1, 1])

    def test_silencing_releases_both_notes(self):
        self.engine.trigger_layer_pad(KIT_LAYER, CRSH)
        self.engine.trigger_layer_pad(KIT_LAYER, CRSH)
        self.engine.assign_channel(KIT_LAYER, 1)
        for note in self.kit[CRSH]["notes"]:
            self.assertNotIn(note, self.engine._synth.pressed)


class AmpShapeTest(unittest.TestCase):
    def setUp(self):
        self.engine = SynthEngine()
        self.kit = self.engine._channels[KIT_LAYER]["data"]

    def test_shape_retriggers_and_follows_dec(self):
        crash = self.kit[CRSH]
        lfos = crash["amp_lfos"]
        for note, lfo in zip(crash["notes"], lfos):
            self.assertIs(note.amplitude, lfo)
        self.engine.trigger_layer_pad(KIT_LAYER, CRSH)
        self.assertEqual([l.retriggers for l in lfos], [1, 0])
        self.engine.set_channel_param(KIT_LAYER, CRSH, "decay", 2.0)
        for lfo in lfos:
            self.assertAlmostEqual(lfo.rate, 0.5)

    def test_clap_bursts_stay_fixed(self):
        lfos = self.kit[CLAP]["amp_lfos"]
        rate = lfos[0].rate
        self.engine.set_channel_param(KIT_LAYER, CLAP, "decay", 0.5)
        self.assertEqual([l.rate for l in lfos], [rate, rate])

    def test_clap_bursts_land_one_per_block(self):
        self.assertEqual(lfo_block_values(self.kit[CLAP]["amp_lfos"][0], 8),
                         [1.0, 0.12, 0.9, 0.12, 0.85, 0.85, 0.85, 0.85])

    def test_decay_curve_falls_from_full(self):
        values = lfo_block_values(self.kit[RIDE]["amp_lfos"][0], 200)
        self.assertGreater(values[0], 0.9)
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertLess(values[-1], 0.1)


class ChokeTest(unittest.TestCase):
    def setUp(self):
        self.engine = SynthEngine()
        self.kit = self.engine._channels[KIT_LAYER]["data"]

    def test_closed_hat_cuts_the_open_hat(self):
        self.engine.trigger_layer_pad(KIT_LAYER, OHH)
        self.engine.trigger_layer_pad(KIT_LAYER, CHH)
        ohh = self.kit[OHH]
        self.assertAlmostEqual(live(ohh).envelope.release_time,
                               synth_engine._CHOKE_RELEASE)
        self.engine.trigger_layer_pad(KIT_LAYER, OHH)          # its own tail again
        self.assertIs(live(ohh).envelope, ohh["envelope"])
        self.assertAlmostEqual(live(ohh).envelope.release_time,
                               ohh["params"]["decay"])

    def test_dec_edit_while_choked_lands_on_next_hit(self):
        self.engine.trigger_layer_pad(KIT_LAYER, CHH)
        self.engine.set_channel_param(KIT_LAYER, OHH, "decay", 0.8)
        self.assertAlmostEqual(live(self.kit[OHH]).envelope.release_time,
                               synth_engine._CHOKE_RELEASE)
        self.engine.trigger_layer_pad(KIT_LAYER, OHH)
        self.assertAlmostEqual(live(self.kit[OHH]).envelope.release_time, 0.8)

    def test_other_sounds_unaffected(self):
        self.engine.trigger_layer_pad(KIT_LAYER, 0)
        self.engine.trigger_layer_pad(KIT_LAYER, CHH)
        self.assertIs(live(self.kit[0]).envelope, self.kit[0]["envelope"])


class LegacyGrooveTest(unittest.TestCase):
    def saved_kit(self):
        kit = [dict(s["params"]) for s in sound_presets.build_kit_instance()]
        for params in kit:
            params["decay"] = 0.9       # an old, never-heard DEC
            params["amp"] = 0.5
        kit[CRSH]["tune"] = 9000.0      # the old crash's pitch
        return kit

    def test_v2_kit_is_upgraded(self):
        engine = SynthEngine()
        saved = self.saved_kit()
        engine.restore_sounds({"kit": saved[:8],
                               "layers": [{"id": 0, "params": saved}]},
                              legacy_kit=True)
        for kit in (engine._sequencer_kit, engine._channels[KIT_LAYER]["data"]):
            for pad, sound in enumerate(kit):
                self.assertEqual(sound["params"]["decay"], sound["defaults"]["decay"], pad)
                self.assertEqual(sound["params"]["amp"], 0.5, pad)
        crash = engine._channels[KIT_LAYER]["data"][CRSH]
        self.assertEqual(crash["params"]["tune"], crash["defaults"]["tune"])

    def test_v3_kit_loads_as_saved(self):
        engine = SynthEngine()
        saved = self.saved_kit()
        engine.restore_sounds({"layers": [{"id": 0, "params": saved}]})
        crash = engine._channels[KIT_LAYER]["data"][CRSH]
        self.assertEqual(crash["params"]["decay"], 0.9)
        self.assertEqual(crash["params"]["tune"], 9000.0)


class WaveTableTest(unittest.TestCase):
    def test_tables_line_up_with_the_editor(self):
        self.assertEqual(len(sound_presets.WAVEFORM_TABLES), synth_params.NUM_WAVEFORMS)
        self.assertEqual(len(sound_presets.WAVEFORM_DIVISORS), synth_params.NUM_WAVEFORMS)
        for name in synth_params.WAVEFORM_NAMES:
            self.assertEqual(len(name), 4)

    def test_every_table_fits_int16(self):
        tables = list(sound_presets.WAVEFORM_TABLES) + [
            sound_presets._NOISE, sound_presets._CYMBAL, sound_presets._RIDE,
            sound_presets._SHORT_NOISE]
        for table in tables:
            self.assertTrue(all(-32768 <= v <= 32767 for v in table))
            self.assertLessEqual(len(table), 16384)   # synthio.waveform_max_length

    def test_sixteen_instruments(self):
        names = sound_presets.INSTRUMENT_NAMES
        self.assertEqual(len(names), 16)
        self.assertEqual(len(set(names)), 16)
        for name in names:
            self.assertEqual(len(name), 4, name)


class MelodicVoiceTest(unittest.TestCase):
    def setUp(self):
        self.engine = SynthEngine()

    def assign(self, name, layer=1):
        self.engine.assign_channel(layer, instrument_id(name))
        return self.engine._channels[layer]["data"]

    def test_divisor_wave_plays_the_pad_pitch(self):
        voice = self.assign("CHRD")
        self.engine.trigger_layer_pad(1, 12)
        self.assertAlmostEqual(fakes.live_pair(voice)["note"].frequency * 10,
                               self.engine.pad_frequency(1, 12))

    def test_every_voice_sums_its_bend(self):
        for name in sound_presets.INSTRUMENT_NAMES[1:]:
            voice = self.assign(name)
            for pair in voice["pairs"]:
                self.assertIs(pair["note"].bend, pair["bend"], name)
                self.assertIs(pair["detune_note"].bend, pair["bend"], name)
            self.assertIsNot(*(pair["bend"] for pair in voice["pairs"]))

    def test_vibrato_rides_in_the_sum(self):
        voice = self.assign("CHIP")
        for pair in voice["pairs"]:
            self.assertIs(pair["bend"].a, voice["lfo"])

    def test_pitch_envelope_punches_each_hit(self):
        voice = self.assign("JUNG")
        for pair in voice["pairs"]:
            penv = pair["penv_lfo"]
            self.assertIs(pair["bend"].b, penv)
            self.assertAlmostEqual(penv.scale + penv.offset, 7 / 12)   # starts a fifth up
            self.assertAlmostEqual(penv.offset - penv.scale, 0.0)      # lands on the note
        self.engine.trigger_layer_pad(1, 12)
        self.engine.release_layer_pad(1, 12)
        self.engine.trigger_layer_pad(1, 13)                           # not legato
        self.assertEqual([p["penv_lfo"].retriggers for p in voice["pairs"]], [1, 1])
        self.assertEqual(fakes.live_pair(voice)["bend"].c, 0.0)

    def test_legato_glides_without_a_punch(self):
        voice = self.assign("JUNG")
        self.engine.trigger_layer_pad(1, 12)
        self.engine.trigger_layer_pad(1, 13)                           # 12 still held
        pair  = fakes.live_pair(voice)
        glide = pair["glide_lfo"]
        self.assertIs(pair["bend"].c, glide)
        self.assertEqual(pair["penv_lfo"].retriggers, 1)
        start = glide.scale + glide.offset                             # octaves from new to old
        self.assertAlmostEqual(2 ** start * self.engine.pad_frequency(1, 13),
                               self.engine.pad_frequency(1, 12))
        self.assertAlmostEqual(glide.offset - glide.scale, 0.0)

    def test_glide_off_never_slides(self):
        voice = self.assign("BASS")
        self.engine.trigger_layer_pad(1, 12)
        self.engine.trigger_layer_pad(1, 13)
        self.assertEqual(fakes.live_pair(voice)["bend"].c, 0.0)

    def test_penv_off_clears_the_sum(self):
        voice = self.assign("ZAP ")
        self.engine.set_channel_param(1, None, "penv", 0.0)
        for pair in voice["pairs"]:
            self.assertEqual(pair["bend"].b, 0.0)


class MelodicRetriggerTest(unittest.TestCase):
    """A separate note starts fresh on the voice's other pair of Notes; a
    legato one carries on the same pair (and can glide)."""

    def setUp(self):
        self.engine = SynthEngine()
        self.engine.assign_channel(1, instrument_id("JUNG"))
        self.voice = self.engine._channels[1]["data"]
        self.log = self.engine._synth.press_log

    def mains(self):
        return [pair["note"] for pair in self.voice["pairs"]]

    def test_separate_notes_alternate_pairs(self):
        a, b = self.mains()
        for pad in (12, 13, 14):
            self.engine.trigger_layer_pad(1, pad)
            self.engine.release_layer_pad(1, pad)
        self.assertEqual(self.log, [a, b, a])

    def test_last_note_fades_new_note_is_full(self):
        a, b = self.mains()
        self.engine.trigger_layer_pad(1, 12)
        self.engine.release_layer_pad(1, 12)
        self.engine.trigger_layer_pad(1, 13)
        self.assertIs(a.envelope, synth_engine._VOICE_FADE_ENVELOPE)
        self.assertIs(self.voice["pairs"][0]["detune_note"].envelope,
                      synth_engine._VOICE_FADE_ENVELOPE)
        self.assertIs(b.envelope, self.voice["envelope"])

    def test_legato_ties_on_without_a_repress(self):
        a, _ = self.mains()
        self.engine.trigger_layer_pad(1, 12)
        self.engine.trigger_layer_pad(1, 13)                           # 12 still held
        self.engine.trigger_layer_pad(1, 14)
        self.assertEqual(self.log, [a])                                # no jump back to full
        self.assertIn(a, self.engine._synth.pressed)
        self.assertIs(a.envelope, self.voice["envelope"])
        self.assertAlmostEqual(a.frequency, self.engine.pad_frequency(1, 14))
        pair = fakes.live_pair(self.voice)
        self.assertEqual(pair["penv_lfo"].retriggers, 1)               # no re-punch

    def test_tie_without_glide_just_moves_the_pitch(self):
        self.engine.set_channel_param(1, None, "glide", 0.0)
        a, _ = self.mains()
        self.engine.trigger_layer_pad(1, 12)
        self.engine.trigger_layer_pad(1, 13)
        self.assertEqual(self.log, [a])
        pair = fakes.live_pair(self.voice)
        self.assertEqual(pair["bend"].c, 0.0)
        self.assertEqual(pair["penv_lfo"].retriggers, 1)

    def test_tie_restarts_the_hold_window(self):
        fakes.CLOCK.t = 0.0
        self.engine.trigger_layer_pad(1, 12)
        fakes.CLOCK.t = 2.0
        self.engine.trigger_layer_pad(1, 13)                           # tied at 2 s
        fakes.CLOCK.t = 3.5                                            # past the first window
        self.engine.update(fakes.CLOCK.t)
        self.assertIn(self.mains()[0], self.engine._synth.pressed)
        fakes.CLOCK.t = 5.5
        self.engine.update(fakes.CLOCK.t)
        self.assertNotIn(self.mains()[0], self.engine._synth.pressed)

    def test_auto_released_note_is_pressed_again(self):
        a, _ = self.mains()
        fakes.CLOCK.t = 0.0
        self.engine.trigger_layer_pad(1, 12)
        fakes.CLOCK.t = 4.0                                            # past JUNG's hold
        self.engine.update(fakes.CLOCK.t)
        self.engine.trigger_layer_pad(1, 13)                           # 12's pad still down
        self.assertEqual(self.log, [a, a])

    def test_no_sustain_voice_replucks(self):
        self.engine.assign_channel(1, instrument_id("MALL"))
        voice = self.engine._channels[1]["data"]
        a = voice["pairs"][0]["note"]
        self.engine.trigger_layer_pad(1, 12)
        self.engine.trigger_layer_pad(1, 13)
        self.assertEqual(self.log, [a, a])

    def test_detune_switched_on_mid_note_presses_it(self):
        a, _ = self.mains()
        self.engine.trigger_layer_pad(1, 12)
        self.engine.set_channel_param(1, None, "detune", 10.0)
        self.engine.trigger_layer_pad(1, 13)
        detune = self.voice["pairs"][0]["detune_note"]
        self.assertEqual(self.log, [a, a, detune])

    def test_release_lets_go_of_the_live_pair(self):
        self.engine.trigger_layer_pad(1, 12)
        self.engine.release_layer_pad(1, 12)
        self.engine.trigger_layer_pad(1, 13)
        self.engine.release_layer_pad(1, 13)
        for note in voice_notes(self.voice):
            self.assertNotIn(note, self.engine._synth.pressed)

    def test_edit_reaches_the_live_pair_and_the_next(self):
        a, b = self.mains()
        self.engine.trigger_layer_pad(1, 12)
        self.engine.release_layer_pad(1, 12)
        self.engine.trigger_layer_pad(1, 13)                           # b live, a fading
        self.engine.set_channel_param(1, None, "release", 0.9)
        self.assertEqual(b.envelope.release_time, 0.9)
        self.assertIs(a.envelope, synth_engine._VOICE_FADE_ENVELOPE)
        self.engine.release_layer_pad(1, 13)
        self.engine.trigger_layer_pad(1, 14)                           # back to a
        self.assertEqual(a.envelope.release_time, 0.9)
        self.engine.set_channel_param(1, None, "cutoff", 700.0)
        for note in voice_notes(self.voice):
            self.assertEqual(note.filter.frequency, 700.0)

    def test_silencing_releases_every_note(self):
        self.engine.trigger_layer_pad(1, 12)
        self.engine.release_layer_pad(1, 12)
        self.engine.trigger_layer_pad(1, 13)
        self.engine.assign_channel(1, 0)
        for note in voice_notes(self.voice):
            self.assertNotIn(note, self.engine._synth.pressed)


if __name__ == "__main__":
    unittest.main()
