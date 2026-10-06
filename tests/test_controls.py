"""
The Phase 4 controls: LOOP/SEQ and MUTE on a tap, CLEAR with its MENU
confirm, and the channel view (VIEW, KEY MODE select / mute).
"""

import unittest

import fakes  # installs the CircuitPython fakes first

import palette
from pad_views import ChannelView
from config import (BTN_MENU, BTN_PLAY_STOP, BTN_RECORD, BTN_MUTE, BTN_MODE,
                    BTN_VIEW, BTN_KEY_MODE, BTN_CLEAR, NUM_LOOP_LAYERS)
from harness import run

TRACK_PAD = NUM_LOOP_LAYERS   # the channel view's pad for track 1


def record_freeform_loop(h):
    yield from h.tap(BTN_RECORD)
    yield from h.pad_tap(0)
    yield 0.5
    yield from h.tap(BTN_RECORD)


def colors_over(h, read, seconds):
    seen = set()
    for _ in range(int(seconds / 0.01)):
        seen.add(read())
        yield 0.01
    return seen


def kit_presses(h, pad):
    return fakes.kit_presses(h.synth._synth, h.synth._channels[0]["data"][pad])


class ModeAndMuteKeysTest(unittest.TestCase):
    def test_loop_seq_is_a_tap(self):
        def scenario(h):
            h.down(BTN_MODE)
            yield 0.02                                    # acts on the press
            assert h.seq._is_display_owner and not h.looper._is_display_owner
            h.up(BTN_MODE)
            yield from h.tap(BTN_MODE)
            assert h.looper._is_display_owner
        run(scenario)

    def test_a_playing_freeform_loop_locks_seq_out(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            yield from h.tap(BTN_MODE)
            assert h.text == "LOCK"
            assert h.looper._is_display_owner
        run(scenario)

    def test_mute_acts_on_press(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            h.down(BTN_MUTE)
            yield 0.02
            assert h.looper._layers[0].state == "MUTE"
            yield 1.0                                     # no long press any more
            h.up(BTN_MUTE)
            yield 0.02
            assert h.looper._layers[0].state == "MUTE"
            yield from h.tap(BTN_MODE)                    # SEQ: the track
            yield from h.tap(BTN_MUTE)
            assert h.seq._muted_tracks == 1
        run(scenario)


class ClearTest(unittest.TestCase):
    def test_menu_confirms_clearing_the_channel(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            yield from h.tap(BTN_CLEAR)
            assert h.text == "CLR1"
            seen = yield from colors_over(h, lambda: h.key_color(BTN_CLEAR), 0.5)
            assert seen == {palette.ARMED_CLEAR, palette.OFF}, seen   # blinking
            assert h.looper._layers[0].state == "PLY "
            yield from h.tap(BTN_MENU)
            assert h.looper._layers[0].state == "IDLE"
            assert h.text == "DONE"
            yield 0.05
            assert h.key_color(BTN_CLEAR) == palette.OFF
        run(scenario)

    def test_clear_again_widens_to_every_channel(self):
        def scenario(h):
            yield from h.tap(BTN_MODE)                    # SEQ
            yield from h.pad_tap(0)                       # track 1, step 1
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(TRACK_PAD + 1)           # track 2
            yield from h.pad_tap(5)
            yield from h.tap(BTN_MUTE)
            yield from h.tap(BTN_CLEAR)
            assert h.text == "CLR2"
            yield from h.tap(BTN_CLEAR)
            assert h.text == "CLRA"
            yield from h.tap(BTN_CLEAR)
            assert h.text == "CLR2"
            yield from h.tap(BTN_MENU)                    # just track 2, unmuted
            assert not any(h.seq._grid[1]) and h.seq._muted_tracks == 0
            assert h.seq._grid[0][0]
            yield from h.taps(BTN_CLEAR, 2)
            yield from h.tap(BTN_MENU)
            assert not any(any(track) for track in h.seq._grid)
        run(scenario)

    def test_any_other_key_cancels_and_does_nothing_else(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            yield from h.tap(BTN_CLEAR)
            yield from h.tap(BTN_PLAY_STOP)               # cancels; no pause
            assert h.looper.transport_playing
            assert h.text == "L1  ", h.text
            yield from h.tap(BTN_CLEAR)
            yield from h.tap(BTN_RECORD)                  # cancels; no overdub
            assert h.looper._layers[0].state == "PLY "
            yield from h.tap(BTN_MENU)                    # a plain MENU again
            assert h.text == "SND "
            assert h.looper._layers[0].state == "PLY "
        run(scenario)

    def test_times_out(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            yield from h.tap(BTN_CLEAR)
            yield 3.2
            assert h.key_color(BTN_CLEAR) == palette.OFF
            yield from h.tap(BTN_MENU)
            assert h.text == "SND "
            assert h.looper._layers[0].state == "PLY "
        run(scenario)

    def test_pads_keep_playing_while_armed(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            yield from h.tap(BTN_CLEAR)
            before = kit_presses(h, 3)
            yield from h.pad_tap(3)
            assert kit_presses(h, 3) == before + 1
            assert h.text == "CLR1"
            yield from h.tap(BTN_MENU)
            assert h.looper._layers[0].state == "IDLE"
        run(scenario)


class ChannelViewColorsTest(unittest.TestCase):
    class Source:
        def __init__(self, statuses, played=None):
            self.statuses = statuses
            self.played   = played or {}

        def channel_status(self, n):
            return self.statuses[n]

        def played_at(self, n):
            return self.played.get(n, -1.0)

    def view(self, layers, tracks, played=None):
        return ChannelView(self.Source(layers, played), self.Source(tracks))

    def test_each_state(self):
        layers = ["empty", "content", "muted", "rec", "content", "muted",
                  "empty", "empty"]
        view = self.view(layers, ["content"] + ["empty"] * 7, played={4: 9.95, 5: 9.95})
        frame = list(view.frame(10.0))
        self.assertEqual(frame[0], palette.OFF)
        self.assertEqual(frame[1], palette.HAS_CONTENT)
        self.assertEqual(frame[2], palette.MUTED)
        self.assertEqual(frame[3], palette.RECORDING)
        self.assertEqual(frame[4], palette.PLAYBACK)      # just played
        self.assertEqual(frame[5], palette.MUTED)         # muted: no flash
        self.assertEqual(frame[TRACK_PAD], palette.HAS_CONTENT)
        self.assertEqual(frame[TRACK_PAD + 1], palette.OFF)

    def test_armed_blinks(self):
        view = self.view(["armed"] + ["empty"] * 7, ["empty"] * 8)
        seen = {view.frame(t / 100)[0] for t in range(100)}
        self.assertEqual(seen, {palette.RECORDING, palette.OFF})

    def test_steady_between_notes(self):
        # No pulse on any channel: content holds one color until a note.
        view = self.view(["content", "muted", "empty"] + ["empty"] * 5, ["empty"] * 8)
        for pad, want in ((0, palette.HAS_CONTENT), (1, palette.MUTED), (2, palette.OFF)):
            seen = {view.frame(t / 50)[pad] for t in range(100)}
            self.assertEqual(seen, {want}, pad)


class ChannelViewTest(unittest.TestCase):
    def test_shows_the_session(self):
        def scenario(h):
            yield from h.tap(BTN_MODE)                    # SEQ
            yield from h.pad_tap(0)                       # track 1 has a step
            yield from h.tap(BTN_MODE)                    # LOOP
            yield from record_freeform_loop(h)            # layer 1 playing
            yield 0.2
            yield from h.tap(BTN_VIEW)
            yield 0.2
            assert h.pad_color(TRACK_PAD) == palette.HAS_CONTENT
            assert h.pad_color(5) == palette.OFF
            seen = yield from colors_over(h, lambda: h.pad_color(0), 1.0)
            # Layer 1 (the selected one) shows only its activity: its note
            # flashing, otherwise steady.
            assert seen == {palette.PLAYBACK, palette.HAS_CONTENT}, seen
            yield from h.tap(BTN_VIEW)                    # back: the keyboard
            yield 0.05
            assert h.pad_color(TRACK_PAD) == palette.OFF
        run(scenario)

    def test_select_a_layer_returns_to_the_keyboard(self):
        def scenario(h):
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(3)
            assert h.looper.active_idx == 3
            yield from h.pad_tap(5)                       # plays layer 4 again
            assert h.looper._layers[3].last_pad == 5
        run(scenario)

    def test_select_a_track_switches_to_seq(self):
        def scenario(h):
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(TRACK_PAD + 4)
            assert h.seq._is_display_owner and h.seq.selected_track == 4
            assert h.text == "T5  ", h.text
            yield from h.pad_tap(6)                       # the step view again
            assert h.seq._grid[4][6]
        run(scenario)

    def test_lock_blocks_crossing_to_seq(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(TRACK_PAD + 1)
            assert h.text == "LOCK"
            assert h.looper._is_display_owner
            before = kit_presses(h, 2)
            yield from h.pad_tap(2)                       # still the channel view:
            assert kit_presses(h, 2) == before            # silent, selects layer 3
            assert h.looper.active_idx == 2
        run(scenario)

    def test_busy_while_recording_another_layer(self):
        def scenario(h):
            yield from h.tap(BTN_RECORD)
            yield from h.pad_tap(0)                       # recording layer 1
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(2)
            assert h.text == "BUSY"
            assert h.looper.active_idx == 0
            yield from h.pad_tap(0)                       # its own layer is fine
            assert h.looper._rec_state == "REC "
            yield from h.pad_tap(4)                       # back on the keyboard:
            assert [pad for _, pad in h.looper._layers[0].events] == [0, 4]
        run(scenario)

    def test_mute_mode_stays_and_resets_to_select(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            assert h.key_color(BTN_KEY_MODE) == palette.OFF
            yield from h.tap(BTN_VIEW)
            assert h.key_color(BTN_KEY_MODE) == palette.KEY_SELECT
            yield from h.tap(BTN_KEY_MODE)
            assert h.text == "MUT "
            assert h.key_color(BTN_KEY_MODE) == palette.KEY_MUTE
            yield from h.pad_tap(0)
            assert h.looper._layers[0].state == "MUTE"
            yield 0.1
            assert h.pad_color(0) != palette.HAS_CONTENT
            yield from h.pad_tap(TRACK_PAD + 2)           # tracks too
            assert h.seq._muted_tracks == 1 << 2
            yield from h.pad_tap(0)                       # still in the view
            assert h.looper._layers[0].state == "PLY "
            yield from h.taps(BTN_VIEW, 2)                # out and back in
            assert h.key_color(BTN_KEY_MODE) == palette.KEY_SELECT
            yield from h.pad_tap(1)
            assert h.looper.active_idx == 1               # select again
        run(scenario)

    def test_a_held_note_still_releases(self):
        def scenario(h):
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(1)                       # BASS
            voice = h.synth._channels[1]["data"]
            h.pad_down(0)
            yield 0.05
            yield from h.tap(BTN_VIEW)
            h.pad_up(0)                                   # released in the view
            yield 0.02
            assert voice["sounding_pad"] is None
        run(scenario)

    def test_a_tap_cancels_an_armed_clear(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            yield from h.tap(BTN_VIEW)
            yield from h.tap(BTN_CLEAR)
            yield from h.pad_tap(1)                       # select layer 2
            yield from h.tap(BTN_MENU)                    # opens the menu
            assert h.text == "SND "
            assert h.looper._layers[0].state == "PLY "
        run(scenario)


if __name__ == "__main__":
    unittest.main()
