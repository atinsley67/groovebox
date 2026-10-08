"""
The pad views: each draws a color per pad from a mode's state, for code.py
to send (DisplayManager.set_pad_frame). VIEW switches between the active
mode's own view and the channel view; colors come from palette.py, and
are a starting point to tune on the device.

  KeyboardView  LOOP's own view: the active layer's pads
  StepView      SEQ's own view: the selected track's 16 steps
  ChannelView   every channel at once, for choosing and muting them

frame() runs up to ~60 times a second, so none of them allocate: each
fills one reused list from colors built at import (or construction).
"""

import palette
from config import NUM_LOOP_LAYERS, NUM_PADS, NUM_TRACKS, STEPS_PER_BAR


class KeyboardView:
    """The active loop layer, as you play it:
      your press, not recording     yellow
      your press while recording    red (recording or overdubbing it)
      the arp's note (arp on)       white: a playhead over your chord
      playback hitting the pad      blue, briefly
      a live press beats playback, so you can see your fingers in an overdub
      idle                          off
    With the layer's arp on, "your press" is the fingers (arp.held_mask),
    not the arp's notes (which the looper counts as held).
    """

    def __init__(self, looper, arp):
        self._looper = looper
        self._arp    = arp
        self._frame  = [palette.OFF] * NUM_PADS

    def frame(self, now):
        looper = self._looper
        arp    = self._arp
        if arp.is_on(looper.active_idx):
            held = arp.held_mask
            note = arp.note_pad
        else:
            held = looper.held_mask
            note = None
        flash  = looper.flash_mask
        press  = palette.RECORDING if looper.capturing else palette.LIVE
        frame  = self._frame
        for pad in range(NUM_PADS):
            bit = 1 << pad
            if pad == note:
                frame[pad] = palette.PLAYHEAD
            elif held & bit:
                frame[pad] = press
            elif flash & bit:
                frame[pad] = palette.PLAYBACK
            else:
                frame[pad] = palette.OFF
        return frame


class StepView:
    """The selected track's bar, step n on pad n:
      on-step                       dim blue (dim grey on a muted track)
      the playhead                  white
      an on-step under the playhead full blue as it fires
    """

    def __init__(self, seq):
        self._seq   = seq
        self._frame = [palette.OFF] * NUM_PADS

    def frame(self, now):
        seq      = self._seq
        steps    = seq.selected_steps
        muted    = seq.selected_muted
        on_color = palette.MUTED if muted else palette.HAS_CONTENT
        playhead = seq.current_step if seq.playing else -1
        frame    = self._frame
        for pad in range(NUM_PADS):
            on = pad < STEPS_PER_BAR and steps[pad]
            if pad == playhead:
                frame[pad] = palette.PLAYBACK if on and not muted else palette.PLAYHEAD
            else:
                frame[pad] = on_color if on else palette.OFF
        return frame


# ── The channel view ──────────────────────────────────────────────────────────

_FLASH    = 0.1   # seconds a channel stays bright after playing a note
_BLINK_HZ = 2.5   # armed / counting-in blink rate


class ChannelView:
    """Every channel's state, loop layers 1-8 on pads 0-7 (the top two
    rows) and sequencer tracks 1-8 on pads 8-15 (the bottom two). code.py
    handles the taps (KEY MODE select / mute). The selected channel isn't
    marked: a pulse there hid its own activity.
      empty                        off
      has content                  palette.HAS_CONTENT
      muted                        palette.MUTED
      a note just played on it     palette.PLAYBACK, briefly
      recording / overdubbing      red; blinking while armed or counting in
    """

    def __init__(self, looper, seq):
        # (mode, first pad, channel count): the looper's layers, then the
        # sequencer's tracks. Both answer channel_status() / played_at().
        self._sources = ((looper, 0, NUM_LOOP_LAYERS),
                         (seq, NUM_LOOP_LAYERS, NUM_TRACKS))
        self._frame = [palette.OFF] * NUM_PADS

    def frame(self, now):
        blink = int(now * _BLINK_HZ * 2) % 2 == 0
        frame = self._frame
        for source, first, count in self._sources:
            for n in range(count):
                status = source.channel_status(n)
                if status == "rec":
                    color = palette.RECORDING
                elif status == "armed":
                    color = palette.RECORDING if blink else palette.OFF
                elif status != "muted" and now - source.played_at(n) < _FLASH:
                    color = palette.PLAYBACK
                elif status == "content":
                    color = palette.HAS_CONTENT
                elif status == "muted":
                    color = palette.MUTED
                else:
                    color = palette.OFF
                frame[first + n] = color
        return frame
