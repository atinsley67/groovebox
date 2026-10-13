"""
Parameter schemas for live sound editing (the menu's SOUND section).

Pure data plus stepping/formatting helpers -- no synthio or hardware
dependency, so this module has no project-local imports and is safe to
exercise standalone.

PARAM_SCHEMA covers the melodic voices (see
synth_engine.SynthEngine._apply_voice_params). DRUM_PARAM_SCHEMA is a
smaller, range-limited schema for the drum-kit sounds -- the
sequencer's kit, or any loop layer assigned KIT (see
SynthEngine._apply_drum_params). menu.py picks whichever schema applies
and shows it as a list, in the order given here.
"""

# Waveform count/order must match sound_presets.WAVEFORM_TABLES.
WAVEFORM_NAMES = ["SIN ", "SQR ", "SAW ", "TRI ", "SUB ", "PULS", "ORGN",
                  "MALL", "BELL", "CHRD", "SSAW"]
NUM_WAVEFORMS  = len(WAVEFORM_NAMES)
LFO_DEST_NAMES = ["OFF ", "VIB ", "TREM", "FILT"]

# Each entry is one item of the SOUND list. kind:
#   "continuous" - stepped by +/-, either "ratio" (log-scaled, wide-range
#                   params like time/frequency) or "linear" (fixed delta,
#                   for already-bounded 0..1-ish params)
#   "discrete"   - cycles through `count` integer values (0..count-1)
#   "action"     - no value; menu.py triggers it on MENU (after a confirm)
PARAM_SCHEMA = [
    {"key": "amp", "label": "AMP ",
     "kind": "continuous", "step_kind": "linear", "step": 0.05,
     "lo": 0.0, "hi": 1.0, "fmt": "pct"},
    {"key": "wave", "label": "WAVE",
     "kind": "discrete", "count": NUM_WAVEFORMS, "fmt": "wave"},
    {"key": "attack", "label": "ATK ",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.2,
     "lo": 0.001, "hi": 2.0, "fmt": "time"},
    {"key": "decay", "label": "DEC ",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.2,
     "lo": 0.01, "hi": 2.0, "fmt": "time"},
    {"key": "sustain", "label": "SUS ",
     "kind": "continuous", "step_kind": "linear", "step": 0.05,
     "lo": 0.0, "hi": 1.0, "fmt": "pct"},
    {"key": "release", "label": "REL ",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.2,
     "lo": 0.01, "hi": 3.0, "fmt": "time"},
    {"key": "cutoff", "label": "CUT ",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.12,
     "lo": 200.0, "hi": 10000.0, "fmt": "hz"},
    {"key": "resonance", "label": "RES ",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.15,
     "lo": 0.5, "hi": 8.0, "fmt": "q"},
    {"key": "lfo_rate", "label": "LFOR",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.25,
     "lo": 0.1, "hi": 20.0, "fmt": "hz"},
    {"key": "lfo_depth", "label": "LFOD",
     "kind": "continuous", "step_kind": "linear", "step": 0.05,
     "lo": 0.0, "hi": 1.0, "fmt": "pct"},
    {"key": "lfo_dest", "label": "LDST",
     "kind": "discrete", "count": 4, "fmt": "lfo_dest"},
    {"key": "ring", "label": "RING",
     "kind": "continuous", "step_kind": "linear", "step": 40.0,
     "lo": 0.0, "hi": 2000.0, "fmt": "hz0"},
    {"key": "detune", "label": "DTUN",
     "kind": "continuous", "step_kind": "linear", "step": 2.0,
     "lo": 0.0, "hi": 50.0, "fmt": "cents"},
    # Pitch envelope: each note starts this many semitones off (+ above,
    # - below) and slides onto its pitch over PTIM.
    {"key": "penv", "label": "PENV",
     "kind": "continuous", "step_kind": "linear", "step": 1.0,
     "lo": -24.0, "hi": 24.0, "fmt": "semi"},
    {"key": "ptime", "label": "PTIM",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.2,
     "lo": 0.005, "hi": 1.0, "fmt": "time"},
    # Glide: a note played while the last is still held slides from it.
    {"key": "glide", "label": "GLID",
     "kind": "continuous", "step_kind": "linear", "step": 0.02,
     "lo": 0.0, "hi": 0.5, "fmt": "time0"},
    {"key": "reset", "label": "RST ", "kind": "action"},
]

