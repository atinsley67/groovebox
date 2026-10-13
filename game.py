"""
ECHO: a rhythm game hidden in the groovebox. Hold MENU while it starts up,
then press PLAY.

How it plays
------------
A backing groove runs from the count-in to game over and never stops. Over
it, the box and you take turns, 2 bars each, so every round is 4 bars:

  ME   The box plays a short phrase on the pads, lighting each pad it plays.
       The function keys glow cyan.
  YOU  You play it back, in time. The function keys glow yellow.

The last 4 beats before your turn always get a count: the display counts
4 3 2 1 and the keys fade from cyan to yellow, with a stick click on each
beat (woodblock, woodblock, woodblock, rimshot) that comes after the
phrase's last note -- none lands on a note. The last 4 beats of your turn
get the same count, softer, fading back to cyan for the box's turn.

Each stage has one phrase. Round 1 plays its 2 most important notes (the
ones on the strongest beats: beat 1, then 3); every clean round adds the
next one (beats 2 and 4, then the off-beats, then 16ths), so the phrase
fills in like a build. A stage takes at most MAX_ROUNDS clean rounds, so a
long phrase starts with more of it in play. Each melody spans a band of 2
to 4 of the lit pad rows, placed over the rows left longest unplayed, so
over a few stages every row comes round. Play it all back and the stage
is clear: a crash on the next downbeat. The early stages bring variety,
not skill -- a new melody, voice and key, more pads, the track building
up -- and only then do the stages start, one step at a time, on speed,
rhythm and the round's shape (see STAGES), so it stays kid-friendly for a
good while.

Your notes always sound. A wrong pad (OOPS) or a missed note (MISS) is a
strike: at most one a round. The round repeats, and the track's top layer
drops out until you play a clean one. Three strikes and it's over; a stage
clear gives one back. PLAY starts again.

Keys: PLAY starts (blinking green when it's waiting). MENU opens a list
like the groovebox's -- TOP (the top 10), RST (back to the start) and QUIT
(back to the groovebox) -- UP / DOWN move, MENU picks, RECORD closes. With
the menu closed, UP / DOWN set the volume.

The top 10
----------
A score that makes the top 10 (game_scores.py, kept on the drive) gets a
name. After the game-over sting the display shows its place ("*03"),
then the name -- the last one entered, to start from -- with the letter
being edited flashing: UP / DOWN change it (held, they run
through the letters), MENU takes it and moves on, RECORD goes back one.
"_" is a blank, for a shorter name (saved as a space). After the fourth
it's saved ("DONE"). The menu's TOP shows the board: each entry's
place, name and score in turn; UP / DOWN go through them, MENU or RECORD
back to the list.

The shape of a round
--------------------
The box has 2 bars (ME_STEPS) and so do you (YOU_STEPS). The count always
fills the box's last 4 beats, the count-out yours. What changes is how
much of the box's 2 bars the phrase fills (SHAPES): the gap before your
turn shrinks from a whole bar (shape A) to 2 beats (B) to none (C), and
the same gap follows your turn. The game opens with a demo round: the box
plays your part too, on your voice, so you see the spacing before you
play it. The count-in says DEMO in place of GO, and the demo says GO over
its last 2 beats, just before the real thing. (Later shapes get no demo:
mid-game, one reads as a round to copy.)

Judging
-------
A note's target is the start of your turn plus its place in the phrase.
A press on the right pad within the stage's window of an unmatched target
is a hit: NICE within NICE_SHARE of the window, otherwise EARL or LATE. The
window starts at 150 ms and tightens with the speed steps, and is never
more than 45% of the phrase's shortest gap, so two notes can't both claim
a press. Presses before the first target's window or after the last one's
aren't judged.

The code
--------
compose() and Game hold all the logic and touch the hardware only through
the synth and display they're given, so the tests drive them with fakes.
run() is the thin hardware loop. Like the groovebox, the main loop
allocates nothing: the phrase lives in fixed bytearrays and the patterns
are constants.
"""

import random
from array import array

import config
import game_scores
import keymap
import palette
import scales
from event_types import BTN_DOWN, PAD_DOWN, PAD_UP
from sound_presets import INSTRUMENT_NAMES
from synth_params import WAVEFORM_NAMES

# ── Tuning ────────────────────────────────────────────────────────────────────
# Added to every press time before judging, in seconds: raise it if on-time
# presses keep reading LATE (lower it for EARL).
AUDIO_OFFSET = 0.0
NICE_SHARE   = 0.4    # a hit this close (share of the window) is NICE
WINDOW_GAP_SHARE = 0.45   # the window's cap, as a share of the shortest gap
MAX_BPM      = 140
MAX_ROUNDS   = 4      # clean rounds a stage takes at most (see _start_stage)
LIVES        = 3
VOLUME       = 100    # % to start at; UP / DOWN step it
VOLUME_STEP  = 5

# ── The round ─────────────────────────────────────────────────────────────────
STEPS_PER_BAR  = 16
ME_STEPS       = 32   # the box's turn: 2 bars
YOU_STEPS      = 32   # yours: 2 bars
COUNT_STEPS    = 16   # the stick count: the 4 beats before your turn
COUNT_IN_STEPS = 16   # the bar before the first round

# Round shapes: how many steps of the box's 2 bars the phrase may span.
SHAPE_A, SHAPE_B, SHAPE_C = 0, 1, 2
SHAPES = (
    16,   # A: beats 1-4, then a whole bar of count; a bar's rest after you
    24,   # B: beats 1-6, 2 beats of gap either side
    32,   # C: beats 1-8, no gap
)

# Rhythm cells: one beat's 4 steps, bit n = step n of the beat.
_Q   = 0b0001   # x...
_R   = 0b0000   # ....
_E   = 0b0101   # x.x.
_OFF = 0b0100   # ..x.
_DOT = 0b1001   # x..x
_S3  = 0b1011   # xx.x
_S4  = 0b1111   # xxxx
_CELL_NOTES = bytes((0, 1, 1, 2, 1, 2, 2, 3, 1, 2, 2, 3, 2, 3, 3, 4))  # bits set

