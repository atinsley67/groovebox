import board

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
LED_DRIVER_ADDR = 0x5B  # Adafruit AW9523 GPIO/LED driver with address pins soldered to make LEDS off at startup

# ── 8 pad buttons (active-low, internal pull-up) ─────────────────────────────
# Left column (bottom breadboard) — shortest, straight-down runs to the pads.
PAD_PINS = [
    board.GP0, board.GP1, board.GP2, board.GP3,
    board.GP4, board.GP5, board.GP6, board.GP7,
]

# ── Function buttons (active-low, internal pull-up) ──────────────────────────
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

# ── Diagnostics ───────────────────────────────────────────────────────────────
# True: print main-loop timing to the serial console every 5 s (see
# timing_probe.py). Leave False for normal playing.
TIMING_PROBE = False

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

# ── AW9523 LED layout ─────────────────────────────────────────────────────────
# LEDs 0-7:  primary status (step on/off, pad-in-loop indicators)
# LEDs 8-15: secondary status (playback position, record/play state)
LED_RECORD   = 8   # lit while recording or armed
LED_PLAY     = 9   # lit while playing
LED_BEAT     = 10  # pulses on each beat