# Below this a GLID value counts as off (linear float steps back down to
# "zero" can land a hair above it).
GLIDE_OFF = 0.001

# Reduced, range-limited schema for the drum-kit sounds
# (sound_presets.build_kit_instance()).
# No WAVE swap and tighter attack/decay ceilings than PARAM_SCHEMA, so edits
# reshape a sound rather than turning it into a sustained melodic voice.
DRUM_PARAM_SCHEMA = [
    {"key": "amp", "label": "AMP ",
     "kind": "continuous", "step_kind": "linear", "step": 0.05,
     "lo": 0.0, "hi": 1.0, "fmt": "pct"},
    # Low floor: the long-noise sounds play their table at a few Hz (see
    # sound_presets' module docstring).
    {"key": "tune", "label": "TUNE",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.03,
     "lo": 1.0, "hi": 10000.0, "fmt": "hz"},
    {"key": "attack", "label": "ATK ",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.2,
     "lo": 0.001, "hi": 0.3, "fmt": "time"},
    # A drum's whole length (sound_presets._perc_env); the crash wants seconds.
    {"key": "decay", "label": "DEC ",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.2,
     "lo": 0.005, "hi": 4.0, "fmt": "time"},
    {"key": "cutoff", "label": "TONE",
     "kind": "continuous", "step_kind": "ratio", "ratio": 1.12,
     "lo": 300.0, "hi": 10000.0, "fmt": "hz"},
    {"key": "ring", "label": "SNAP",
     "kind": "continuous", "step_kind": "linear", "step": 40.0,
     "lo": 0.0, "hi": 2000.0, "fmt": "hz0"},
    {"key": "reset", "label": "RST ", "kind": "action"},
]


def default_params(wave_idx, attack, decay, sustain, release):
    """Seed a voice's params dict to match its original hardcoded sound."""
    return {
        "amp": 0.8,
        "wave": wave_idx, "detune": 0.0,
        "attack": attack, "decay": decay, "sustain": sustain, "release": release,
        "cutoff": 10000.0, "resonance": 0.7071067811865475,
        "lfo_rate": 5.0, "lfo_depth": 0.0, "lfo_dest": 0,
        "ring": 0.0,
        "penv": 0.0, "ptime": 0.05, "glide": 0.0,
    }


def default_drum_params(tune, attack, decay, cutoff=10000.0, ring=0.0, amp=1.0):
    """Seed a drum/kit sound's params dict to match its original hardcoded sound."""
    return {"amp": amp, "tune": tune, "attack": attack, "decay": decay,
            "cutoff": cutoff, "ring": ring}


def step_value(entry, current, direction):
    """Move a continuous/discrete param one tap in `direction` (+1 or -1)."""
    if entry["kind"] == "discrete":
        return (current + direction) % entry["count"]
    if entry["step_kind"] == "ratio":
        new = current * (entry["ratio"] ** direction)
    else:
        new = current + entry["step"] * direction
    return max(entry["lo"], min(entry["hi"], new))


def format_value(entry, value):
    """Format a value for the 4-char alphanumeric display (caller truncates/pads)."""
    fmt = entry.get("fmt")
    if fmt == "wave":
        return WAVEFORM_NAMES[value]
    if fmt == "lfo_dest":
        return LFO_DEST_NAMES[value]
    if fmt == "cents":
        return "OFF" if value == 0 else f"{int(value)}c"
    if fmt == "hz0":
        return "OFF" if value == 0 else _fmt_hz(value)
    if fmt == "semi":
        return "OFF" if value == 0 else f"{int(value):+d}"
    if fmt == "time0":
        return "OFF" if value < GLIDE_OFF else _fmt_time(value)
    if fmt == "hz":
        return _fmt_hz(value)
    if fmt == "time":
        return _fmt_time(value)
    if fmt == "pct":
        return f"{int(round(value * 100))}%"
    if fmt == "q":
        return f"{value:.1f}"
    return str(value)


def _fmt_hz(v):
    if v >= 1000:
        return f"{v / 1000:.1f}k"
    if v < 10:
        return f"{v:.1f}"
    return f"{int(v)}"


def _fmt_time(v):
    if v < 1.0:
        return f"{int(round(v * 1000))}ms"
    return f"{v:.1f}s"
