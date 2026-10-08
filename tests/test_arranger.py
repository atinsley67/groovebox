"""
AUTO, the mute arranger: arranger.Arranger on its own (fake channels, a
seeded random), then end to end through the menu and the main loop.
"""

import random
import unittest

import fakes  # noqa: F401  (installs the CircuitPython fakes first)

import arranger
from arranger import Arranger
from config import BTN_MENU, BTN_DEC, BTN_MODE, BTN_PLAY_STOP, BTN_RECORD
from harness import run
from looper import NoteList


class FakeMode:
    """Channels with content and a mute each; records every set_muted."""

    def __init__(self, content=()):
        self.content = set(content)
        self.muted   = set()
        self.sets    = []

    def can_arrange(self, n):
        return n in self.content

    def is_muted(self, n):
        return n in self.muted

    def set_muted(self, n, muted):
        self.sets.append((n, muted))
        (self.muted.add if muted else self.muted.discard)(n)


def make(layers=(), tracks=(), seed=1):
    looper = FakeMode(layers)
    seq    = FakeMode(tracks)
    return Arranger(looper, seq, rng=random.Random(seed)), looper, seq


def playing(looper, seq):
    return ({n for n in looper.content if n not in looper.muted} |
            {8 + n for n in seq.content if n not in seq.muted})


def sets(looper, seq):
    return len(looper.sets) + len(seq.sets)


class MovesTest(unittest.TestCase):
    def test_settles_around_three_quarters_playing(self):
        counts = []
        for seed in range(10):
            arr, looper, seq = make(layers=range(4), tracks=range(4), seed=seed)
            arr.start()
            for n in range(2000):
                arr.on_unit(n, "bar")
                counts.append(len(playing(looper, seq)))
        mean = sum(counts) / len(counts)
        self.assertTrue(5.2 < mean < 6.4, mean)            # ~6 of 8, less the breakdowns
        self.assertGreater(counts.count(8), 0.08 * len(counts))   # the full mix, often
        self.assertLess(sum(1 for c in counts if c <= 3), 0.18 * len(counts))

    def test_never_below_a_third(self):
        for seed in range(20):
            arr, looper, seq = make(layers=range(5), tracks=range(4), seed=seed)
            arr.start()
            for n in range(600):
                arr.on_unit(n, "bar")
                self.assertGreaterEqual(len(playing(looper, seq)), 3, (seed, n))

    def test_small_moves_are_one_or_two_and_mid_block_only_one(self):
        arr, looper, seq = make(layers=range(6), tracks=range(6), seed=3)
        arr.start()
        arr.on_unit(0, "bar")                              # lining up
        for n in range(1, 1500):
            block_line = not arr._plan and n >= arr._next
            before = sets(looper, seq)
            word   = arr.on_unit(n, "bar")
            changes = sets(looper, seq) - before
            if word in arranger._WORDS:
                self.assertIn(changes, (1, 2) if block_line else (1,), (n, word))
            elif word is not None:
                self.assertTrue(block_line, (n, word))     # breakdowns / drops

    def test_breakdowns_and_their_drops(self):
        arr, looper, seq = make(layers=range(4), tracks=range(5), seed=7)
        arr.start()
        breakdowns = drops = 0
        breakdown_at = None
        for n in range(3000):
            word = arr.on_unit(n, "bar")
            if word in arranger._BREAKDOWN_WORDS:
                breakdowns += 1
                self.assertEqual(len(playing(looper, seq)), 3)    # straight to the floor
                self.assertIsNone(breakdown_at)
                breakdown_at = n
            elif word in arranger._DROP_WORDS:
                drops += 1
                self.assertEqual(len(playing(looper, seq)), 9)    # every channel back
                self.assertIn(n - breakdown_at, (8, 16))          # 1 or 2 blocks later
                breakdown_at = None
        self.assertGreater(breakdowns, 10)
        self.assertGreaterEqual(drops, breakdowns - 1)

    def test_changes_only_on_phrase_lines_in_8_bar_blocks(self):
        for seed in range(20):
            arr, looper, seq = make(layers=range(5), tracks=range(3), seed=seed)
            arr.start()
            arr.on_unit(0, "bar")                          # lining up
            boundaries = set()
            for n in range(1, 400):
                before = sets(looper, seq)
                nxt = arr._next
                arr.on_unit(n, "bar")
                if arr._next != nxt:
                    boundaries.add(n)
                if sets(looper, seq) != before:
                    self.assertIn(n, boundaries, (seed, n))
                    self.assertEqual(n % 2, 0, (seed, n))
            for line in range(8, 400, 8):
                self.assertIn(line, boundaries, (seed, line))


