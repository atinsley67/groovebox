"""
ECHO (game.py): composing phrases, the shape of a round, judging, the
stages, the keys, and the code.py launcher that picks it.

Most tests drive game.Game with a fake synth and display (time is just a
number they step), then one runs game.run() on the faked hardware.
"""

import importlib.util
import os
import random
import sys
import types
import unittest

import fakes

import config
from echo import game
from core import hw, keymap, palette
from config import (BTN_DEC, BTN_INC, BTN_MENU, BTN_MODE, BTN_MUTE,
                    BTN_PLAY_STOP, BTN_RECORD)
from core.event_types import BTN_DOWN, BTN_UP, PAD_DOWN, PAD_UP
from echo.game import (CALL, KIT, PLAYER, ME_STEPS, YOU_STEPS, SHAPES, STAGES,
                       MAX_NOTES, Game, Phrase, compose, stage_row, beat_strength)

_KICK, _WOOD, _RIM, _CRSH = 0, 7, 11, 15
_DT = 0.001   # seconds per update in these tests

# Stages (0-based) by what the tests need of them.
_SHAPE_A, _SHAPE_B, _SHAPE_C = 0, 11, 16   # the first stage of each shape
_THREE_LAYERS = 3                          # the clap comes in at 3 layers
_BEFORE_SPEED = 8                          # 90 BPM, then 95


class FakeSound:
    """Records what the game plays, stamped with the test's time."""

    def __init__(self):
        self.t        = 0.0
        self.log      = []
        self.assigned = {}
        self.volumes  = {}
        self.tracks   = {}       # sequencer kit volumes
        self.params   = {}       # (layer, key) -> value
        self.octaves  = {}       # layer -> octaves moved since assigned
        self.tuning   = None
        self.fades    = 0

    def trigger_layer_pad(self, layer, pad):
        self.log.append((self.t, "on", layer, pad))

    def release_layer_pad(self, layer, pad):
        self.log.append((self.t, "off", layer, pad))

    def trigger(self, track):
        """The sequencer kit: logged as layer "seq"."""
        self.log.append((self.t, "on", "seq", track))

    def assign_channel(self, layer, instrument):
        self.assigned[layer] = instrument
        self.octaves[layer]  = 0

    def transpose_channel(self, layer, octaves):
        self.octaves[layer] += octaves

    def set_channel_volume(self, layer, pct):
        self.volumes[layer] = pct

    def set_track_volume(self, track, pct):
        self.tracks[track] = pct

    def set_channel_param(self, layer, pad, key, value):
        self.params[(layer, key)] = value

    def set_tuning(self, key, scale):
        self.tuning = (key, scale)

    def fade_all(self):
        self.fades += 1

    def ons(self, layer, pad=None, since=-1.0):
        return [t for t, kind, lay, p in self.log
                if kind == "on" and lay == layer and (pad is None or p == pad) and t >= since]


class FakeDisp:
    def __init__(self):
        self.text  = None
        self.texts = []
        self.frame = None
        self.keys  = {}

    def show(self, text):
        self.text = text
        self.texts.append(text)

    def set_pad_frame(self, frame):
        self.frame = list(frame)

    def set_key_color(self, button, color):
        self.keys[button] = color


class Runner:
    """A Game on fakes, and a clock the test moves forward."""

    def __init__(self, seed=1, dt=_DT):
        self.sound = FakeSound()
        self.disp  = FakeDisp()
        self.quits = 0
        self.game  = Game(self.sound, self.disp, rng=random.Random(seed),
                          on_quit=self._quit)
        self.t  = 0.0
        self.dt = dt

    def _quit(self):
        self.quits += 1

    def to(self, t):
        """Run the game up to time t, an update every dt."""
        while self.t < t:
            self.t = min(t, self.t + self.dt)
            self.sound.t = self.t
            self.game.update(self.t)

    def wait(self, seconds):
        self.to(self.t + seconds)

    def next_section(self):
        self.to(self.game.section_end + 0.0005)

    def press(self, pad, at=None):
        self.game.handle((PAD_DOWN, pad, self.t if at is None else at), self.t)

    def release(self, pad):
        self.game.handle((PAD_UP, pad, self.t), self.t)

    def tap(self, pad):
        self.press(pad)
        self.release(pad)

    def down(self, button):
        self.game.handle((BTN_DOWN, button, self.t), self.t)

    def up(self, button):
        self.game.handle((BTN_UP, button, self.t), self.t)

    def button(self, button):
        self.down(button)
        self.up(button)

    def draw(self):
        self.game.draw(self.t)
        return self.disp.text

    def start(self):
        self.button(BTN_PLAY_STOP)

    def jump_to_stage(self, stage):
        """Start a game, but at `stage` (no demo): its first real round
        starts after the count-in."""
        self.start()
        self.game._start_stage(stage)
        self.game._demo = False

    def active_notes(self):
        g = self.game
        return [i for i in range(g.phrase.n) if g.active(i)]

    def play_turn(self, offset=0.0, pads=None):
        """Play this round's turn: each note in play at its target plus
        `offset`, on its own pad (or pads[k] for the k-th)."""
        g = self.game
        self.to(g.you_start - 0.2)
        for k, i in enumerate(self.active_notes()):
            self.to(g.target(i) + offset)
            self.tap(g.phrase.pads[i] if pads is None else pads[k])

    def clean_round(self):
        self.play_turn()
        self.next_section()

    def clear_stage(self):
        stage = self.game.stage
        while self.game.stage == stage:
            if self.game.demo:
                self.next_section()
            else:
                self.clean_round()


def _other_pad(pad):
    return (pad + 1) % config.NUM_PADS


# ── Composing ─────────────────────────────────────────────────────────────────

