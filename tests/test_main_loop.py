"""
End-to-end scenarios through the real code.py main loop (see harness.py):
the list menu, pads staying live under it, RECORD as its back key, MUTE /
CLEAR inert in it, the BPM item and tempo lock, UP/DOWN channel volume, and
grooves.
"""

import json
import unittest

import fakes  # installs the CircuitPython fakes first

import palette
from harness import Harness, run
from config import (BTN_MENU, BTN_PLAY_STOP, BTN_INC, BTN_DEC, BTN_RECORD,
                    BTN_MUTE, BTN_MODE, BTN_VIEW, BTN_CLEAR, NUM_LOOP_LAYERS)

ROOT_LABELS = ["SND ", "ASGN", "BPM ", "EXT ", "MIRR", "SAVE", "LOAD", "AUT "]
MSG = 0.7   # just past the menu's _MSG_DURATION


def open_menu_at(h, label):
    """Open the menu and move the highlight to a root item."""
    yield from h.tap(BTN_MENU)
    for _ in range(ROOT_LABELS.index(label)):
        yield from h.tap(BTN_INC)
    assert h.text == label, h.text


def switch_mode(h):
    yield from h.tap(BTN_MODE)


def select_layer(h, layer):
    """Choose a loop layer in the channel view (back to the keyboard after)."""
    yield from h.tap(BTN_VIEW)
    yield from h.pad_tap(layer)


def select_track(h, track):
    yield from h.tap(BTN_VIEW)
    yield from h.pad_tap(NUM_LOOP_LAYERS + track)


def record_freeform_loop(h):
    yield from h.tap(BTN_RECORD)
    yield from h.pad_tap(0)
    yield 0.5
    yield from h.tap(BTN_RECORD)


class MenuNavigationTest(unittest.TestCase):
    def test_root_is_a_wrapping_list(self):
        def scenario(h):
            yield 0.05
            yield from h.tap(BTN_MENU)
            seen = []
            for _ in ROOT_LABELS:
                seen.append(h.text)
                yield from h.tap(BTN_INC)
            assert seen == ROOT_LABELS, seen
            assert h.text == "SND "
            yield from h.tap(BTN_DEC)
            assert h.text == "AUT "
            yield from h.tap(BTN_RECORD)             # close from root
            assert h.text == "L1  ", h.text
            assert h.looper._rec_state == "IDLE"    # the back press doesn't arm
        run(scenario)

    def test_record_backs_out_one_level(self):
        def scenario(h):
            yield from open_menu_at(h, "BPM ")
            yield from h.tap(BTN_MENU)
            assert h.text == "b120"
            yield from h.tap(BTN_RECORD)
            assert h.text == "BPM "
            yield from h.tap(BTN_RECORD)
            assert h.text == "L1  "
            yield from h.tap(BTN_RECORD)             # menu closed: records again
            assert h.looper._rec_state == "ARM "
        run(scenario)

    def test_play_stop_is_the_transport_in_the_menu(self):
        def scenario(h):
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_PLAY_STOP)
            assert h.looper.transport_playing
            assert h.text == "SND "                  # still in the menu
            yield from switch_mode(h)                # SEQ, menu still open
            yield from h.tap(BTN_PLAY_STOP)
            assert h.seq.playing
            assert h.text == "SND "
        run(scenario)

    def test_loop_only_items_in_seq(self):
        def scenario(h):
            yield from switch_mode(h)
            yield from open_menu_at(h, "ASGN")
            yield from h.tap(BTN_MENU)
            assert h.text == "N/A "
            yield MSG
            assert h.text == "ASGN"
        run(scenario)


