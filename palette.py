"""
The key colors, in one place: hue = meaning, brightness = activity (see
the plan's color language). So far what the LED compatibility layer
(pixels.py), the channel view (channel_view.py) and the new function keys
need; the other pad views will add to it. Every value is full-scale RGB --
config.PIXEL_BRIGHTNESS caps them all, so DIM is relative to that cap. All
to be tuned by playing on the device.
"""

DIM = 0.25   # the "state" level (has content, playing): a fraction of full


def scaled(color, level):
    return (int(color[0] * level), int(color[1] * level), int(color[2] * level))


OFF    = (0, 0, 0)
RED    = (255, 0, 0)
ORANGE = (255, 80, 0)
BLUE   = (0, 48, 255)
GREEN  = (0, 255, 0)
WHITE  = (255, 255, 255)

PLAYBACK  = BLUE                # a pad sounding (loop playback, sequencer steps)
RECORDING = RED                 # RECORD key: recording or armed
PLAYING   = scaled(GREEN, DIM)  # PLAY/STOP key: transport running
BEAT      = GREEN               # PLAY/STOP key: the beat pulse
PRESSED   = WHITE               # io_test: a key held down

HAS_CONTENT = scaled(BLUE, DIM)   # channel view: a channel with something in it
MUTED       = scaled(WHITE, DIM)  # grey: content, but silent
ARMED_CLEAR = ORANGE              # CLEAR key: a clear waiting for MENU to confirm
KEY_SELECT  = WHITE               # KEY MODE key: pad taps select
KEY_MUTE    = MUTED               # KEY MODE key: pad taps mute