# The stages. Two kinds of change, kept apart:
#   variety -- a new phrase every stage, the lead voice, the key, more pads,
#              the backing layers, a note more to remember
#   skill   -- the tempo and timing window ("speed"), a new rhythm cell, a
#              tighter round shape
# The first 8 stages are all variety: quarter notes at 90 BPM, in the widest
# window. After that, each stage takes at most one skill step. A stage's
# phrase has `notes` notes, so it takes notes - 1 clean rounds, or
# MAX_ROUNDS if that's fewer. From the last row on, each stage repeats it
# 5 BPM faster (up to MAX_BPM).
_SHAPE, _BPM, _ROWS, _CELLS, _NOTES, _WINDOW, _LAYERS, _VOICE, _KEY = 0, 1, 2, 3, 4, 5, 6, 7, 8
_A, _C, _D, _E_KEY, _G = 9, 0, 2, 4, 7   # keys (scales.KEY_NAMES)
_EIGHTHS = (_Q, _R, _E)
_OFFBEAT = (_Q, _R, _E, _OFF)
_DOTTED  = (_Q, _R, _E, _OFF, _DOT)
_ALL     = (_Q, _R, _E, _OFF, _DOT, _S3, _S4)
STAGES = (
    # shape   bpm rows cells     notes  ms layers voice   key       the step
    (SHAPE_A,  90, 1, (_Q, _R),   3, 150, 1, "PLUK", _A),
    (SHAPE_A,  90, 1, (_Q, _R),   4, 150, 2, "PLUK", _A),
    (SHAPE_A,  90, 2, (_Q, _R),   4, 150, 2, "MALL", _C),
    (SHAPE_A,  90, 2, (_Q, _R),   4, 150, 3, "MALL", _C),
    (SHAPE_A,  90, 2, (_Q, _R),   4, 150, 3, "KALI", _D),
    (SHAPE_A,  90, 3, (_Q, _R),   4, 150, 4, "KALI", _D),
    (SHAPE_A,  90, 3, (_Q, _R),   4, 150, 4, "ORGN", _G),
    (SHAPE_A,  90, 3, (_Q, _R),   4, 150, 5, "ORGN", _G),
    (SHAPE_A,  90, 3, _EIGHTHS,   5, 150, 5, "PLUK", _A),     # eighths
    (SHAPE_A,  95, 3, _EIGHTHS,   5, 140, 5, "MALL", _C),     # speed
    (SHAPE_A,  95, 4, _EIGHTHS,   5, 140, 5, "KALI", _D),
    (SHAPE_B,  95, 3, _EIGHTHS,   5, 140, 5, "ORGN", _G),     # shape B
    (SHAPE_B, 100, 3, _EIGHTHS,   6, 130, 5, "PLUK", _E_KEY), # speed
    (SHAPE_B, 100, 4, _OFFBEAT,   6, 130, 5, "MALL", _A),     # off-beats
    (SHAPE_B, 105, 4, _OFFBEAT,   6, 120, 5, "KALI", _C),     # speed
    (SHAPE_B, 105, 4, _DOTTED,    6, 120, 5, "ORGN", _D),     # dotted
    (SHAPE_C, 105, 4, _DOTTED,    7, 120, 5, "PLUK", _G),     # shape C
    (SHAPE_C, 110, 4, _DOTTED,    7, 110, 5, "MALL", _A),     # speed
    (SHAPE_C, 110, 4, _ALL,       8, 110, 5, "KALI", _C),     # 16ths
    (SHAPE_C, 115, 4, _ALL,       8, 100, 5, "ORGN", _D),     # speed
)
MAX_NOTES = 10

# ── Sounds ────────────────────────────────────────────────────────────────────
# Loop layers of the synth engine, at their defaults except where set up in
# Game.__init__.
KIT, BASS, PLAYER, CHORDS, CALL = 0, 1, 2, 4, 5
_GAME_LAYERS = (KIT, BASS, PLAYER, CHORDS, CALL)
_PLUK = INSTRUMENT_NAMES.index("PLUK")
_CHRD = INSTRUMENT_NAMES.index("CHRD")
# The lead voices: name -> (instrument, octaves moved, SOUND params). Each
# is moved from where the groovebox has it so its bottom pad is A3 (in the
# key of A): down out of the thin, out-of-tune top register the 3-octave
# pad range reaches; the organ up. KALI is the game's own: the marimba's
# short envelope on a triangle, darker -- a soft kalimba, clean where the
# groovebox's BELL rings on inharmonic partials that clash with the chord.
_TRI = WAVEFORM_NAMES.index("TRI ")
_LEADS = {
    "PLUK": ("PLUK", -2, ()),
    "MALL": ("MALL", -1, ()),
    "KALI": ("MALL", -1, (("wave", _TRI), ("cutoff", 3500.0))),
    "ORGN": ("ORGN",  1, ()),
}

# Kit pads (sound_presets.KIT_SOUND_BUILDERS).
_KICK, _CHH, _OHH, _CLAP, _WOOD, _RIM, _SHKR, _CRSH = 0, 2, 3, 5, 7, 11, 12, 15

# Backing patterns, bit n = step n of the bar.
_KICK_STEPS   = 0x1111   # four on the floor
_HAT_STEPS    = 0x4444   # off-beats
_CLAP_STEPS   = 0x1010   # 2 and 4
_CHORD_STEPS  = 0x4040   # the off-beats of 2 and 4
_SHAKER_STEPS = 0xAAAA   # the 16ths between the 8ths
_OPEN_HAT_STEPS = 0x4000 # the bar's last off-beat, in place of the closed hat
_NO_NOTE = 255
# The bass riff, a scale note (keymap.NOTE_OF_PAD) per step: root on the
# off-beats, up to the 5th and the 7th in the second half.
_BASS_NOTES = bytes((_NO_NOTE, _NO_NOTE, 0, _NO_NOTE, _NO_NOTE, _NO_NOTE, 0, _NO_NOTE,
                     _NO_NOTE, _NO_NOTE, 3, _NO_NOTE, _NO_NOTE, _NO_NOTE, 4, _NO_NOTE))
_BASS_PADS = bytes([_NO_NOTE if n == _NO_NOTE else keymap.PAD_OF_NOTE[n]
                    for n in _BASS_NOTES])
_BASS_GATE  = 1.5         # steps
# The bass, softened so its attack doesn't mask the game's notes: a sine
# with overtones for BASS's saw, eased in, and darker. (Its SOUND params.)
_SOFT_BASS  = (("wave", WAVEFORM_NAMES.index("SUB ")), ("attack", 0.035),
               ("cutoff", 700.0), ("resonance", 0.7))
# The chord stab, pushed back behind the melody, which shares its register:
# darker, and quieter than the rest of the game.
_SOFT_CHORD  = (("cutoff", 1600.0), ("resonance", 0.8))
_CHORD_SHARE = 0.7        # of the game's volume
# The count-out: the count-in's woodblock, quieter. The synth's sequencer
# kit has its own copy of the woodblock (its track 7) with its own volume.
_SOFT_WOOD  = 7
_SOFT_SHARE = 0.45        # of the game's volume
_CHORD_PAD  = keymap.PAD_OF_NOTE[0]
_CALL_GATE  = 0.7         # share of the gap to the next note
_STING_NOTES = (3, 2, 0)  # the game-over "wah-wah-wahh": 5th, 4th, root

_SCALE_LEN = len(scales.SCALES[scales.DEFAULT_SCALE][1])
_ROOT_PADS = scales.root_mask(scales.DEFAULT_SCALE)
_ROW_PADS  = len(config.PAD_KEYS[0])

