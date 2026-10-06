"""Quantized recording keeps a melodic layer's note joins as played:
overlapping notes stay overlapping, separate notes stay separate."""

import unittest

import fakes  # installs the CircuitPython fakes first

import looper
from event_types import PAD_DOWN, PAD_UP
from looper import LooperMode
from synth_engine import SynthEngine

STEP = 0.125      # 120 BPM sixteenths
BASS_LAYER = 1    # melodic by default
KIT_LAYER  = 0
A, B = 12, 13


class _Seq:
    step_dur = STEP


def quantized(pos):
    """Where the looper snaps a note start recorded at `pos`."""
    return int(pos / STEP + (1.0 - looper._QUANT_BIAS)) * STEP


class JoinTest(unittest.TestCase):
    def setUp(self):
        self.loop = LooperMode(SynthEngine(), None, _Seq())
        self.loop._synced = True

    def recording(self, layer_idx=BASS_LAYER):
        self.loop._active_idx = layer_idx
        self.loop._rec_state  = looper._RECORDING
        self.loop._loop_start = 0.0
        return self.loop._layers[layer_idx]

    def overdubbing(self, dur):
        self.loop._active_idx = BASS_LAYER
        layer = self.loop._layers[BASS_LAYER]
        layer.state, layer.loop_duration, layer.play_start = looper._OVERDUB, dur, 0.0
        return layer

    def down(self, pad, now):
        self.loop.handle_event((PAD_DOWN, pad), now)

    def up(self, pad, now):
        self.loop.handle_event((PAD_UP, pad), now)

    def test_overlap_survives_quantization(self):
        layer = self.recording()
        self.down(A, 0.30)       # snaps back to 0.25
        self.down(B, 0.60)       # snaps forward to 0.625
        self.up(A, 0.62)         # would have landed at 0.57: before B
        self.up(B, 0.90)
        self.assertEqual([p for _, p in layer.events], [A, B])
        self.assertEqual(layer.releases, [(quantized(0.60) + 0.30, B)])

    def test_short_note_inside_a_held_one(self):
        layer = self.recording()
        self.down(A, 0.30)
        self.down(B, 0.60)
        self.up(B, 0.70)         # the voice stops here, live
        self.up(A, 0.95)         # ignored live, so not recorded
        self.assertEqual([p for _, p in layer.releases], [B])

    def test_separate_notes_stay_separate(self):
        layer = self.recording()
        self.down(A, 0.36)       # snaps forward to 0.375
        self.up(A, 0.66)         # its release follows: 0.675
        self.down(B, 0.70)       # snaps back to 0.625 -- before that release
        b_on = quantized(0.70)
        rel, pad = layer.releases[0]
        self.assertEqual(pad, A)
        self.assertAlmostEqual(rel, b_on - 0.04)   # the real 40 ms gap, kept
        self.assertGreater(rel, quantized(0.36))

    def test_tight_gap_gets_the_minimum(self):
        layer = self.recording()
        self.down(A, 0.36)
        self.up(A, 0.69)
        self.down(B, 0.70)       # played 10 ms after the release
        self.assertAlmostEqual(layer.releases[0][0],
                               quantized(0.70) - looper._MIN_NOTE_GAP)

    def test_release_never_moves_before_its_own_start(self):
        layer = self.recording()
        self.down(A, 0.36)       # 0.375
        self.up(A, 0.37)
        self.down(B, 0.38)       # also 0.375
        self.assertEqual(layer.releases[0][0], quantized(0.36))

    def test_untouched_when_already_apart(self):
        layer = self.recording()
        self.down(A, 0.26)       # 0.25
        self.up(A, 0.40)         # 0.39
        self.down(B, 0.50)       # 0.5
        self.assertAlmostEqual(layer.releases[0][0], quantized(0.26) + 0.14)

    def test_overdub_separate_notes_stay_separate(self):
        layer = self.overdubbing(2.0)
        self.down(A, 1.36)       # 1.375
        self.up(A, 1.66)         # 1.675
        self.down(B, 1.70)       # 1.625
        self.assertAlmostEqual(layer.releases[0][0], quantized(1.70) - 0.04)

    def test_overdub_overlap_survives(self):
        layer = self.overdubbing(2.0)
        self.down(A, 1.30)
        self.down(B, 1.60)
        self.up(A, 1.62)
        self.up(B, 1.90)
        self.assertEqual([p for _, p in layer.releases], [B])

    def test_overdub_seam_is_left_alone(self):
        layer = self.overdubbing(2.0)
        self.down(A, 1.80)       # 1.75
        self.up(A, 1.97)         # 1.92
        self.down(B, 2.05)       # next pass: 0.0
        self.assertAlmostEqual(layer.releases[0][0], quantized(1.80) + 0.17)

    def test_kit_layer_untouched(self):
        layer = self.recording(KIT_LAYER)
        self.down(A, 0.30)
        self.down(B, 0.60)
        self.up(A, 0.62)
        self.up(B, 0.90)
        self.assertEqual(layer.releases, [])     # drums self-release

    def test_freeform_untouched(self):
        self.loop._synced = False
        layer = self.recording()
        self.down(A, 0.30)
        self.down(B, 0.60)
        self.up(A, 0.62)
        self.assertEqual(layer.releases, [(0.62, A)])


if __name__ == "__main__":
    unittest.main()
