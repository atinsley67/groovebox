import board

# Hardware: a NeoKey 4x4 pad grid + 2x5 function block, a NeoPixel under
# every key, an I2S DAC and an HT16K33 4-char display. Wiring, calibration
# and tuning: HARDWARE.md.

# ── I2S DAC (Adafruit UDA1334A or similar) ───────────────────────────────────
I2S_DATA_OUT    = board.GP18
I2S_BIT_CLOCK   = board.GP19
I2S_WORD_SELECT = board.GP20

# ── I2C (the display) ─────────────────────────────────────────────────────────
# GP16/GP17 is a valid I2C0 SDA/SCL pair.
I2C_SDA = board.GP16
I2C_SCL = board.GP17

# 400 kHz (I2C fast mode, which the display supports) makes every display
# write ~4x quicker than the 100 kHz default. If the display glitches, or
# the board fails to start, go back to 100000.
I2C_FREQUENCY = 400000

ALPHANUM_ADDR   = 0x70  # Adafruit quad 14-segment display (HT16K33)

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
BTN_VIEW        = "view"   # does nothing until the pad views exist

# ── NeoKey pins ───────────────────────────────────────────────────────────────
# ROW pins are the lines on the diodes' anode side, COL pins the cathode
# side (hw.py hands them to keypad swapped -- an RP2350 workaround, see
# there). On the pad grid that matches the board's own row/column labels;
# the function block's diodes run the other way, so its labelled rows are
# its COL pins here. Spare: GP21, GP26-GP28.
PAD_ROW_PINS   = [board.GP2, board.GP3, board.GP4, board.GP5]
PAD_COL_PINS   = [board.GP7, board.GP8, board.GP0, board.GP1]
PAD_PIXEL_PIN  = board.GP6    # pad grid NeoPixel data (330-470 ohm in series)
FUNC_ROW_PINS  = [board.GP12, board.GP13, board.GP14, board.GP15, board.GP22]  # the piece's 5 labelled columns
FUNC_COL_PINS  = [board.GP10, board.GP11]                                     # its 2 labelled rows
FUNC_PIXEL_PIN = board.GP9    # function block NeoPixel data (330-470 ohm in series)

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
# order; see HARDWARE.md).
#
# Pad n is the n-th position reading row by row from the top left (pads 0-3
# are the top row). Kit sounds and sequencer steps follow that order;
# melodic notes run the other way up, lowest at the bottom left (see
# keymap.NOTE_OF_PAD).
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
TIMING_PROBE = False

# ── Audio ─────────────────────────────────────────────────────────────────────
SAMPLE_RATE = 22050
NUM_PADS    = 16

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

# ── Status LED layout (the modes' LED bitmask) ────────────────────────────────
# Bits 0..NUM_PADS-1 are the pads (step on/off, pad sounding); the bits
# below sit above them: LED_RECORD is the RECORD key, LED_PLAY + LED_BEAT
# the PLAY/STOP key (see pixels.py). Replaced by colors once the pad views
# exist.
LED_RECORD   = 16  # lit while recording (not while armed / counting in)
LED_PLAY     = 17  # lit while playing
LED_BEAT     = 18  # pulses on each beat