# ── States ────────────────────────────────────────────────────────────────────
# NAME: a top-10 score's name being entered, after the game-over sting.
TITLE, COUNT_IN, PLAY, STING, OVER, NAME = 0, 1, 2, 3, 4, 5
_PENDING, _HIT, _MISSED = 0, 1, 2

# ── The menu ──────────────────────────────────────────────────────────────────
MENU_ITEMS = ("TOP ", "RST ", "QUIT")
_MENU_TOP, _MENU_RESET, _MENU_QUIT = 0, 1, 2
_VIEW_SWAP = 0.7    # seconds each of a top-10 entry's rank, name and score shows

# ── The name editor (a top-10 score) ──────────────────────────────────────────
_NAME_KEYS = (config.BTN_INC, config.BTN_DEC, config.BTN_MENU, config.BTN_RECORD)
_NAME_KEY_LIT     = palette.MENU_OPEN
_NAME_BLINK_HZ    = 2.0    # the letter being edited, against empty
_NAME_REPEAT_WAIT = 0.4    # UP / DOWN held this long start repeating...
_NAME_REPEAT_GAP  = 0.12   # ...a letter every this long
_RANK_HOLD        = 1.5    # "*03 " before the editor

# ── Display ───────────────────────────────────────────────────────────────────
_COUNT_IN_TEXT = ("  3 ", "  2 ", "  1 ", " GO ")
_COUNT_TEXT    = ("  4 ", "  3 ", "  2 ", "  1 ")
_PRAISE = ("YEAH", "SICK", "TUFF", "DOPE", "WAVY", "FIRE", "COOL")
_GRADE_HOLD = 0.3
_SWAP       = 1.0   # seconds between the two words on the title / game over

# ── Lights ────────────────────────────────────────────────────────────────────
_FRAME_INTERVAL = 1 / 60
_BEAT_FLASH = 0.08
_PLAY_BLINK_HZ = 2.0   # PLAY, waiting to be pressed

_FLASH_NONE, _FLASH_CALL, _FLASH_HIT, _FLASH_WRONG, _FLASH_MISS, _FLASH_DEMO = 0, 1, 2, 3, 4, 5
_FLASH_COLORS = (palette.OFF, palette.PLAYBACK, palette.GAME_HIT, palette.RED,
                 palette.WHITE, palette.LIVE)
_HIT_FLASH, _WRONG_FLASH, _MISS_FLASH = 0.2, 0.3, 0.4

_AREA       = palette.scaled(palette.WHITE, 0.08)
_AREA_PULSE = palette.scaled(palette.YELLOW, 0.4)
_LIFE       = palette.scaled(palette.RED, 0.5)
_OVER_KEYS  = palette.scaled(palette.RED, palette.DIM)


def _rank_text(rank):
    """A top-10 place (0 = the top) as shown: "*01 ". (Not "#": on the
    14-segment display it looks like a B.)"""
    return f"*{rank + 1:02d} "


def _mix(a, b, share):
    return (int(a[0] + (b[0] - a[0]) * share), int(a[1] + (b[1] - a[1]) * share),
            int(a[2] + (b[2] - a[2]) * share))


def _fade_keys(start, end):
    """(steady, beat flash) for each beat of a count, from `start`'s colour
    to `end`'s, a step a beat."""
    return tuple(
        (palette.scaled(_mix(start, end, (beat + 1) / 4), palette.DIM),
         _mix(start, end, (beat + 1) / 4))
        for beat in range(4))


# The function block's cue: (steady, beat flash) per phase. The count fades
# from the box's cyan to your yellow, the count-out back again.
_ME_KEYS  = (palette.GAME_CALL, palette.CYAN)
_YOU_KEYS = (palette.scaled(palette.YELLOW, palette.DIM), palette.YELLOW)
_COUNT_KEYS     = _fade_keys(palette.CYAN, palette.YELLOW)
_COUNT_OUT_KEYS = _fade_keys(palette.YELLOW, palette.CYAN)


# ── The phrase ────────────────────────────────────────────────────────────────

class Phrase:
    """A stage's phrase, in time order: note i plays at `steps[i]` (from
    the start of its turn) on pad `pads[i]` (scale note `notes[i]`), and is
    revealed in round `rank[i]` order -- the round 1 skeleton first."""

    def __init__(self):
        self.n     = 0
        self.steps = bytearray(MAX_NOTES)
        self.pads  = bytearray(MAX_NOTES)
        self.notes = bytearray(MAX_NOTES)
        self.rank  = bytearray(MAX_NOTES)


def stage_row(stage):
    """STAGES' row for `stage` (0 = the first), past the table's end the
    last row 5 BPM faster a stage."""
    if stage < len(STAGES):
        return STAGES[stage]
    last = STAGES[-1]
    bpm  = min(MAX_BPM, last[_BPM] + 5 * (stage - len(STAGES) + 1))
    return (last[_SHAPE], bpm) + last[_ROWS:]


def beat_strength(step):
    """0 for the strongest place in a phrase (a bar's downbeat) to 4 (a
    16th between 8ths)."""
    if step % 16 == 0:
        return 0
    if step % 8 == 0:
        return 1
    if step % 4 == 0:
        return 2
    if step % 2 == 0:
        return 3
    return 4


_MELODY_TRIES = 40