class ChannelsTest(unittest.TestCase):
    def test_starting_mutes_take_part_too(self):
        arr, looper, seq = make(layers=range(4), tracks=range(4))
        looper.muted.update(range(4))                      # muted when AUTO starts
        arr.start()
        for n in range(200):
            arr.on_unit(n, "bar")
        self.assertTrue(any(muted is False for _, muted in looper.sets))

    def test_reads_hand_changes_live(self):
        arr, looper, seq = make(layers=range(6))
        arr.start()
        arr.on_unit(0, "bar")
        looper.muted.update(range(5))                      # by hand: one left playing
        for n in range(1, 9):
            arr.on_unit(n, "bar")                          # bar 8: the next line
        self.assertGreaterEqual(len(playing(looper, seq)), 2)   # back up to the floor

    def test_stop_leaves_the_mutes(self):
        arr, looper, seq = make(layers=range(4), tracks=range(4))
        arr.start()
        for n in range(64):
            arr.on_unit(n, "bar")
        state = (set(looper.muted), set(seq.muted))
        arr.stop()
        for n in range(64, 200):
            self.assertIsNone(arr.on_unit(n, "bar"))
        self.assertEqual((looper.muted, seq.muted), state)

    def test_too_little_to_vary(self):
        arr, looper, seq = make(layers=[0])
        arr.start()
        for n in range(200):
            self.assertIsNone(arr.on_unit(n, "bar"))
        self.assertEqual(looper.sets, [])

    def test_words_fit_the_display(self):
        for word in arranger._WORDS + arranger._BREAKDOWN_WORDS + arranger._DROP_WORDS:
            self.assertEqual(len(word), 4, word)


class PhraseClockTest(unittest.TestCase):
    def test_waits_for_the_next_8_bar_line(self):
        arr, looper, seq = make(layers=range(4), tracks=range(4))
        arr.start()
        arr.on_unit(3, "bar")
        self.assertEqual(arr._next, 8)
        for n in range(4, 9):
            self.assertIsNone(arr.on_unit(n, "bar"))       # bar 8 only lines up
        self.assertTrue(looper.sets == [] and seq.sets == [])

    def test_restart_lines_up_again(self):
        arr, looper, seq = make(layers=range(4), tracks=range(4))
        arr.start()
        for n in range(21):
            arr.on_unit(n, "bar")
        before = sets(looper, seq)
        self.assertIsNone(arr.on_unit(0, "bar"))           # the transport restarted
        self.assertEqual(sets(looper, seq), before)
        self.assertIn(arr._next, (2, 4, 8))

    def test_passes_come_in_2_pass_blocks(self):
        arr, looper, seq = make(layers=range(4))
        arr.start()
        boundaries = []
        for n in range(200):
            nxt = arr._next
            arr.on_unit(n, "pass")
            if arr._next != nxt:
                boundaries.append(n)
        for line in range(2, 200, 2):
            self.assertIn(line, boundaries)
        self.assertTrue(looper.sets)


class AutoMainLoopTest(unittest.TestCase):
    def test_menu_switches_it_and_mutes_land_on_bar_lines(self):
        def scenario(h):
            h.menu._arranger._rng = random.Random(4)
            yield from h.tap(BTN_MODE)                        # SEQ
            for track_pad in (0, 4, 8, 12):                   # track 1: 4 steps
                yield from h.pad_tap(track_pad)
            for track in (1, 2, 3):                           # tracks 2-4: a step each
                h.seq._grid[track][2] = True
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_DEC)
            assert h.text == "AUT "
            yield from h.tap(BTN_MENU)
            assert h.text == "AUT*"
            yield from h.tap(BTN_RECORD)                      # close the menu
            yield from h.tap(BTN_PLAY_STOP)
            changes, words = [], set()
            last = h.seq._muted_tracks
            for _ in range(int(40 / 0.005)):                  # 20 bars at 120 BPM
                if h.seq._muted_tracks != last:
                    changes.append(h.seq.current_step)
                    last = h.seq._muted_tracks
                words.add(h.text)
                yield 0.005
            assert changes, "AUTO changed nothing"
            # Changed before each bar's first step, which then played.
            assert set(changes) == {0}, changes
            assert words & set(arranger._WORDS + arranger._BREAKDOWN_WORDS +
                               arranger._DROP_WORDS), words
            yield from h.tap(BTN_MENU)                        # reopens on AUT
            assert h.text == "AUT*"
            yield from h.tap(BTN_MENU)                        # off
            assert h.text == "AUT "
        run(scenario)

    def test_freeform_loop_counts_passes(self):
        def scenario(h):
            h.menu._arranger._rng = random.Random(4)
            yield from h.tap(BTN_RECORD)
            yield from h.pad_tap(0)
            yield 0.4
            yield from h.tap(BTN_RECORD)                      # layer 1: a 0.5 s loop
            for layer in (1, 2):                              # two more layers
                h.looper._layers[layer].events = NoteList(h.looper._layers[0].events)
                h.looper._layers[layer].loop_duration = h.looper._layers[0].loop_duration
                h.looper._layers[layer].play_start = h.looper._layers[0].play_start
                h.looper._layers[layer].state = "PLY "
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_DEC)
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_RECORD)
            muted_seen = False
            for _ in range(100):                              # 10 s: ~20 passes
                if any(l.state == "MUTE" for l in h.looper._layers):
                    muted_seen = True
                yield 0.1
            assert muted_seen
        run(scenario)


if __name__ == "__main__":
    unittest.main()