class ComposeTest(unittest.TestCase):
    ROWS = list(STAGES) + [stage_row(19)]

    def phrases(self, row, count=200):
        phrase = Phrase()
        arrays = (phrase.steps, phrase.pads, phrase.notes, phrase.rank)
        for seed in range(count):
            compose(phrase, row, random.Random(seed))
            for before, now in zip(arrays, (phrase.steps, phrase.pads, phrase.notes, phrase.rank)):
                self.assertIs(before, now)
                self.assertEqual(len(now), MAX_NOTES)
            yield phrase

    def test_exactly_the_stage_note_count(self):
        for row in self.ROWS:
            for phrase in self.phrases(row):
                self.assertEqual(phrase.n, row[game._NOTES], row)

    def test_the_first_stage_is_three_quarter_notes(self):
        for phrase in self.phrases(STAGES[0]):
            steps = list(phrase.steps[:phrase.n])
            self.assertEqual(len(steps), 3)
            self.assertTrue(set(steps) <= {0, 4, 8, 12})
            self.assertTrue({0, 8} <= set(steps))

    def test_rhythm_in_the_shape_and_on_the_strong_beats(self):
        for row in self.ROWS:
            span = SHAPES[row[game._SHAPE]]
            cells = row[game._CELLS]
            for phrase in self.phrases(row):
                steps = list(phrase.steps[:phrase.n])
                self.assertEqual(steps, sorted(set(steps)))
                self.assertLess(steps[-1], span)
                for strong in range(0, span, 8):    # every bar's beats 1 and 3
                    self.assertIn(strong, steps, (row, steps))
                for beat in range(span // 4):
                    cell = 0
                    for step in steps:
                        if step // 4 == beat:
                            cell |= 1 << (step % 4)
                    self.assertIn(cell, cells, (row, steps))

    def test_pitch_in_reach_ending_on_a_root(self):
        for row in self.ROWS:
            top = row[game._ROWS] * 4 - 1
            for phrase in self.phrases(row):
                notes = list(phrase.notes[:phrase.n])
                self.assertTrue(all(0 <= note <= top for note in notes), (row, notes))
                self.assertEqual(notes[-1] % 5, 0)
                for i in range(phrase.n):
                    self.assertEqual(phrase.pads[i], keymap.PAD_OF_NOTE[phrase.notes[i]])

    def test_reveal_order_strongest_first(self):
        for row in self.ROWS:
            for phrase in self.phrases(row, 50):
                n = phrase.n
                self.assertEqual(sorted(phrase.rank[:n]), list(range(n)))
                by_rank = sorted(range(n), key=lambda i: phrase.rank[i])
                keys = [(beat_strength(phrase.steps[i]), phrase.steps[i]) for i in by_rank]
                self.assertEqual(keys, sorted(keys))

    def test_four_quarters_reveal_1_and_3_then_2_then_4(self):
        phrase = Phrase()
        compose(phrase, STAGES[1], random.Random(0))
        self.assertEqual(list(phrase.steps[:4]), [0, 4, 8, 12])
        order = sorted(range(4), key=lambda i: phrase.rank[i])
        self.assertEqual([phrase.steps[i] for i in order], [0, 8, 4, 12])

    def test_variety_first(self):
        """The first 8 stages change no skill: quarter notes at 90 BPM in
        the widest window, shape A -- but every one brings something new."""
        first = STAGES[0]
        for row in STAGES[:8]:
            self.assertEqual((row[game._SHAPE], row[game._BPM], row[game._WINDOW],
                              row[game._CELLS]),
                             (game.SHAPE_A, 90, 150, (game._Q, game._R)))
        for before, after in zip(STAGES[:8], STAGES[1:8]):
            self.assertNotEqual(before[game._ROWS:], after[game._ROWS:])
        self.assertEqual(first[game._BPM], 90)

    def test_then_one_skill_step_at_a_time(self):
        for before, after in zip(STAGES, STAGES[1:]):
            speed = (after[game._BPM] != before[game._BPM] or
                     after[game._WINDOW] != before[game._WINDOW])
            steps = [speed, after[game._CELLS] != before[game._CELLS],
                     after[game._SHAPE] != before[game._SHAPE]]
            self.assertLessEqual(sum(steps), 1, after)
            self.assertLessEqual(after[game._BPM] - before[game._BPM], 5)
            self.assertLessEqual(after[game._NOTES] - before[game._NOTES], 1)
            self.assertLessEqual(after[game._ROWS] - before[game._ROWS], 1)
            self.assertLessEqual(after[game._WINDOW], before[game._WINDOW])

    def test_every_stage_voice_is_a_real_instrument(self):
        for row in STAGES:
            self.assertIn(row[game._VOICE], game._LEADS)
        for instrument, _, _ in game._LEADS.values():
            self.assertIn(instrument, game.INSTRUMENT_NAMES)
            # Squeaky and out of tune up there; ringing and clashing.
            self.assertNotIn(instrument, ("CHIP", "BELL"))

    def test_the_leads_sit_low_enough(self):
        """Every lead's top pad (3 octaves up) stays under ~3.6 kHz, in any
        key the stages use: above that the waves go thin and out of tune."""
        from core import synth_engine
        engine = synth_engine.SynthEngine()
        top_pad = keymap.PAD_OF_NOTE[15]
        for name, (instrument, octaves, _) in game._LEADS.items():
            engine.assign_channel(CALL, game.INSTRUMENT_NAMES.index(instrument))
            engine.transpose_channel(CALL, octaves)
            for key in {row[game._KEY] for row in STAGES}:
                engine.set_tuning(key, 0)
                self.assertLess(engine.pad_frequency(CALL, top_pad), 3600, (name, key))

    def test_band_sizes(self):
        self.assertEqual(list(game.band_sizes(1, 3)), [1])
        self.assertEqual(list(game.band_sizes(2, 4)), [2])
        self.assertEqual(list(game.band_sizes(3, 4)), [2])
        self.assertEqual(list(game.band_sizes(4, 5)), [2, 3])
        self.assertEqual(list(game.band_sizes(4, 8)), [2, 3, 4])   # long: a mix

    def test_melodies_stay_in_their_band_and_reach_its_edges(self):
        row = STAGES[-1]                                 # 4 rows, 8 notes
        phrase = Phrase()
        for band in ((0, 1), (2, 3), (1, 3), (0, 3)):
            short = 0
            for seed in range(100):
                compose(phrase, row, random.Random(seed), band)
                reached = {note // 4 for note in phrase.notes[:phrase.n]}
                self.assertTrue(min(reached) >= band[0] and max(reached) <= band[1], band)
                self.assertEqual(phrase.notes[phrase.n - 1] % 5, 0)   # ends on a root
                short += not {band[0], band[1]} <= reached
            self.assertLessEqual(short, 5, band)        # of 100: nearly always

    def test_past_the_table_the_tempo_keeps_rising_to_a_cap(self):
        last = STAGES[-1]
        self.assertEqual(stage_row(len(STAGES))[game._BPM], last[game._BPM] + 5)
        self.assertEqual(stage_row(50)[game._BPM], game.MAX_BPM)
        self.assertEqual(stage_row(50)[2:], last[2:])


# ── The shape of a round ──────────────────────────────────────────────────────

class ShapeTest(unittest.TestCase):
    def test_play_starts_the_count_in_then_a_demo_round(self):
        r = Runner()
        g = r.game
        r.tap(3)
        self.assertEqual(g.state, game.TITLE)    # a pad just plays
        r.start()
        self.assertEqual(g.state, game.COUNT_IN)
        sd = g.step_dur
        self.assertAlmostEqual(sd, 60 / (90 * 4))
        r.to(4 * sd * 3 + 0.001)
        self.assertEqual(r.draw(), "DEMO")         # a demo comes first, not play
        r.next_section()
        self.assertEqual(g.state, game.PLAY)
        self.assertTrue(g.demo)
        self.assertEqual(g.reveal, 2)
        r.wait(0.01)
        self.assertEqual(r.draw(), "ME  ")         # no second DEMO: it just said so

    def test_go_ends_the_demo(self):
        r = Runner()
        r.start()
        r.next_section()
        g = r.game
        sd = g.step_dur
        out = g.you_start + (YOU_STEPS - 16) * sd   # the count-out's first beat
        texts = []
        for beat in range(4):
            r.to(out + 4 * beat * sd + 0.001)
            texts.append(r.draw())
        self.assertEqual(texts, ["YOU ", "YOU ", " GO ", " GO "])
        r.next_section()
        self.assertFalse(g.demo)
        r.wait(0.01)
        self.assertEqual(r.draw(), "ME  ")

    def test_no_demo_counts_in_with_go(self):
        r = Runner()
        r.jump_to_stage(0)                          # no demo
        r.to(12 * r.game.step_dur + 0.001)
        self.assertEqual(r.draw(), " GO ")


    def test_every_round_is_four_bars_and_the_count_is_before_your_turn(self):
        r = Runner()
        r.jump_to_stage(_SHAPE_A)
        r.next_section()                        # the count-in
        g = r.game
        sd = g.step_dur
        start = g.section_end - 64 * sd
        self.assertAlmostEqual(g.section_end - start, 4 * 16 * sd)
        self.assertAlmostEqual(g.you_start, start + ME_STEPS * sd)
        r.to(g.you_start + 0.001)
        sticks = sorted([(t, _WOOD) for t in r.sound.ons(KIT, _WOOD, since=start)] +
                        [(t, _RIM) for t in r.sound.ons(KIT, _RIM, since=start)])
        want = [start + (ME_STEPS - 16 + 4 * k) * sd for k in range(4)]
        self.assertEqual([pad for _, pad in sticks], [_WOOD, _WOOD, _WOOD, _RIM])
        for (t, _), due in zip(sticks, want):
            self.assertAlmostEqual(t, due, delta=_DT * 1.5)

    def test_the_soft_count_out_ends_your_turn(self):
        r = Runner()
        r.jump_to_stage(_SHAPE_A)
        r.next_section()
        g = r.game
        sd = g.step_dur
        r.play_turn()
        r.to(g.section_end - 0.001)
        outs = r.sound.ons("seq", game._SOFT_WOOD, since=g.you_start)
        want = [g.you_start + (YOU_STEPS - 16 + 4 * k) * sd for k in range(4)]
        self.assertEqual(len(outs), 4)
        for t, due in zip(outs, want):
            self.assertAlmostEqual(t, due, delta=_DT * 1.5)
        # Quieter than the count-in: the woodblock's own copy, at under half.
        self.assertEqual(r.sound.tracks[game._SOFT_WOOD], round(game.VOLUME * game._SOFT_SHARE))
        # The keys fade back toward cyan through it.
        r.to(g.section_end - 2 * sd)
        r.draw()
        self.assertEqual(r.disp.keys[BTN_MODE], game._COUNT_OUT_KEYS[3][0])

    def test_no_click_lands_on_a_note(self):
        for stage in (_SHAPE_B, _SHAPE_C, len(STAGES) - 1):
            for seed in range(8):
                r = Runner(seed=seed)
                r.jump_to_stage(stage)
                g = r.game
                g._reveal = g.phrase.n          # the whole phrase in play
                r.next_section()
                sd = g.step_dur
                start = g.you_start - ME_STEPS * sd
                last  = max(g.phrase.steps[i] for i in range(g.phrase.n))
                r.play_turn()
                r.to(g.section_end - 0.001)
                clicks = sorted(r.sound.ons(KIT, _WOOD, since=start) +
                                r.sound.ons(KIT, _RIM, since=start))
                outs = r.sound.ons("seq", game._SOFT_WOOD, since=start)
                want = [ME_STEPS - 16 + 4 * k for k in range(4)
                        if ME_STEPS - 16 + 4 * k > last]
                self.assertEqual(len(clicks), len(want), (stage, seed, last))
                self.assertEqual(len(outs), len(want))
                for t, step in zip(clicks, want):
                    self.assertAlmostEqual(t, start + step * sd, delta=_DT * 1.5)
                for t, step in zip(outs, want):
                    self.assertAlmostEqual(t, g.you_start + step * sd, delta=_DT * 1.5)

    def test_the_display_still_counts_four_when_the_clicks_dont(self):
        r = Runner(seed=2)
        r.jump_to_stage(_SHAPE_C)
        g = r.game
        g._reveal = g.phrase.n
        r.next_section()
        start, sd = g.you_start - ME_STEPS * g.step_dur, g.step_dur
        for k, text in enumerate(("  4 ", "  3 ", "  2 ", "  1 ")):
            r.to(start + (16 + 4 * k) * sd + 0.001)
            self.assertEqual(r.draw(), text)

    def test_the_gap_after_your_turn_matches_the_one_before(self):
        for stage in (_SHAPE_A, _SHAPE_B, _SHAPE_C):
            r = Runner()
            r.jump_to_stage(stage)
            span = SHAPES[stage_row(stage)[game._SHAPE]]
            self.assertEqual(ME_STEPS - span, YOU_STEPS - span)

    def test_a_round_lasts_its_whole_length(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        g = r.game
        you_start, end = g.you_start, g.section_end
        r.to(end - 0.002)                       # the last step has fired...
        self.assertEqual(g.you_start, you_start)  # ...but it's still this round
        r.to(end + 0.0005)
        self.assertAlmostEqual(g.you_start, end + ME_STEPS * g.step_dur)

    def test_the_display_through_a_round(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        g, sd = r.game, r.game.step_dur
        start = g.you_start - ME_STEPS * sd
        r.to(start + 0.001)
        self.assertEqual(r.draw(), "ME  ")
        for k, text in enumerate(("  4 ", "  3 ", "  2 ", "  1 ")):
            r.to(start + (16 + 4 * k) * sd + 0.001)
            self.assertEqual(r.draw(), text)
        r.to(g.you_start + 0.001)
        self.assertEqual(r.draw(), "YOU ")

    def test_praise_through_the_rest_bar(self):
        r = Runner(seed=3)
        r.jump_to_stage(0)
        r.next_section()
        g = r.game
        r.play_turn()
        r.wait(0.5)
        word = r.draw()
        self.assertIn(word, game._PRAISE)
        r.to(g.you_start + 16 * g.step_dur + 0.01)   # the rest bar
        self.assertEqual(r.draw(), word)
        r.next_section()
        r.wait(0.01)
        self.assertEqual(r.draw(), "ME  ")

    def test_the_call_plays_the_notes_in_play_on_the_grid(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        g = r.game
        start = g.you_start - ME_STEPS * g.step_dur
        r.to(g.you_start)
        want = [start + g.phrase.steps[i] * g.step_dur for i in r.active_notes()]
        got  = r.sound.ons(CALL, since=start)
        self.assertEqual(len(got), 2)
        for t, due in zip(got, want):
            self.assertAlmostEqual(t, due, delta=_DT * 1.5)


class DemoTest(unittest.TestCase):
    def test_the_demo_plays_your_part_and_judges_nothing(self):
        r = Runner()
        r.start()
        r.next_section()
        g = r.game
        self.assertTrue(g.demo)
        you_start = g.you_start
        r.to(you_start - 0.01)
        for i in r.active_notes():
            r.to(g.target(i) + 0.03)
            r.tap(_other_pad(g.phrase.pads[i]))   # wrong, on purpose
        targets = [g.target(i) for i in r.active_notes()]
        r.to(g.section_end - 0.01)
        demo = [t for t in r.sound.ons(PLAYER, since=you_start - 0.001)
                if any(abs(t - target) < _DT * 1.5 for target in targets)]
        self.assertEqual(len(demo), 2)
        self.assertEqual(g.lives, game.LIVES)
        r.next_section()
        self.assertFalse(g.demo)
        self.assertEqual(g.reveal, 2)        # the same notes, for real now

    def test_only_the_opening_is_a_demo(self):
        """Not when a later stage brings a new shape: mid-game, a demo
        reads as a round to copy (it was, on the device)."""
        r = Runner(dt=0.004)
        r.start()
        r.next_section()
        g = r.game
        demos = {}
        while g.stage < _SHAPE_C:
            demos.setdefault(g.stage, g.demo)
            r.clear_stage()
        demos[g.stage] = g.demo
        self.assertEqual([stage for stage, demo in sorted(demos.items()) if demo], [0])
        self.assertIn(_SHAPE_B, demos)
        self.assertIn(_SHAPE_C, demos)

    def test_a_restart_starts_with_a_demo(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        for _ in range(game.LIVES):
            if r.game.state == game.PLAY:
                r.next_section()          # nothing played: a miss
        r.wait(5)
        self.assertEqual(r.game.state, game.OVER)
        r.start()
        r.next_section()
        self.assertTrue(r.game.demo)


# ── Judging ───────────────────────────────────────────────────────────────────

class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.r = Runner()
        self.r.jump_to_stage(0)
        self.r.next_section()
        self.g = self.r.game
        self.first = self.r.active_notes()[0]

    def press_first(self, offset, pad=None):
        g, i = self.g, self.first
        self.r.to(g.target(i) + max(0.0, offset))
        at = g.target(i) + offset
        self.r.press(g.phrase.pads[i] if pad is None else pad, at=at)
        return self.r.draw()

    def test_on_time_is_nice(self):
        self.assertEqual(self.press_first(0.0), "NICE")
        self.assertEqual(self.g.score, 3)
        self.assertEqual(self.r.disp.frame[self.g.phrase.pads[self.first]], palette.GAME_HIT)

    def test_the_window_starts_wide(self):
        self.assertAlmostEqual(self.g.window, 0.150)

    def test_the_nice_edge(self):
        self.assertEqual(self.press_first(game.NICE_SHARE * self.g.window - 0.001), "NICE")

    def test_late_and_early(self):
        self.assertEqual(self.press_first(0.7 * self.g.window), "LATE")
        self.assertEqual(self.g.score, 1)
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        g = r.game
        i = r.active_notes()[1]
        r.to(g.target(i) - 0.7 * g.window)
        r.press(g.phrase.pads[i])
        self.assertEqual(r.draw(), "EARL")

    def test_outside_the_window_is_a_strike(self):
        # The second note is in play, so a press just after the first
        # note's window is still in the turn.
        self.assertEqual(self.press_first(self.g.window + 0.01), "OOPS")
        self.assertEqual(self.g.lives, game.LIVES - 1)

    def test_a_wrong_pad_is_a_strike(self):
        pad = _other_pad(self.g.phrase.pads[self.first])
        self.assertEqual(self.press_first(0.0, pad), "OOPS")
        self.assertEqual(self.g.lives, game.LIVES - 1)
        self.assertEqual(self.r.disp.frame[pad], palette.RED)

    def test_a_missed_note_is_a_strike(self):
        g = self.g
        self.r.to(g.target(self.first) + g.window + 0.002)
        self.assertEqual(self.r.draw(), "MISS")
        self.assertEqual(g.lives, game.LIVES - 1)

    def test_one_strike_a_round(self):
        g = self.g
        self.press_first(0.0, _other_pad(g.phrase.pads[self.first]))
        self.r.tap(_other_pad(g.phrase.pads[self.first]))
        self.r.next_section()                  # and the rest missed
        self.assertEqual(g.lives, game.LIVES - 1)

    def test_presses_during_the_count_are_not_judged(self):
        g = self.g
        self.r.to(g.you_start - 4 * g.step_dur)
        self.r.tap(5)
        self.assertEqual(g.lives, game.LIVES)

    def test_presses_in_the_rest_bar_are_not_judged(self):
        g = self.g
        self.r.play_turn()
        self.r.to(g.you_start + 20 * g.step_dur)
        self.r.tap(5)
        self.assertEqual(g.lives, game.LIVES)

    def test_audio_offset_moves_every_press(self):
        saved = game.AUDIO_OFFSET
        game.AUDIO_OFFSET = 0.03
        try:
            self.assertEqual(self.press_first(-0.03), "NICE")
        finally:
            game.AUDIO_OFFSET = saved

    def test_the_window_is_capped_by_the_shortest_gap(self):
        r = Runner()
        r.jump_to_stage(len(STAGES) - 1)       # 115 BPM, 80 ms
        g = r.game
        phrase = g.phrase
        phrase.n = 2
        phrase.steps[0], phrase.steps[1] = 0, 1
        phrase.rank[0], phrase.rank[1] = 0, 1
        r.next_section()
        self.assertAlmostEqual(g.window, game.WINDOW_GAP_SHARE * g.step_dur)
        self.assertLess(g.window, 0.080)


# ── Progression ───────────────────────────────────────────────────────────────

class ProgressionTest(unittest.TestCase):
    def test_a_clean_round_reveals_the_next_note(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        r.clean_round()
        self.assertEqual(r.game.reveal, 3)
        self.assertEqual(r.game.score, 2 * 3 + 5)

    def rows_by_stage(self, seed, stages=len(STAGES)):
        r = Runner(seed=seed)
        g = r.game
        g.start(0.0)
        used = []
        for stage in range(stages):
            g._start_stage(stage)
            used.append({note // 4 for note in g.phrase.notes[:g.phrase.n]})
        return used

    def test_every_lit_row_comes_round(self):
        """While a row is lit, a few stages never pass without a melody on
        it: each stage's band goes over the row left longest unplayed."""
        for seed in range(20):
            used = self.rows_by_stage(seed)
            for stage, row in enumerate(STAGES):
                lit = row[game._ROWS]
                window = range(max(0, stage - lit), stage + 1)
                for r in range(lit):
                    lit_since = min(s for s in range(len(STAGES)) if STAGES[s][game._ROWS] > r)
                    if lit_since > window.start:
                        continue                    # not lit long enough to judge
                    self.assertTrue(any(r in used[s] for s in window), (seed, stage, r))

    def test_a_newly_lit_row_is_used_straight_away(self):
        for seed in range(20):
            used = self.rows_by_stage(seed)
            for stage in range(1, len(STAGES)):
                before, now = STAGES[stage - 1][game._ROWS], STAGES[stage][game._ROWS]
                if now > before and stage > 0:
                    newest = now - 1
                    if all(newest not in used[s] for s in range(stage)):
                        self.assertIn(newest, used[stage], (seed, stage))

    def test_long_melodies_mix_2_3_and_4_rows(self):
        spans = set()
        for seed in range(20):
            for stage, rows in enumerate(self.rows_by_stage(seed)):
                if STAGES[stage][game._ROWS] == 4 and STAGES[stage][game._NOTES] >= 7:
                    spans.add(max(rows) - min(rows) + 1)
        self.assertEqual(spans, {2, 3, 4})

    def test_long_phrases_start_further_in(self):
        r = Runner()
        g = r.game
        for stage, row in enumerate(STAGES):
            g._start_stage(stage)
            n = g.phrase.n
            self.assertEqual(g.reveal, 2 if n <= game.MAX_ROUNDS + 1 else n - game.MAX_ROUNDS + 1)
            self.assertLessEqual(n - g.reveal + 1, game.MAX_ROUNDS)   # clean rounds to clear it
        self.assertEqual(g.reveal, 5)          # the last stage: 8 notes, 5 to start

    def test_a_strike_repeats_the_round_and_drops_a_layer(self):
        r = Runner()
        r.jump_to_stage(_THREE_LAYERS)
        r.next_section()
        g = r.game
        self.assertEqual(g.layers, 3)
        r.next_section()                       # nothing played
        self.assertEqual(g.reveal, 2)
        self.assertEqual(g.layers, 2)
        r.clean_round()
        self.assertEqual(g.reveal, 3)
        self.assertEqual(g.layers, 3)

    def test_the_breakdown_is_audible(self):
        r = Runner()
        r.jump_to_stage(_THREE_LAYERS)         # the clap is layer 3
        r.next_section()
        g = r.game
        r.next_section()                       # a strike
        start = r.t
        r.wait(16 * g.step_dur)
        self.assertEqual(r.sound.ons(KIT, game._CLAP, since=start), [])

    def test_a_stage_clear(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        g = r.game
        r.next_section()                       # a strike: 2 lives
        r.clear_stage()
        self.assertEqual(g.stage, 1)
        self.assertEqual(g.lives, game.LIVES)  # one back

    def test_the_last_note_shows_the_next_level_and_a_crash_follows(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        g = r.game
        while g.reveal < g.phrase.n:
            r.clean_round()
        r.play_turn()
        r.wait(0.5)
        self.assertEqual(r.draw(), "LVL2")
        line = g.section_end
        r.next_section()
        crashes = r.sound.ons(KIT, _CRSH)
        self.assertEqual(len(crashes), 1)
        self.assertAlmostEqual(crashes[0], line, delta=_DT * 1.5)   # the downbeat

    def test_the_tempo_changes_on_the_bar_line(self):
        r = Runner()
        r.jump_to_stage(_BEFORE_SPEED)         # 90 BPM, then 95
        r.next_section()
        g = r.game
        while g.reveal < g.phrase.n:
            r.clean_round()
        r.play_turn()
        old_sd = g.step_dur
        line = g.section_end
        r.next_section()                       # the stage clear
        new_sd = g.step_dur
        self.assertAlmostEqual(new_sd, 60 / (95 * 4))
        self.assertNotAlmostEqual(old_sd, new_sd)
        r.wait(2.0)
        kicks = r.sound.ons(KIT, _KICK, since=line - 4 * old_sd - 0.001)
        want = [line - 4 * old_sd] + [line + 4 * k * new_sd for k in range(len(kicks) - 1)]
        for t, due in zip(kicks, want):
            self.assertAlmostEqual(t, due, delta=_DT * 1.5)

    def test_game_over_and_restart(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        g = r.game
        r.next_section()
        r.next_section()
        self.assertEqual(g.lives, 1)
        r.to(g.you_start + 0.5)                # the third miss
        self.assertEqual(g.state, game.STING)
        self.assertEqual(r.draw(), "BUST")
        r.wait(3.5)
        self.assertEqual(g.state, game.OVER)
        score = g.score
        r.to(g._over_at + 1.5)
        self.assertEqual(r.draw(), f"{score:4d}")
        r.tap(4)                               # pads don't restart
        self.assertEqual(g.state, game.OVER)
        r.start()
        self.assertEqual(g.state, game.COUNT_IN)
        self.assertEqual((g.lives, g.score, g.stage), (game.LIVES, 0, 0))

    def test_play_does_nothing_mid_game(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        g = r.game
        you_start = g.you_start
        r.start()
        r.wait(0.1)
        self.assertEqual((g.state, g.you_start), (game.PLAY, you_start))


# ── Keys, the menu, lights, the clock ─────────────────────────────────────────

class MenuTest(unittest.TestCase):
    def test_the_menu_list(self):
        r = Runner()
        r.button(BTN_MENU)
        self.assertTrue(r.game.menu_open)
        self.assertEqual(r.draw(), "TOP ")
        self.assertEqual(r.disp.keys[BTN_MENU], palette.MENU_OPEN)
        r.button(BTN_INC)
        self.assertEqual(r.draw(), "RST ")
        r.button(BTN_INC)
        self.assertEqual(r.draw(), "QUIT")
        r.button(BTN_INC)
        self.assertEqual(r.draw(), "TOP ")     # wraps
        r.button(BTN_DEC)
        self.assertEqual(r.draw(), "QUIT")
        r.button(BTN_RECORD)                   # closes
        self.assertFalse(r.game.menu_open)
        self.assertEqual(r.sound.volumes[KIT], game.VOLUME)   # UP / DOWN were the menu's

    def test_reset_goes_back_to_the_start(self):
        r = Runner()
        r.jump_to_stage(3)
        r.next_section()
        r.wait(1.0)
        g = r.game
        r.button(BTN_MENU)
        r.button(BTN_INC)
        r.button(BTN_MENU)                     # RST
        self.assertEqual(g.state, game.TITLE)
        self.assertGreaterEqual(r.sound.fades, 1)
        played = len(r.sound.log)
        r.wait(2.0)
        self.assertEqual(len(r.sound.log), played)   # silence
        self.assertIn(r.draw(), ("ECHO", "PLAY"))
        r.start()
        self.assertEqual((g.state, g.stage), (game.COUNT_IN, 0))

    def test_quit_on_the_release(self):
        r = Runner()
        r.button(BTN_MENU)
        r.button(BTN_DEC)                      # QUIT (from TOP, wrapping)
        # Not on the press: the reload would find MENU held and start the
        # game again.
        r.down(BTN_MENU)
        self.assertEqual(r.quits, 0)
        self.assertEqual(r.draw(), "BYE ")
        r.up(BTN_MENU)
        self.assertEqual(r.quits, 1)

    def test_holding_menu_from_startup_doesnt_quit(self):
        r = Runner()
        r.up(BTN_MENU)                         # the key held at boot
        self.assertEqual(r.quits, 0)
        self.assertEqual(r.game.state, game.TITLE)

    def test_play_from_the_menu_starts(self):
        r = Runner()
        r.button(BTN_MENU)
        r.start()
        self.assertFalse(r.game.menu_open)
        self.assertEqual(r.game.state, game.COUNT_IN)


class FakeStore:
    """game_scores' load / save, in memory."""

    def __init__(self, board=None, error=None):
        self.board = board if board is not None else game.game_scores.empty()
        self.saved = []
        self.error = error

    def load(self):
        return self.board

    def save(self, board):
        if self.error:
            raise self.error
        self.saved.append([list(entry) for entry in board["top"]])


def _board(*scores, last="ALEX"):
    return {"top": [[f"P{i:<3}", s] for i, s in enumerate(scores)], "last": last}


class LeaderboardTest(unittest.TestCase):
    def runner(self, store):
        r = Runner()
        r.game = Game(r.sound, r.disp, rng=random.Random(1), on_quit=r._quit, store=store)
        return r

    def bust(self, r, score):
        """Lose a game with `score`, through to the end of the sting."""
        r.jump_to_stage(0)
        r.next_section()
        r.game._score = score
        while r.game.state == game.PLAY:
            r.wait(0.05)
        while r.game.state == game.STING:
            r.wait(0.05)

    def test_a_top_score_gets_a_name(self):
        store = FakeStore(_board(900, 500, 100))
        r = self.runner(store)
        self.bust(r, 600)
        g = r.game
        self.assertEqual(g.state, game.NAME)
        self.assertEqual(r.draw(), "*02 ")                 # where it placed
        r.wait(game._RANK_HOLD + 0.01)
        # The last name entered, its first letter flashing.
        frames = set()
        for _ in range(8):
            frames.add(r.draw())
            r.wait(0.05)
        self.assertEqual(frames, {"ALEX", " LEX"})
        lit = {b for b, color in r.disp.keys.items() if color != palette.OFF}
        self.assertEqual(lit, set(game._NAME_KEYS))
        r.button(BTN_INC)                                  # A -> B
        r.button(BTN_MENU)                                 # take it
        r.button(BTN_DEC)                                  # L -> K
        r.button(BTN_RECORD)                               # back to the first...
        r.button(BTN_INC)                                  # ...B -> C
        r.button(BTN_MENU)
        r.button(BTN_MENU)
        r.button(BTN_MENU)
        self.assertEqual(r.game._name_texts[0], "CKEX")
        r.button(BTN_MENU)                                 # the fourth: saved
        self.assertEqual(g.state, game.OVER)
        self.assertEqual(store.saved, [[["P0  ", 900], ["CKEX", 600], ["P1  ", 500], ["P2  ", 100]]])
        self.assertEqual(g.board["last"], "CKEX")
        self.assertEqual(r.draw(), "DONE")
        r.start()                                          # and play again
        self.assertEqual(g.state, game.COUNT_IN)

    def test_letters_wrap_and_repeat_when_held(self):
        r = self.runner(FakeStore(_board(last="AAAA")))
        self.bust(r, 50)
        r.button(BTN_DEC)                                  # A wraps to space
        self.assertEqual(r.game._name_texts[0], "_AAA")
        r.down(BTN_INC)                                    # space -> A, then held...
        # ...repeats at the wait, then every gap: 5 of them.
        r.wait(game._NAME_REPEAT_WAIT + 4 * game._NAME_REPEAT_GAP + 0.01)
        r.up(BTN_INC)
        letter = r.game._name_texts[0][0]
        self.assertEqual(letter, "F")                      # A, then 5 repeats
        r.wait(1.0)
        self.assertEqual(r.game._name_texts[0][0], "F")    # stopped on release

    def test_a_three_letter_name(self):
        """The blank shows as "_" while editing, and saves as a space."""
        store = FakeStore(_board(last="ALEX"))
        r = self.runner(store)
        self.bust(r, 300)
        for _ in range(3):
            r.button(BTN_MENU)                             # A, L, E as they are
        r.button(BTN_DEC)                                  # X -> W ...
        while r.game._name_texts[0][3] != "_":
            r.button(BTN_INC)                              # ... round to the blank
        self.assertEqual(r.game._name_texts, ("ALE_", "ALE "))   # blinks to empty
        r.button(BTN_MENU)
        self.assertEqual(store.saved[-1][0], ["ALE ", 300])
        r.button(BTN_MENU)
        r.button(BTN_MENU)                                 # TOP
        r.wait(game._VIEW_SWAP + 0.01)
        self.assertEqual(r.draw(), "ALE ")

    def test_record_on_the_first_letter_stays(self):
        r = self.runner(FakeStore())
        self.bust(r, 50)
        r.button(BTN_RECORD)
        self.assertEqual(r.game._name_pos, 0)

    def test_not_top_ten_skips_the_name(self):
        store = FakeStore(_board(*range(1000, 0, -100)))   # 10 scores, the lowest 100
        r = self.runner(store)
        self.bust(r, 100)                                  # a tie: below them all
        self.assertEqual(r.game.state, game.OVER)
        self.assertEqual(store.saved, [])

    def test_no_score_no_name(self):
        r = self.runner(FakeStore())
        self.bust(r, 0)
        self.assertEqual(r.game.state, game.OVER)

    def test_a_failed_save_says_why_and_keeps_the_score(self):
        store = FakeStore(error=OSError(30))
        r = self.runner(store)
        self.bust(r, 300)
        for _ in range(4):
            r.button(BTN_MENU)
        self.assertEqual(r.draw(), "RO  ")
        self.assertEqual(r.game.board["top"], [["AAAA", 300]])

    def test_menu_is_the_editor_s_while_naming(self):
        r = self.runner(FakeStore())
        self.bust(r, 300)
        r.button(BTN_MENU)
        self.assertFalse(r.game.menu_open)
        self.assertEqual(r.game._name_pos, 1)
        r.start()                                          # PLAY does nothing here
        self.assertEqual(r.game.state, game.NAME)

    def test_the_top_ten_in_the_menu(self):
        r = self.runner(FakeStore(_board(900, 500)))
        r.button(BTN_MENU)
        r.button(BTN_MENU)                                 # TOP
        self.assertTrue(r.game.menu_open)
        shown = []
        for _ in range(3):
            shown.append(r.draw())
            r.wait(game._VIEW_SWAP)
        self.assertEqual(shown, ["*01 ", "P0  ", " 900"])
        r.button(BTN_INC)
        self.assertEqual(r.draw(), "*02 ")
        r.wait(game._VIEW_SWAP * 2 + 0.01)
        self.assertEqual(r.draw(), " 500")
        r.button(BTN_INC)                                  # wraps
        self.assertEqual(r.draw(), "*01 ")
        r.button(BTN_RECORD)                               # back to the list
        self.assertEqual(r.draw(), "TOP ")
        r.button(BTN_RECORD)                               # and out
        self.assertFalse(r.game.menu_open)

    def test_an_empty_board(self):
        r = self.runner(FakeStore())
        r.button(BTN_MENU)
        r.button(BTN_MENU)
        self.assertEqual(r.draw(), "NONE")
        r.button(BTN_INC)                                  # nothing to browse
        self.assertEqual(r.draw(), "NONE")

    def test_the_view_shows_a_new_score(self):
        r = self.runner(FakeStore())
        self.bust(r, 300)
        for _ in range(4):
            r.button(BTN_MENU)
        r.button(BTN_MENU)                                 # the menu, now OVER
        r.button(BTN_MENU)                                 # TOP
        r.wait(game._VIEW_SWAP + 0.01)
        self.assertEqual(r.draw(), "AAAA")


class KeysTest(unittest.TestCase):
    def test_volume(self):
        r = Runner()
        r.button(BTN_DEC)
        self.assertEqual(r.draw(), "V 95")
        for layer in game._GAME_LAYERS:
            want = round(95 * game._CHORD_SHARE) if layer == game.CHORDS else 95
            self.assertEqual(r.sound.volumes[layer], want)
        r.button(BTN_INC)
        r.button(BTN_INC)
        self.assertEqual(r.sound.volumes[KIT], 100)
        r.button(BTN_MUTE)                     # nothing
        self.assertEqual(r.sound.volumes[KIT], 100)

    def test_voices(self):
        r = Runner()
        self.assertEqual(r.sound.assigned[PLAYER], game._PLUK)
        self.assertEqual(r.sound.assigned[game.CHORDS], game._CHRD)

    def test_the_soft_bass(self):
        r = Runner()
        params = {key: value for (layer, key), value in r.sound.params.items()
                  if layer == game.BASS}
        self.assertEqual(params, dict(game._SOFT_BASS))
        self.assertEqual(game.WAVEFORM_NAMES[params["wave"]], "SUB ")

    def test_the_chord_sits_back(self):
        r = Runner()
        params = {key: value for (layer, key), value in r.sound.params.items()
                  if layer == game.CHORDS}
        self.assertEqual(params, dict(game._SOFT_CHORD))
        self.assertLess(r.sound.volumes[game.CHORDS], r.sound.volumes[CALL])

    def test_the_kalimba(self):
        r = Runner()
        stage = next(s for s, row in enumerate(STAGES) if row[game._VOICE] == "KALI")
        r.game._start_stage(stage)
        mall = game.INSTRUMENT_NAMES.index("MALL")
        for layer in (CALL, PLAYER):
            self.assertEqual(r.sound.assigned[layer], mall)
            self.assertEqual(r.sound.octaves[layer], -1)
            self.assertEqual(game.WAVEFORM_NAMES[r.sound.params[(layer, "wave")]], "TRI ")

    def test_each_stage_brings_its_voice_and_key(self):
        r = Runner()
        r.start()
        self.assertEqual(r.sound.assigned[CALL], game._PLUK)   # stage 1: PLUK
        self.assertEqual(r.sound.octaves[CALL], -2)            # two octaves down
        self.assertIsNone(r.sound.tuning)              # and A, the default
        r.game._start_stage(2)                         # MALL in C
        mall = game.INSTRUMENT_NAMES.index("MALL")
        self.assertEqual((r.sound.assigned[CALL], r.sound.assigned[PLAYER]), (mall, mall))
        self.assertEqual((r.sound.octaves[CALL], r.sound.octaves[PLAYER]), (-1, -1))
        self.assertEqual(r.sound.tuning, (game._C, 0))
        assigned = dict(r.sound.assigned)
        r.game._start_stage(3)                         # the same voice and key
        self.assertEqual(r.sound.assigned, assigned)
        r.game.start(r.t)                              # a new game: back to PLUK in A
        self.assertEqual(r.sound.assigned[CALL], game._PLUK)
        self.assertEqual(r.sound.tuning, (game._A, 0))

    def test_pads_always_sound(self):
        r = Runner()
        r.press(9)
        self.assertEqual(r.sound.ons(PLAYER, 9), [0.0])
        r.release(9)
        self.assertEqual(r.sound.log[-1][1:], ("off", PLAYER, 9))

    def test_the_title_asks_for_play(self):
        r = Runner()
        r.wait(0.01)
        self.assertEqual(r.draw(), "ECHO")
        self.assertEqual(r.disp.keys[BTN_PLAY_STOP], palette.BEAT)
        r.to(1.1)
        self.assertEqual(r.draw(), "PLAY")
        r.to(1.3)
        r.draw()
        self.assertEqual(r.disp.keys[BTN_PLAY_STOP], palette.OFF)   # blinking


class LightsTest(unittest.TestCase):
    def test_the_cue_keys_follow_the_turns(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        g = r.game
        cue = BTN_MODE                         # left column: a cue key
        start = g.you_start - ME_STEPS * g.step_dur
        r.to(start + 2 * g.step_dur)
        r.draw()
        self.assertEqual(r.disp.keys[cue], palette.GAME_CALL)
        self.assertEqual(r.disp.keys[BTN_PLAY_STOP], palette.PLAYING)
        r.to(g.you_start + 2 * g.step_dur)
        r.draw()
        self.assertEqual(r.disp.keys[cue], game._YOU_KEYS[0])
        r.to(g.you_start + 4 * g.step_dur + 0.01)
        r.draw()
        self.assertEqual(r.disp.keys[BTN_PLAY_STOP], palette.BEAT)   # on the beat

    def test_lives_on_the_right_column(self):
        r = Runner()
        r.jump_to_stage(0)
        r.next_section()
        right = [row[-1] for row in config.FUNC_LAYOUT][-3:]
        r.draw()
        self.assertEqual([r.disp.keys[b] for b in right], [game._LIFE] * 3)
        r.next_section()                       # a strike
        r.draw()
        self.assertEqual([r.disp.keys[b] for b in right],
                         [game._LIFE, game._LIFE, palette.OFF])

    def test_the_area_and_its_roots(self):
        r = Runner()
        r.jump_to_stage(0)
        r.wait(0.01)
        r.draw()
        for pad in range(config.NUM_PADS):
            note = keymap.NOTE_OF_PAD[pad]
            if note == 0:
                want = palette.ROOT_NOTE
            elif note < 4:
                want = game._AREA
            else:
                want = palette.OFF
            self.assertEqual(r.disp.frame[pad], want, pad)


class ClockTest(unittest.TestCase):
    def test_the_kick_stays_on_the_grid(self):
        r = Runner()
        r.start()
        r.wait(20.0)
        sd = 60 / (90 * 4)
        kicks = r.sound.ons(KIT, _KICK)
        self.assertGreater(len(kicks), 25)
        for k, t in enumerate(kicks):
            self.assertAlmostEqual(t, k * 4 * sd, delta=_DT * 1.5)


# ── On the (faked) hardware ───────────────────────────────────────────────────

class _Stop(BaseException):
    pass


class RunTest(unittest.TestCase):
    def test_run_plays_on_the_real_engine(self):
        fakes.CLOCK.t = 0.0
        real = hw.Hardware()
        frames = [0]
        play_key = keymap.BUTTON_OF_KEY.index(BTN_PLAY_STOP)

        class ScriptedHardware:
            i2c = real.i2c

            def scan(self):
                frames[0] += 1
                if frames[0] == 10:
                    real._func.events.push(fakes.Event(play_key, True))
                if frames[0] == 40:
                    real._func.events.push(fakes.Event(play_key, False))
                if frames[0] > 5000:
                    raise _Stop()
                fakes.CLOCK.t += 0.001
                return real.scan()

        from core import display
        from echo import game_intro
        from core import synth_engine
        built = {}
        saved = (synth_engine.SynthEngine, display.DisplayManager, game_intro.run)

        def intro(hw_, disp, sound, layer, volume):
            built["intro"] = (layer, volume)   # tested in test_game_intro.py

        class Synth(synth_engine.SynthEngine):
            def __init__(self):
                super().__init__()
                built["synth"] = self

        class Disp(display.DisplayManager):
            def __init__(self, i2c):
                super().__init__(i2c)
                built["disp"] = self

        synth_engine.SynthEngine, display.DisplayManager, game_intro.run = Synth, Disp, intro
        try:
            with self.assertRaises(_Stop):
                game.run(ScriptedHardware())
        finally:
            synth_engine.SynthEngine, display.DisplayManager, game_intro.run = saved
        self.assertEqual(built["intro"], (CALL, game.VOLUME))
        # Five seconds in (PLAY at 0.01 s): the count-in's 2.7 s are over,
        # and the demo round's box is playing.
        self.assertEqual(built["disp"]._seg.text, "ME  ")
        self.assertGreater(len(built["synth"]._synth.press_log), 12)   # kick, hat, call


class HeldAtStartupTest(unittest.TestCase):
    """hw.held_at_startup reads a function key straight off its matrix
    lines (keypad doesn't report a key already down when it starts)."""

    def tearDown(self):
        fakes.HELD_LINES.clear()

    @staticmethod
    def lines(button):
        """The key's (anode, cathode) pins, from the wiring hw._matrix hands
        keypad: its row pins are config's COL pins, its column pins
        config's ROW pins, and keypad numbers key = row * columns + column."""
        key = keymap.BUTTON_OF_KEY.index(button)
        columns = len(config.FUNC_ROW_PINS)
        return config.FUNC_ROW_PINS[key % columns], config.FUNC_COL_PINS[key // columns]

    def test_menu_on_this_build(self):
        # MENU is key 1: the function block's second anode line, first
        # cathode line.
        self.assertEqual(self.lines(BTN_MENU), ("GP13", "GP10"))

    def test_only_the_held_key_reads_down(self):
        fakes.HELD_LINES.add(self.lines(BTN_MENU))
        for row in config.FUNC_LAYOUT:
            for button in row:
                self.assertEqual(hw.held_at_startup(button), button == BTN_MENU, button)

    def test_nothing_held(self):
        self.assertFalse(hw.held_at_startup(BTN_MENU))

    def test_it_lets_go_of_the_pins(self):
        fakes.HELD_LINES.add(self.lines(BTN_MENU))
        hw.held_at_startup(BTN_MENU)
        self.assertEqual(fakes.OPEN_PINS, set())


class LauncherTest(unittest.TestCase):
    def launch(self, menu_held):
        """Run code.py with MENU held at startup or not; which program it
        ran, on which hardware."""
        ran = []
        order = []

        class StubHardware:
            def __init__(self):
                order.append("hardware")

        def held(button):
            order.append("check")
            return menu_held and button == BTN_MENU

        import echo
        import gbox
        saved = (hw.Hardware, hw.held_at_startup)
        # (package, module name, stub): code.py's `from echo import game`
        # takes the package's attribute, or sys.modules' entry if it has none.
        stubs = (
            (echo, "game", types.SimpleNamespace(run=lambda h: ran.append(("game", type(h))))),
            (gbox, "groovebox", types.SimpleNamespace(main=lambda h: ran.append(("groovebox", type(h))))),
        )
        missing = object()
        saved_mods = [(package, name, getattr(package, name, missing),
                       sys.modules.get(f"{package.__name__}.{name}", missing))
                      for package, name, _ in stubs]
        hw.Hardware, hw.held_at_startup = StubHardware, held
        for package, name, stub in stubs:
            setattr(package, name, stub)
            sys.modules[f"{package.__name__}.{name}"] = stub
        try:
            path = os.path.join(fakes.ROOT, "code.py")
            spec = importlib.util.spec_from_file_location("launcher", path)
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        finally:
            hw.Hardware, hw.held_at_startup = saved
            for package, name, attr, mod in saved_mods:
                if attr is missing:
                    delattr(package, name)
                else:
                    setattr(package, name, attr)
                key = f"{package.__name__}.{name}"
                if mod is missing:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = mod
        self.assertEqual(order, ["check", "hardware"])   # before keypad claims the pins
        return ran

    def test_menu_held_runs_the_game(self):
        self.assertEqual([name for name, _ in self.launch(True)], ["game"])

    def test_otherwise_the_groovebox(self):
        ran = self.launch(False)
        self.assertEqual([name for name, _ in ran], ["groovebox"])
        self.assertEqual(ran[0][1].__name__, "StubHardware")


if __name__ == "__main__":
    unittest.main()
