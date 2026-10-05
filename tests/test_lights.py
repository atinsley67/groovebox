"""
Phase 5's lights: the keyboard view (live / recording / playback / idle
layout), the step view (on-steps, playhead, firing, muted), and every
function key's light.
"""

import unittest

import fakes  # noqa: F401  (installs the CircuitPython fakes first)

import palette
from config import (BTN_MENU, BTN_PLAY_STOP, BTN_RECORD, BTN_MUTE, BTN_MODE,
                    BTN_INC, BTN_DEC, BTN_VIEW, BTN_KEY_MODE, BTN_CLEAR)
from harness import run


def record_freeform_loop(h, pad=0):
    yield from h.tap(BTN_RECORD)
    yield from h.pad_tap(pad)
    yield 0.5
    yield from h.tap(BTN_RECORD)


def colors_over(h, read, seconds):
    seen = []
    for _ in range(int(seconds / 0.01)):
        seen.append(read())
        yield 0.01
    return seen


class KeyboardViewTest(unittest.TestCase):
    def test_live_press_is_yellow(self):
        def scenario(h):
            h.pad_down(7)
            yield 0.02
            assert h.pad_color(7) == palette.LIVE
            h.pad_up(7)
            yield 0.02
            assert h.pad_color(7) == palette.OFF
        run(scenario)

    def test_press_while_recording_is_red(self):
        def scenario(h):
            yield from h.tap(BTN_RECORD)                  # armed: still a preview
            h.pad_down(3)
            yield 0.02
            assert h.pad_color(3) == palette.RECORDING    # that press started the take
            h.pad_up(3)
            yield 0.3
            yield from h.tap(BTN_RECORD)                  # committed: playing
            h.pad_down(4)
            yield 0.02
            assert h.pad_color(4) == palette.LIVE
            h.pad_up(4)
            yield 0.02
            yield from h.tap(BTN_RECORD)                  # overdub
            h.pad_down(4)
            yield 0.02
            assert h.pad_color(4) == palette.RECORDING
            h.pad_up(4)
            yield 0.02
        run(scenario)

    def test_playback_flashes_blue_and_a_live_press_wins(self):
        def scenario(h):
            yield from record_freeform_loop(h, pad=2)
            seen = yield from colors_over(h, lambda: h.pad_color(2), 1.2)
            assert palette.PLAYBACK in seen
            h.pad_down(2)                                 # held across its playback
            yield 0.02
            seen = yield from colors_over(h, lambda: h.pad_color(2), 1.2)
            assert set(seen) == {palette.LIVE}, set(seen)
            h.pad_up(2)
            yield 0.02
        run(scenario)

    def test_idle_pads_are_off(self):
        def scenario(h):
            yield 0.05
            assert {h.pad_color(pad) for pad in range(16)} == {palette.OFF}
            yield from h.tap(BTN_VIEW)
            yield from h.pad_tap(1)                       # BASS: melodic
            yield 0.05
            assert {h.pad_color(pad) for pad in range(16)} == {palette.OFF}
        run(scenario)


class StepViewTest(unittest.TestCase):
    def test_steps_playhead_and_firing(self):
        def scenario(h):
            yield from h.tap(BTN_MODE)                    # SEQ
            yield from h.pad_tap(4)
            assert h.pad_color(4) == palette.HAS_CONTENT
            assert h.pad_color(5) == palette.OFF          # stopped: no playhead
            yield from h.tap(BTN_PLAY_STOP)
            pads = {4: [], 5: []}
            for _ in range(250):                          # a bar and a bit
                for pad in pads:
                    pads[pad].append((h.seq.current_step, h.pad_color(pad)))
                yield 0.01
            # Each pad's color while the playhead is on it, and while not.
            on4  = {c for step, c in pads[4] if step == 4}
            off4 = {c for step, c in pads[4] if step != 4}
            on5  = {c for step, c in pads[5] if step == 5}
            assert palette.PLAYBACK in on4, on4           # the on-step fires
            assert palette.HAS_CONTENT in off4
            assert palette.PLAYHEAD in on5, on5           # an off-step under the playhead
        run(scenario)

    def test_muted_track_shows_grey_and_does_not_fire(self):
        def scenario(h):
            yield from h.tap(BTN_MODE)
            yield from h.pad_tap(4)
            yield from h.tap(BTN_MUTE)
            yield 0.05
            assert h.pad_color(4) == palette.MUTED
            yield from h.tap(BTN_PLAY_STOP)
            seen = yield from colors_over(h, lambda: h.pad_color(4), 2.2)
            assert palette.PLAYBACK not in seen
            assert palette.PLAYHEAD in seen
        run(scenario)