class PadsUnderMenuTest(unittest.TestCase):
    def test_pads_play_the_loop_layer(self):
        def scenario(h):
            yield from h.tap(BTN_MENU)
            sound = h.synth._channels[0]["data"][2]
            presses = fakes.kit_presses(h.synth._synth, sound)
            h.pad_down(2)
            yield 0.02
            assert fakes.kit_presses(h.synth._synth, sound) == presses + 1
            assert h.pad_color(2) == palette.LIVE, "the looper keeps the pad lights"
            assert h.text == "SND ", "the menu keeps the text"
            h.pad_up(2)
            yield 0.02
            assert h.pad_color(2) != palette.LIVE
        run(scenario)

    def test_pads_toggle_steps_in_seq(self):
        def scenario(h):
            yield from switch_mode(h)
            yield from h.tap(BTN_MENU)
            yield from h.pad_tap(3)
            assert h.seq._grid[0][3]
            assert h.pad_color(3) == palette.HAS_CONTENT
            assert h.text == "SND "
            yield from h.tap(BTN_RECORD)
            assert h.text == "T1  "
        run(scenario)

    def test_channel_view_selects_under_the_menu(self):
        def scenario(h):
            yield from h.tap(BTN_MENU)
            yield from select_layer(h, 4)
            assert h.looper.active_idx == 4
            assert h.text == "SND "
        run(scenario)

    def test_held_note_releases_after_menu_opens(self):
        def scenario(h):
            yield from select_layer(h, 1)   # BASS, melodic: needs a release
            voice = h.synth._channels[1]["data"]
            h.pad_down(0)
            yield 0.05
            assert voice["sounding_pad"] == 0
            yield from h.tap(BTN_MENU)
            h.pad_up(0)
            yield 0.02
            assert voice["sounding_pad"] is None
        run(scenario)


class InertInMenuTest(unittest.TestCase):
    def test_record_closes_instead_of_arming(self):
        def scenario(h):
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_RECORD)
            assert h.looper.is_idle
            assert h.looper._rec_state == "IDLE"
            assert h.text == "L1  "
        run(scenario)

    def test_record_does_not_arm_a_synced_take(self):
        def scenario(h):
            yield from switch_mode(h)
            yield from h.tap(BTN_PLAY_STOP)    # sequencer running
            yield from switch_mode(h)
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_RECORD)
            assert h.looper.is_idle
            assert not h.looper._synced
        run(scenario)

    def test_mute_does_nothing(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            layer = h.looper._layers[0]
            assert layer.state == "PLY "
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_MUTE)
            assert layer.state == "PLY "
            yield from h.tap(BTN_RECORD)
            yield from h.tap(BTN_MUTE)
            assert layer.state == "MUTE"
        run(scenario)

    def test_clear_does_nothing(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_CLEAR)
            assert h.text == "SND "
            yield from h.tap(BTN_MENU)                # select SND, not a confirm
            assert h.looper._layers[0].state == "PLY "
        run(scenario)

    def test_sync_still_detected_outside_menu(self):
        def scenario(h):
            yield from switch_mode(h)
            yield from h.tap(BTN_PLAY_STOP)
            yield from switch_mode(h)
            yield from h.tap(BTN_RECORD)
            assert h.looper._synced
            assert h.looper._rec_state == "CNT "
        run(scenario)


