"""
Sound definitions for the groovebox's two pad contexts.

build_sounds() — eight fixed synthio sounds, one per pad: a full drum kit
(2 kicks, 2 hi-hats, snare, clap, cowbell, woodblock). Used by the sequencer
(always) and by drum-kit loop layer 0. Bass/lead sounds live on the 7
melodic loop layers instead (build_melodic_voices()), so the kit pads are
free to all be percussion.

All percussive sounds have sustain_level=0 so releasing immediately
after triggering lets the decay play out naturally. The noise-heavy voices
(hi-hats, snare, clap) use a looped table of random samples in place of a
tonal waveform -- synthio has no dedicated noise oscillator, but a
single-cycle random table read at audio rate reads as bright, gritty noise
once shaped by an envelope and filter. This is the same trick used in
Adafruit's own synthio drum examples.

build_melodic_voices() — seven distinct voices, one per melodic loop layer
(config.NUM_KIT_LAYERS..7). Each voice's 8 pads play a minor pentatonic run
in equal temperament; all seven voices share the same tonic and differ only
by octave, so pads select a note (never a different key) and any voices
played together stay in tune with each other.
"""

import array
import math
import random
import synthio

import synth_params

_W = 256  # waveform table length

def _sine():
    return array.array("h", [int(32767 * math.sin(2 * math.pi * i / _W)) for i in range(_W)])