class FunctionKeyLightsTest(unittest.TestCase):
    def test_play_stop(self):
        def scenario(h):
            yield 0.05
            assert h.key_color(BTN_PLAY_STOP) == palette.OFF
            yield from record_freeform_loop(h)            # freeform: no clock
            seen = yield from colors_over(h, lambda: h.key_color(BTN_PLAY_STOP), 1.0)
            assert set(seen) == {palette.PLAYING}, set(seen)
            yield from h.tap(BTN_PLAY_STOP)               # paused
            assert h.key_color(BTN_PLAY_STOP) == palette.OFF
        run(scenario)

    def test_play_stop_flashes_with_the_clock(self):
        def scenario(h):
            yield from h.tap(BTN_MODE)
            yield from h.tap(BTN_PLAY_STOP)
            seen = yield from colors_over(h, lambda: h.key_color(BTN_PLAY_STOP), 1.0)
            assert set(seen) == {palette.PLAYING, palette.BEAT}, set(seen)
        run(scenario)

    def test_record(self):
        def scenario(h):
            assert h.key_color(BTN_RECORD) == palette.OFF
            yield from h.tap(BTN_RECORD)                  # armed: blinking
            seen = yield from colors_over(h, lambda: h.key_color(BTN_RECORD), 1.0)
            assert set(seen) == {palette.RECORDING, palette.OFF}, set(seen)
            yield from h.pad_tap(0)                       # recording: solid
            seen = yield from colors_over(h, lambda: h.key_color(BTN_RECORD), 0.5)
            assert set(seen) == {palette.RECORDING}, set(seen)
            yield from h.tap(BTN_RECORD)                  # playing
            assert h.key_color(BTN_RECORD) == palette.OFF
            yield from h.tap(BTN_RECORD)                  # overdub: solid
            assert h.key_color(BTN_RECORD) == palette.RECORDING
        run(scenario)

    def test_record_shows_from_seq_too(self):
        def scenario(h):
            yield from h.tap(BTN_MODE)                    # SEQ, running
            yield from h.tap(BTN_PLAY_STOP)
            yield from h.tap(BTN_MODE)                    # LOOP: arm a synced take
            yield from h.tap(BTN_RECORD)
            yield from h.tap(BTN_MODE)                    # back to SEQ, counting in
            assert h.seq._is_display_owner
            seen = yield from colors_over(h, lambda: h.key_color(BTN_RECORD), 0.6)
            assert set(seen) == {palette.RECORDING, palette.OFF}, set(seen)
        run(scenario)

    def test_mute(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            assert h.key_color(BTN_MUTE) == palette.OFF
            yield from h.tap(BTN_MUTE)
            assert h.key_color(BTN_MUTE) == palette.MUTED
            yield from h.tap(BTN_MODE)                    # SEQ: track 1 isn't muted
            assert h.key_color(BTN_MUTE) == palette.OFF
            yield from h.tap(BTN_MUTE)
            assert h.key_color(BTN_MUTE) == palette.MUTED
        run(scenario)

    def test_loop_seq_colors(self):
        def scenario(h):
            yield 0.05
            assert h.key_color(BTN_MODE) == palette.LOOP_MODE
            yield from h.tap(BTN_MODE)
            assert h.key_color(BTN_MODE) == palette.SEQ_MODE
        run(scenario)

    def test_white_while_pressed(self):
        def scenario(h):
            for button in (BTN_MENU, BTN_INC, BTN_DEC, BTN_VIEW):
                assert h.key_color(button) == palette.OFF, button
                h.down(button)
                yield 0.02
                assert h.key_color(button) == palette.PRESSED, button
                h.up(button)
                yield 0.02
                assert h.key_color(button) == palette.OFF, button
            # That MENU opened the menu, and VIEW the channel view: close both.
            yield from h.tap(BTN_RECORD)
            yield from h.tap(BTN_VIEW)
            # The rest keep their own meaning while pressed.
            h.down(BTN_CLEAR)
            yield 0.02
            assert h.key_color(BTN_CLEAR) == palette.ARMED_CLEAR
            h.up(BTN_CLEAR)
            yield 0.02
            h.down(BTN_KEY_MODE)                          # cancels the clear
            yield 0.02
            assert h.key_color(BTN_KEY_MODE) == palette.OFF   # no channel view
            h.up(BTN_KEY_MODE)
            yield 0.02
        run(scenario)


if __name__ == "__main__":
    unittest.main()
