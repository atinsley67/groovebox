"""
The work that runs in bursts mid-playback, and what's left sounding when
playback stops:

  - a take's end (_fit_to_duration), an overdub's end (NoteList.sort) and
    MIRR (mirror_active_layer) work on the flat arrays by index instead of
    building (pos, pad) tuples. They must do exactly what the tuple
    versions did: each is checked against that version, kept here as the
    reference, over many random layers.
  - pause and mute let go of the melodic notes playback left sounding;
    SAVE / LOAD stop playback and fade everything out before the file work.
"""

import random
import unittest

import fakes  # installs the CircuitPython fakes first

import groove
import looper
import palette
import synth_engine
from config import BTN_MENU, BTN_INC, BTN_RECORD, MAX_LOOP_EVENTS
from harness import run
from looper import LooperMode, NoteList
from synth_engine import SynthEngine

KIT_LAYER  = 0
BASS_LAYER = 1
GRID = 0.125


class _Seq:
    step_dur = GRID


# ── The tuple versions, as they were ──────────────────────────────────────────

def reference_fit(events, releases, duration):
    merged = sorted([(p, 0, pad) for p, pad in events] +
                    [(p, 1, pad) for p, pad in releases])
    out_events, out_releases = [], []
    onset_wrapped = {}
    for pos, kind, pad in merged:
        if kind == 0:
            wrapped = pos >= duration
            onset_wrapped[pad] = wrapped
            out_events.append((max(0.0, pos - duration) if wrapped else pos, pad))
        else:
            if pos >= duration:
                if onset_wrapped.get(pad):
                    pos = min(pos - duration, duration - looper._SEAM_EPS)
                else:
                    pos = duration - looper._SEAM_EPS
            out_releases.append((pos, pad))
    return out_events, out_releases


def reference_mirror(events, releases, dur, needs_release):
    half = dur / 2
    seam = dur - looper._SEAM_EPS
    merged = sorted([(p, 0, pad, i) for i, (p, pad) in enumerate(events)] +
                    [(p, 1, pad, 0) for p, pad in releases])
    open_by_pad, release_of = {}, {}
    for pos, kind, pad, i in merged:
        if kind == 0:
            open_by_pad.setdefault(pad, []).append(i)
        else:
            stack = open_by_pad.get(pad)
            if stack:
                release_of[stack.pop()] = pos
    out_events, out_releases = [], []
    for i, (pos, pad) in enumerate(events):
        if pos >= half:
            continue
        out_events.append((pos, pad))
        out_events.append((pos + half, pad))
        rel = release_of.get(i)
        if rel is not None:
            out_releases.append((rel, pad))
            out_releases.append((min(rel + half, seam), pad))
        elif needs_release:
            out_releases.append((seam, pad))
    return out_events, out_releases


def stored(pairs):
    """Pairs as a NoteList holds them (float32 positions)."""
    return list(NoteList(pairs))


def same_notes(test, got, want):
    """Same notes, and `got` in position order. (Notes at one position may
    come in either order: the tuple versions broke those ties by pad.)"""
    test.assertEqual(sorted(got), sorted(stored(want)))
    test.assertEqual([p for p, _ in got], sorted(p for p, _ in got))


def random_layer(rng, dur, past_end):
    """Onsets on a grid (so some share a position), some pads repeated, each
    with a release after it, or none; with past_end, some land at or past
    `dur` the way quantization can push them."""
    events, releases = [], []
    top = dur + (3 * GRID if past_end else 0.0)
    for _ in range(rng.randint(0, 40)):
        pos = rng.randrange(int(top / GRID)) * GRID
        if not past_end:
            pos = min(pos, dur - GRID)
        pad = rng.choice((3, 5, 12, 12, 13))
        events.append((pos, pad))
        if rng.random() < 0.8:
            rel = pos + rng.randint(0, 6) * GRID / 2
            releases.append((rel if past_end else min(rel, dur - GRID / 4), pad))
    rng.shuffle(events)
    rng.shuffle(releases)
    return stored(events), stored(releases)


