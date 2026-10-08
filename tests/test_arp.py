"""The arpeggiator (arp.py): its patterns and timing on its own, the
looper's exact presses, and the whole path through code.py -- KEY MODE,
the ARP menu item, and arp takes recorded on the grid."""

import random
import unittest

import fakes  # noqa: F401  (installs the CircuitPython fakes first)

import looper
import palette
from arp import Arpeggiator
from config import (BTN_MENU, BTN_INC, BTN_RECORD, BTN_MODE, BTN_PLAY_STOP,
                    BTN_VIEW, BTN_KEY_MODE, NUM_LOOP_LAYERS)
from event_types import PAD_DOWN, PAD_UP
from harness import FRAME, run
from looper import LooperMode
from synth_engine import SynthEngine

STEP = 0.125            # 120 BPM sixteenths
BASS_LAYER = 1          # melodic by default
LOW, MID, HIGH = 12, 13, 14   # the bottom row's first three notes, rising


class _Seq:
    step_dur     = STEP
    current_step = 0


def play(arp, start, end, frame=0.001):
    """Every event arp.update() gives from `start` to `end`."""
    events = []
    for i in range(int(round((end - start) / frame)) + 1):
        events.extend(arp.update(start + i * frame))
    return events


def notes(events):
    return [(t, pad) for etype, pad, t in events if etype == PAD_DOWN]


def offs(events):
    return [(t, pad) for etype, pad, t in events if etype == PAD_UP]


# ── The arp on its own ────────────────────────────────────────────────────────

