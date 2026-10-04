import board

# ── Which button / LED hardware is wired up ───────────────────────────────────
# "breadboard": 8 loose pad buttons + 7 function buttons, LEDs on the AW9523.
# "neokey":     the NeoKey 4x4 pad grid + 2x5 function block, a NeoPixel
#               under every key (see the NeoKey section below, and
#               NEOKEY_BRINGUP.md). Only one is wired at a time, so the two
#               reuse the same GPIOs.
HARDWARE = "neokey"

# ── I2S DAC (Adafruit UDA1334A or similar) ───────────────────────────────────
# Right column (top breadboard, next to the DAC) — keeps peripheral wiring off
# the bottom breadboard entirely.
I2S_DATA_OUT    = board.GP18
I2S_BIT_CLOCK   = board.GP19
I2S_WORD_SELECT = board.GP20

# ── I2C shared bus ────────────────────────────────────────────────────────────
# Right column; GP16/GP17 is a valid I2C0 SDA/SCL pair.
I2C_SDA = board.GP16
I2C_SCL = board.GP17

# 400 kHz (I2C fast mode, which both chips support) makes every display and
# LED write ~4x quicker than the 100 kHz default. If the display or LEDs
# glitch, or the board fails to start, go back to 100000.
I2C_FREQUENCY = 400000

ALPHANUM_ADDR   = 0x70  # Adafruit quad 14-segment display (HT16K33)
LED_DRIVER_ADDR = 0x5B  # Adafruit AW9523 GPIO/LED driver with address pins soldered to make LEDS off at startup (breadboard only)

# ── Breadboard: 8 pad buttons (active-low, internal pull-up) ─────────────────
# Left column (bottom breadboard) — shortest, straight-down runs to the pads.
PAD_PINS = [
    board.GP0, board.GP1, board.GP2, board.GP3,
    board.GP4, board.GP5, board.GP6, board.GP7,
]

# ── Breadboard: function buttons (active-low, internal pull-up) ──────────────
# Left column (bottom breadboard) — same side as the pads, GP15 left spare.
BTN_MODE_PIN      = board.GP8   # cycle layer/track (short), switch mode (long), select channel (hold+pad)
BTN_RECORD_PIN    = board.GP9   # arm record / cycle step page
BTN_PLAY_STOP_PIN = board.GP10  # global play/pause (short), clear active mode (2 s long)
BTN_INC_PIN       = board.GP11  # UP: active channel's volume up; menu: highlight / value up
BTN_DEC_PIN       = board.GP12  # DOWN: active channel's volume down; menu: highlight / value down
BTN_MUTE_PIN      = board.GP13  # mute/unmute active layer (short), clear active layer (0.6 s long)
BTN_MENU_PIN      = board.GP14  # open the MENU overlay; "select" while it's open

# ── Button identifiers (payload in BTN_DOWN / BTN_UP events) ─────────────────
BTN_MODE        = "mode"
BTN_RECORD      = "rec"
BTN_PLAY_STOP   = "play"
# The UP / DOWN keys. Not BTN_UP / BTN_DOWN: those are the button
# press/release event types (event_types.py).
BTN_INC         = "inc"
BTN_DEC         = "dec"
BTN_MUTE        = "mute"
BTN_MENU        = "menu"
BTN_VIEW        = "view"   # NeoKey only; does nothing until the pad views exist

# ── NeoKey ────────────────────────────────────────────────────────────────────
# Pins: the board's own row and column lines, as labelled on each piece.
# (hw_neokey.py hands them to keypad swapped -- an RP2350 workaround, see
# there; wire them as named here.) Each piece's lines run in order along
# the Pico's left header, so one ribbon per piece lands on one stretch of
# it: the pad grid on header pins 1-11, the function block on 12-20 (the
# GND pins inside each stretch give that piece its pixel ground). Spare
# after this: GP21, GP26-GP28.
PAD_ROW_PINS   = [board.GP2, board.GP3, board.GP4, board.GP5]
PAD_COL_PINS   = [board.GP7, board.GP8, board.GP0, board.GP1]
PAD_PIXEL_PIN  = board.GP6    # pad grid NeoPixel data (330-470 ohm in series)
FUNC_COL_PINS  = [board.GP10, board.GP11]                                 # the piece's 2 rows
FUNC_ROW_PINS  = [board.GP12, board.GP13, board.GP14, board.GP15, board.GP22]  # its 5 columns
FUNC_PIXEL_PIN = board.GP9   # function block NeoPixel data (330-470 ohm in series)