def _square():
    return array.array("h", [32767 if i < _W // 2 else -32767 for i in range(_W)])

def _saw():
    return array.array("h", [int(32767 * (1.0 - 2.0 * i / _W)) for i in range(_W)])

def _triangle():
    return array.array("h", [int(32767 * (4 * abs(i / _W - 0.5) - 1)) for i in range(_W)])

def _ramp_down():
    """One-shot LFO waveform: starts high, ends low."""
    return array.array("h", [int(32767 * (1.0 - 2.0 * i / _W)) for i in range(_W)])

def _harmonic_sine(harmonics):
    """A sine fundamental plus extra overtones, peak-normalized to fill the
    int16 range. harmonics: [(multiple, relative_amplitude), ...] on top of
    the fundamental (amplitude 1.0). Used to give low drum hits body above
    their fundamental, since small/bookshelf speakers can't reproduce true
    sub-bass but reproduce 100-300 Hz fine."""
    raw = []
    for i in range(_W):
        t = 2 * math.pi * i / _W
        v = math.sin(t)
        for mult, amp in harmonics:
            v += amp * math.sin(mult * t)
        raw.append(v)
    peak = max(abs(v) for v in raw)
    return array.array("h", [int(32767 * v / peak) for v in raw])

def _noise():
    """Single-cycle table of random samples. synthio has no noise oscillator,
    so looping this at audio rate is the standard way to get noise out of it
    -- the "frequency" a Note plays it at just sets how bright/coarse the
    noise reads, same as choosing a sample rate. Used for hi-hats, snare,
    and clap, which all need real hiss rather than a pitched tone."""
    return array.array("h", [random.randint(-32767, 32767) for _ in range(_W)])

# Shared waveform tables for SYNTH EDIT's WAVE param. Order/count must match
# synth_params.WAVEFORM_NAMES / NUM_WAVEFORMS: sine, square, saw, triangle.
WAVEFORM_TABLES = [_sine(), _square(), _saw(), _triangle()]


def build_sounds():
    """
    Return a list of 8 dicts, each describing one pad's sound.
    Keys: 'note' (synthio.Note), 'hold_ms' (how long to hold before release).

    Caller should:
        synth.press([s['note']])
        # after hold_ms, synth.release([s['note']])
    For sustain_level=0 sounds, hold_ms=0 is fine; the envelope handles decay.
    """
    square = _square()
    triangle = _triangle()
    ramp   = _ramp_down()
    noise  = _noise()

    # Sine-plus-overtones waveforms so each kick has body above its
    # fundamental -- bookshelf/small speakers roll off well before 55 Hz but
    # reproduce 100-300 Hz fine.
    house_kick_wave = _harmonic_sine([(2, 0.4), (3, 0.2)])
    dnb_kick_wave   = _harmonic_sine([(2, 0.5), (3, 0.3), (4, 0.15)])

    # ── House kick ───────────────────────────────────────────────────────────
    # Deep, round, long -- a smoother/slower pitch drop and a long decay for
    # a sustained "boom" rather than a tight hit.
    house_kick_lfo = synthio.LFO(
        waveform=ramp, rate=1 / 0.09, scale=0.85, offset=0.85, once=True,
    )
    house_kick = synthio.Note(
        frequency=52,
        waveform=house_kick_wave,
        envelope=synthio.Envelope(
            attack_time=0.002, attack_level=1.0,
            decay_time=0.42,   sustain_level=0.0,
            release_time=0.03,
        ),
        bend=house_kick_lfo,
        filter=_filter(synthio.FilterMode.LOW_PASS, 1500, 0.9),
        amplitude=1.0,
    )

    # ── Drum & bass kick ─────────────────────────────────────────────────────
    # Short, tight, punchy -- a much faster/bigger pitch snap, a decay a
    # third the length of the house kick, and a more open filter so the
    # attack transient reads as a hard click instead of a soft thump.
    dnb_kick_lfo = synthio.LFO(
        waveform=ramp, rate=1 / 0.03, scale=1.3, offset=1.3, once=True,
    )
    dnb_kick = synthio.Note(
        frequency=60,
        waveform=dnb_kick_wave,
        envelope=synthio.Envelope(
            attack_time=0.001, attack_level=1.0,
            decay_time=0.15,   sustain_level=0.0,
            release_time=0.015,
        ),
        bend=dnb_kick_lfo,
        filter=_filter(synthio.FilterMode.LOW_PASS, 3200, 1.0),
        amplitude=1.0,
    )

    # ── Closed hi-hat ────────────────────────────────────────────────────────
    # Real noise (not a pitched square) run through a tight high-pass and a
    # very short decay, for an actual "tch" transient instead of a beep.
    chh = synthio.Note(
        frequency=8000,
        waveform=noise,
        envelope=synthio.Envelope(
            attack_time=0.001, attack_level=1.0,
            decay_time=0.035,  sustain_level=0.0,
            release_time=0.005,
        ),
        filter=_filter(synthio.FilterMode.HIGH_PASS, 7000, 1.2),
        amplitude=0.85,
    )

    # ── Open hi-hat ──────────────────────────────────────────────────────────
    # Same noise source, but a band-pass instead of high-pass (airier, less
    # harsh) and a decay over 15x longer -- a wash, not a click.
    ohh = synthio.Note(
        frequency=6500,
        waveform=noise,
        envelope=synthio.Envelope(
            attack_time=0.001, attack_level=1.0,
            decay_time=0.55,   sustain_level=0.0,
            release_time=0.02,
        ),
        filter=_filter(synthio.FilterMode.BAND_PASS, 5000, 0.8),
        amplitude=0.75,
    )

    # ── Snare ────────────────────────────────────────────────────────────────
    # Noise body (for actual hiss) plus the classic ring-mod "crack" on top.
    snare = synthio.Note(
        frequency=200,
        waveform=noise,
        envelope=synthio.Envelope(
            attack_time=0.001, attack_level=1.0,
            decay_time=0.17,   sustain_level=0.0,
            release_time=0.02,
        ),
        ring_frequency=180, ring_waveform=square,
        filter=_filter(synthio.FilterMode.LOW_PASS, 3500, 1.0),
        amplitude=1.0,
    )

    # ── Clap ─────────────────────────────────────────────────────────────────
    # A narrow resonant band-pass gives noise a nasal, "papery" quality, and
    # a soft (not instant) attack smears the onset the way several quick
    # claps landing together do -- both are what separate this from the snare.
    clap = synthio.Note(
        frequency=1500,
        waveform=noise,
        envelope=synthio.Envelope(
            attack_time=0.006, attack_level=1.0,
            decay_time=0.18,   sustain_level=0.0,
            release_time=0.02,
        ),
        filter=_filter(synthio.FilterMode.BAND_PASS, 1600, 2.5),
        amplitude=0.9,
    )

    # ── Cowbell ──────────────────────────────────────────────────────────────
    # The classic 808-style trick: two square waves at an inharmonic ratio
    # (here via ring mod, ~1.44:1, close to the real cowbell's 587/845 Hz
    # partials) through a resonant band-pass centered on the clang.
    cowbell = synthio.Note(
        frequency=587,
        waveform=square,
        envelope=synthio.Envelope(
            attack_time=0.002, attack_level=1.0,
            decay_time=0.32,   sustain_level=0.0,
            release_time=0.05,
        ),
        ring_frequency=845, ring_waveform=square,
        filter=_filter(synthio.FilterMode.BAND_PASS, 850, 3.0),
        amplitude=0.8,
    )

    # ── Woodblock ────────────────────────────────────────────────────────────
    # Deliberately the cowbell's opposite: no ring mod (clean, not metallic),
    # a plain triangle through a sharp resonant peak for a hollow "tock",
    # and a decay a fifth as long -- dry and dead rather than ringing out.
    woodblock = synthio.Note(
        frequency=950,
        waveform=triangle,
        envelope=synthio.Envelope(
            attack_time=0.001, attack_level=1.0,
            decay_time=0.06,   sustain_level=0.0,
            release_time=0.01,
        ),
        filter=_filter(synthio.FilterMode.BAND_PASS, 1100, 4.0),
        amplitude=0.85,
    )

    # hold_ms: ms to hold note before releasing (0 = release immediately)
    # Every kit sound here is percussive (sustain_level=0), so hold_ms=0
    # throughout -- the envelope's own decay carries the sound out.
    return [
        _drum_entry("KICK", house_kick, 0, bend_lfo=house_kick_lfo),
        _drum_entry("DNBK", dnb_kick,   0, bend_lfo=dnb_kick_lfo),
        _drum_entry("CHH ", chh,        0),
        _drum_entry("OHH ", ohh,        0),
        _drum_entry("SNRE", snare,      0),
        _drum_entry("CLAP", clap,       0),
        _drum_entry("COWB", cowbell,    0),
        _drum_entry("WOOD", woodblock,  0),
    ]


def _filter(mode, frequency, q=0.7071067811865475):
    """A Biquad for the drum-kit TONE param, seeded with each sound's own
    filter type/cutoff/resonance. Mode and Q aren't part of DRUM_PARAM_SCHEMA
    (only cutoff is live-editable), so whatever's picked here is permanent --
    see synth_engine._apply_drum_params, which reads mode/Q back off the
    existing filter rather than hardcoding them."""
    return synthio.Biquad(mode, frequency=frequency, Q=q)


def _drum_entry(name, note, hold_ms, bend_lfo=None):
    """Build a build_sounds() entry, seeding params/defaults from the note
    itself so the literals set on it above stay the single source of truth.

    bend_lfo: a once=True pitch-envelope LFO driving note.bend, if any.
    synth.press() does not retrigger LFOs on its own, so the caller must
    call bend_lfo.retrigger() before each press for the sweep to replay.
    """
    params = synth_params.default_drum_params(
        tune=note.frequency,
        attack=note.envelope.attack_time,
        decay=note.envelope.decay_time,
        cutoff=note.filter.frequency,
        ring=note.ring_frequency,
        amp=note.amplitude,
    )
    return {"note": note, "hold_ms": hold_ms, "name": name,
            "params": params, "defaults": dict(params), "bend_lfo": bend_lfo}


# Minor pentatonic, in standard 12-tone equal temperament (semitones from
# root): only 5 notes/octave, so this runs one note past the octave to fill
# all 8 pads. No half-step-apart degrees anywhere in it, which matters more
# here than in a fixed chord progression -- different voices are layered
# live/independently, so whatever pads happen to land together need to stay
# consonant on their own, not just when following a written chart.
_PENTATONIC_SEMITONES = (0, 3, 5, 7, 10, 12, 15, 17)

def _pentatonic_scale(root_freq):
    """8 frequencies: root_freq's minor pentatonic run, pad 0 = root."""
    return [root_freq * 2 ** (s / 12) for s in _PENTATONIC_SEMITONES]


def build_melodic_voices():
    """
    Return a list of 7 dicts, one per melodic loop layer (layers
    config.NUM_KIT_LAYERS..7 map to list index 0..6). Each dict has:
      'note'        - dedicated synthio.Note; frequency is set per-trigger
      'detune_note' - a second synthio.Note for unison detune (SYNTH EDIT's
                      'DTUN'), pressed alongside 'note' only when
                      params['detune'] != 0
      'lfo'         - a persistent synthio.LFO reused for vibrato/tremolo/
                      filter-wobble, whichever 'lfo_dest' selects
      'scale'       - 8 frequencies for that voice (pad 0..7)
      'hold_ms'     - like build_sounds(), ms to hold before auto-release
                      (a soft ceiling on live-held notes -- see synth_engine;
                      the sustained voices below ship with several seconds
                      of headroom instead of the old few-hundred-ms cap)
      'name'        - 4-char display name
      'params'      - live-editable dict driving SYNTH EDIT (see synth_params.py)
      'defaults'    - frozen copy of 'params' at build time, for voice reset
    """
    # Every voice is an octave transposition of the same tonic (_ROOT_HZ)
    # rather than an independently-chosen root -- so pad N is always the
    # same pitch class on every voice, and any two voices played together
    # stay consonant no matter which pads are pressed. (Previously each
    # voice built its own major scale from its own root, so e.g. BASS was
    # effectively in a different key than STAB -- that's what was clashing.)
    _ROOT_HZ = 55.0  # A1

    # name,   wave_idx,  octave  attack  decay  sustain  release  hold_ms
    # wave_idx: 0=sine 1=square 2=saw 3=triangle (see WAVEFORM_TABLES)
    # octave: relative to _ROOT_HZ, e.g. -1 = an octave below, 2 = two above.
    # Voices are aimed at house / tech-house / DnB grooves rather than
    # generic synth roles: two bass registers (a rolling BASS and a growling
    # DnB REES), a squelchy ACID line, a house STAB, a tech-house arp PLUK,
    # a DnB HOOV lead, and an atmospheric PAD.
    specs = [
        ("BASS", 2,  0, 0.010, 0.12, 0.65, 0.12, 2500),  # rolling house/tech-house bassline
        ("REES", 2, -1, 0.015, 0.15, 0.80, 0.20, 3000),  # DnB reese: detuned + filter wobble
        ("ACID", 1,  1, 0.003, 0.18, 0.30, 0.08,  250),  # 303-style acid squelch
        ("STAB", 2,  3, 0.002, 0.12, 0.00, 0.05,  150),  # house chord stab
        ("PLUK", 3,  4, 0.004, 0.10, 0.00, 0.04,  130),  # tech-house arp pluck
        ("HOOV", 2,  2, 0.020, 0.15, 0.55, 0.15, 2500),  # DnB hoover/rave lead
        ("PAD ", 0,  1, 0.100, 0.20, 0.80, 0.40, 4000),  # atmospheric pad
    ]
    # Per-voice tweaks beyond default_params()'s flat/open starting point
    # (cutoff=10000 i.e. unfiltered, resonance=0.707, detune/LFO off) --
    # keyed by name so each voice's genre character is audible immediately,
    # not just after opening SYNTH EDIT.
    overrides = {
        "BASS": {"cutoff": 1800.0, "resonance": 1.1},
        "REES": {"detune": 18.0, "cutoff": 900.0, "resonance": 2.5,
                  "lfo_rate": 4.0, "lfo_depth": 0.5, "lfo_dest": 3},   # 3 = filter wobble
        "ACID": {"cutoff": 600.0, "resonance": 5.5,
                  "lfo_rate": 3.0, "lfo_depth": 0.6, "lfo_dest": 3},
        "STAB": {"cutoff": 3500.0, "resonance": 0.9},
        "PLUK": {"cutoff": 6000.0},
        "HOOV": {"detune": 30.0, "cutoff": 2500.0, "resonance": 2.0},
    }
    voices = []
    for name, wave_idx, octave, atk, dec, sus, rel, hold_ms in specs:
        scale  = _pentatonic_scale(_ROOT_HZ * 2 ** octave)
        params = synth_params.default_params(wave_idx, atk, dec, sus, rel)
        params.update(overrides.get(name, {}))

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

        # Primary and detune notes share the same Envelope/Biquad instances so
        # a param edit only has to update one object to affect both oscillators.
        note = synthio.Note(frequency=scale[0], waveform=waveform,
                             envelope=envelope, filter=filt)
        detune_note = synthio.Note(frequency=scale[0], waveform=waveform,
                                    envelope=envelope, filter=filt)

        voices.append({
            "note": note, "detune_note": detune_note, "lfo": synthio.LFO(),
            "scale": scale, "hold_ms": hold_ms, "name": name,
            "params": dict(params), "defaults": dict(params),
        })
    return voices