class PatternTest(unittest.TestCase):
    def pattern(self, mode, presses, count):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.set(BASS_LAYER, "mode", mode)
        for pad in presses:
            arp.press(pad, 0.0, BASS_LAYER)
        return [pad for _, pad in notes(play(arp, 0.0, (count - 1) * STEP))]

    def test_up_goes_by_pitch(self):
        self.assertEqual(self.pattern(0, [HIGH, LOW, MID], 4), [LOW, MID, HIGH, LOW])

    def test_down(self):
        self.assertEqual(self.pattern(1, [LOW, HIGH, MID], 4), [HIGH, MID, LOW, HIGH])

    def test_up_down_does_not_repeat_the_ends(self):
        self.assertEqual(self.pattern(2, [LOW, MID, HIGH], 6),
                         [LOW, MID, HIGH, MID, LOW, MID])

    def test_order_is_as_pressed(self):
        self.assertEqual(self.pattern(4, [HIGH, LOW, MID], 4), [HIGH, LOW, MID, HIGH])

    def test_random_never_repeats_a_note(self):
        random.seed(3)
        played = self.pattern(3, [LOW, MID, HIGH], 60)
        self.assertEqual(set(played), {LOW, MID, HIGH})
        for a, b in zip(played, played[1:]):
            self.assertNotEqual(a, b)

    def test_a_note_added_mid_run_joins_the_pattern(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.press(LOW, 0.0, BASS_LAYER)
        arp.press(HIGH, 0.0, BASS_LAYER)
        first = notes(play(arp, 0.0, STEP))
        arp.press(MID, STEP + 0.01, BASS_LAYER)
        rest = notes(play(arp, STEP + 0.01, 4 * STEP))
        self.assertEqual([p for _, p in first + rest], [LOW, HIGH, HIGH, LOW, MID])


class GateTest(unittest.TestCase):
    def test_half_gate(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.press(LOW, 0.0, BASS_LAYER)
        arp.press(MID, 0.0, BASS_LAYER)
        events = play(arp, 0.0, 0.2)
        self.assertEqual(notes(events), [(0.0, LOW), (STEP, MID)])
        self.assertEqual(offs(events), [(STEP / 2, LOW), (STEP * 3 / 2, MID)])

    def test_legato_starts_the_next_note_first(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.set(BASS_LAYER, "gate", 3)   # 100%
        arp.press(LOW, 0.0, BASS_LAYER)
        arp.press(MID, 0.0, BASS_LAYER)
        events = play(arp, 0.0, 0.2)
        self.assertEqual(events, [(PAD_DOWN, LOW, 0.0),
                                  (PAD_DOWN, MID, STEP), (PAD_UP, LOW, STEP)])

    def test_legato_on_one_pad_retriggers(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.set(BASS_LAYER, "gate", 3)
        arp.press(LOW, 0.0, BASS_LAYER)
        events = play(arp, 0.0, 0.2)
        self.assertEqual(events, [(PAD_DOWN, LOW, 0.0),
                                  (PAD_UP, LOW, STEP), (PAD_DOWN, LOW, STEP)])

    def test_lifting_the_fingers_lets_the_last_note_finish(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.press(LOW, 0.0, BASS_LAYER)
        play(arp, 0.0, 0.03)
        arp.release(LOW, 0.03)
        events = play(arp, 0.03, 1.0)
        self.assertEqual(events, [(PAD_UP, LOW, STEP / 2)])

    def test_legato_note_gets_a_release_when_fingers_lift(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.set(BASS_LAYER, "gate", 3)
        arp.press(LOW, 0.0, BASS_LAYER)
        play(arp, 0.0, 0.03)
        arp.release(LOW, 0.03)
        self.assertEqual(play(arp, 0.03, 1.0), [(PAD_UP, LOW, STEP)])

    def test_stop_silences_now(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.press(LOW, 0.0, BASS_LAYER)
        play(arp, 0.0, 0.01)
        self.assertEqual(list(arp.stop(0.02)), [(PAD_UP, LOW, 0.02)])
        self.assertEqual(arp.held_mask, 0)
        self.assertIsNone(arp.note_pad)
        self.assertEqual(play(arp, 0.02, 1.0), [])


class FirstNoteTest(unittest.TestCase):
    """Where the first note belongs -- and so the whole arp's grid."""

    def synced(self, rate=1):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.set(BASS_LAYER, "rate", rate)
        arp.sync(1.0, STEP)
        return arp

    def first_at(self, arp, t, count_in_start=None):
        arp.press(LOW, t, BASS_LAYER, count_in_start)
        return notes(arp.update(t))[0][0]

    def test_a_late_press_starts_on_the_line(self):
        for late in (0.05, 0.6):
            self.assertEqual(self.first_at(self.synced(), 1.0 + late * STEP), 1.0)

    def test_a_press_late_in_the_step_starts_on_the_next(self):
        arp = self.synced()
        self.assertEqual(self.first_at(arp, 1.0 + 0.7 * STEP), 1.0 + STEP)
        # sounding already, timed on the line ahead; the next a step after it
        self.assertEqual(notes(play(arp, 1.1, 1.3)), [(1.0 + 2 * STEP, LOW)])

    def test_same_rule_as_recording(self):
        rec = LooperMode(SynthEngine(), None, _Seq())
        for i in range(25):
            offset = i * 0.005
            self.assertAlmostEqual(self.first_at(self.synced(), 1.0 + offset) - 1.0,
                                   rec._quantize_pos(offset), places=9)

    def test_32nds_snap_to_their_own_grid(self):
        arp = self.synced(rate=2)
        first = self.first_at(arp, 1.0 + 0.6 * STEP)
        self.assertEqual(first, 1.0 + STEP / 2)
        self.assertEqual([t for t, _ in notes(play(arp, 1.08, 1.3))],
                         [1.0 + k * STEP / 2 for k in (2, 3, 4)])

    def test_count_in_press_starts_on_the_one(self):
        arp = self.synced()
        self.assertEqual(self.first_at(arp, 1.3, count_in_start=1.5), 1.5)
        self.assertEqual(notes(play(arp, 1.3, 1.63)), [(1.5 + STEP, LOW)])

    def test_unsynced_starts_at_the_press(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        self.assertEqual(self.first_at(arp, 0.4321), 0.4321)


class ClockTest(unittest.TestCase):
    def test_a_tick_pins_the_next_note_to_its_grid(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.press(LOW, 0.03, BASS_LAYER)         # free-running: 0.03, 0.155...
        play(arp, 0.03, 0.031)
        arp.sync(0.1, STEP)                      # the tempo clock starts
        # 0.155 moves to the nearest half step from that tick
        self.assertEqual(notes(play(arp, 0.1, 0.2)), [(0.1 + STEP / 2, LOW)])

    def test_bpm_change_lands_one_new_step_after_the_last_note(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.press(LOW, 0.0, BASS_LAYER)
        play(arp, 0.0, 0.01)
        arp.set_step_dur(0.1)
        self.assertEqual(notes(play(arp, 0.01, 0.15)), [(0.1, LOW)])

    def test_rate_change_mid_run(self):
        arp = Arpeggiator(NUM_LOOP_LAYERS, STEP)
        arp.press(LOW, 0.0, BASS_LAYER)
        play(arp, 0.0, 0.01)
        arp.set(BASS_LAYER, "rate", 0)           # 8TH
        self.assertEqual([t for t, _ in notes(play(arp, 0.01, 0.6))], [0.25, 0.5])


# ── The looper's exact presses ────────────────────────────────────────────────

class ExactPressTest(unittest.TestCase):
    def setUp(self):
        self.loop = LooperMode(SynthEngine(), None, _Seq())
        self.loop._synced = True
        self.loop._active_idx = BASS_LAYER

    def test_recorded_where_timed_not_quantized(self):
        self.loop._rec_state, self.loop._loop_start = looper._RECORDING, 0.0
        layer = self.loop._layers[BASS_LAYER]
        self.loop.handle_event((PAD_DOWN, LOW), 3 * STEP / 2, exact=True)
        self.loop.handle_event((PAD_UP, LOW), 2 * STEP, exact=True)
        self.assertEqual(fakes.notes(layer.events), [(3 * STEP / 2, LOW)])
        self.assertEqual(fakes.notes(layer.releases), [(2 * STEP, LOW)])

    def test_overdub_on_the_seam_goes_to_the_top(self):
        layer = self.loop._layers[BASS_LAYER]
        layer.state, layer.loop_duration, layer.play_start = looper._OVERDUB, 2.0, 0.0
        self.loop.handle_event((PAD_DOWN, LOW), 2.0 - 1e-12, exact=True)
        self.loop.handle_event((PAD_UP, LOW), 2.0 + STEP / 2, exact=True)
        self.assertEqual(fakes.notes(layer.events), [(0.0, LOW)])
        self.assertAlmostEqual(layer.releases[0][0], STEP / 2)

    def test_count_in_takes_only_a_press_on_the_one(self):
        loop = self.loop
        loop._begin_countdown("beat", 0.0)
        loop.handle_event(("tk", 12), 1.5)       # ARM1: the 1 is at 2.0
        self.assertEqual(loop.count_in_start, 2.0)
        loop.handle_event((PAD_DOWN, MID), 1.6, exact=True)   # a preview
        loop.handle_event((PAD_UP, MID), 1.65, exact=True)
        loop.handle_event((PAD_DOWN, LOW), 2.0, exact=True)   # aimed at the 1
        loop.handle_event(("tk", 0), 2.0)
        self.assertEqual(fakes.notes(loop._layers[BASS_LAYER].events), [(0.0, LOW)])


# ── Through code.py ───────────────────────────────────────────────────────────

def wait_until(h, condition, timeout=10.0):
    end = h.t + timeout
    while not condition():
        assert h.t < end, "timed out"
        yield FRAME


def wait_to(h, t):
    if t > h.t:
        yield t - h.t


def bass_with_arp(h):
    """LOOP mode on the bass layer, its arp on."""
    yield from h.tap(BTN_VIEW)
    yield from h.pad_tap(BASS_LAYER)
    yield from h.tap(BTN_KEY_MODE)
    assert h.text == "ARP ", h.text


def clock_running(h):
    yield from h.tap(BTN_MODE)          # SEQ
    yield from h.tap(BTN_PLAY_STOP)     # the tempo clock
    yield from h.tap(BTN_MODE)          # LOOP


def recording(h):
    yield from h.tap(BTN_RECORD)
    yield from wait_until(h, lambda: h.looper._rec_state == "REC ")


def finish_take(h):
    yield from h.tap(BTN_RECORD)
    yield from wait_until(h, lambda: h.looper._layers[BASS_LAYER].state == "PLY ")


def positions(layer):
    """A take's note starts, in steps."""
    return [round(pos / STEP, 6) for pos, _ in layer.events]


class KeyModeTest(unittest.TestCase):
    def test_switches_the_layer_arp(self):
        def scenario(h):
            assert h.key_color(BTN_KEY_MODE) == palette.OFF
            yield from bass_with_arp(h)
            assert h.key_color(BTN_KEY_MODE) == palette.KEY_ARP
            assert h.arp.is_on(BASS_LAYER)
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(0)                   # layer 1: its own arp, off
            assert h.key_color(BTN_KEY_MODE) == palette.OFF
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(BASS_LAYER)
            assert h.key_color(BTN_KEY_MODE) == palette.KEY_ARP
            yield from h.tap(BTN_KEY_MODE)
            assert h.text == "KEYS"
            assert h.key_color(BTN_KEY_MODE) == palette.OFF
        run(scenario)

    def test_does_nothing_in_seq(self):
        def scenario(h):
            yield from h.tap(BTN_MODE)
            yield from h.tap(BTN_KEY_MODE)
            assert h.text not in ("ARP ", "KEYS"), h.text
            assert h.key_color(BTN_KEY_MODE) == palette.OFF
        run(scenario)

    def test_held_pads_and_the_arp_note_light_up(self):
        def scenario(h):
            yield from bass_with_arp(h)
            h.pad_down(LOW)
            h.pad_down(MID)
            yield 0.05
            assert h.pad_color(LOW) == palette.PLAYHEAD     # the arp's note
            assert h.pad_color(MID) == palette.LIVE         # just held
            h.pad_up(LOW)
            h.pad_up(MID)
            yield 0.2
        run(scenario)

    def test_switching_off_mid_hold_leaves_nothing_stuck(self):
        def scenario(h):
            yield from bass_with_arp(h)
            voice = h.synth._channels[BASS_LAYER]["data"]
            h.pad_down(LOW)
            yield 0.05
            assert voice["sounding_pad"] == LOW
            yield from h.tap(BTN_KEY_MODE)                # off, still holding
            assert voice["sounding_pad"] is None
            h.pad_up(LOW)                                 # still the arp's
            yield 0.05
            assert h.looper.held_mask == 0
            yield from h.pad_tap(MID, hold=0.3)           # plain keys again
            assert voice["sounding_pad"] is None
        run(scenario)

    def test_layer_change_mid_hold_leaves_nothing_stuck(self):
        def scenario(h):
            yield from bass_with_arp(h)
            voice = h.synth._channels[BASS_LAYER]["data"]
            h.pad_down(LOW)
            yield 0.05
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(2)                       # another layer
            assert h.looper.active_idx == 2
            assert voice["sounding_pad"] is None
            assert h.arp.note_pad is None
            h.pad_up(LOW)
            yield 0.3
            assert voice["sounding_pad"] is None
        run(scenario)


class MenuTest(unittest.TestCase):
    def test_arp_settings(self):
        def scenario(h):
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(BASS_LAYER)
            yield from h.tap(BTN_MENU)
            yield from h.taps(BTN_INC, 2)
            assert h.text == "ARP "
            yield from h.tap(BTN_MENU)
            assert h.text == "MODE"
            yield from h.tap(BTN_INC)
            assert h.text == "RATE"
            yield from h.tap(BTN_MENU)
            assert h.text == "16TH"
            yield from h.tap(BTN_INC)
            assert h.text == "32ND"
            yield from h.tap(BTN_RECORD)
            assert h.text == "RATE"
            assert h.arp.get(BASS_LAYER, "rate") == 2
            assert h.arp.get(0, "rate") == 1             # per layer
            yield from h.tap(BTN_MODE)                    # SEQ: back to root
            assert h.text == "ARP ", h.text
            yield from h.tap(BTN_MENU)
            assert h.text == "N/A "
        run(scenario)


class RecordedArpTest(unittest.TestCase):
    """Synced takes: every note exactly on the grid, the first one on the
    line the press snapped to."""

    def test_16ths_started_late_land_on_the_line(self):
        def scenario(h):
            yield from clock_running(h)
            yield from bass_with_arp(h)
            yield from recording(h)
            start = h.looper._loop_start
            yield from wait_to(h, start + 4.05 * STEP)   # 5% late for step 5
            for pad in (HIGH, LOW, MID):
                h.pad_down(pad)
            yield 8 * STEP
            for pad in (HIGH, LOW, MID):
                h.pad_up(pad)
            yield from finish_take(h)
            layer = h.looper._layers[BASS_LAYER]
            assert positions(layer) == [float(k) for k in range(4, 13)], positions(layer)
            assert [p for _, p in layer.events] == [LOW, MID, HIGH] * 3
            lengths = [round((off - on) / STEP, 6) for (on, _), (off, _)
                       in zip(layer.events, layer.releases)]
            assert lengths == [0.5] * 9, lengths
        run(scenario)

    def test_32nds_are_not_quantized_onto_16ths(self):
        def scenario(h):
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(BASS_LAYER)
            yield from h.tap(BTN_MENU)
            yield from h.taps(BTN_INC, 2)
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_INC)
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_INC)
            assert h.text == "32ND"
            yield from h.taps(BTN_RECORD, 3)              # out of the menu
            yield from clock_running(h)
            yield from h.tap(BTN_KEY_MODE)
            yield from recording(h)
            start = h.looper._loop_start
            yield from wait_to(h, start + 4.6 * STEP)
            h.pad_down(LOW)
            h.pad_down(MID)
            yield 4 * STEP
            h.pad_up(LOW)
            h.pad_up(MID)
            yield from finish_take(h)
            got = positions(h.looper._layers[BASS_LAYER])
            want = [4.5 + k / 2 for k in range(len(got))]
            assert len(got) >= 8 and got == want, got
        run(scenario)

    def test_count_in_press_starts_the_take(self):
        def scenario(h):
            yield from clock_running(h)
            yield from bass_with_arp(h)
            yield from h.tap(BTN_RECORD)
            yield from wait_until(h, lambda: h.looper.count_in_start is not None)
            h.pad_down(LOW)
            yield from wait_until(h, lambda: h.looper._rec_state == "REC ")
            yield 3 * STEP + 0.01
            h.pad_up(LOW)
            yield from finish_take(h)
            layer = h.looper._layers[BASS_LAYER]
            assert positions(layer) == [0.0, 1.0, 2.0, 3.0], positions(layer)
            assert round(layer.releases[0][0] / STEP, 6) == 0.5
        run(scenario)


if __name__ == "__main__":
    unittest.main()
