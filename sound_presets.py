"""
Sound definitions for the groovebox's instruments.

Two kinds of instrument, both instantiable any number of times so every
channel that uses one owns an independent copy (its own Notes, Envelopes,
Biquads, LFOs and params -- editing one copy never touches another):

KIT (instrument id 0) -- sixteen synthio sounds, one per pad: a full drum
kit (2 kicks, 2 hi-hats, snare, clap, cowbell, woodblock on the top two
rows; 3 toms, rimshot, shaker, conga, ride, crash on the bottom two).
build_kit_instance() returns one fresh copy. Any loop layer assigned KIT
gets its own; the sequencer owns a copy of the first 8, one per track.

How synthio plays a drum: every kit sound is pressed and released in the
same instant (hold_ms=0), and synthio jumps straight to the envelope's
*release* stage on release -- decay_time never runs. So a kit sound's
length is its release_time, and its DEC param sets both (see _perc_env).

Noise: synthio has no noise oscillator, so noise is a table of random
samples. A looped table is periodic, though -- play a 256-sample table at
8 kHz and you get an 8 kHz tone, not hiss. The hats, clap, shaker and
cymbals therefore use long tables (thousands of samples) played at about
one table sample per output sample, which reads as real noise; their TUNE
default is that rate (a few Hz). Only the snare keeps the short table, where
the 200 Hz buzz it makes is the drum's body.

Metal: the cymbals and hats mix that noise with six square waves at the
TR-808's inharmonic cymbal frequencies, baked into the same long table so
one Note carries both -- TUNE then shifts the metal's pitch.

Melodic voices (instrument ids 1-15, MELODIC_VOICE_SPECS) -- one voice per
channel. Each voice's 16 pads play a run of the global key and scale
(scales.py) in equal temperament, lowest at the bottom left
(keymap.NOTE_OF_PAD); all voices share the same tonic and differ only by
octave, so pads select a note (never a different key) and any voices
played together stay in tune with each other. The engine owns the pitches
(SynthEngine's shared pad table); a voice holds only its octave.

instantiate_instrument(id) is the one factory the engine uses to hand a
channel a brand-new instance. Waveform tables are built once at import and
shared by every instance -- only the small wrapper objects are duplicated.
"""

import array
import math
import os
import synthio

import config
import scales
import synth_params

_W = 256  # waveform table length

# synthio updates envelopes and LFOs once per block of this many samples.
_BLOCK = 256

# The long tables below are built at import, on the device, so they're
# written to keep per-sample Python work to a minimum: noise comes straight
# from os.urandom, and the 808 metal is computed once and mixed in.


def _sine():
    return array.array("h", [int(32767 * math.sin(2 * math.pi * i / _W)) for i in range(_W)])