class BpmItemTest(unittest.TestCase):
    def test_edit_bpm(self):
        def scenario(h):
            yield from open_menu_at(h, "BPM ")
            yield from h.tap(BTN_MENU)
            assert h.text == "b120"
            yield from h.tap(BTN_INC)
            assert h.text == "b121" and h.bpm == 121
            yield from h.hold(BTN_DEC, 1.0)    # 1 step, then auto-repeat
            assert h.bpm <= 121 - 5, h.bpm
            assert h.text == f"b{h.bpm:3d}"
            yield from h.tap(BTN_MENU)          # done
            assert h.text == "BPM "
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_RECORD)        # back also leaves the editor
            assert h.text == "BPM "
        run(scenario)

    def test_bpm_clamped(self):
        def scenario(h):
            yield from open_menu_at(h, "BPM ")
            yield from h.tap(BTN_MENU)
            yield from h.hold(BTN_DEC, 12.0)
            assert h.bpm == 40 and h.text == "b 40"
        run(scenario)

    def test_up_down_no_longer_change_bpm(self):
        def scenario(h):
            yield from h.tap(BTN_INC)
            yield from h.tap(BTN_DEC)
            assert h.bpm == 120
        run(scenario)

    def test_locked_by_freeform_loop(self):
        def scenario(h):
            yield from record_freeform_loop(h)
            yield from open_menu_at(h, "BPM ")
            yield from h.tap(BTN_MENU)
            assert h.text == "LOCK"
            yield MSG
            assert h.text == "b120"             # still readable
            yield from h.tap(BTN_INC)
            assert h.text == "LOCK" and h.bpm == 120
        run(scenario)

    def test_locked_by_synced_take(self):
        def scenario(h):
            yield from switch_mode(h)
            yield from h.tap(BTN_PLAY_STOP)
            yield from switch_mode(h)
            yield from h.tap(BTN_RECORD)        # synced count-in: tempo locked
            yield from open_menu_at(h, "BPM ")
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_INC)
            assert h.bpm == 120
        run(scenario)

    def test_change_reanchors_running_clock(self):
        def scenario(h):
            yield from switch_mode(h)
            yield from h.tap(BTN_PLAY_STOP)
            yield 0.3
            yield from open_menu_at(h, "BPM ")
            yield from h.tap(BTN_MENU)
            yield from h.hold(BTN_INC, 2.0)
            assert h.bpm > 130
            assert h.seq.playing
        run(scenario)


class ChannelVolumeTest(unittest.TestCase):
    def test_steps_active_layer_and_flashes(self):
        def scenario(h):
            yield from h.tap(BTN_DEC)
            assert h.synth.channel_volume(0) == 95
            assert h.text == "V 95"
            h.pad_down(1)                       # LEDs stay live under the flash
            yield 0.02
            assert h.pad_color(1) == palette.LIVE and h.text == "V 95"
            h.pad_up(1)
            yield 1.1
            assert h.text == "L1  ", h.text
        run(scenario)

    def test_per_layer(self):
        def scenario(h):
            yield from h.tap(BTN_DEC)
            yield from select_layer(h, 1)
            assert h.looper.active_idx == 1
            yield from h.taps(BTN_DEC, 2)
            assert h.synth.channel_volume(1) == 90
            assert h.synth.channel_volume(0) == 95
            yield from h.hold(BTN_INC, 1.0)     # auto-repeat, clamped at 100
            assert h.synth.channel_volume(1) == 100
            assert h.text == "V100"
        run(scenario)

    def test_seq_track(self):
        def scenario(h):
            yield from switch_mode(h)
            yield from select_track(h, 1)
            yield from h.tap(BTN_DEC)
            assert h.synth.track_volume(1) == 95
            assert h.synth.track_volume(0) == 100
            assert h.synth.channel_volume(1) == 100
            assert h.text == "V 95"
            yield 1.1
            assert h.text == "T2  "
        run(scenario)

    def test_menu_takes_over_from_volume_repeat(self):
        def scenario(h):
            h.down(BTN_DEC)
            yield 0.2
            yield from h.tap(BTN_MENU)
            volume = h.synth.channel_volume(0)
            yield 1.0
            assert h.synth.channel_volume(0) == volume
            assert h.text == "SND "
            h.up(BTN_DEC)
            yield 0.05
        run(scenario)

    def test_survives_assign(self):
        def scenario(h):
            yield from select_layer(h, 1)                 # BASS
            yield from h.taps(BTN_DEC, 10)
            assert h.synth.channel_volume(1) == 50
            yield from open_menu_at(h, "ASGN")
            yield from h.tap(BTN_MENU)
            assert h.text == "BASS"
            yield from h.tap(BTN_DEC)
            assert h.text == "KIT "
            yield 0.3                                     # settle: swaps live
            assert h.synth._channels[1]["type"] == "kit"
            yield from h.tap(BTN_MENU)                    # keep it
            assert h.text == "ASGN"
            assert h.synth.channel_volume(1) == 50
            for sound in h.synth._channels[1]["data"]:
                assert abs(fakes.level(sound["notes"][0].amplitude) - sound["params"]["amp"] * 0.5) < 1e-9
        run(scenario)

    def test_assign_list_is_every_instrument(self):
        def scenario(h):
            # Layer 1 holds KIT, so the list starts there.
            names = h.synth.list_instrument_names()
            yield from open_menu_at(h, "ASGN")
            yield from h.tap(BTN_MENU)
            seen = []
            for _ in names:
                seen.append(h.text)
                yield from h.tap(BTN_INC)
            assert seen == names, seen
            yield from h.tap(BTN_RECORD)                  # cancel
            yield 0.3
            assert h.synth.channel_instrument_id(0) == 0
        run(scenario)


