import array
import audiobusio
import math
import synthio

import clock
import config
import scales
from sound_presets import (build_kit_instance, instantiate_instrument,
                           upgrade_v2_kit_params, voice_notes,
                           INSTRUMENT_NAMES, WAVEFORM_DIVISORS, WAVEFORM_TABLES)
from synth_params import GLIDE_OFF

_VIBRATO_MAX_BEND = 1.0 / 12  # bend depth (1 semitone) at full LFO depth
_FULL_VOLUME      = 100       # channel volumes are whole percents, 0-100
_LN2              = math.log(2)
# How fast a choked sound (an open hat cut by the closed hat) dies away.
_CHOKE_RELEASE    = 0.02
# Only its release matters: a choked sound is already releasing.
_CHOKE_ENVELOPE   = synthio.Envelope(
    attack_time=0.001,         attack_level=1.0,
    decay_time=_CHOKE_RELEASE, sustain_level=0.0,
    release_time=_CHOKE_RELEASE,
)
# The same for a melodic note's tail when a new, separate note starts
# (_next_pair). Gentler than a drum's: synthio steps envelopes every
# ~12 ms, and on a clean low note a big step is itself a click.
_VOICE_FADE       = 0.05
_VOICE_FADE_ENVELOPE = synthio.Envelope(
    attack_time=0.001,      attack_level=1.0,
    decay_time=_VOICE_FADE, sustain_level=0.0,
    release_time=_VOICE_FADE,
)


def _clamp_volume(pct):
    return max(0, min(_FULL_VOLUME, int(pct)))


def _restored_volumes(saved, count):
    """Saved channel volumes, clamped. Any that are missing or malformed --
    e.g. a groove saved before channel volumes existed -- load at full."""
    if not isinstance(saved, list):
        saved = []
    volumes = []
    for i in range(count):
        value = saved[i] if i < len(saved) else _FULL_VOLUME
        if not isinstance(value, (int, float)):
            value = _FULL_VOLUME
        volumes.append(_clamp_volume(value))
    return volumes


def _merged_params(target, saved):
    """A sound's built-in defaults with any saved values on top. Only keys
    the sound actually has are taken, so a groove saved before (or after)
    a param was added/removed still loads."""
    params = dict(target["defaults"])
    for key in params:
        if key in saved:
            params[key] = saved[key]
    return params


