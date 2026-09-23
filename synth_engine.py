import audiobusio
import synthio
import time

import config
from sound_presets import build_sounds, build_melodic_voices, WAVEFORM_TABLES

_VIBRATO_MAX_BEND = 1.0 / 12  # bend depth (1 semitone) at full LFO depth


class SynthEngine:
    def __init__(self):
        self._audio = audiobusio.I2SOut(
            bit_clock=config.I2S_BIT_CLOCK,
            word_select=config.I2S_WORD_SELECT,
            data=config.I2S_DATA_OUT,
        )
        self._synth = synthio.Synthesizer(sample_rate=config.SAMPLE_RATE)
        self._audio.play(self._synth) # type: ignore # The local stub doesn't like this, but it's correct.

        self._sounds = build_sounds()

        # One dedicated voice per melodic loop layer; index i == loop layer
        # (config.NUM_KIT_LAYERS + i).
        self._melodic_voices = build_melodic_voices()
        # Most voices' construction args already match their params 1:1, but
        # a voice can ship with e.g. LFO routing already engaged (params
        # differing from a freshly-constructed Note's defaults) -- apply
        # once up front so that's live immediately, not just after first edit.
        for voice in self._melodic_voices:
            self._apply_voice_params(voice)

        # Track scheduled auto-releases: list of (release_at, note)
        self._pending_releases = []

    # ── Public API ────────────────────────────────────────────────────────────

    def trigger(self, pad_index):
        """Press a pad. Schedules auto-release based on the sound's hold_ms."""
        if pad_index < 0 or pad_index >= len(self._sounds):
            return
        sound = self._sounds[pad_index]
        bend_lfo = sound.get("bend_lfo")
        if bend_lfo is not None:
            bend_lfo.retrigger()
        self._press_with_hold([sound["note"]], sound["hold_ms"])

    def note_off(self, pad_index):
        """Manually release a held note (called on PAD_UP for melodic pads)."""
        if pad_index < 0 or pad_index >= len(self._sounds):
            return
        self._release([self._sounds[pad_index]["note"]])

    def layer_is_melodic(self, layer_idx):
        return layer_idx >= config.NUM_KIT_LAYERS

    def trigger_layer_pad(self, layer_idx, pad_index):
        """Press a pad in the context of a loop layer: kit layers play one of
        the 8 fixed sounds (like trigger()); melodic layers play a scale
        degree on that layer's own dedicated voice (plus a detuned unison
        voice, if that voice's 'detune' param is nonzero)."""
        if not self.layer_is_melodic(layer_idx):
            self.trigger(pad_index)
            return
        voice = self._melodic_voices[layer_idx - config.NUM_KIT_LAYERS]
        freq  = voice["scale"][pad_index]
        voice["note"].frequency = freq

        notes = [voice["note"]]
        detune_cents = voice["params"]["detune"]
        if detune_cents:
            voice["detune_note"].frequency = freq * (2 ** (detune_cents / 1200.0))
            notes.append(voice["detune_note"])
        self._press_with_hold(notes, voice["hold_ms"])

    def release_layer_pad(self, layer_idx):
        """Manually release a melodic layer's voice (PAD_UP while recording/overdubbing)."""
        if not self.layer_is_melodic(layer_idx):
            return
        voice = self._melodic_voices[layer_idx - config.NUM_KIT_LAYERS]
        # Releasing a note that isn't pressed is a no-op, so it's safe to
        # always release both regardless of the current detune setting.
        self._release([voice["note"], voice["detune_note"]])

    # ── SYNTH EDIT parameter access ─────────────────────────────────────────────

    def get_voice_param(self, voice_idx, key):
        return self._melodic_voices[voice_idx]["params"][key]

    def set_voice_param(self, voice_idx, key, value):
        voice = self._melodic_voices[voice_idx]
        voice["params"][key] = value
        self._apply_voice_params(voice)

    def reset_voice(self, voice_idx):
        """Restore a melodic voice to the sound it was built with."""
        voice = self._melodic_voices[voice_idx]
        voice["params"] = dict(voice["defaults"])
        self._apply_voice_params(voice)

    def get_drum_param(self, pad_idx, key):
        return self._sounds[pad_idx]["params"][key]

    def set_drum_param(self, pad_idx, key, value):
        sound = self._sounds[pad_idx]
        sound["params"][key] = value
        self._apply_drum_params(sound)

    def reset_drum(self, pad_idx):
        """Restore a drum/kit sound to the sound it was built with."""
        sound = self._sounds[pad_idx]
        sound["params"] = dict(sound["defaults"])
        self._apply_drum_params(sound)

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

    def sound_name(self, pad_index):
        return self._sounds[pad_index]["name"]

    def is_melodic(self, pad_index):
        """Melodic pads need explicit note_off on PAD_UP."""
        return self._sounds[pad_index]["hold_ms"] > 0

    def deinit(self):
        self._synth.deinit()
        self._audio.deinit()
