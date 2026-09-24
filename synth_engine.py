import audiobusio
import synthio
import time

import config
from sound_presets import (build_kit_instance, instantiate_instrument,
                           INSTRUMENT_NAMES, WAVEFORM_TABLES)

_VIBRATO_MAX_BEND = 1.0 / 12  # bend depth (1 semitone) at full LFO depth


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
        # loop layer's kit copy.
        self._sequencer_kit = build_kit_instance()

        # One independent instrument instance per loop layer (see
        # sound_presets.instantiate_instrument). Default mapping is layer i
        # = instrument id i: layer 0 = KIT, layers 1-7 = BASS..PAD.
        self._channels = [self._new_channel(i) for i in range(config.NUM_LOOP_LAYERS)]

    # ── Sequencer API (sequencer's own kit) ───────────────────────────────────

    def trigger(self, pad_index):
        """Press a pad. Schedules auto-release based on the sound's hold_ms."""
        if pad_index < 0 or pad_index >= len(self._sequencer_kit):
            return
        self._trigger_drum(self._sequencer_kit[pad_index])

    def note_off(self, pad_index):
        """Manually release a held note (called on PAD_UP for melodic pads)."""
        if pad_index < 0 or pad_index >= len(self._sequencer_kit):
            return
        self._release([self._sequencer_kit[pad_index]["note"]])

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
        of their 8 sounds; melodic channels play a scale degree on the
        channel's own voice (plus a detuned unison voice, if that voice's
        'detune' param is nonzero)."""
        channel = self._channels[layer_idx]
        if channel["type"] == "kit":
            if 0 <= pad_index < len(channel["data"]):
                self._trigger_drum(channel["data"][pad_index])
            return
        voice = channel["data"]
        freq  = voice["scale"][pad_index]
        voice["note"].frequency = freq
        voice["sounding_pad"]   = pad_index

        notes = [voice["note"]]
        detune_cents = voice["params"]["detune"]
        if detune_cents:
            voice["detune_note"].frequency = freq * (2 ** (detune_cents / 1200.0))
            notes.append(voice["detune_note"])
        self._press_with_hold(notes, voice["hold_ms"])

    def release_layer_pad(self, layer_idx, pad_index):
        """Release a loop layer's note for this pad (PAD_UP, or a recorded
        note-off during playback).

        Mono-voice guard: a melodic channel is one voice shared by all 8
        pads, so a release that belongs to an earlier pad (e.g. legato
        playing, or independently-quantized starts on playback) must not
        cut off a newer note on a different pad -- it's ignored unless
        `pad_index` is the pad the voice is currently sounding."""
        channel = self._channels[layer_idx]
        if channel["type"] == "kit":
            sound = channel["data"][pad_index]
            if sound["hold_ms"] > 0:
                self._release([sound["note"]])
            return
        voice = channel["data"]
        if voice["sounding_pad"] != pad_index:
            return
        voice["sounding_pad"] = None
        # Releasing a note that isn't pressed is a no-op, so it's safe to
        # always release both regardless of the current detune setting.
        self._release([voice["note"], voice["detune_note"]])

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
        self._channels[layer_idx] = self._new_channel(instrument_id)
        return old

    def restore_channel(self, layer_idx, channel):
        """Put a channel previously returned by assign_channel() back as-is."""
        self._silence_channel(self._channels[layer_idx])
        self._channels[layer_idx] = channel

    # ── Sound-editor parameter access ─────────────────────────────────────────

    def get_channel_param(self, layer_idx, pad_or_none, key):
        target, _ = self._channel_target(layer_idx, pad_or_none)
        return target["params"][key]

    def set_channel_param(self, layer_idx, pad_or_none, key, value):
        target, apply = self._channel_target(layer_idx, pad_or_none)
        target["params"][key] = value
        apply(target)

    def reset_channel(self, layer_idx, pad_or_none):
        """Restore a channel's voice (or one of its kit sounds) to the sound
        it was built with."""
        target, apply = self._channel_target(layer_idx, pad_or_none)
        target["params"] = dict(target["defaults"])
        apply(target)

    def get_drum_param(self, pad_idx, key):
        return self._sequencer_kit[pad_idx]["params"][key]

    def set_drum_param(self, pad_idx, key, value):
        sound = self._sequencer_kit[pad_idx]
        sound["params"][key] = value
        self._apply_drum_params(sound)

    def reset_drum(self, pad_idx):
        """Restore a sequencer kit sound to the sound it was built with."""
        sound = self._sequencer_kit[pad_idx]
        sound["params"] = dict(sound["defaults"])
        self._apply_drum_params(sound)

    # ── Grooves (called by code.py for the menu's SAVE / LOAD) ────────────────

    def snapshot_sounds(self):
        """Every sound edit as plain data: the sequencer kit's 8 sounds, and
        each loop layer's instrument id plus its params (one dict for a
        melodic voice, one per pad for a kit)."""
        layers = []
        for channel in self._channels:
            if channel["type"] == "melodic":
                params = dict(channel["data"]["params"])
            else:
                params = [dict(sound["params"]) for sound in channel["data"]]
            layers.append({"id": channel["id"], "params": params})
        return {"kit": [dict(sound["params"]) for sound in self._sequencer_kit],
                "layers": layers}

    def restore_sounds(self, data):
        """Put back a snapshot_sounds(). Every layer gets a fresh instance of
        its saved instrument (silencing whatever it had), then the saved
        params on top -- see _merged_params."""
        for sound, saved in zip(self._sequencer_kit, data.get("kit", [])):
            sound["params"] = _merged_params(sound, saved)
            self._apply_drum_params(sound)

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
            if channel["type"] == "melodic":
                voice = channel["data"]
                voice["params"] = _merged_params(voice, saved)
                self._apply_voice_params(voice)
            else:
                for sound, sound_saved in zip(channel["data"], saved):
                    sound["params"] = _merged_params(sound, sound_saved)
                    self._apply_drum_params(sound)

    def _channel_target(self, layer_idx, pad_or_none):
        """(params-owning dict, apply fn) for a channel: melodic channels
        have one voice (pad ignored); kit channels pick a sound by pad."""
        channel = self._channels[layer_idx]
        if channel["type"] == "melodic":
            return channel["data"], self._apply_voice_params
        return channel["data"][pad_or_none or 0], self._apply_drum_params

    def _apply_voice_params(self, voice):
        params   = voice["params"]
        waveform = WAVEFORM_TABLES[params["wave"]]
        notes    = (voice["note"], voice["detune_note"])
        lfo      = voice["lfo"]
        dest     = params["lfo_dest"]
        depth    = params["lfo_depth"]
        lfo.rate = params["lfo_rate"]

        # Envelope/Biquad are immutable value objects in synthio -- rebuild
        # rather than mutate, and share the new instance across both notes.
        envelope = synthio.Envelope(
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

        for note in notes:
            note.waveform = waveform
            note.envelope = envelope
            note.filter   = filt

            ring_freq = params["ring"]
            note.ring_frequency = ring_freq
            if ring_freq and note.ring_waveform is None:
                note.ring_waveform = WAVEFORM_TABLES[1]  # square: bright ring carrier

        amp = params["amp"]
        if dest == 1 and depth > 0:  # vibrato: wobble pitch around center
            lfo.scale, lfo.offset = depth * _VIBRATO_MAX_BEND, 0.0
            for note in notes:
                note.bend, note.amplitude = lfo, amp
        elif dest == 2 and depth > 0:  # tremolo: wobble amplitude below the voice's set level
            lfo.scale, lfo.offset = amp * depth / 2, amp * (1.0 - depth / 2)
            for note in notes:
                note.amplitude, note.bend = lfo, 0.0
        else:  # off, filter wobble (handled above via the filter itself), or depth == 0
            for note in notes:
                note.bend, note.amplitude = 0.0, amp

    def _apply_drum_params(self, sound):
        params, note = sound["params"], sound["note"]
        note.frequency = params["tune"]
        note.amplitude = params["amp"]

        old_env = note.envelope
        note.envelope = synthio.Envelope(
            attack_time=params["attack"], attack_level=old_env.attack_level,
            decay_time=params["decay"],   sustain_level=old_env.sustain_level,
            release_time=old_env.release_time,
        )

        old_filt = note.filter
        note.filter = synthio.Biquad(
            old_filt.mode,
            frequency=params["cutoff"], Q=old_filt.Q,
        )

        ring_freq = params["ring"]
        note.ring_frequency = ring_freq
        if ring_freq and note.ring_waveform is None:
            note.ring_waveform = WAVEFORM_TABLES[1]  # square: bright ring carrier

    # ── Private ───────────────────────────────────────────────────────────────

    def _new_channel(self, instrument_id):
        channel = instantiate_instrument(instrument_id)
        if channel["type"] == "melodic":
            # Most voices' construction args already match their params 1:1,
            # but a voice can ship with e.g. LFO routing already engaged --
            # apply once up front so that's live immediately, not just
            # after the first edit.
            self._apply_voice_params(channel["data"])
        return channel

    def _silence_channel(self, channel):
        """Release everything a channel might be sounding and drop its
        scheduled auto-releases, so nothing is left pointing at (or still
        playing from) an instance that's about to leave its slot."""
        if channel["type"] == "melodic":
            voice = channel["data"]
            voice["sounding_pad"] = None
            notes = [voice["note"], voice["detune_note"]]
        else:
            notes = [sound["note"] for sound in channel["data"]]
        self._synth.release(notes)
        self._pending_releases = [
            r for r in self._pending_releases
            if not any(r[1] is n for n in notes)
        ]

    def _trigger_drum(self, sound):
        bend_lfo = sound.get("bend_lfo")
        if bend_lfo is not None:
            bend_lfo.retrigger()
        self._press_with_hold([sound["note"]], sound["hold_ms"])

    def _press_with_hold(self, notes, hold_ms):
        # Release any previous press of these notes before re-triggering,
        # otherwise synthio stacks voices.
        self._synth.release(notes)
        self._synth.press(notes)

        if hold_ms == 0:
            # Percussive: release immediately; envelope handles the tail.
            self._synth.release(notes)
        else:
            release_at = time.monotonic() + hold_ms / 1000.0
            key = notes[0]
            # Remove stale entry for this voice if any
            self._pending_releases = [r for r in self._pending_releases if r[1] is not key]
            self._pending_releases.append((release_at, key, notes))

    def _release(self, notes):
        self._synth.release(notes)
        key = notes[0]
        self._pending_releases = [r for r in self._pending_releases if r[1] is not key]

    def update(self):
        """Process scheduled releases. Call once per main-loop iteration."""
        if not self._pending_releases:
            return
        now = time.monotonic()
        still_pending = []
        for release_at, key, notes in self._pending_releases:
            if now >= release_at:
                self._synth.release(notes)
            else:
                still_pending.append((release_at, key, notes))
        self._pending_releases = still_pending

    def deinit(self):
        self._synth.deinit()
        self._audio.deinit()