class SoundEditTest(unittest.TestCase):
    def test_melodic_list_and_value_editing(self):
        def scenario(h):
            yield from select_layer(h, 1)                 # BASS
            yield from open_menu_at(h, "SND ")
            yield from h.tap(BTN_MENU)
            assert h.text == "BASS"                       # target name first
            yield MSG
            assert h.text == "AMP "
            yield from h.tap(BTN_INC)
            assert h.text == "WAVE"
            yield from h.tap(BTN_MENU)                    # edit
            assert h.text == "SAW "
            yield from h.tap(BTN_INC)
            assert h.text == "TRI "
            assert h.synth.get_channel_param(1, None, "wave") == 3
            yield from h.tap(BTN_MENU)                    # back to the list
            assert h.text == "WAVE"
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_RECORD)                  # back also leaves editing
            assert h.text == "WAVE"
            yield from h.tap(BTN_RECORD)
            assert h.text == "SND "
            yield from h.tap(BTN_MENU)
            yield MSG
            assert h.text == "WAVE", "highlight remembered"
            yield from h.tap(BTN_DEC)
            yield from h.tap(BTN_DEC)
            assert h.text == "RST ", "RST is last, the list wraps"
        run(scenario)

    def test_kit_target_follows_last_pad(self):
        def scenario(h):
            yield from open_menu_at(h, "SND ")
            yield from h.tap(BTN_MENU)
            assert h.text == "KICK"                       # layer 1's last pad: 0
            yield MSG
            assert h.text == "AMP "
            yield from h.pad_tap(4)                       # play the snare
            assert h.text == "SNRE"
            yield MSG
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_DEC)
            assert h.text == "95% ", h.text
            assert abs(h.synth.get_channel_param(0, 4, "amp") - 0.95) < 1e-9
            assert h.synth.get_channel_param(0, 0, "amp") == 1.0
            yield from h.pad_tap(4)                       # same target: no flash
            assert h.text == "95% ", h.text
        run(scenario)

    def test_highlight_remembered_per_schema(self):
        def scenario(h):
            yield from open_menu_at(h, "SND ")            # kit layer 1
            yield from h.tap(BTN_MENU)
            yield MSG
            yield from h.taps(BTN_INC, 2)
            assert h.text == "ATK "
            yield from select_layer(h, 1)                 # BASS: own highlight
            assert h.text == "BASS"
            yield MSG
            assert h.text == "AMP "
            yield from select_layer(h, 0)
            yield MSG
            assert h.text == "ATK "
        run(scenario)

    def test_retarget_to_other_schema_leaves_editing(self):
        def scenario(h):
            yield from select_layer(h, 1)
            yield from open_menu_at(h, "SND ")
            yield from h.tap(BTN_MENU)
            yield MSG
            yield from h.tap(BTN_MENU)                    # editing BASS AMP
            assert h.text == "80% ", h.text
            yield from select_layer(h, 0)                 # kit: back to the list
            yield MSG
            assert h.text == "AMP "
            yield from select_layer(h, 2)                 # REES, same schema
            yield MSG
            yield from h.tap(BTN_MENU)
            yield from select_layer(h, 3)                 # ACID: keeps editing
            yield MSG
            assert h.text == "80% ", h.text
        run(scenario)

    def test_reset_needs_confirm(self):
        def scenario(h):
            yield from switch_mode(h)                     # SEQ: track 1's sound
            yield from open_menu_at(h, "SND ")
            yield from h.tap(BTN_MENU)
            assert h.text == "KICK"
            yield MSG
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_DEC)                     # AMP 95%
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_DEC)                     # wrap to RST
            assert h.text == "RST "
            yield from h.tap(BTN_MENU)
            assert h.text == "SURE"
            assert abs(h.synth.get_drum_param(0, "amp") - 0.95) < 1e-9
            yield from h.tap(BTN_RECORD)                  # back cancels
            assert h.text == "RST "
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_MENU)
            assert h.text == "DONE"
            assert h.synth.get_drum_param(0, "amp") == 1.0
        run(scenario)

    def test_seq_track_change_flashes_name(self):
        def scenario(h):
            yield from switch_mode(h)
            yield from open_menu_at(h, "SND ")
            yield from h.tap(BTN_MENU)
            yield MSG
            yield from select_track(h, 1)
            assert h.text == "DNBK"
        run(scenario)