# Key scanning (keypad, in the background). A change is reported once it has
# been seen on KEY_DEBOUNCE_THRESHOLD scans in a row, KEY_SCAN_INTERVAL
# apart: raise the threshold if a key ever double-triggers.
KEY_SCAN_INTERVAL      = 0.004   # seconds
KEY_DEBOUNCE_THRESHOLD = 2
# Subtracted from every key timestamp, so a recorded press lands where you
# played it. keypad stamps the scan that confirms a change: on average half
# a scan after the contact, plus the extra scans of the threshold.
KEY_TIME_ADJUST = (KEY_DEBOUNCE_THRESHOLD - 0.5) * KEY_SCAN_INTERVAL

# NeoPixel brightness cap (0.0-1.0) for both strips. USB powers everything,
# and the pixels run at ~4.3 V: start low, tune on the device.
PIXEL_BRIGHTNESS = 0.2

# Layout tables, each written as you look at the piece (top row first).
# KEYS tables hold the keypad key number at each position, PIXELS tables
# the NeoPixel index under it -- both found with io_test.py on the device
# (it shows each key's number as you press it, and walks the pixels in
# order). The defaults are a best guess until then.
#
# Pad n is the n-th position reading row by row from the top left, so the 8
# musical pads (NUM_PADS) are the top two rows.
PAD_KEYS = [
    [0, 4,  8, 12],
    [1, 5,  9, 13],
    [2, 6, 10, 14],
    [3, 7, 11, 15],
]
PAD_PIXELS = [
    [0,   1,  2,  3],
    [7,   6,  5,  4],
    [8,   9, 10, 11],
    [15, 14, 13, 12],
]

# The function block, standing as 5 rows x 2 columns. FUNC_LAYOUT is which
# button each key is -- rearrange freely; None = unassigned (no events).
FUNC_LAYOUT = [
    [BTN_MODE,   BTN_INC],
    [BTN_MENU,   BTN_DEC],
    [BTN_RECORD, BTN_PLAY_STOP],
    [BTN_MUTE,   BTN_VIEW],
    [None,       None],
]
FUNC_KEYS = [
    [0, 5],
    [1, 6],
    [2, 7],
    [3, 8],
    [4, 9],
]
FUNC_PIXELS = [
    [0, 1],
    [3, 2],
    [4, 5],
    [7, 6],
    [8, 9],
]

# ── Diagnostics ───────────────────────────────────────────────────────────────
# True: print main-loop timing to the serial console every 5 s (see
# timing_probe.py). Leave False for normal playing.
TIMING_PROBE = True

# ── Audio ─────────────────────────────────────────────────────────────────────
SAMPLE_RATE = 22050
NUM_PADS    = 8

# ── Sequencer ─────────────────────────────────────────────────────────────────
DEFAULT_BPM   = 120
STEPS_PER_BAR = 16
NUM_TRACKS    = 8

# ── Looper ────────────────────────────────────────────────────────────────────
NUM_LOOP_LAYERS = 8
MAX_LOOP_EVENTS = 256   # per layer
# Each layer's instrument is assigned from the menu (default: layer 0 = drum
# kit, layers 1-7 = melodic voices) -- see sound_presets.INSTRUMENT_NAMES.

# ── Modes ─────────────────────────────────────────────────────────────────────
MODE_LOOPER    = 0
MODE_SEQUENCER = 1
MODE_GAME      = 2
NUM_MODES      = 2  # game not yet implemented

MODE_NAMES = ["LOOP", "SEQ "]

# ── Status LED layout (the modes' 16-LED bitmask) ─────────────────────────────
# LEDs 0-7:  primary status (step on/off, pad-in-loop indicators)
# LEDs 8-15: secondary status (playback position, record/play state)
# Breadboard: AW9523 pins. NeoKey: LEDs 0-7 are pads 0-7, LED_RECORD the
# RECORD key, LED_PLAY + LED_BEAT the PLAY/STOP key (see pixels.py).
LED_RECORD   = 8   # lit while recording (not while armed / counting in)
LED_PLAY     = 9   # lit while playing
LED_BEAT     = 10  # pulses on each beat
