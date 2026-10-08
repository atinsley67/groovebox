"""
The key colors, in one place: hue = meaning, brightness = activity (see
the colour key at the top of docs/BUTTONS.md). The pad views (pad_views.py) and code.py's
function-key lights take every color from here. Every value is full-scale
RGB -- config.PIXEL_BRIGHTNESS caps them all, so DIM is relative to that
cap. All to be tuned by playing on the device.
"""

DIM = 0.25   # the "state" level (has content, playing): a fraction of full


def scaled(color, level):
    return (int(color[0] * level), int(color[1] * level), int(color[2] * level))


OFF     = (0, 0, 0)
RED     = (255, 0, 0)
ORANGE  = (255, 80, 0)
YELLOW  = (255, 190, 0)
GREEN   = (0, 255, 0)
CYAN    = (0, 200, 255)
BLUE    = (0, 48, 255)
PURPLE  = (150, 0, 255)
WHITE   = (255, 255, 255)

# ── Pads ──────────────────────────────────────────────────────────────────────
PLAYBACK    = BLUE                  # a note sounding: loop playback, a step firing
LIVE        = YELLOW                # your own press, not recording
RECORDING   = RED                   # your own press while recording / overdubbing
HAS_CONTENT = scaled(GREEN, DIM)     # a channel with something in it; an on-step
MUTED       = scaled(YELLOW, DIM)    # grey: content, but silent
PLAYHEAD    = scaled(WHITE, 0.5)    # the step being played (off-step)
ROOT_NOTE   = scaled(PURPLE, DIM)     # an idle melodic pad playing the key's tonic

# ── Function keys ─────────────────────────────────────────────────────────────
PLAYING     = scaled(GREEN, DIM)    # PLAY/STOP: transport running
BEAT        = GREEN                 # PLAY/STOP: the beat pulse
LOOP_MODE   = scaled(CYAN, DIM)     # LOOP/SEQ: in LOOP
SEQ_MODE    = scaled(PURPLE, DIM)   # LOOP/SEQ: in SEQ
ARMED_CLEAR = ORANGE                # CLEAR: a clear waiting for MENU to confirm
KEY_SELECT  = WHITE                 # KEY MODE: pad taps select
KEY_MUTE    = MUTED                 # KEY MODE: pad taps mute
KEY_ARP     = YELLOW                # KEY MODE: the active layer's arp is on
PRESSED     = WHITE                 # MENU / UP / DOWN / VIEW while held; io_test
MENU_OPEN   = scaled(WHITE, DIM)    # MENU: the menu is open