def _square():
    return array.array("h", [32767 if i < _W // 2 else -32767 for i in range(_W)])

def _saw():
    return array.array("h", [int(32767 * (1.0 - 2.0 * i / _W)) for i in range(_W)])

def _triangle():
    return array.array("h", [int(32767 * (4 * abs(i / _W - 0.5) - 1)) for i in range(_W)])

def _pulse():
    """A 25% pulse, DC-free (the high part is 3x the low) so the filter and
    envelope don't thump on a DC offset."""
    return array.array("h", [32767 if i < _W // 4 else -10922 for i in range(_W)])

def _ramp_down():
    """One-shot LFO waveform: starts high, ends low."""
    return array.array("h", [int(32767 * (1.0 - 2.0 * i / _W)) for i in range(_W)])

def _partials(partials):
    """Sum of sines at whole-number multiples of the table's frequency,
    peak-normalized to fill the int16 range. partials: [(multiple,
    amplitude), ...]."""
    raw = []
    for i in range(_W):
        t = 2 * math.pi * i / _W
        raw.append(sum(amp * math.sin(mult * t) for mult, amp in partials))
    peak = max(abs(v) for v in raw)
    return array.array("h", [int(32767 * v / peak) for v in raw])

def _harmonic_sine(harmonics):
    """A sine fundamental plus extra overtones. harmonics: [(multiple,
    relative_amplitude), ...] on top of the fundamental (amplitude 1.0).
    Used to give low sounds body above their fundamental, since
    small/bookshelf speakers can't reproduce true sub-bass but reproduce
    100-300 Hz fine."""
    return _partials([(1, 1.0)] + harmonics)

def _noise(n):
    """n random samples (int16 straight from random bytes). Played at
    config.SAMPLE_RATE / n Hz (one table sample per output sample) it's
    white noise that only repeats every n samples; see the module
    docstring."""
    return array.array("h", os.urandom(2 * n))

def _noise_rate(table):
    """The Note frequency that plays `table` one sample per output sample."""
    return config.SAMPLE_RATE / len(table)

# The TR-808's six cymbal/hat square oscillators (Hz).
_808_METAL_HZ = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)
_METAL_LEN    = 4096

def _metal():
    """The 808's six square waves summed, as a list of _METAL_LEN ints in
    -6..6. Each square gets a whole number of cycles over the table so it
    loops seamlessly, at whatever frequency is nearest the 808's when the
    table plays at one sample per output sample. The squares are naive
    (not band-limited) on purpose: their aliasing is extra inharmonic
    clang."""
    n, half = _METAL_LEN, _METAL_LEN // 2
    f0  = config.SAMPLE_RATE / n
    ks  = [max(1, round(hz / f0)) for hz in _808_METAL_HZ]
    out = [0] * n
    for k in ks:
        for i in range(n):
            out[i] += 1 if (i * k) % n < half else -1
    return out

def _metal_mix(noise, metal, metal_amount):
    """`noise` with `metal` (from _metal) mixed in; a longer noise table
    repeats the metal, which is periodic anyway."""
    keep  = 1.0 - metal_amount
    sq    = int(32767 * metal_amount / len(_808_METAL_HZ))   # per square
    mask  = len(metal) - 1
    out   = array.array("h", noise)
    for i in range(len(out)):
        out[i] = int(keep * out[i]) + sq * metal[i & mask]
    return out

def _supersaw(n, center, spread):
    """Three naive saws `spread` cycles apart around `center` cycles per
    table: played at note_freq / center (WAVEFORM_DIVISORS), that's a saw
    on the note plus one either side, (center +- spread) / center apart --
    the beating detune of a supersaw, from one Note."""
    ks   = (center - spread, center, center + spread)
    half = n // 2
    acc  = [0] * n
    for k in ks:
        for i in range(n):
            acc[i] += half - (i * k) % n
    gain = 32767 / (len(ks) * half)
    return array.array("h", [int(gain * v) for v in acc])

def _decay_curve(fast_share, fast_rate, slow_rate):
    """One-shot amplitude LFO waveform: the sum of a fast and a slow
    exponential fall, 1.0 at the start. synthio envelopes ramp linearly; a
    cymbal dies away exponentially -- a loud splash, then a long tail."""
    n = 64
    def level(i):
        t = i / (n - 1)
        return (fast_share * math.exp(-fast_rate * t) +
                (1.0 - fast_share) * math.exp(-slow_rate * t))
    return array.array("h", [int(32767 * level(i)) for i in range(n)])

def _block_steps(levels):
    """One-shot, non-interpolated amplitude LFO waveform whose entries play
    one per synthio block (_BLOCK samples, ~12 ms), starting with
    levels[0]. Returns (waveform, rate in Hz)."""
    # A retriggered LFO's first block already reads one step in, so pad
    # the front; the last entry is held once the LFO finishes, so pad the
    # back too (a finished one-shot sits just short of its last entry).
    table = [levels[0]] + list(levels) + [levels[-1]]
    steps = len(table) - 1
    # 1.001: land just past each entry, never just short of it.
    rate  = 1.001 / steps * config.SAMPLE_RATE / _BLOCK
    return array.array("h", [int(32767 * v) for v in table]), rate


# Shared waveform tables for the SOUND editor's WAVE param. Order/count must
# match synth_params.WAVEFORM_NAMES / NUM_WAVEFORMS.
WAVEFORM_TABLES = [
    _sine(), _square(), _saw(), _triangle(),
    # SUB: sine plus low overtones, so a sub bass is still heard on small
    # speakers.
    _harmonic_sine([(2, 0.3), (3, 0.2), (4, 0.05)]),
    _pulse(),
    # ORGN: drawbar-style organ, the 90s house organ.
    _harmonic_sine([(2, 0.8), (3, 0.6), (4, 0.4), (6, 0.25), (8, 0.2)]),
    # MALL: a marimba bar's 1 : 4 : 10 overtones.
    _harmonic_sine([(4, 0.35), (10, 0.12)]),
    # BELL: a bell's inharmonic partials (~1 : 2.75 : 5.5 : 9) as harmonics
    # of a quarter of the note -- divisor 4.
    _partials([(4, 1.0), (11, 0.6), (22, 0.35), (36, 0.2)]),
    # CHRD: a whole minor-7th chord (just 10 : 12 : 15 : 18), each tone with
    # a few saw-like overtones; the pad's note is harmonic 10 -- divisor 10.
    _partials([(tone * n, (1.0 if tone == 10 else 0.85) / n)
               for tone in (10, 12, 15, 18) for n in (1, 2, 3, 4)]),
    # SSAW: supersaw -- divisor 64.
    _supersaw(4096, 64, 1),
]

# What each WAVEFORM_TABLES entry's Note frequency is divided by: the
# multi-partial tables hold the note as harmonic N of a lower fundamental
# (that's what lets them place partials off the harmonic series).
WAVEFORM_DIVISORS = [1, 1, 1, 1, 1, 1, 1, 1, 4, 10, 64]

# Kit waveforms, built once and shared by every kit instance (building them
# per instance would duplicate the tables for no audible benefit).
_SQUARE   = WAVEFORM_TABLES[1]
_TRIANGLE = WAVEFORM_TABLES[3]
_RAMP     = _ramp_down()
# The snare's short noise table: at its 200 Hz the repeat is a buzz that
# reads as the drum's body (see module docstring).
_SHORT_NOISE = _noise(_W)
# Long noise (~0.19 s before it repeats) for the clap and shaker.
_NOISE    = _noise(4096)
_808      = _metal()
# Noise plus 808 metal, for the hats and crash: ~0.37 s per repeat, long
# enough not to "whoosh" through a crash's tail.
_CYMBAL   = _metal_mix(_noise(8192), _808, 0.4)
# Mostly metal, for the ride's ping.
_RIDE     = _metal_mix(_NOISE, _808, 0.8)
del _808   # only needed to build the two above
# Sine-plus-overtones waveforms so each kick has body above its
# fundamental -- bookshelf/small speakers roll off well before 55 Hz but
# reproduce 100-300 Hz fine.
_HOUSE_KICK_WAVE = _harmonic_sine([(2, 0.4), (3, 0.2)])
_DNB_KICK_WAVE   = _harmonic_sine([(2, 0.5), (3, 0.3), (4, 0.15)])
# Toms and conga: a lighter touch of overtones than the kicks, so they read
# as skin rather than boom.
_TOM_WAVE        = _harmonic_sine([(2, 0.25), (3, 0.1)])

# Amplitude shapes (one-shot LFO waveforms; see _drum_entry).
_CRASH_CURVE = _decay_curve(0.55, 9.0, 2.2)
_RIDE_CURVE  = _decay_curve(0.3, 8.0, 2.5)
_OHH_CURVE   = _decay_curve(0.0, 0.0, 3.5)
# An 808 clap: three quick slaps ~12 ms apart, then the tail.
_CLAP_BURSTS, _CLAP_BURST_RATE = _block_steps([1.0, 0.12, 0.9, 0.12, 0.85])


# ── Kit ───────────────────────────────────────────────────────────────────────
# One builder per pad sound, each returning a fresh _drum_entry() dict.
# hold_ms: ms to hold note before releasing (0 = release immediately).
# Every kit sound here is percussive, so hold_ms=0 throughout -- the
# envelope's release carries the sound out (see _perc_env).
#
# Pads 0-13 except the hats, clap and shaker (2, 3, 5, 12) keep the
# lengths they always actually played at: the old release times, which
# were the real length all along (see module docstring).

def _perc_env(decay, attack=0.001):
    """A drum envelope. synthio releases a drum the instant it's pressed and
    goes straight to the release stage, so release_time is the sound's
    whole length; decay_time is set to match only so the two read the same
    (and so DEC means the same if a sound is ever held)."""
    return synthio.Envelope(
        attack_time=attack, attack_level=1.0,
        decay_time=decay,   sustain_level=0.0,
        release_time=decay,
    )


def _build_house_kick():
    # Deep and round -- a smoother/slower pitch drop than the DnB kick.
    lfo = synthio.LFO(
        waveform=_RAMP, rate=1 / 0.09, scale=0.85, offset=0.85, once=True,
    )
    note = synthio.Note(
        frequency=52,
        waveform=_HOUSE_KICK_WAVE,
        envelope=_perc_env(0.03, attack=0.002),
        bend=lfo,
        filter=_filter(synthio.FilterMode.LOW_PASS, 1500, 0.9),
        amplitude=1.0,
    )
    return _drum_entry("KICK", note, 0, bend_lfo=lfo)


def _build_dnb_kick():
    # Short, tight, punchy -- a much faster/bigger pitch snap and a more
    # open filter so the attack transient reads as a hard click instead of
    # a soft thump.
    lfo = synthio.LFO(
        waveform=_RAMP, rate=1 / 0.03, scale=1.3, offset=1.3, once=True,
    )
    note = synthio.Note(
        frequency=60,
        waveform=_DNB_KICK_WAVE,
        envelope=_perc_env(0.015),
        bend=lfo,
        filter=_filter(synthio.FilterMode.LOW_PASS, 3200, 1.0),
        amplitude=1.0,
    )
    return _drum_entry("DNBK", note, 0, bend_lfo=lfo)


def _build_chh():
    # 808 metal plus noise through a tight high-pass: a crisp "tch". Shares
    # a choke group with the open hat, so it cuts an open hat off.
    note = synthio.Note(
        frequency=_noise_rate(_CYMBAL),
        waveform=_CYMBAL,
        envelope=_perc_env(0.03),
        filter=_filter(synthio.FilterMode.HIGH_PASS, 6500, 1.0),
        amplitude=0.85,
    )
    return _drum_entry("CHH ", note, 0, choke="hat")


def _build_ohh():
    # The closed hat's source opened up: a lower high-pass and a long
    # exponential tail -- a wash, not a click.
    note = synthio.Note(
        frequency=_noise_rate(_CYMBAL),
        waveform=_CYMBAL,
        envelope=_perc_env(0.45),
        filter=_filter(synthio.FilterMode.HIGH_PASS, 5500, 0.8),
        amplitude=0.75,
    )
    return _drum_entry("OHH ", note, 0, amp_curve=_OHH_CURVE, choke="hat")


def _build_snare():
    # Noise body (for actual hiss) plus the classic ring-mod "crack" on top.
    note = synthio.Note(
        frequency=200,
        waveform=_SHORT_NOISE,
        envelope=_perc_env(0.02),
        ring_frequency=180, ring_waveform=_SQUARE,
        filter=_filter(synthio.FilterMode.LOW_PASS, 3500, 1.0),
        amplitude=1.0,
    )
    return _drum_entry("SNRE", note, 0)


def _build_clap():
    # A narrow resonant band-pass gives noise a nasal, "papery" quality,
    # and three quick slaps before the tail (_CLAP_BURSTS) are what make a
    # clap a clap rather than a snare.
    note = synthio.Note(
        frequency=_noise_rate(_NOISE),
        waveform=_NOISE,
        envelope=_perc_env(0.15),
        filter=_filter(synthio.FilterMode.BAND_PASS, 1500, 2.0),
        amplitude=0.9,
    )
    return _drum_entry("CLAP", note, 0, amp_curve=_CLAP_BURSTS,
                       amp_rate=_CLAP_BURST_RATE)


def _build_cowbell():
    # The classic 808-style trick: two square waves at an inharmonic ratio
    # (here via ring mod, ~1.44:1, close to the real cowbell's 587/845 Hz
    # partials) through a resonant band-pass centered on the clang.
    note = synthio.Note(
        frequency=587,
        waveform=_SQUARE,
        envelope=_perc_env(0.05, attack=0.002),
        ring_frequency=845, ring_waveform=_SQUARE,
        filter=_filter(synthio.FilterMode.BAND_PASS, 850, 3.0),
        amplitude=0.8,
    )
    return _drum_entry("COWB", note, 0)


def _build_woodblock():
    # Deliberately the cowbell's opposite: no ring mod (clean, not metallic),
    # a plain triangle through a sharp resonant peak for a hollow "tock",
    # dry and dead rather than ringing out.
    note = synthio.Note(
        frequency=950,
        waveform=_TRIANGLE,
        envelope=_perc_env(0.01),
        filter=_filter(synthio.FilterMode.BAND_PASS, 1100, 4.0),
        amplitude=0.85,
    )
    return _drum_entry("WOOD", note, 0)


def _tom(name, frequency, sweep):
    # A pitched skin: the kicks' falling-pitch trick, gentler and higher,
    # so the three toms sit a step apart as a set. sweep: the drop, in
    # octaves, over the first ~0.1 s.
    lfo = synthio.LFO(
        waveform=_RAMP, rate=1 / 0.1, scale=sweep / 2, offset=sweep / 2, once=True,
    )
    note = synthio.Note(
        frequency=frequency,
        waveform=_TOM_WAVE,
        envelope=_perc_env(0.03, attack=0.002),
        bend=lfo,
        filter=_filter(synthio.FilterMode.LOW_PASS, 2500, 0.9),
        amplitude=0.9,
    )
    return _drum_entry(name, note, 0, bend_lfo=lfo)


def _build_low_tom():
    return _tom("LTOM", 98, 0.5)


def _build_mid_tom():
    return _tom("MTOM", 131, 0.45)


def _build_high_tom():
    return _tom("HTOM", 175, 0.4)


def _build_rimshot():
    # 808-style rim: two inharmonic tones (square ring-modded, ~500 and
    # ~1700 Hz) through a band-pass, gone in a few tens of ms -- a click
    # with a pitch, sharper and brighter than the woodblock.
    note = synthio.Note(
        frequency=500,
        waveform=_SQUARE,
        envelope=_perc_env(0.005),
        ring_frequency=1700, ring_waveform=_SQUARE,
        filter=_filter(synthio.FilterMode.BAND_PASS, 1800, 2.0),
        amplitude=0.8,
    )
    return _drum_entry("RIM ", note, 0)


def _build_shaker():
    # Noise like the hats, but a soft attack (the beads arriving a little
    # spread out) and a band-pass rather than high-pass: a "shh", not a "tch".
    note = synthio.Note(
        frequency=_noise_rate(_NOISE),
        waveform=_NOISE,
        envelope=_perc_env(0.05, attack=0.015),
        filter=_filter(synthio.FilterMode.BAND_PASS, 6000, 1.0),
        amplitude=0.6,
    )
    return _drum_entry("SHKR", note, 0)


def _build_conga():
    # A tuned hand drum: higher than the toms, a quick small pitch snap and
    # a resonant low-pass for its rounded "doom".
    lfo = synthio.LFO(
        waveform=_RAMP, rate=1 / 0.03, scale=0.15, offset=0.15, once=True,
    )
    note = synthio.Note(
        frequency=330,
        waveform=_TOM_WAVE,
        envelope=_perc_env(0.02),
        bend=lfo,
        filter=_filter(synthio.FilterMode.LOW_PASS, 2200, 1.6),
        amplitude=0.85,
    )
    return _drum_entry("CONG", note, 0, bend_lfo=lfo)


def _build_ride():
    # Mostly 808 metal with a little noise, through a band-pass on the ping:
    # a bell-like "ting" that rings on and fades exponentially.
    note = synthio.Note(
        frequency=_noise_rate(_RIDE),
        waveform=_RIDE,
        envelope=_perc_env(1.6),
        filter=_filter(synthio.FilterMode.BAND_PASS, 4200, 1.0),
        amplitude=0.7,
    )
    return _drum_entry("RIDE", note, 0, amp_curve=_RIDE_CURVE)


def _build_crash():
    # Noise-heavy metal, opened wide: a loud splash that falls fast, then
    # a long tail (_CRASH_CURVE).
    note = synthio.Note(
        frequency=_noise_rate(_CYMBAL),
        waveform=_CYMBAL,
        envelope=_perc_env(2.5, attack=0.002),
        filter=_filter(synthio.FilterMode.HIGH_PASS, 3500, 0.7),
        amplitude=0.8,
    )
    return _drum_entry("CRSH", note, 0, amp_curve=_CRASH_CURVE)


# Pad order: pad n plays KIT_SOUND_BUILDERS[n]() (pads read row by row from
# the top left, so the original 8 are the top two rows).
KIT_SOUND_BUILDERS = [
    _build_house_kick, _build_dnb_kick, _build_chh,      _build_ohh,
    _build_snare,      _build_clap,     _build_cowbell,  _build_woodblock,
    _build_low_tom,    _build_mid_tom,  _build_high_tom, _build_rimshot,
    _build_shaker,     _build_conga,    _build_ride,     _build_crash,
]

def build_kit_instance(count=None):
    """
    Return a fresh list of dicts, each describing one pad's sound: the
    whole kit, or only its first `count` sounds.
    Keys: 'notes' (two synthio.Notes, played in turn) and 'live', 'hold_ms'
    (how long to hold before release), 'name', 'params'/'defaults',
    'bend_lfos', 'amp_lfos', 'amp_lfo_fixed', 'choke' -- see _drum_entry.

    Caller should press the note after s['live'] and make it live:
        synth.press([note])
        # after hold_ms, synth.release([note])
    For sustain_level=0 sounds, hold_ms=0 is fine; the envelope handles decay.
    """
    return [build() for build in KIT_SOUND_BUILDERS[:count]]


# Pads whose sound was rebuilt when grooves went to v3 (the long-noise hats,
# clap and shaker, and the new ride and crash).
_V3_REBUILT_PADS = (2, 3, 5, 12, 14, 15)

def upgrade_v2_kit_params(pad, saved):
    """A kit sound's params saved by a groove from before v3, made to fit
    today's kit. Before v3 a drum's DEC did nothing (see module docstring)
    and its real length was fixed -- today's default -- so a saved DEC is
    dropped. The rebuilt pads keep only their level: their old TUNE and
    TONE values belonged to a different sound."""
    if pad in _V3_REBUILT_PADS:
        return {k: v for k, v in saved.items() if k == "amp"}
    return {k: v for k, v in saved.items() if k != "decay"}


def _filter(mode, frequency, q=0.7071067811865475):
    """A Biquad for the drum-kit TONE param, seeded with each sound's own
    filter type/cutoff/resonance. Mode and Q aren't part of DRUM_PARAM_SCHEMA
    (only cutoff is live-editable), so whatever's picked here is permanent --
    see synth_engine._apply_drum_params, which reads mode/Q back off the
    existing filter rather than hardcoding them."""
    return synthio.Biquad(mode, frequency=frequency, Q=q)


def _drum_entry(name, note, hold_ms, bend_lfo=None, amp_curve=None,
                amp_rate=None, choke=None):
    """Build a kit sound entry, seeding params/defaults from the note
    itself so the literals set on it above stay the single source of truth.

    bend_lfo: a once=True pitch-envelope LFO driving note.bend, if any.
    synth.press() does not retrigger LFOs on its own, so the caller must
    call bend_lfo.retrigger() before each press for the sweep to replay.

    amp_curve: a one-shot amplitude shape (an LFO waveform) on top of the
    envelope. It becomes 'amp_lfo', which then drives note.amplitude with
    the sound's level as its scale; like bend_lfo it needs a retrigger
    before each press. It runs over the sound's DEC, or at a fixed
    amp_rate (Hz) if one is given ('amp_lfo_fixed').

    choke: a group name; playing a sound cuts off any other sound in the
    same kit with the same group (an open hat closed by the closed hat).

    Each sound is played on two identical Notes in turn ('notes'; 'live'
    is the one the last hit used), each with its own copies of the LFOs
    ('bend_lfos', 'amp_lfos'). synthio doesn't restart a note that's still
    sounding: it re-enters the attack from wherever its tail had got to,
    and a drum's instant release means the attack never runs -- so a hit
    on a still-ringing note would come out at the tail's level. A fresh
    Note always starts at full; the engine fades the previous one out.
    """
    params = synth_params.default_drum_params(
        tune=note.frequency,
        attack=note.envelope.attack_time,
        decay=note.envelope.release_time,
        cutoff=note.filter.frequency,
        ring=note.ring_frequency,
        amp=note.amplitude,
    )
    twin = synthio.Note(
        frequency=note.frequency, waveform=note.waveform,
        envelope=note.envelope, filter=note.filter, amplitude=note.amplitude,
        ring_frequency=note.ring_frequency, ring_waveform=note.ring_waveform,
    )
    notes = (note, twin)
    bend_lfos = None
    if bend_lfo is not None:
        bend_lfos = (bend_lfo, _copy_lfo(bend_lfo))
        twin.bend = bend_lfos[1]
    amp_lfos = None
    if amp_curve is not None:
        amp_lfos = tuple(synthio.LFO(
            waveform=amp_curve, once=True, scale=params["amp"], offset=0.0,
            rate=amp_rate or 1.0 / params["decay"],
            interpolate=amp_rate is None,
        ) for _ in notes)
        for n, lfo in zip(notes, amp_lfos):
            n.amplitude = lfo
    return {"notes": notes, "live": 1, "hold_ms": hold_ms, "name": name,
            "params": params, "defaults": dict(params),
            "bend_lfos": bend_lfos, "amp_lfos": amp_lfos,
            "amp_lfo_fixed": amp_rate is not None,
            "choke": choke, "envelope": note.envelope, "choked": False}


def _copy_lfo(lfo):
    """A one-shot LFO like `lfo`, running independently of it."""
    return synthio.LFO(waveform=lfo.waveform, rate=lfo.rate, scale=lfo.scale,
                       offset=lfo.offset, once=True)


# ── Melodic voices ────────────────────────────────────────────────────────────

# Every voice is an octave transposition of the same tonic (scales.py's
# key) rather than an independently-chosen root -- so pad N is always the
# same pitch class on every voice, and any two voices played together
# stay consonant no matter which pads are pressed. (Previously each
# voice built its own major scale from its own root, so e.g. BASS was
# effectively in a different key than STAB -- that's what was clashing.)
# CHRD is the one exception: it plays a parallel minor-7th chord on
# whichever note, so some chord tones fall outside the scale -- the genre's
# own idiom.

# name,   wave_idx,  octave  attack  decay  sustain  release  hold_ms
# wave_idx: an index into WAVEFORM_TABLES (synth_params.WAVEFORM_NAMES).
# octave: relative to the tonic at A1 (scales.A1_HZ in the default key),
# e.g. -1 = an octave below, 2 = two above.
# Voices are aimed at house / tech-house / DnB / jungle grooves rather
# than generic synth roles. The first seven: two bass registers (a rolling
# BASS and a growling DnB REES), a squelchy ACID line, a house STAB, a
# tech-house arp PLUK, a DnB HOOV lead, and an atmospheric PAD. Then a
# jungle sub (JUNG), a house organ (ORGN), a minor-7th chord stab (CHRD),
# three arp-friendly voices (MALL marimba, BELL, CHIP pulse lead), a
# supersaw (SSAW), and a rave laser (ZAP).
MELODIC_VOICE_SPECS = [
    ("BASS", 2,  0, 0.010, 0.12, 0.65, 0.12, 2500),  # rolling house/tech-house bassline
    ("REES", 2, -1, 0.015, 0.15, 0.80, 0.20, 3000),  # DnB reese: detuned + filter wobble
    ("ACID", 1,  1, 0.003, 0.18, 0.30, 0.08,  250),  # 303-style acid squelch
    ("STAB", 2,  3, 0.002, 0.12, 0.00, 0.05,  150),  # house chord stab
    ("PLUK", 3,  4, 0.004, 0.10, 0.00, 0.04,  130),  # tech-house arp pluck
    ("HOOV", 2,  2, 0.020, 0.15, 0.55, 0.15, 2500),  # DnB hoover/rave lead
    ("PAD ", 0,  1, 0.100, 0.20, 0.80, 0.40, 4000),  # atmospheric pad
    ("JUNG", 4,  0, 0.002, 1.20, 0.55, 0.25, 3000),  # jungle sub: pitch-punched boom
    ("ORGN", 6,  1, 0.003, 0.25, 0.45, 0.06, 2500),  # 90s house organ
    ("CHRD", 9,  2, 0.002, 0.30, 0.00, 0.10,  350),  # deep-house/rave minor-7 stab
    ("MALL", 7,  3, 0.001, 0.40, 0.00, 0.25,  500),  # marimba/mallet arp
    ("BELL", 8,  3, 0.001, 1.50, 0.00, 0.80, 1800),  # glassy bell arp
    ("CHIP", 5,  3, 0.001, 0.12, 0.35, 0.03, 2000),  # pulse-wave rave/chip lead
    ("SSAW", 10, 2, 0.005, 0.35, 0.30, 0.30, 3000),  # trance supersaw
    ("ZAP ", 1,  1, 0.001, 0.40, 0.00, 0.08,  450),  # rave/jungle laser zap
]

# Per-voice tweaks beyond default_params()'s flat/open starting point
# (cutoff=10000 i.e. unfiltered, resonance=0.707, detune/LFO/pitch
# envelope/glide off) -- keyed by name so each voice's genre character is
# audible immediately, not just after opening the SOUND editor.
MELODIC_VOICE_OVERRIDES = {
    "BASS": {"cutoff": 1800.0, "resonance": 1.1},
    "REES": {"detune": 18.0, "cutoff": 900.0, "resonance": 2.5,
              "lfo_rate": 4.0, "lfo_depth": 0.5, "lfo_dest": 3},   # 3 = filter wobble
    # Glide makes overlapping (legato) notes slide, like a 303.
    "ACID": {"cutoff": 600.0, "resonance": 5.5,
              "lfo_rate": 3.0, "lfo_depth": 0.6, "lfo_dest": 3, "glide": 0.06},
    "STAB": {"cutoff": 3500.0, "resonance": 0.9},
    "PLUK": {"cutoff": 6000.0},
    "HOOV": {"detune": 30.0, "cutoff": 2500.0, "resonance": 2.0},
    # Each hit drops a fifth into the note -- the "B" of every "Boom" and
    # "Bo" -- and overlapping notes slide.
    "JUNG": {"amp": 0.9, "cutoff": 1200.0, "resonance": 0.9,
              "penv": 7.0, "ptime": 0.06, "glide": 0.08},
    "ORGN": {"cutoff": 4500.0, "resonance": 0.8},
    "CHRD": {"cutoff": 2800.0, "resonance": 1.4},
    "MALL": {"cutoff": 7000.0},
    "BELL": {"cutoff": 9000.0},
    "CHIP": {"cutoff": 6000.0,
              "lfo_rate": 5.5, "lfo_depth": 0.15, "lfo_dest": 1},  # 1 = vibrato
    "SSAW": {"detune": 12.0, "cutoff": 3200.0, "resonance": 1.2},
    # Low enough that even the top pad's sweep starts under the ~11 kHz
    # ceiling (a sweep from above it folds back to random pitches); a quick
    # drop, then time ringing on the note so each pad lands on its own
    # pitch; no resonant peak, which would ping the same pitch on every pad.
    "ZAP ": {"cutoff": 6000.0, "resonance": 0.8, "penv": 24.0, "ptime": 0.1},
}


def build_melodic_voice_instance(spec):
    """
    Build one fresh melodic voice from a MELODIC_VOICE_SPECS row. Returns a
    dict with:
      'pairs'        - two _voice_pair()s, played in turn: a separate
                       (non-legato) note moves to the other pair and the
                       engine fades the last one out, so the note starts
                       fresh; a legato note stays on the same pair (see
                       synth_engine.trigger_layer_pad)
      'live'         - index of the pair the voice last played on
      'envelope'     - the voice's current synthio.Envelope (a faded-out
                       pair gets it back when it's next played)
      'lfo'          - a persistent synthio.LFO reused for vibrato/tremolo/
                       filter-wobble, whichever 'lfo_dest' selects
      'freq'         - the pitch last played (None = none yet), for glide
      'mult'         - the voice's octave as a frequency ratio: a pad plays
                       the engine's pad pitch (key/scale, octave 0) times this
      'hold_ms'      - like the kit's, ms to hold before auto-release
                       (a soft ceiling on live-held notes -- see synth_engine;
                       the sustained voices ship with several seconds of
                       headroom instead of the old few-hundred-ms cap)
      'name'         - 4-char display name
      'params'       - live-editable dict driving the SOUND editor (see synth_params.py)
      'defaults'     - frozen copy of 'params' at build time, for voice reset
      'sounding_pad' - pad the voice is currently playing (None = none); the
                       engine's mono-voice release guard, see synth_engine
    The caller must apply params once (SynthEngine._apply_voice_params) --
    a voice can ship with e.g. LFO routing already engaged.
    """
    name, wave_idx, octave, atk, dec, sus, rel, hold_ms = spec
    mult   = 2 ** octave
    root   = scales.A1_HZ * mult
    params = synth_params.default_params(wave_idx, atk, dec, sus, rel)
    params.update(MELODIC_VOICE_OVERRIDES.get(name, {}))

    envelope = synthio.Envelope(
        attack_time=atk, attack_level=1.0,
        decay_time=dec,  sustain_level=sus,
        release_time=rel,
    )
    filt = synthio.Biquad(
        synthio.FilterMode.LOW_PASS,
        frequency=params["cutoff"], Q=params["resonance"],
    )
    waveform = WAVEFORM_TABLES[wave_idx]

    return {
        "pairs": (_voice_pair(root, waveform, envelope, filt),
                  _voice_pair(root, waveform, envelope, filt)),
        "live": 1, "envelope": envelope, "lfo": synthio.LFO(),
        "freq": None,
        "mult": mult, "hold_ms": hold_ms, "name": name,
        "params": dict(params), "defaults": dict(params),
        "sounding_pad": None,
    }


def _voice_pair(root, waveform, envelope, filt):
    """One of a melodic voice's two sets of Notes:
      'note'         - the main synthio.Note; frequency is set per-trigger
      'detune_note'  - a second synthio.Note for unison detune (the SOUND
                       editor's 'DTUN'), pressed alongside 'note' only when
                       params['detune'] != 0
      'penv_lfo'     - one-shot pitch envelope (PENV/PTIM), retriggered on
                       each note
      'glide_lfo'    - one-shot slide from the previous note (GLID)
      'bend'         - a synthio.Math summing vibrato + pitch envelope +
                       glide, which drives both notes' bend
    Each pair has its own one-shot LFOs, so a new note's pitch moves never
    touch the pair fading out underneath it. The two notes share their
    Envelope/Biquad instances, so a param edit only has to update one
    object to affect both oscillators."""
    return {
        "note": synthio.Note(frequency=root, waveform=waveform,
                             envelope=envelope, filter=filt),
        "detune_note": synthio.Note(frequency=root, waveform=waveform,
                                    envelope=envelope, filter=filt),
        "penv_lfo":  synthio.LFO(waveform=_RAMP, once=True),
        "glide_lfo": synthio.LFO(waveform=_RAMP, once=True),
        "bend": synthio.Math(synthio.MathOperation.SUM, 0.0, 0.0, 0.0),
    }


def voice_notes(voice):
    """All four of a melodic voice's Notes (both pairs)."""
    return [pair[key] for pair in voice["pairs"]
            for key in ("note", "detune_note")]


def build_melodic_voices():
    """One fresh instance of every melodic voice, in MELODIC_VOICE_SPECS order."""
    return [build_melodic_voice_instance(s) for s in MELODIC_VOICE_SPECS]


# ── Instruments ───────────────────────────────────────────────────────────────

# Instrument id -> 4-char name: 0 = KIT, 1.. = MELODIC_VOICE_SPECS in order.
INSTRUMENT_NAMES = ["KIT "] + [spec[0] for spec in MELODIC_VOICE_SPECS]


def instantiate_instrument(instrument_id):
    """A brand-new, independent instance of instrument `instrument_id`:
    {"type": "kit"|"melodic", "id": ..., "name": ...,
     "data": <list of 16 kit sound dicts> | <one melodic voice dict>}."""
    if instrument_id == 0:
        return {"type": "kit", "id": 0, "name": INSTRUMENT_NAMES[0],
                "data": build_kit_instance()}
    spec = MELODIC_VOICE_SPECS[instrument_id - 1]
    return {"type": "melodic", "id": instrument_id, "name": spec[0],
            "data": build_melodic_voice_instance(spec)}