class GrooveTest(unittest.TestCase):
    def test_slot_labels(self):
        def scenario(h):
            yield from open_menu_at(h, "SAVE")
            yield from h.tap(BTN_MENU)
            assert h.text == "S01 "
            yield from h.tap(BTN_DEC)
            assert h.text == "S16 "
            yield from h.tap(BTN_RECORD)
            yield from h.tap(BTN_INC)
            yield from h.tap(BTN_MENU)
            assert h.text == "L16 "
            yield from h.tap(BTN_MENU)
            assert h.text == "N/A "
        run(scenario)

    def test_volumes_saved_and_loaded(self):
        def scenario(h):
            yield from h.taps(BTN_DEC, 4)                 # layer 1: 80
            yield from switch_mode(h)
            yield from h.taps(BTN_DEC, 2)                 # track 1: 90
            yield 1.1
            yield from open_menu_at(h, "SAVE")
            yield from h.tap(BTN_MENU)
            yield from h.taps(BTN_INC, 2)
            assert h.text == "S03 "
            yield from h.tap(BTN_MENU)
            assert h.text == "DONE"
            yield MSG
            assert h.text == "SAVE"
            yield from h.tap(BTN_INC)
            yield from h.tap(BTN_MENU)
            assert h.text == "L03*"
            yield from h.tap(BTN_RECORD)
            yield from h.tap(BTN_DEC)
            yield from h.tap(BTN_MENU)
            assert h.text == "S03*"
            yield from h.tap(BTN_RECORD)
            yield from h.tap(BTN_RECORD)                  # close
            yield from h.taps(BTN_INC, 2)                 # track 1 back to 100
            h.synth.set_channel_volume(0, 100)
            yield from open_menu_at(h, "LOAD")
            yield from h.tap(BTN_MENU)
            assert h.text == "L03*"
            yield from h.tap(BTN_MENU)
            assert h.text == "DONE"
            assert h.synth.channel_volume(0) == 80
            assert h.synth.track_volume(0) == 90
        run(scenario)

    def test_old_groove_loads_at_full_volume(self):
        h = Harness()
        # A groove from before channel volumes: no layer_vol / track_vol.
        import os
        os.makedirs(h.groove_dir, exist_ok=True)
        with open(h.groove_dir + "/slot2.json", "w") as f:
            json.dump({"v": 1, "bpm": 100, "sync": "none",
                       "sounds": {"kit": [], "layers": []}}, f)

        def scenario(h):
            yield from h.taps(BTN_DEC, 3)
            yield 1.1
            yield from open_menu_at(h, "LOAD")
            yield from h.tap(BTN_MENU)
            yield from h.tap(BTN_INC)
            assert h.text == "L02*"
            yield from h.tap(BTN_MENU)
            assert h.text == "DONE"
            assert h.synth.channel_volume(0) == 100
            assert h.bpm == 100
        h.run(scenario)


if __name__ == "__main__":
    unittest.main()