def band_sizes(rows, n):
    """The pad-row bands an n-note phrase can span when `rows` rows are
    lit: 2 rows (all there are, if fewer), up to about a row for every two
    notes -- so a long phrase can span 2, 3 or 4."""
    smallest = min(2, rows)
    largest  = max(smallest, min(rows, (n + 1) // 2))
    return range(smallest, largest + 1)


_RISE = 0.65   # how often a melody's moves head across its band


def _melody(notes, n, low, high, rng):
    """Write n scale notes (low to high) into `notes`: from a root at one
    end of the range, heading for the other (a rising or a falling line)
    with mostly steps and skips, now and then a repeat, a jump, or an
    octave leap (a row or so on the pads), ending on a root. Returns the
    pad rows it reached, as a bitmask (bit r = row r, from the bottom)."""
    roots = range((low + _SCALE_LEN - 1) // _SCALE_LEN * _SCALE_LEN, high + 1, _SCALE_LEN)
    if rng.random() < 0.5:
        note, heading = roots[0], 1     # rising
    else:
        note, heading = roots[-1], -1   # falling
    rows  = 0
    for i in range(n):
        if i:
            pick = rng.random()
            if pick < 0.15:
                move = 0
            elif pick < 0.55:
                move = 1
            elif pick < 0.8:
                move = 2
            elif pick < 0.9:
                move = 3
            else:
                move = _SCALE_LEN   # an octave
            note += move * (heading if rng.random() < _RISE else -heading)
            if note < low:
                note = 2 * low - note
            if note > high:
                note = 2 * high - note
            note = max(low, min(high, note))
        if i == n - 1:
            note = min(roots, key=lambda root: abs(root - note))
        notes[i] = note
        rows |= 1 << (note // _ROW_PADS)
    return rows


def compose(phrase, row, rng, band=None):
    """Write a new phrase for stage row `row` into `phrase`.

    Rhythm: a cell from the stage's vocabulary for each beat of the shape's
    span, every bar's beats 1 and 3 starting with a note, with exactly the
    stage's note count. Pitch: see _melody, on the pad rows `band` (lowest,
    highest; counted from the bottom; all the stage's rows if None),
    reaching both its edges -- Game picks the band (see _choose_band)."""
    cells   = row[_CELLS]
    most    = row[_NOTES]
    beats   = SHAPES[row[_SHAPE]] // 4
    biggest = max(_CELL_NOTES[cell] for cell in cells)

    n = 0
    strong_left = (beats + 1) // 2   # beats 1 and 3 of every bar
    for beat in range(beats):
        strong = beat % 2 == 0
        if strong:
            strong_left -= 1
        # Leave a note for each strong beat to come, and leave enough to
        # come for the phrase to reach `most`.
        high = most - n - strong_left
        low  = most - n - (beats - beat - 1) * biggest
        options = [cell for cell in cells
                   if (cell & 1 or not strong) and low <= _CELL_NOTES[cell] <= high]
        cell = rng.choice(options) if options else _Q
        for k in range(4):
            if cell & (1 << k) and n < MAX_NOTES:
                phrase.steps[n] = beat * 4 + k
                n += 1
    phrase.n = n

    # The melody: a few goes at it, keeping the first that reaches both
    # edges of the band (or the one that reached most of it).
    lowest, highest = band if band else (0, row[_ROWS] - 1)
    edges = (1 << lowest) | (1 << highest)
    best, best_score = bytearray(MAX_NOTES), -1
    for _ in range(_MELODY_TRIES):
        reached = _melody(phrase.notes, n, lowest * _ROW_PADS,
                          highest * _ROW_PADS + _ROW_PADS - 1, rng)
        score = _CELL_NOTES[reached & edges] * 8 + _CELL_NOTES[reached]
        if score > best_score:
            for i in range(n):
                best[i] = phrase.notes[i]
            best_score = score
        if reached & edges == edges:
            break
    for i in range(n):
        phrase.notes[i] = best[i]
        phrase.pads[i]  = keymap.PAD_OF_NOTE[best[i]]

    # Reveal order: strongest place first, then left to right.
    for i in range(n):
        phrase.rank[i] = _NO_NOTE
    for rank in range(n):
        best, best_key = -1, 0
        for i in range(n):
            if phrase.rank[i] != _NO_NOTE:
                continue
            key = beat_strength(phrase.steps[i]) * 64 + phrase.steps[i]
            if best < 0 or key < best_key:
                best, best_key = i, key
        phrase.rank[best] = rank


# ── The game ──────────────────────────────────────────────────────────────────

class Game:
    """The whole game: feed it key events (handle) and the time (update),
    and it plays `sound` (a synth_engine.SynthEngine) and draws on `disp`
    (a display.DisplayManager) when draw() is called. `on_quit` is called
    when the player quits."""

    def __init__(self, sound, disp, rng=random, on_quit=None, store=None):
        self._sound   = sound
        self._disp    = disp
        self._rng     = rng
        self._on_quit = on_quit
        # The top 10 (a game_scores board), kept on the drive by `store`
        # (game_scores, or a test's stand-in), or only in memory if None.
        self._store = store
        self._board = store.load() if store else game_scores.empty()

        sound.assign_channel(CHORDS, _CHRD)
        for key, value in _SOFT_BASS:
            sound.set_channel_param(BASS, None, key, value)
        for key, value in _SOFT_CHORD:
            sound.set_channel_param(CHORDS, None, key, value)
        self._voice = None
        self._set_voice(STAGES[0][_VOICE])     # the call's, and yours apart
        self._key    = scales.DEFAULT_KEY
        self._volume = VOLUME
        self._apply_volume()

        self._phrase = Phrase()
        # The stage each pad row (from the bottom) was last played in (-1:
        # not yet), for spreading melodies over every lit row.
        self._row_used = [-1] * len(config.PAD_KEYS)
        self._state  = TITLE
        self._stage  = 0
        self._row    = STAGES[0]
        self._lives  = LIVES
        self._score  = 0
        self._reveal = 0         # notes in play this round (by rank)
        self._demo   = False
        self._breakdown = False  # the top layer is out (since a strike)

        # The clock: step n of the current section (the count-in, or a
        # round) is due at anchor + n * step_dur.
        self._step_dur = 0.0
        self._anchor   = 0.0
        self._next     = 0       # the next step to fire
        self._len      = 0       # steps in the section
        self._pos      = -1      # the step last fired
        self._beat_at  = -1.0    # when the last beat fired

        # Judging this round's turn.
        self._you_start = 0.0
        self._window    = 0.0
        self._first_target = 0.0
        self._last_target  = 0.0
        self._judged   = bytearray(MAX_NOTES)
        self._clicks_from = 0    # the first count beat that clicks (0-4)
        self._in_play  = 0       # notes in play this round
        self._hits     = 0
        self._struck   = False

        # Timed releases (-1: none).
        self._bass_pad, self._bass_off = 0, -1.0
        self._call_pad, self._call_off = 0, -1.0
        self._demo_pad, self._demo_off = 0, -1.0

        # Game over.
        self._sting_start = 0.0
        self._sting_next  = 0
        self._over_at     = 0.0
        self._score_text  = "   0"
        self._rank        = None   # where the score goes in the top 10, if it does

        # The name editor: letters as indexes into game_scores.CHARS, the
        # one being edited, and its two blink frames (the name, and the
        # name with that letter empty), made only when they change.
        self._name       = bytearray(game_scores.NAME_LEN)
        self._name_pos   = 0
        self._name_texts = ("    ", "    ")
        self._name_at    = 0.0
        self._repeat     = 0       # UP / DOWN held: +1 / -1 (0: neither)
        self._repeat_at  = 0.0

        # The menu, and its top-10 view.
        self._menu_open = False
        self._menu_item = 0
        self._viewing   = False
        self._view_item = 0
        self._view_at   = 0.0
        self._view_texts = ()     # (rank, name, score) texts per entry, while viewing
        self._quitting  = False   # QUIT picked: quits when MENU comes up

        # Lights and text.
        self._held        = 0          # pads held (bit n = pad n)
        self._flash_until = array("f", [0.0] * config.NUM_PADS)
        self._flash_kind  = bytearray(config.NUM_PADS)
        self._pulse_until = 0.0
        self._frame       = [palette.OFF] * config.NUM_PADS
        self._area        = 0          # pads in reach (bit n = pad n)
        self._title_at    = 0.0        # when the title (or game over) began
        self._base_text   = "ECHO"
        self._text        = None
        self._text_until  = 0.0
        self._shown       = None

        right = [row[-1] for row in config.FUNC_LAYOUT]
        self._life_keys = tuple(b for b in right[-LIVES:] if b is not None)
        self._cue_keys  = tuple(b for row in config.FUNC_LAYOUT for b in row
                                if b is not None and b != config.BTN_PLAY_STOP and
                                b not in self._life_keys)

    # ── For the tests ─────────────────────────────────────────────────────────

    @property
    def state(self):
        return self._state

    @property
    def stage(self):
        return self._stage

    @property
    def lives(self):
        return self._lives

    @property
    def score(self):
        return self._score

    @property
    def reveal(self):
        return self._reveal

    @property
    def demo(self):
        return self._demo

    @property
    def phrase(self):
        return self._phrase

    @property
    def step_dur(self):
        return self._step_dur

    @property
    def layers(self):
        return self._layers()

    @property
    def you_start(self):
        return self._you_start

    @property
    def window(self):
        return self._window

    @property
    def menu_open(self):
        return self._menu_open

    @property
    def board(self):
        return self._board

    @property
    def section_end(self):
        """When the count-in or the current round ends."""
        return self._anchor + self._len * self._step_dur

    def target(self, i):
        """When phrase note i is due in this round's turn."""
        return self._you_start + self._phrase.steps[i] * self._step_dur

    def active(self, i):
        return self._phrase.rank[i] < self._reveal

    # ── Input ─────────────────────────────────────────────────────────────────

    def handle(self, event, now):
        """A key event from hw.scan(): (type, pad or button, time)."""
        etype, data, t = event
        if etype == PAD_DOWN:
            self._held |= 1 << data
            self._sound.trigger_layer_pad(PLAYER, data)
            if self._state == PLAY and not self._demo:
                self._judge(data, t + AUDIO_OFFSET, now)
        elif etype == PAD_UP:
            self._held &= ~(1 << data)
            self._sound.release_layer_pad(PLAYER, data)
        elif etype == BTN_DOWN:
            self._button(data, now)
        elif data == config.BTN_MENU and self._quitting:
            # Quit on the release: with MENU still down, the reload would
            # see it held and start the game again.
            self._on_quit()
        elif data == config.BTN_INC or data == config.BTN_DEC:
            self._repeat = 0

    def _button(self, button, now):
        if self._quitting:
            return
        if self._state == NAME:
            self._name_key(button, now)
        elif button == config.BTN_PLAY_STOP:
            if self._state == TITLE or self._state == OVER:
                self._menu_open = self._viewing = False
                self.start(now)
        elif self._viewing:
            # The top-10 view: UP / DOWN browse, MENU or RECORD back to the list.
            if button == config.BTN_INC or button == config.BTN_DEC:
                if self._view_texts:
                    step = 1 if button == config.BTN_INC else -1
                    self._view_item = (self._view_item + step) % len(self._view_texts)
                    self._view_at   = now
            elif button == config.BTN_MENU or button == config.BTN_RECORD:
                self._viewing = False
                self._view_texts = ()
        elif self._menu_open:
            if button == config.BTN_MENU:
                self._pick(now)
            elif button == config.BTN_INC or button == config.BTN_DEC:
                step = 1 if button == config.BTN_INC else -1
                self._menu_item = (self._menu_item + step) % len(MENU_ITEMS)
            elif button == config.BTN_RECORD:
                self._menu_open = False
        elif button == config.BTN_MENU:
            self._menu_open = True
            self._menu_item = 0
        elif button == config.BTN_INC or button == config.BTN_DEC:
            step = VOLUME_STEP if button == config.BTN_INC else -VOLUME_STEP
            self._volume = max(0, min(100, self._volume + step))
            self._apply_volume()
            self._flash(f"V{self._volume:3d}", now, 1.0)

    def _pick(self, now):
        """MENU on the highlighted menu item."""
        if self._menu_item == _MENU_TOP:
            # Stays in the menu: RECORD comes back to the list.
            top = self._board["top"]
            self._view_texts = tuple(
                (_rank_text(rank), top[rank][0], f"{top[rank][1]:4d}")
                for rank in range(len(top)))
            self._viewing, self._view_item, self._view_at = True, 0, now
            return
        self._menu_open = False
        if self._menu_item == _MENU_RESET:
            self.reset(now)
        elif self._on_quit:
            self.reset(now)          # silence, until MENU comes up
            self._quitting  = True
            self._base_text = "BYE "

    def _apply_volume(self):
        for layer in _GAME_LAYERS:
            share = _CHORD_SHARE if layer == CHORDS else 1.0
            self._sound.set_channel_volume(layer, round(self._volume * share))
        self._sound.set_track_volume(_SOFT_WOOD, round(self._volume * _SOFT_SHARE))

    # ── Starting ──────────────────────────────────────────────────────────────

    def start(self, now):
        """A new game: the count-in, from `now`."""
        self._lives, self._score = LIVES, 0
        for r in range(len(self._row_used)):
            self._row_used[r] = -1
        self._breakdown = False
        self._start_stage(0)
        self._state  = COUNT_IN
        self._anchor = now
        self._next   = 0
        self._len    = COUNT_IN_STEPS
        self._pos    = -1
        self._text_until = 0.0

    def reset(self, now):
        """Stop, and back to the title: PLAY starts again."""
        self._state = TITLE
        self._title_at = now
        self._bass_off = self._call_off = self._demo_off = -1.0
        self._sound.fade_all()
        self._text_until = 0.0
        for pad in range(config.NUM_PADS):
            self._flash_until[pad] = 0.0

    def _start_stage(self, stage):
        """Set up `stage`: its tempo (from the next round), pads and phrase
        -- and, for the first, the demo round that opens the game."""
        self._stage = stage
        self._row   = row = stage_row(stage)
        self._step_dur = 60.0 / (row[_BPM] * 4)
        band = self._choose_band(row[_ROWS], row[_NOTES])
        compose(self._phrase, row, self._rng, band)
        for i in range(self._phrase.n):
            self._row_used[self._phrase.notes[i] // _ROW_PADS] = stage
        # Round 1 is the 2-note skeleton -- unless the stage would take more
        # than MAX_ROUNDS that way: a long phrase starts further in.
        n = self._phrase.n
        self._reveal = min(n, max(2, n - MAX_ROUNDS + 1))
        self._set_voice(row[_VOICE])
        if row[_KEY] != self._key:
            self._key = row[_KEY]
            self._sound.set_tuning(self._key, scales.DEFAULT_SCALE)
        # Only the game's opening: a demo when a later stage's shape
        # changes plays like any round, so it reads as one to copy.
        self._demo = stage == 0
        top = row[_ROWS] * _ROW_PADS
        self._area = 0
        for pad in range(config.NUM_PADS):
            if keymap.NOTE_OF_PAD[pad] < top:
                self._area |= 1 << pad

    def _choose_band(self, rows, n):
        """The pad rows (lowest, highest, from the bottom) for a new n-note
        phrase with `rows` rows lit: a size from band_sizes, placed over
        the row left longest unplayed, so every lit row comes round over a
        few stages (a newly lit one straight away)."""
        size = self._rng.choice(band_sizes(rows, n))
        places, stalest = [], 0
        for lowest in range(rows - size + 1):
            oldest = min(self._row_used[r] for r in range(lowest, lowest + size))
            if not places or oldest < stalest:
                places, stalest = [lowest], oldest
            elif oldest == stalest:
                places.append(lowest)
        lowest = self._rng.choice(places)
        return lowest, lowest + size - 1

    def _set_voice(self, name):
        """The call's voice and yours: a fresh instance of _LEADS' `name`
        on each, moved and set up as it says. Nothing if it's already the
        voice."""
        if name == self._voice:
            return
        self._voice = name
        instrument, octaves, params = _LEADS[name]
        instrument = INSTRUMENT_NAMES.index(instrument)
        for layer in (CALL, PLAYER):
            self._sound.assign_channel(layer, instrument)
            self._sound.transpose_channel(layer, octaves)
            for key, value in params:
                self._sound.set_channel_param(layer, None, key, value)

    def _start_round(self, due):
        self._state  = PLAY
        self._anchor = due
        self._next   = 0
        self._len    = ME_STEPS + YOU_STEPS
        self._you_start = due + ME_STEPS * self._step_dur
        self._struck = False
        self._hits   = 0
        self._in_play = 0
        phrase = self._phrase
        first, last, gap, prev = -1, -1, 0, -1
        for i in range(phrase.n):
            self._judged[i] = _PENDING
            if not self.active(i):
                continue
            self._in_play += 1
            step = phrase.steps[i]
            if first < 0:
                first = step
            if prev >= 0 and (gap == 0 or step - prev < gap):
                gap = step - prev
            prev = last = step
        self._window = self._row[_WINDOW] / 1000
        if gap:
            self._window = min(self._window, WINDOW_GAP_SHARE * gap * self._step_dur)
        self._first_target = self._you_start + first * self._step_dur
        self._last_target  = self._you_start + last * self._step_dur
        # The count's clicks start after the phrase's last note, so none
        # lands on one: a long phrase gets fewer, later. (The display and
        # the keys still count all 4 beats.) Your turn has the same layout,
        # so the count-out clicks on the same beats.
        self._clicks_from = 0
        while (self._clicks_from < 4 and
               ME_STEPS - COUNT_STEPS + 4 * self._clicks_from <= last):
            self._clicks_from += 1

    # ── Time ──────────────────────────────────────────────────────────────────

    def update(self, now):
        """Fire whatever is due by `now`. Call every main-loop pass."""
        state = self._state
        if state == PLAY and not self._demo:
            self._expire(now)
            state = self._state
        if state == COUNT_IN or state == PLAY:
            while True:
                due = self._anchor + self._next * self._step_dur
                if now < due:
                    break
                if self._next >= self._len:
                    # The section's over: the next one starts here, and its
                    # first step is due straight away.
                    self._end_section(due)
                    state = self._state
                    if state != COUNT_IN and state != PLAY:
                        break
                    continue
                self._fire(self._next, due)
                self._pos   = self._next
                self._next += 1
        elif state == STING:
            self._play_sting(now)
        elif state == NAME:
            if self._repeat and now >= self._repeat_at:
                self._repeat_at = now + _NAME_REPEAT_GAP
                self._step_letter(self._repeat)
        elif state == OVER:
            swap = int((now - self._over_at) / _SWAP) % 2
            self._base_text = self._score_text if swap else "BUST"
        elif state == TITLE and not self._quitting:
            swap = int((now - self._title_at) / _SWAP) % 2
            self._base_text = "PLAY" if swap else "ECHO"
        self._releases(now)

    def _releases(self, now):
        sound = self._sound
        if self._bass_off >= 0 and now >= self._bass_off:
            sound.release_layer_pad(BASS, self._bass_pad)
            self._bass_off = -1.0
        if self._call_off >= 0 and now >= self._call_off:
            sound.release_layer_pad(CALL, self._call_pad)
            self._call_off = -1.0
        if self._demo_off >= 0 and now >= self._demo_off:
            sound.release_layer_pad(PLAYER, self._demo_pad)
            self._demo_off = -1.0

    def _fire(self, step, due):
        """Step `step` of the section, due at `due`."""
        self._backing(step % STEPS_PER_BAR, due)
        if step % 4 == 0:
            self._beat_at = due
        if self._state == COUNT_IN:
            if step % 4 == 0:
                beat = step // 4
                # Into a demo round, not straight into play: "DEMO", not "GO".
                self._base_text = "DEMO" if beat == 3 and self._demo else _COUNT_IN_TEXT[beat]
            return

        phrase = self._phrase
        if step < ME_STEPS:
            if step == 0:
                self._base_text = "ME  "
            for i in range(phrase.n):
                if phrase.steps[i] == step and self.active(i):
                    self._call_note(i, due)
            count = step - (ME_STEPS - COUNT_STEPS)
            if count >= 0 and count % 4 == 0:
                beat = count // 4
                if beat >= self._clicks_from:
                    self._sound.trigger_layer_pad(KIT, _RIM if beat == 3 else _WOOD)
                self._base_text  = _COUNT_TEXT[beat]
                self._pulse_until = due + _BEAT_FLASH
        else:
            you_step = step - ME_STEPS
            if you_step == 0:
                self._base_text = "YOU "
            if self._demo:
                for i in range(phrase.n):
                    if phrase.steps[i] == you_step and self.active(i):
                        self._demo_note(i, due)
            # The count-out: softly, leading back to the box's turn.
            count = you_step - (YOU_STEPS - COUNT_STEPS)
            if count >= 0 and count % 4 == 0:
                if count // 4 >= self._clicks_from:
                    self._sound.trigger(_SOFT_WOOD)
                if self._demo and count >= 8:
                    self._base_text = " GO "   # its last 2 beats: the real thing next

    def _backing(self, bar_step, due):
        sound  = self._sound
        layers = self._layers()
        bit    = 1 << bar_step
        if _KICK_STEPS & bit:
            sound.trigger_layer_pad(KIT, _KICK)
        if layers >= 5 and _OPEN_HAT_STEPS & bit:
            sound.trigger_layer_pad(KIT, _OHH)
        elif _HAT_STEPS & bit:
            sound.trigger_layer_pad(KIT, _CHH)
        if layers >= 2 and _BASS_PADS[bar_step] != _NO_NOTE:
            if self._bass_off >= 0:
                sound.release_layer_pad(BASS, self._bass_pad)
            self._bass_pad = _BASS_PADS[bar_step]
            self._bass_off = due + _BASS_GATE * self._step_dur
            sound.trigger_layer_pad(BASS, self._bass_pad)
        if layers >= 3 and _CLAP_STEPS & bit:
            sound.trigger_layer_pad(KIT, _CLAP)
        if layers >= 4 and _CHORD_STEPS & bit:
            sound.trigger_layer_pad(CHORDS, _CHORD_PAD)
        if layers >= 5 and _SHAKER_STEPS & bit:
            sound.trigger_layer_pad(KIT, _SHKR)

    def _layers(self):
        layers = self._row[_LAYERS]
        if self._breakdown and layers > 1:
            layers -= 1
        return layers

    def _gate(self, i):
        """How long phrase note i sounds: _CALL_GATE of the gap to the next
        note in play (a beat after the last), at least a step."""
        phrase = self._phrase
        gap = 4
        for j in range(i + 1, phrase.n):
            if self.active(j):
                gap = phrase.steps[j] - phrase.steps[i]
                break
        return max(1.0, _CALL_GATE * gap) * self._step_dur

    def _call_note(self, i, due):
        pad = self._phrase.pads[i]
        if self._call_off >= 0:
            self._sound.release_layer_pad(CALL, self._call_pad)
        gate = self._gate(i)
        self._call_pad, self._call_off = pad, due + gate
        self._sound.trigger_layer_pad(CALL, pad)
        self._flash_pad(pad, _FLASH_CALL, due + gate)

    def _demo_note(self, i, due):
        pad = self._phrase.pads[i]
        if self._demo_off >= 0:
            self._sound.release_layer_pad(PLAYER, self._demo_pad)
        gate = self._gate(i)
        self._demo_pad, self._demo_off = pad, due + gate
        self._sound.trigger_layer_pad(PLAYER, pad)
        self._flash_pad(pad, _FLASH_DEMO, due + gate)

    def _end_section(self, due):
        """The count-in or a round has ended at `due`: on to the next."""
        if self._state == COUNT_IN:
            self._start_round(due)
            return
        if self._demo:
            self._demo = False
        else:
            self._expire(None)
            if self._state != PLAY:
                return
            if not self._struck:
                self._breakdown = False
                self._score = min(9999, self._score + 5 * (self._stage + 1))
                if self._reveal >= self._phrase.n:
                    self._start_stage(self._stage + 1)
                    if self._lives < LIVES:
                        self._lives += 1
                    self._sound.trigger_layer_pad(KIT, _CRSH)   # level up
                else:
                    self._reveal += 1
        self._start_round(due)

    # ── Judging ───────────────────────────────────────────────────────────────

    def _judge(self, pad, t, now):
        window = self._window
        if t < self._first_target - window or t > self._last_target + window:
            return   # not your turn: playing along
        phrase = self._phrase
        best, best_dt = -1, 0.0
        for i in range(phrase.n):
            if (not self.active(i) or self._judged[i] != _PENDING or
                    phrase.pads[i] != pad):
                continue
            dt = t - self.target(i)
            if -window <= dt <= window and (best < 0 or abs(dt) < abs(best_dt)):
                best, best_dt = i, dt
        if best < 0:
            self._flash_pad(pad, _FLASH_WRONG, now + _WRONG_FLASH)
            self._strike("OOPS", now)
            return
        self._judged[best] = _HIT
        self._hits += 1
        self._flash_pad(pad, _FLASH_HIT, now + _HIT_FLASH)
        if abs(best_dt) <= NICE_SHARE * window:
            self._score = min(9999, self._score + 3)
            self._flash("NICE", now, _GRADE_HOLD)
        else:
            self._score = min(9999, self._score + 1)
            self._flash("EARL" if best_dt < 0 else "LATE", now, _GRADE_HOLD)
        if self._hits == self._in_play and not self._struck:
            # All of it, clean: the word stays up for the rest of the turn.
            if self._reveal >= self._phrase.n:
                n = self._stage + 2
                self._base_text = f"LVL{n}" if n < 10 else f"LV{n}"
            else:
                self._base_text = self._rng.choice(_PRAISE)

    def _expire(self, now):
        """Misses: notes in play whose window has passed by `now` (None: the
        round is over, so all of them)."""
        phrase = self._phrase
        for i in range(phrase.n):
            if not self.active(i) or self._judged[i] != _PENDING:
                continue
            if now is not None and now <= self.target(i) + self._window:
                continue
            self._judged[i] = _MISSED
            at = self.target(i) + self._window if now is None else now
            self._flash_pad(phrase.pads[i], _FLASH_MISS, at + _MISS_FLASH)
            self._strike("MISS", at)
            if self._state != PLAY:
                return

    def _strike(self, text, now):
        self._flash(text, now, _GRADE_HOLD)
        if self._struck:
            return   # one a round
        self._struck    = True
        self._breakdown = True
        self._lives    -= 1
        if self._lives <= 0:
            self._game_over(now)

    # ── Game over ─────────────────────────────────────────────────────────────

    def _game_over(self, now):
        self._state = STING
        if self._bass_off >= 0:
            self._sound.release_layer_pad(BASS, self._bass_pad)
            self._bass_off = -1.0
        self._sting_start = now
        self._sting_next  = 0
        self._base_text   = "BUST"
        self._text_until  = 0.0
        self._score_text  = f"{self._score:4d}"
        self._rank        = game_scores.rank_for(self._board, self._score)

    def _play_sting(self, now):
        beat = 4 * self._step_dur
        if self._sting_next < len(_STING_NOTES):
            due = self._sting_start + self._sting_next * beat
            if now >= due:
                pad = keymap.PAD_OF_NOTE[_STING_NOTES[self._sting_next]]
                if self._call_off >= 0:
                    self._sound.release_layer_pad(CALL, self._call_pad)
                self._call_pad, self._call_off = pad, due + 0.7 * beat
                self._sound.trigger_layer_pad(CALL, pad)
                self._sting_next += 1
        elif now >= self._sting_start + (len(_STING_NOTES) + 1) * beat:
            self._over_at = now
            if self._rank is None:
                self._state = OVER
            else:
                self._start_name(now)

    # ── A top-10 score: the name ──────────────────────────────────────────────

    def _start_name(self, now):
        """Show where the score placed, then edit its name: the last name
        entered, from its first letter."""
        self._state = NAME
        self._menu_open = self._viewing = False
        last = self._board["last"]
        for i in range(game_scores.NAME_LEN):
            self._name[i] = max(0, game_scores.CHARS.find(last[i]))
        self._name_pos = 0
        self._repeat   = 0
        self._name_at  = now
        self._name_changed()
        self._flash(_rank_text(self._rank), now, _RANK_HOLD)

    def _name_string(self):
        """The name as it'll be saved (a blank is a space)."""
        name = ""
        for i in range(game_scores.NAME_LEN):
            name += game_scores.CHARS[self._name[i]]
        return name

    def _name_changed(self):
        """Make the editor's two blink frames for the name as it stands: it
        with blanks shown as "_" (so a 3-letter name can be entered, and
        seen), and the same with the letter being edited empty."""
        shown = self._name_string().replace(" ", "_")
        pos   = self._name_pos
        self._name_texts = (shown, shown[:pos] + " " + shown[pos + 1:])

    def _step_letter(self, step):
        pos = self._name_pos
        self._name[pos] = (self._name[pos] + step) % len(game_scores.CHARS)
        self._name_changed()

    def _name_key(self, button, now):
        """UP / DOWN change the letter (held, they repeat), MENU takes it
        and moves on -- saving after the last -- and RECORD goes back one."""
        if button == config.BTN_INC or button == config.BTN_DEC:
            self._repeat    = 1 if button == config.BTN_INC else -1
            self._repeat_at = now + _NAME_REPEAT_WAIT
            self._step_letter(self._repeat)
        elif button == config.BTN_MENU:
            self._name_pos += 1
            if self._name_pos >= game_scores.NAME_LEN:
                self._save_name(now)
                return
            self._name_changed()
        elif button == config.BTN_RECORD:
            if self._name_pos > 0:
                self._name_pos -= 1
                self._name_changed()
        self._text_until = 0.0     # straight to the editor, past the rank

    def _save_name(self, now):
        """Put the score on the board and write it to the drive. Nothing is
        playing, so the write's stall goes unheard. If it fails, the score
        stays on this session's board and the display says why."""
        game_scores.insert(self._board, self._rank, self._name_string(), self._score)
        self._state, self._over_at, self._repeat = OVER, now, 0
        text = "DONE"
        if self._store:
            try:
                self._store.save(self._board)
            except OSError as e:
                text = game_scores.error_label(e)
        self._flash(text, now, _RANK_HOLD)

    # ── Lights and text ───────────────────────────────────────────────────────

    def _flash(self, text, now, hold):
        self._text, self._text_until = text, now + hold

    def _flash_pad(self, pad, kind, until):
        self._flash_kind[pad]  = kind
        self._flash_until[pad] = until

    def draw(self, now):
        """The pads, the function keys and the text, for `now`."""
        disp  = self._disp
        state = self._state
        playing = state == COUNT_IN or state == PLAY

        frame = self._frame
        pulse = now < self._pulse_until
        for pad in range(config.NUM_PADS):
            bit = 1 << pad
            if now < self._flash_until[pad]:
                color = _FLASH_COLORS[self._flash_kind[pad]]
            elif self._held & bit:
                color = palette.LIVE
            elif playing and self._area & bit:
                if pulse:
                    color = _AREA_PULSE
                elif _ROOT_PADS & bit:
                    color = palette.ROOT_NOTE
                else:
                    color = _AREA
            else:
                color = palette.OFF
            frame[pad] = color
        disp.set_pad_frame(frame)

        beat = now < self._beat_at + _BEAT_FLASH
        if playing:
            pos = self._pos if self._pos >= 0 else 0
            if state == COUNT_IN:
                cue = _COUNT_KEYS[pos // 4]
            elif pos < ME_STEPS - COUNT_STEPS:
                cue = _ME_KEYS
            elif pos < ME_STEPS:
                cue = _COUNT_KEYS[(pos - (ME_STEPS - COUNT_STEPS)) // 4]
            elif pos < ME_STEPS + YOU_STEPS - COUNT_STEPS:
                cue = _YOU_KEYS
            else:
                cue = _COUNT_OUT_KEYS[(pos - (ME_STEPS + YOU_STEPS - COUNT_STEPS)) // 4]
            color = cue[1] if beat else cue[0]
        elif state == TITLE:
            color = palette.GAME_CALL
        else:
            color = _OVER_KEYS
        for button in self._cue_keys:
            disp.set_key_color(button, color)
        if self._menu_open:
            disp.set_key_color(config.BTN_MENU, palette.MENU_OPEN)
        for i in range(len(self._life_keys)):
            lit = playing and i < self._lives
            disp.set_key_color(self._life_keys[i], _LIFE if lit else palette.OFF)
        if state == NAME:
            # Just the keys that do something now.
            for button in self._cue_keys:
                disp.set_key_color(button, palette.OFF)
            for button in _NAME_KEYS:
                disp.set_key_color(button, _NAME_KEY_LIT)

        # PLAY, like the groovebox's: flashing on the beat while the game
        # runs; blinking when it's waiting to start.
        if playing:
            play = palette.BEAT if beat else palette.PLAYING
        elif (state == TITLE or state == OVER) and not self._quitting:
            blink = int(now * _PLAY_BLINK_HZ * 2) % 2 == 0
            play = palette.BEAT if blink else palette.OFF
        else:
            play = palette.OFF
        disp.set_key_color(config.BTN_PLAY_STOP, play)

        if self._viewing:
            if self._view_texts:
                part = int((now - self._view_at) / _VIEW_SWAP) % 3   # rank, name, score
                text = self._view_texts[self._view_item][part]
            else:
                text = "NONE"
        elif self._menu_open:
            text = MENU_ITEMS[self._menu_item]
        elif now < self._text_until:
            text = self._text
        elif state == NAME:
            blink = int((now - self._name_at) * _NAME_BLINK_HZ * 2) % 2
            text = self._name_texts[blink]
        else:
            text = self._base_text
        if text is not self._shown:
            self._shown = text
            disp.show(text)


# ── The hardware loop ─────────────────────────────────────────────────────────

def run(hw):
    """Run the game on `hw` (hw.Hardware, built by code.py). Never returns:
    quitting reloads, back into the groovebox."""
    import supervisor

    import clock
    import game_intro
    from display import DisplayManager
    from synth_engine import SynthEngine

    sound = SynthEngine()
    disp  = DisplayManager(hw.i2c)
    game_intro.run(hw, disp, sound, CALL, VOLUME)
    game  = Game(sound, disp, on_quit=supervisor.reload, store=game_scores)
    lights_at = 0.0
    while True:
        now    = clock.now()
        events = hw.scan()
        if events:
            lights_at = 0.0   # show a press straight away
        for event in events:
            game.handle(event, now)
        game.update(now)
        sound.update(now)
        if now >= lights_at:
            lights_at = now + _FRAME_INTERVAL
            game.draw(now)
        disp.update(now)
