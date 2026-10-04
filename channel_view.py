"""
The channel view: every channel's state on the pads, for choosing and
muting channels. VIEW toggles it; code.py handles the pad taps (KEY MODE
select / mute) -- this module only draws.

  pads 0-7  : loop layers 1-8 (the top two rows)
  pads 8-15 : sequencer tracks 1-8 (the bottom two rows)

Colors (palette.py; a starting point to tune on the device):
  empty                        off
  has content                  dim blue
  muted                        dim grey
  a note just played on it     full blue, briefly
  recording / overdubbing      red; blinking while armed or counting in
  the selected channel         its own color, slowly pulsing (empty: blue)

frame() runs a few dozen times a second, so it allocates nothing: it
fills one reused list from colors built at import.
"""

import palette
from config import NUM_LOOP_LAYERS, NUM_TRACKS

_FLASH        = 0.1   # seconds a channel stays bright after playing a note
_BLINK_HZ     = 2.5   # armed / counting-in blink rate
_PULSE_PERIOD = 1.6   # seconds per pulse of the selected channel
_PULSE_STEPS  = 8     # brightness levels in a pulse


def _pulse(color, low, high):
    """The pulse's brightness levels for `color`, low to high."""
    return [palette.scaled(color, low + (high - low) * i / (_PULSE_STEPS - 1))
            for i in range(_PULSE_STEPS)]


_PULSE_CONTENT = _pulse(palette.BLUE, palette.DIM, 0.7)
_PULSE_MUTED   = _pulse(palette.WHITE, palette.DIM, 0.7)
_PULSE_EMPTY   = _pulse(palette.BLUE, 0.03, palette.DIM)


class ChannelView:
    def __init__(self, looper, seq):
        # (mode, first pad, channel count): the looper's layers, then the
        # sequencer's tracks. Both answer channel_status() / played_at().
        self._sources = ((looper, 0, NUM_LOOP_LAYERS),
                         (seq, NUM_LOOP_LAYERS, NUM_TRACKS))
        self._frame = [palette.OFF] * (NUM_LOOP_LAYERS + NUM_TRACKS)

    def frame(self, now, selected_pad):
        """A color per pad. selected_pad: the pad of the selected channel
        (the active mode's layer or track)."""
        phase = (now / _PULSE_PERIOD) % 1.0
        level = int((1.0 - abs(phase * 2 - 1)) * (_PULSE_STEPS - 1) + 0.5)
        blink = int(now * _BLINK_HZ * 2) % 2 == 0
        frame = self._frame
        for source, first, count in self._sources:
            for n in range(count):
                pad      = first + n
                status   = source.channel_status(n)
                selected = pad == selected_pad
                if status == "rec":
                    color = palette.RECORDING
                elif status == "armed":
                    color = palette.RECORDING if blink else palette.OFF
                elif status != "muted" and now - source.played_at(n) < _FLASH:
                    color = palette.PLAYBACK
                elif status == "content":
                    color = _PULSE_CONTENT[level] if selected else palette.HAS_CONTENT
                elif status == "muted":
                    color = _PULSE_MUTED[level] if selected else palette.MUTED
                else:
                    color = _PULSE_EMPTY[level] if selected else palette.OFF
                frame[pad] = color
        return frame
