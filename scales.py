"""
The melodic layers' key and scale -- the menu's KEY and SCAL.

One key and one scale for every melodic layer at once: that's what keeps
independently layered voices in tune with each other. A recorded melodic
note is a pad (a scale degree, keymap.NOTE_OF_PAD), never a pitch, so a
change re-voices every loop already playing, with its rhythm and shape kept.

SCALES runs from the safest to the spiciest. The three pentatonics have no
two notes a half-step apart, so whatever pads land together stay
consonant; the 7-note modes trade that guarantee for colour (and, at 7
notes an octave, the 16 pads span a little over 2 octaves instead of 3).

KEY moves the tonic up to 6 semitones up or 5 down from A, never further:
the bass voices already sit near the bottom of hearing at A, and the top
pad of the highest voices needs to stay under synthio's ~11 kHz ceiling.
"""

import keymap

# (4-char label, semitones from the root within one octave)
SCALES = (
    ("MINP", (0, 3, 5, 7, 10)),          # minor pentatonic
    ("MAJP", (0, 2, 4, 7, 9)),           # major pentatonic: bright
    ("SUS ", (0, 2, 5, 7, 10)),          # suspended pentatonic: open, deep house
    ("DOR ", (0, 2, 3, 5, 7, 9, 10)),    # dorian: jazzy minor
    ("AEOL", (0, 2, 3, 5, 7, 8, 10)),    # aeolian: natural minor
    ("PHRY", (0, 1, 3, 5, 7, 8, 10)),    # phrygian: dark
    ("HMIN", (0, 2, 3, 5, 7, 8, 11)),    # harmonic minor: rave drama
)

KEY_NAMES = ("C   ", "C#  ", "D   ", "D#  ", "E   ", "F   ",
             "F#  ", "G   ", "G#  ", "A   ", "A#  ", "B   ")

DEFAULT_KEY   = 9   # A
DEFAULT_SCALE = 0   # MINP

# The voices' shared tonic at octave 0 in the default key: A1. Each voice
# plays it 2 ** octave higher (sound_presets.MELODIC_VOICE_SPECS).
A1_HZ = 55.0


def valid_key(key):
    return isinstance(key, int) and 0 <= key < len(KEY_NAMES)


def valid_scale(scale):
    return isinstance(scale, int) and 0 <= scale < len(SCALES)


def root_offset(key):
    """Semitones from A to `key`'s tonic, nearest first: -5 (E) .. +6 (D#)."""
    return (key - DEFAULT_KEY + 5) % 12 - 5


def fill_pitches(pitches, key, scale):
    """Write each pad's frequency at octave 0 into `pitches` (indexed by
    pad), in place: a change allocates no long-lived objects."""
    steps = SCALES[scale][1]
    count = len(steps)
    root  = A1_HZ * 2 ** (root_offset(key) / 12)
    for pad in range(len(pitches)):
        note = keymap.NOTE_OF_PAD[pad]
        semitones = steps[note % count] + 12 * (note // count)
        pitches[pad] = root * 2 ** (semitones / 12)


def root_mask(scale):
    """Bitmask of the pads playing the tonic, in any octave (bit n = pad n)."""
    count = len(SCALES[scale][1])
    mask = 0
    for pad in range(len(keymap.NOTE_OF_PAD)):
        if keymap.NOTE_OF_PAD[pad] % count == 0:
            mask |= 1 << pad
    return mask