class SynthEngine:
    def __init__(self):
        self._audio = audiobusio.I2SOut(
            bit_clock=config.I2S_BIT_CLOCK,
            word_select=config.I2S_WORD_SELECT,
            data=config.I2S_DATA_OUT,
        )
        self._synth = synthio.Synthesizer(sample_rate=config.SAMPLE_RATE)
        self._audio.play(self._synth) # type: ignore # The local stub doesn't like this, but it's correct.

        # Track scheduled auto-releases: list of (release_at, key_note, notes)
        self._pending_releases = []

        # The sequencer's own kit (track n = sound n), independent of any
        # loop layer's kit copy: the kit's first NUM_TRACKS sounds.
        self._sequencer_kit = build_kit_instance(config.NUM_TRACKS)

        # Channel volumes (0-100 %), one per sequencer track and one per
        # loop layer, scaling every sound in the channel on top of its own
        # AMP param. They belong to the track/layer slot, not to the
        # instrument instance in it, so a layer keeps its level across an
        # ASSIGN swap.
        self._track_volumes = [_FULL_VOLUME] * config.NUM_TRACKS
        self._layer_volumes = [_FULL_VOLUME] * config.NUM_LOOP_LAYERS

        # The melodic key and scale (scales.py), shared by every melodic
        # layer: each pad's pitch at octave 0, which a voice multiplies by
        # its own octave ('mult'). One flat array, rewritten in place on a
        # change -- nothing for the garbage collector to walk.
        self._key       = scales.DEFAULT_KEY
        self._scale     = scales.DEFAULT_SCALE
        self._pad_pitch = array.array("f", [0.0] * config.NUM_PADS)
        self._root_mask = 0
        self.set_tuning(self._key, self._scale)

        # One independent instrument instance per loop layer (see
        # sound_presets.instantiate_instrument). Default mapping is layer i
        # = instrument id i: layer 0 = KIT, layers 1-7 = BASS..PAD.
        self._channels = [self._new_channel(i, self._layer_gain(i))
                          for i in range(config.NUM_LOOP_LAYERS)]

    # ── Sequencer API (sequencer's own kit) ───────────────────────────────────

    def trigger(self, pad_index):
        """Press a pad. Schedules auto-release based on the sound's hold_ms."""
        if pad_index < 0 or pad_index >= len(self._sequencer_kit):
            return
        self._trigger_drum(self._sequencer_kit, pad_index)

    def note_off(self, pad_index):
        """Manually release a held note (called on PAD_UP for melodic pads)."""
        if pad_index < 0 or pad_index >= len(self._sequencer_kit):
            return
        sound = self._sequencer_kit[pad_index]
        self._release([sound["notes"][sound["live"]]])

    def sound_name(self, pad_index):
        return self._sequencer_kit[pad_index]["name"]

    def is_melodic(self, pad_index):
        """Melodic pads need explicit note_off on PAD_UP."""
        return self._sequencer_kit[pad_index]["hold_ms"] > 0

    # ── Loop-layer API (per-channel instances) ────────────────────────────────

    def layer_is_melodic(self, layer_idx):
        return self._channels[layer_idx]["type"] == "melodic"

    def layer_pad_needs_release(self, layer_idx, pad_index):
        """True if a note played on this layer/pad doesn't self-release and
        needs an explicit release -- any melodic voice, or a sustained
        (hold_ms > 0) kit sound."""
        channel = self._channels[layer_idx]
        if channel["type"] == "melodic":
            return True
        return channel["data"][pad_index]["hold_ms"] > 0

    def trigger_layer_pad(self, layer_idx, pad_index):
        """Press a pad in the context of a loop layer: kit channels play one
        of their 16 sounds; melodic channels play a scale degree on the
        channel's own voice (plus a detuned unison voice, if that voice's
        'detune' param is nonzero)."""
        channel = self._channels[layer_idx]
        if channel["type"] == "kit":
            if 0 <= pad_index < len(channel["data"]):
                self._trigger_drum(channel["data"], pad_index)
            return
        voice  = channel["data"]
        params = voice["params"]
        freq   = self._pad_pitch[pad_index] * voice["mult"]
        # Legato -- the last note's pad still held -- carries that note on
        # (and can glide). A separate note starts fresh on the other pair:
        # synthio would otherwise re-enter the attack from wherever the
        # last note's tail had got to, an instant jump in level that clicks
        # on clean, low sounds.
        legato = voice["sounding_pad"] is not None
        if not legato:
            self._next_pair(voice)
        pair = voice["pairs"][voice["live"]]
        notes = [pair["note"]]
        detune_cents = params["detune"]
        if detune_cents:
            notes.append(pair["detune_note"])
        # A legato note on a still-held, sustaining note just moves its
        # pitch (gliding if GLID is on): re-pressing it would jump straight
        # back to full level mid-wave -- the same click. A voice with no
        # sustain has died away while held, so it re-plucks instead.
        tie = legato and params["sustain"] > 0 and self._all_held(notes)
        self._start_pitch_mods(voice, pair, freq, legato, tie)
        voice["sounding_pad"] = pad_index
        # The multi-partial waves hold the note as a harmonic of a lower
        # fundamental (sound_presets.WAVEFORM_DIVISORS).
        osc_freq = freq / WAVEFORM_DIVISORS[params["wave"]]
        pair["note"].frequency = osc_freq
        if detune_cents:
            pair["detune_note"].frequency = osc_freq * (2 ** (detune_cents / 1200.0))
        if tie:
            self._schedule_release(notes, voice["hold_ms"])   # a fresh hold window
        else:
            self._press_with_hold(notes, voice["hold_ms"])

    def _all_held(self, notes):
        """True if every one of `notes` is still sounding and not yet
        released (synthio's own envelope state)."""
        for note in notes:
            state = self._synth.note_info(note)[0]
            if state is None or state == synthio.EnvelopeState.RELEASE:
                return False
        return True

    def _next_pair(self, voice):
        """Move a melodic voice to its other pair of Notes, fading the last
        pair's release out quickly (it's already released: the voice only
        moves on a non-legato note)."""
        last = voice["pairs"][voice["live"]]
        last["note"].envelope = last["detune_note"].envelope = _VOICE_FADE_ENVELOPE
        voice["live"] = 1 - voice["live"]
        pair = voice["pairs"][voice["live"]]
        pair["note"].envelope = pair["detune_note"].envelope = voice["envelope"]

    def _start_pitch_mods(self, voice, pair, freq, legato, tie):
        """Set up a melodic note's one-shot pitch moves, before it sounds:
        a glide from the previous note if that one is still held (legato)
        and GLID is on, otherwise the PENV pitch envelope -- unless the note
        is tied on (`tie`, see trigger_layer_pad), which isn't a new hit. A
        slide doesn't re-punch -- like a 303's slide, it carries on from the
        last note."""
        params = voice["params"]
        prev   = voice["freq"]
        bend   = pair["bend"]
        voice["freq"] = freq
        glide = params["glide"]
        if glide >= GLIDE_OFF and legato and prev and prev != freq:
            lfo = pair["glide_lfo"]
            octaves = math.log(prev / freq) / _LN2
            lfo.scale, lfo.offset = octaves / 2, octaves / 2
            lfo.rate = 1.0 / glide
            lfo.retrigger()
            bend.c = lfo
            return
        bend.c = 0.0
        if params["penv"] and not tie:
            pair["penv_lfo"].retrigger()

    def release_layer_pad(self, layer_idx, pad_index):
        """Release a loop layer's note for this pad (PAD_UP, or a recorded
        note-off during playback).

        Mono-voice guard: a melodic channel is one voice shared by all the
        pads, so a release that belongs to an earlier pad (e.g. legato
        playing, or independently-quantized starts on playback) must not
        cut off a newer note on a different pad -- it's ignored unless
        `pad_index` is the pad the voice is currently sounding."""
        channel = self._channels[layer_idx]
        if channel["type"] == "kit":
            sound = channel["data"][pad_index]
            if sound["hold_ms"] > 0:
                self._release([sound["notes"][sound["live"]]])
            return
        voice = channel["data"]
        if voice["sounding_pad"] != pad_index:
            return
        voice["sounding_pad"] = None
        # Releasing a note that isn't pressed is a no-op, so it's safe to
        # always release both regardless of the current detune setting.
        pair = voice["pairs"][voice["live"]]
        self._release([pair["note"], pair["detune_note"]])

    def pad_frequency(self, layer_idx, pad_index):
        """The pitch a melodic layer's pad plays in the current key/scale."""
        return self._pad_pitch[pad_index] * self._channels[layer_idx]["data"]["mult"]

    # ── Key and scale (the menu's KEY / SCAL) ─────────────────────────────────

    @property
    def key(self):
        return self._key

    @property
    def scale(self):
        return self._scale

    @property
    def root_mask(self):
        """Bitmask of the pads playing the tonic (bit n = pad n)."""
        return self._root_mask

    def set_tuning(self, key, scale):
        """Change the melodic key and/or scale (scales.py). Takes effect
        from each voice's next note; one already sounding rings out at its
        old pitch."""
        self._key, self._scale = key, scale
        scales.fill_pitches(self._pad_pitch, key, scale)
        self._root_mask = scales.root_mask(scale)

    def release_layer_notes(self, layer_idx, keep_mask=0):
        """Release whatever a loop layer has sounding that waits for a
        release -- its melodic voice's note, or a sustained kit pad -- with
        the sound's own release, as if its pad were let go: on pause or
        mute, where the recorded note-off would otherwise never come and
        the note would ring on to its hold_ms ceiling. Percussive kit
        sounds are left to ring out. Pads in keep_mask (bit n = pad n: ones
        the player is holding) are left alone -- their PAD_UP releases
        them."""
        channel = self._channels[layer_idx]
        if channel["type"] == "melodic":
            pad = channel["data"]["sounding_pad"]
            if pad is not None and not keep_mask & (1 << pad):
                self.release_layer_pad(layer_idx, pad)
            return
        for pad in range(len(channel["data"])):
            sound = channel["data"][pad]
            if sound["hold_ms"] > 0 and not keep_mask & (1 << pad):
                self._release([sound["notes"][sound["live"]]])

    def fade_all(self):
        """Fade out everything sounding, quickly: the menu's SAVE / LOAD,
        just before file work that stalls the main loop -- and any audio
        still playing through the stall could click. Every note gets a
        short fade-out envelope and is released, and pending auto-releases
        are dropped. Each sound gets its own envelope back on its next note
        (_next_pair, _trigger_drum)."""
        for channel in self._channels:
            if channel["type"] == "melodic":
                voice = channel["data"]
                notes = voice_notes(voice)
                for note in notes:
                    note.envelope = _VOICE_FADE_ENVELOPE
                voice["sounding_pad"] = None
                self._synth.release(notes)
            else:
                self._choke_kit(channel["data"])
        self._choke_kit(self._sequencer_kit)
        self._pending_releases.clear()

    def _choke_kit(self, kit):
        for sound in kit:
            self._choke(sound)
            self._synth.release(sound["notes"])

    def channel_instrument_id(self, layer_idx):
        return self._channels[layer_idx]["id"]

    def channel_sound_name(self, layer_idx, pad_index=None):
        """The layer's instrument name, or for a kit channel with a pad
        given, that pad's sound name."""
        channel = self._channels[layer_idx]
        if channel["type"] == "kit" and pad_index is not None:
            return channel["data"][pad_index]["name"]
        return channel["name"]

    def list_instrument_names(self):
        return INSTRUMENT_NAMES

    def assign_channel(self, layer_idx, instrument_id):
        """Give a loop layer a brand-new instance of `instrument_id`. The
        old instance is silenced (held notes released, pending auto-releases
        purged) and returned, so a caller can put it back later via
        restore_channel() with its edits intact."""
        old = self._channels[layer_idx]
        self._silence_channel(old)
        self._channels[layer_idx] = self._new_channel(instrument_id,
                                                      self._layer_gain(layer_idx))
        return old

    def restore_channel(self, layer_idx, channel):
        """Put a channel previously returned by assign_channel() back as-is
        (re-levelled to the slot's current volume)."""
        self._silence_channel(self._channels[layer_idx])
        self._channels[layer_idx] = channel
        self._apply_channel_level(layer_idx)

    # ── Channel volume (code.py's UP/DOWN outside the menu) ───────────────────

    def channel_volume(self, layer_idx):
        """A loop layer's volume, 0-100 (%)."""
        return self._layer_volumes[layer_idx]

    def set_channel_volume(self, layer_idx, pct):
        self._layer_volumes[layer_idx] = _clamp_volume(pct)
        self._apply_channel_level(layer_idx)

    def track_volume(self, track_idx):
        """A sequencer track's volume, 0-100 (%)."""
        return self._track_volumes[track_idx]

    def set_track_volume(self, track_idx, pct):
        self._track_volumes[track_idx] = _clamp_volume(pct)
        self._apply_drum_level(self._sequencer_kit[track_idx],
                               self._track_gain(track_idx))

    # ── Sound-editor parameter access ─────────────────────────────────────────

    def get_channel_param(self, layer_idx, pad_or_none, key):
        target, _ = self._channel_target(layer_idx, pad_or_none)
        return target["params"][key]

    def set_channel_param(self, layer_idx, pad_or_none, key, value):
        target, apply = self._channel_target(layer_idx, pad_or_none)
        target["params"][key] = value
        apply(target, self._layer_gain(layer_idx))

    def reset_channel(self, layer_idx, pad_or_none):
        """Restore a channel's voice (or one of its kit sounds) to the sound
        it was built with."""
        target, apply = self._channel_target(layer_idx, pad_or_none)
        target["params"] = dict(target["defaults"])
        apply(target, self._layer_gain(layer_idx))

    def get_drum_param(self, pad_idx, key):
        return self._sequencer_kit[pad_idx]["params"][key]

    def set_drum_param(self, pad_idx, key, value):
        sound = self._sequencer_kit[pad_idx]
        sound["params"][key] = value
        self._apply_drum_params(sound, self._track_gain(pad_idx))

    def reset_drum(self, pad_idx):
        """Restore a sequencer kit sound to the sound it was built with."""
        sound = self._sequencer_kit[pad_idx]
        sound["params"] = dict(sound["defaults"])
        self._apply_drum_params(sound, self._track_gain(pad_idx))

    # ── Grooves (called by code.py for the menu's SAVE / LOAD) ────────────────

    def snapshot_sounds(self):
        """Every sound edit as plain data: the sequencer kit's sounds, each
        loop layer's instrument id plus its params (one dict for a melodic
        voice, one per pad for a kit), every track and layer volume, and
        the melodic key and scale."""
        layers = []
        for channel in self._channels:
            if channel["type"] == "melodic":
                params = dict(channel["data"]["params"])
            else:
                params = [dict(sound["params"]) for sound in channel["data"]]
            layers.append({"id": channel["id"], "params": params})
        return {"kit": [dict(sound["params"]) for sound in self._sequencer_kit],
                "layers": layers,
                "track_vol": list(self._track_volumes),
                "layer_vol": list(self._layer_volumes),
                "key": self._key, "scale": self._scale}

    def restore_sounds(self, data, legacy_kit=False):
        """Put back a snapshot_sounds(). Every layer gets a fresh instance of
        its saved instrument (silencing whatever it had), then the saved
        params on top -- see _merged_params. Volumes go back first, so every
        sound is levelled as it's rebuilt. legacy_kit: the data is from a
        groove older than v3, whose kit params are upgraded first
        (sound_presets.upgrade_v2_kit_params). A groove from before key and
        scale existed (or with a bad one) loads in the default, A minor
        pentatonic: what it was made in."""
        def kit_saved(pad, saved):
            if legacy_kit and isinstance(saved, dict):
                return upgrade_v2_kit_params(pad, saved)
            return saved

        self._track_volumes = _restored_volumes(data.get("track_vol"),
                                                len(self._track_volumes))
        self._layer_volumes = _restored_volumes(data.get("layer_vol"),
                                                len(self._layer_volumes))

        key, scale = data.get("key"), data.get("scale")
        self.set_tuning(key if scales.valid_key(key) else scales.DEFAULT_KEY,
                        scale if scales.valid_scale(scale) else scales.DEFAULT_SCALE)

        for pad, (sound, saved) in enumerate(zip(self._sequencer_kit,
                                                 data.get("kit", []))):
            sound["params"] = _merged_params(sound, kit_saved(pad, saved))
        for track, sound in enumerate(self._sequencer_kit):
            self._apply_drum_params(sound, self._track_gain(track))

        saved_layers = data.get("layers", [])
        for idx in range(len(self._channels)):
            entry = saved_layers[idx] if idx < len(saved_layers) else {}
            instrument_id = entry.get("id", idx)
            if not 0 <= instrument_id < len(INSTRUMENT_NAMES):
                instrument_id = idx
            self.assign_channel(idx, instrument_id)
            channel = self._channels[idx]
            saved   = entry.get("params")
            if not saved:
                continue
            gain = self._layer_gain(idx)
            if channel["type"] == "melodic":
                voice = channel["data"]
                voice["params"] = _merged_params(voice, saved)
                self._apply_voice_params(voice, gain)
            else:
                for pad, (sound, sound_saved) in enumerate(zip(channel["data"], saved)):
                    sound["params"] = _merged_params(sound, kit_saved(pad, sound_saved))
                    self._apply_drum_params(sound, gain)

    def _channel_target(self, layer_idx, pad_or_none):
        """(params-owning dict, apply(target, gain) fn) for a channel:
        melodic channels have one voice (pad ignored); kit channels pick a
        sound by pad."""
        channel = self._channels[layer_idx]
        if channel["type"] == "melodic":
            return channel["data"], self._apply_voice_params
        return channel["data"][pad_or_none or 0], self._apply_drum_params

    def _layer_gain(self, layer_idx):
        return self._layer_volumes[layer_idx] / _FULL_VOLUME

    def _track_gain(self, track_idx):
        return self._track_volumes[track_idx] / _FULL_VOLUME

    def _apply_channel_level(self, layer_idx):
        """Re-level every sound in a loop layer after its volume changed."""
        channel = self._channels[layer_idx]
        gain    = self._layer_gain(layer_idx)
        if channel["type"] == "melodic":
            self._apply_voice_level(channel["data"], gain)
        else:
            for sound in channel["data"]:
                self._apply_drum_level(sound, gain)

    def _apply_voice_params(self, voice, gain):
        """Push a melodic voice's params onto its notes. gain is the
        channel volume (0.0-1.0) scaling the AMP param."""
        params   = voice["params"]
        waveform = WAVEFORM_TABLES[params["wave"]]
        lfo      = voice["lfo"]
        dest     = params["lfo_dest"]
        depth    = params["lfo_depth"]
        lfo.rate = params["lfo_rate"]

        # Envelope/Biquad are immutable value objects in synthio -- rebuild
        # rather than mutate, and share the new instance across the notes.
        envelope = voice["envelope"] = synthio.Envelope(
            attack_time=params["attack"], attack_level=1.0,
            decay_time=params["decay"],   sustain_level=params["sustain"],
            release_time=params["release"],
        )

        if dest == 3 and depth > 0:  # filter wobble: sweep cutoff itself
            # Biquad.frequency takes an LFO directly (an acid/reese-style
            # filter sweep, not just pitch/volume like the other dests).
            # Cap the swing so it can't approach Nyquist (11025 Hz at our
            # 22050 Hz sample rate) or go non-positive at high depth/cutoff.
            center = params["cutoff"]
            span   = max(0.0, min(center * depth * 0.85,
                                   9000.0 - center, center - 100.0))
            lfo.offset, lfo.scale = center, span
            filt = synthio.Biquad(synthio.FilterMode.LOW_PASS,
                                   frequency=lfo, Q=params["resonance"])
        else:
            filt = synthio.Biquad(synthio.FilterMode.LOW_PASS,
                                   frequency=params["cutoff"], Q=params["resonance"])

        # Pitch envelope: a one-shot ramp from PENV semitones off down to
        # the note, summed into the bend with vibrato and glide (bend.b).
        octaves = params["penv"] / 12.0
        for pair in voice["pairs"]:
            penv_lfo = pair["penv_lfo"]
            penv_lfo.scale, penv_lfo.offset = octaves / 2, octaves / 2
            penv_lfo.rate = 1.0 / params["ptime"]
            pair["bend"].b = penv_lfo if octaves else 0.0

        # Only the live pair takes the new envelope now: the other may be
        # fading out (_next_pair), and gets it when it's next played.
        live = voice["pairs"][voice["live"]]
        live["note"].envelope = live["detune_note"].envelope = envelope

        ring_freq = params["ring"]
        for note in voice_notes(voice):
            note.waveform = waveform
            note.filter   = filt
            note.ring_frequency = ring_freq
            if ring_freq and note.ring_waveform is None:
                note.ring_waveform = WAVEFORM_TABLES[1]  # square: bright ring carrier

        self._apply_voice_level(voice, gain)

    def _apply_voice_level(self, voice, gain):
        """A melodic voice's amplitude (both notes, and the tremolo range)
        and pitch-LFO routing: AMP scaled by the channel volume. Safe to run
        on its own after a volume change -- it only touches what depends on
        the level, and the vibrato/tremolo routing it shares with it."""
        params = voice["params"]
        lfo    = voice["lfo"]
        dest   = params["lfo_dest"]
        depth  = params["lfo_depth"]
        amp    = params["amp"] * gain
        if dest == 1 and depth > 0:  # vibrato: wobble pitch around center
            lfo.scale, lfo.offset = depth * _VIBRATO_MAX_BEND, 0.0
            vibrato, level = lfo, amp
        elif dest == 2 and depth > 0:  # tremolo: wobble amplitude below the voice's set level
            lfo.scale, lfo.offset = amp * depth / 2, amp * (1.0 - depth / 2)
            vibrato, level = 0.0, lfo
        else:  # off, filter wobble (handled above via the filter itself), or depth == 0
            vibrato, level = 0.0, amp
        for pair in voice["pairs"]:
            bend = pair["bend"]   # vibrato (a) + pitch envelope (b) + glide (c)
            bend.a = vibrato
            for note in (pair["note"], pair["detune_note"]):
                note.bend, note.amplitude = bend, level

    def _apply_drum_params(self, sound, gain):
        """Push a kit sound's params onto its notes. gain is the channel
        volume (0.0-1.0) scaling the AMP param."""
        params, notes = sound["params"], sound["notes"]
        self._apply_drum_level(sound, gain)
        if sound["amp_lfos"] is not None and not sound["amp_lfo_fixed"]:
            for lfo in sound["amp_lfos"]:
                lfo.rate = 1.0 / params["decay"]   # the shape spans the sound

        # A drum is released the instant it's pressed, so its release is
        # its whole length -- DEC sets both (sound_presets._perc_env). Only
        # the live note takes it now (unless choked): the other is fading
        # out, and gets it on its next hit.
        old_env = sound["envelope"]
        sound["envelope"] = synthio.Envelope(
            attack_time=params["attack"], attack_level=old_env.attack_level,
            decay_time=params["decay"],   sustain_level=old_env.sustain_level,
            release_time=params["decay"],
        )
        if not sound["choked"]:
            notes[sound["live"]].envelope = sound["envelope"]

        old_filt = notes[0].filter
        filt = synthio.Biquad(old_filt.mode, frequency=params["cutoff"], Q=old_filt.Q)
        ring_freq = params["ring"]
        for note in notes:
            note.frequency = params["tune"]
            note.filter    = filt
            note.ring_frequency = ring_freq
            if ring_freq and note.ring_waveform is None:
                note.ring_waveform = WAVEFORM_TABLES[1]  # square: bright ring carrier

    def _apply_drum_level(self, sound, gain):
        level = sound["params"]["amp"] * gain
        if sound["amp_lfos"] is None:
            for note in sound["notes"]:
                note.amplitude = level
        else:   # the shape's scale is the level (sound_presets._drum_entry)
            for lfo in sound["amp_lfos"]:
                lfo.scale = level

    # ── Private ───────────────────────────────────────────────────────────────

    def _new_channel(self, instrument_id, gain):
        """A fresh instance of `instrument_id`, levelled for a slot at `gain`."""
        channel = instantiate_instrument(instrument_id)
        if channel["type"] == "melodic":
            # Most voices' construction args already match their params 1:1,
            # but a voice can ship with e.g. LFO routing already engaged --
            # apply once up front so that's live immediately, not just
            # after the first edit.
            self._apply_voice_params(channel["data"], gain)
        else:
            for sound in channel["data"]:
                self._apply_drum_level(sound, gain)
        return channel

    def _silence_channel(self, channel):
        """Release everything a channel might be sounding and drop its
        scheduled auto-releases, so nothing is left pointing at (or still
        playing from) an instance that's about to leave its slot."""
        if channel["type"] == "melodic":
            voice = channel["data"]
            voice["sounding_pad"] = None
            notes = voice_notes(voice)
        else:
            notes = [note for sound in channel["data"] for note in sound["notes"]]
        self._synth.release(notes)
        self._pending_releases = [
            r for r in self._pending_releases
            if not any(r[1] is n for n in notes)
        ]

    def _trigger_drum(self, kit, pad_index):
        sound = kit[pad_index]
        group = sound["choke"]
        if group is not None:
            for other in kit:
                if other is not sound and other["choke"] == group:
                    self._choke(other)
        # Hit on the sound's other Note, so the hit starts fresh at full
        # level, and fade the last hit out (sound_presets._drum_entry).
        notes = sound["notes"]
        last  = sound["live"]
        this  = 1 - last
        notes[last].envelope = _CHOKE_ENVELOPE
        note = notes[this]
        note.envelope = sound["envelope"]
        sound["live"], sound["choked"] = this, False
        if sound["bend_lfos"] is not None:
            sound["bend_lfos"][this].retrigger()
        if sound["amp_lfos"] is not None:
            sound["amp_lfos"][this].retrigger()
        self._press_with_hold([note], sound["hold_ms"])

    def _choke(self, sound):
        """Cut a ringing kit sound short. synthio reads a note's envelope
        every block, so swapping in a fast release shortens a release
        already under way; _trigger_drum puts the real one back."""
        if not sound["choked"]:
            sound["choked"] = True
            sound["notes"][sound["live"]].envelope = _CHOKE_ENVELOPE

    def _press_with_hold(self, notes, hold_ms):
        # Release any previous press of these notes before re-triggering,
        # otherwise synthio stacks voices.
        self._synth.release(notes)
        self._synth.press(notes)

        if hold_ms == 0:
            # Percussive: release immediately; envelope handles the tail.
            self._synth.release(notes)
        else:
            self._schedule_release(notes, hold_ms)

    def _schedule_release(self, notes, hold_ms):
        """Auto-release `notes` hold_ms from now, replacing any release
        already scheduled for them."""
        release_at = clock.now() + hold_ms / 1000.0
        key = notes[0]
        self._drop_pending(key)   # a stale entry for this voice, if any
        self._pending_releases.append((release_at, key, notes))

    def _release(self, notes):
        self._synth.release(notes)
        self._drop_pending(notes[0])

    def _drop_pending(self, key):
        """Remove the scheduled release keyed `key` (there's at most one),
        in place: rebuilding the list would allocate on every note."""
        pending = self._pending_releases
        for i in range(len(pending)):
            if pending[i][1] is key:
                del pending[i]
                return

    def update(self, now):
        """Process scheduled releases due by `now` (the main loop's). Called
        every pass, so it allocates nothing unless one is due."""
        pending = self._pending_releases
        i = 0
        while i < len(pending):
            release_at, _, notes = pending[i]
            if now >= release_at:
                self._synth.release(notes)
                del pending[i]
            else:
                i += 1

    def deinit(self):
        self._synth.deinit()
        self._audio.deinit()