class FitToDurationTest(unittest.TestCase):
    def test_matches_the_tuple_version(self):
        rng  = random.Random(1)
        loop = LooperMode(SynthEngine(), None, _Seq())
        for _ in range(300):
            dur = rng.choice((1.0, 2.0, 4.0))
            events, releases = random_layer(rng, dur, past_end=True)
            layer = looper.LoopLayer()
            layer.events, layer.releases = NoteList(events), NoteList(releases)
            loop._fit_to_duration(layer, dur)
            want_events, want_releases = reference_fit(events, releases, dur)
            same_notes(self, list(layer.events), want_events)
            same_notes(self, list(layer.releases), want_releases)

    def test_a_wrapped_note_takes_its_release_along(self):
        layer = looper.LoopLayer()
        layer.events   = NoteList([(0.5, 12), (2.0, 13)])   # 13 snapped onto the end
        layer.releases = NoteList([(0.75, 12), (2.25, 13)])
        LooperMode(SynthEngine(), None, _Seq())._fit_to_duration(layer, 2.0)
        self.assertEqual(list(layer.events), [(0.0, 13), (0.5, 12)])
        self.assertEqual(list(layer.releases), [(0.25, 13), (0.75, 12)])


class MirrorTest(unittest.TestCase):
    def playing(self, loop, idx, events, releases, dur):
        loop._active_idx = idx
        loop._master_dur = dur
        layer = loop._layers[idx]
        layer.events, layer.releases = NoteList(events), NoteList(releases)
        layer.state, layer.loop_duration, layer.play_start = looper._PLAYING, dur, 0.0
        return layer

    def test_matches_the_tuple_version(self):
        rng = random.Random(2)
        for _ in range(300):
            loop = LooperMode(SynthEngine(), None, _Seq())
            idx  = rng.choice((KIT_LAYER, BASS_LAYER))
            dur  = rng.choice((2.0, 4.0))
            events, releases = random_layer(rng, dur, past_end=False)
            layer = self.playing(loop, idx, events, releases, dur)
            want_events, want_releases = reference_mirror(
                events, releases, dur, needs_release=(idx == BASS_LAYER))
            fits = (len(want_events) <= MAX_LOOP_EVENTS and
                    len(want_releases) <= MAX_LOOP_EVENTS)
            self.assertEqual(loop.mirror_active_layer(0.1), fits)
            if fits:
                same_notes(self, list(layer.events), want_events)
                same_notes(self, list(layer.releases), want_releases)
            else:
                self.assertEqual(list(layer.events), events)   # untouched

    def test_too_many_notes_changes_nothing(self):
        loop   = LooperMode(SynthEngine(), None, _Seq())
        events = [(i * 0.01, 12) for i in range(MAX_LOOP_EVENTS // 2 + 1)]
        layer  = self.playing(loop, BASS_LAYER, stored(events), [], 8.0)
        before = list(layer.events)
        self.assertFalse(loop.mirror_active_layer(0.1))
        self.assertEqual(list(layer.events), before)


class StableSortTest(unittest.TestCase):
    def test_ties_keep_their_order(self):
        notes = NoteList([(0.5, 9), (0.25, 4), (0.5, 1), (0.5, 7), (0.0, 3)])
        notes.sort()
        self.assertEqual(list(notes), [(0.0, 3), (0.25, 4), (0.5, 9), (0.5, 1), (0.5, 7)])

    def test_order_by_pos(self):
        import array
        positions = array.array("f", [0.5, 0.25, 0.5, 0.0, 0.5])
        self.assertEqual(looper._order_by_pos(positions), [3, 1, 0, 2, 4])


# ── Pause, mute, SAVE / LOAD ──────────────────────────────────────────────────

class ReleaseOnStopTest(unittest.TestCase):
    def setUp(self):
        self.synth = SynthEngine()
        self.loop  = LooperMode(self.synth, None, _Seq())
        self.voice = self.synth._channels[BASS_LAYER]["data"]
        for idx in (KIT_LAYER, BASS_LAYER):
            layer = self.loop._layers[idx]
            layer.events = NoteList([(0.0, 12)])
            layer.state, layer.loop_duration = looper._PLAYING, 2.0
        self.loop._master_dur = 2.0
        self.loop.set_playing(True, 0.0)

    def sounding(self):
        """The bass note playback started is still held down."""
        return fakes.live_pair(self.voice)["note"] in self.synth._synth.pressed

    def test_pause_lets_go_of_melodic_notes(self):
        self.synth.trigger_layer_pad(BASS_LAYER, 12)
        self.assertTrue(self.sounding())
        self.loop.set_playing(False, 1.0)
        self.assertFalse(self.sounding())
        # with its own release, not a fade
        self.assertIs(fakes.live_pair(self.voice)["note"].envelope, self.voice["envelope"])

    def test_a_held_pad_is_left_alone(self):
        self.loop._active_idx = BASS_LAYER
        self.loop._held_mask  = 1 << 12
        self.synth.trigger_layer_pad(BASS_LAYER, 12)
        self.loop.set_playing(False, 1.0)
        self.assertTrue(self.sounding())

    def test_mute_lets_go(self):
        self.synth.trigger_layer_pad(BASS_LAYER, 12)
        self.loop.toggle_mute(BASS_LAYER)
        self.assertFalse(self.sounding())

    def test_autos_mute_lets_go(self):
        self.synth.trigger_layer_pad(BASS_LAYER, 12)
        self.loop.set_muted(BASS_LAYER, True)
        self.assertFalse(self.sounding())

    def test_clearing_the_layer_lets_go(self):
        self.synth.trigger_layer_pad(BASS_LAYER, 12)
        self.loop.clear_layer(BASS_LAYER)
        self.assertFalse(self.sounding())

    def test_clearing_every_layer_lets_go(self):
        self.synth.trigger_layer_pad(BASS_LAYER, 12)
        self.loop.clear_all()
        self.assertFalse(self.sounding())

    def test_fade_all(self):
        self.synth.trigger_layer_pad(BASS_LAYER, 12)
        self.synth.trigger_layer_pad(KIT_LAYER, 0)
        self.synth.fade_all()
        self.assertEqual(self.synth._synth.pressed, [])
        self.assertEqual(self.synth._pending_releases, [])
        for note in synth_engine.voice_notes(self.voice):
            self.assertIs(note.envelope, synth_engine._VOICE_FADE_ENVELOPE)
        self.synth.trigger_layer_pad(BASS_LAYER, 13)        # the next note: its own again
        self.assertIs(fakes.live_pair(self.voice)["note"].envelope, self.voice["envelope"])


class SaveLoadStopTest(unittest.TestCase):
    SAVE_ITEM = 8
    LOAD_ITEM = 9

    def test_save_stops_and_fades_first(self):
        def scenario(h):
            yield from h.tap(BTN_RECORD)                # a freeform loop on the kit
            yield from h.pad_tap(0)
            yield 0.4
            yield from h.tap(BTN_RECORD)
            assert h.looper.transport_playing
            yield from h.tap(BTN_MENU)
            yield from h.taps(BTN_INC, self.SAVE_ITEM)
            yield from h.tap(BTN_MENU)
            assert h.text == "S01 ", h.text
            yield from h.tap(BTN_MENU)                  # save
            assert not h.looper.transport_playing       # stopped straight away
            assert h.synth._synth.pressed == []
            assert h.text == "S01 ", h.text             # the file work waits out the fade
            yield 0.1
            assert h.text == "DONE", h.text
            assert h.key_color(BTN_MENU) == palette.OFF  # and the menu closed
        run(scenario)

    def test_a_failed_save_stays_on_the_slots(self):
        def scenario(h):
            def read_only(slot, data):
                raise OSError(30)                       # drive not writable
            saved, groove.save = groove.save, read_only
            try:
                yield from h.tap(BTN_MENU)
                yield from h.taps(BTN_INC, self.SAVE_ITEM)
                yield from h.tap(BTN_MENU)
                yield from h.tap(BTN_MENU)
                yield 0.1
                assert h.text == "RO  ", h.text
                assert h.key_color(BTN_MENU) == palette.MENU_OPEN
                yield 0.7                                   # past the flash
                assert h.text == "S01 ", h.text             # still on the slot list
            finally:
                groove.save = saved
        run(scenario)

    def test_an_empty_load_slot_keeps_playing(self):
        def scenario(h):
            yield from h.tap(BTN_RECORD)
            yield from h.pad_tap(0)
            yield 0.4
            yield from h.tap(BTN_RECORD)
            yield from h.tap(BTN_MENU)
            yield from h.taps(BTN_INC, self.LOAD_ITEM)
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_MENU)                  # empty slot
            assert h.text == "N/A ", h.text
            assert h.looper.transport_playing
        run(scenario)


if __name__ == "__main__":
    unittest.main()
