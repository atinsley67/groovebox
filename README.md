# Groovebox

A groovebox built on a Raspberry Pi Pico 2 W running CircuitPython. It has a live looper, a step sequencer, an arpeggiator and a synth with 16 instruments. You play it on a 4x4 grid of light-up mechanical keys and drive it from ten function keys and a 4-character display.

<!-- Photo of the build goes here, e.g.:
![The groovebox](docs/images/groovebox.jpg)
-->

## What it does

- **Looper:** 8 layers sharing one loop length. Record free-form or synced to the sequencer (with a count-in and snap to the 1/16 grid), overdub, mute, double the loop length or mirror its first half.
- **Step sequencer:** 8 drum tracks × 16 steps, running alongside the looper so the two stay in step.
- **Instruments:** a 16-sound drum kit (house and DnB kicks, hats, snare, clap, toms, percussion, ride, crash) and 15 melodic voices: bass, reese, acid, stab, pluck, hoover, pad, jungle sub, organ, chord stab, marimba, bell, chip lead, supersaw and laser. Each layer gets its own copy of its instrument, so sound edits never leak between layers.
- **Sound editing:** waveform, ADSR, filter, LFO, ring mod, detune, pitch envelope and glide for the melodic voices; pitch, length, tone and snap for drums.
- **Key and scale:** every melodic layer plays the same key and scale (pentatonics through Dorian, Phrygian and harmonic minor), so layers always stay in tune. Changing either re-voices loops that are already recorded.
- **Arpeggiator:** per layer, with up, down, up-down, random and as-played modes, three rates and four gate lengths. What it plays is recorded as ordinary notes.
- **Channel view:** all 16 channels (8 loop layers, 8 sequencer tracks) on the pads at once, for selecting or live-muting.
- **AUTO:** an arranger that mutes and unmutes channels on phrase boundaries, with occasional breakdowns and drops.
- **16 save slots** for whole grooves, stored as JSON on the Pico's drive.
- **Lights:** each colour means the same thing everywhere (red recording, yellow your playing, blue content, grey muted, white the playhead).

## Building one

[docs/HARDWARE.md](docs/HARDWARE.md) has the parts list, wiring, layout calibration and troubleshooting. In short: a Pico 2 W on a proto board, an Adafruit NeoKey 5x6 snapped into a 4x4 and a 2x5, a UDA1334A I2S DAC and an HT16K33 quad alphanumeric display, all powered from USB, behind a front panel.

## Installing the code

1. **Install CircuitPython 10.x:** download the UF2 for the [Pico 2 W](https://circuitpython.org/board/raspberry_pi_pico2_w/), hold BOOTSEL while plugging the Pico in, and drag the UF2 onto the drive that appears. It reboots as `CIRCUITPY`.
2. **Add the libraries:** from the [CircuitPython 10.x library bundle](https://circuitpython.org/libraries), copy `adafruit_ht16k33/`, `adafruit_bus_device/` and `neopixel.mpy` into `CIRCUITPY/lib/`.
3. **Copy the code:** every `.py` file in the root of this repo goes in the root of `CIRCUITPY`. Don't copy `tests/` or `docs/`.
4. **Reset the Pico.** A rainbow wave and a scrolling `GROOVEBOX` mean it's working. If nothing lights, open the serial console; the startup error is printed there.

**Updating the code later:** `boot.py` makes the drive writable by the groovebox (so it can save grooves), which makes it **read-only to your computer**. To copy new files over, press BOOTSEL during startup to boot into safe mode, where `boot.py` doesn't run.

If your wiring differs from mine, change the pins and layout tables in [`config.py`](config.py). [docs/HARDWARE.md](docs/HARDWARE.md#calibrating-the-layout) explains how to find the right values with `io_test.py`.

## Playing it

[docs/BUTTONS.md](docs/BUTTONS.md) is the full manual. A first groove:

1. Press **LOOP/SEQ** for SEQ mode, tap some pads to set kick steps, and press **PLAY/STOP**.
2. Press **VIEW**, then tap a pad on the bottom two rows to choose another track, and add steps to it.
3. Press **LOOP/SEQ** for LOOP mode, then **RECORD**. It counts in to the next bar; play some drums, and press **RECORD** again to finish on a bar line.
4. Press **VIEW** and tap a pad on the top two rows to pick an empty layer (layer 2 is a bass), then record a bassline over it.
5. Press **MENU**, scroll to `AUT ` with **UP / DOWN**, and press **MENU** to let the groove arrange itself. **RECORD** closes the menu. **UP / DOWN** set the selected channel's volume.

## How the code fits together

| File | Does |
|---|---|
| `boot.py` | Makes the drive writable by the code, for groove saves |
| `code.py` | The main loop: scans keys, runs the clock, routes events to the modes, menu and views, drives the lights |
| `config.py` | Pins, key and pixel layout tables, tuning and sizes |
| `looper.py` | The 8-layer looper: recording, overdub, sync to the sequencer, playback |
| `sequencer.py` | The 8-track × 16-step sequencer |
| `arp.py` | The arpeggiator, an input effect in front of the looper |
| `arranger.py` | AUTO, the mute arranger |
| `menu.py` | The settings menu: sounds, instruments, ARP, BPM, key and scale, loop length, save and load |
| `synth_engine.py` | The synthio voices: triggering, per-channel instruments, sound parameters, volumes |
| `sound_presets.py` | The drum kit and the melodic instruments |
| `synth_params.py` | The editable sound parameters, their ranges and display names |
| `scales.py` | The keys and scales |
| `groove.py` | Groove files on the drive (SAVE / LOAD) |
| `pad_views.py`, `palette.py` | What the pads show, and the colours |
| `display.py`, `pixels.py` | The 4-character display and the key NeoPixels |
| `hw.py`, `keymap.py` | Key scanning, and the lookups built from config's layout tables |
| `clock.py`, `event_types.py` | The shared timebase and event names |
| `startup.py` | The startup animation |
| `io_test.py` | Hardware test and layout calibration (enabled from `code.py`) |
| `timing_probe.py` | Main-loop timing and heap reports (`config.TIMING_PROBE`) |

### The one rule: keep the main loop allocation-free

CircuitPython can't refill the audio buffer during a garbage collection. If a collection takes longer than the buffer lasts, you hear a click. So the code avoids creating garbage in anything that runs every pass, and keeps long-lived data in flat arrays rather than long lists: a list holding more than about 64 objects can overflow the collector's mark stack and make it re-scan the whole heap, doubling every collection. `tests/test_alloc_patterns.py` checks for patterns that caused clicks before. Bear this in mind when adding features.

## Running the tests

The tests run on a desktop, with no hardware. `tests/fakes.py` stands in for the CircuitPython modules, and `tests/harness.py` runs the real `code.py` main loop against scripted key presses. They need only the Python standard library (3.11 is what I use). From the repo root:

```
python -m unittest discover -s tests
```

For editor autocompletion and type checking against the CircuitPython APIs, install the stubs into a virtual environment:

```
python -m venv .venv
.venv/Scripts/activate        # Windows; on macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Current limitations

- **USB power only.** The NeoPixel power arrangement relies on USB's 5 V. Battery power would need a rethink.
- **The sequencer is one bar long**, and its 8 tracks always play the kit's first 8 sounds.
- **Each loop layer holds 256 notes**, about 16 bars of 16th-note arpeggio.
- **Arpeggiator settings and AUTO aren't saved** with grooves (the notes an arpeggiator recorded are).
- **SAVE and LOAD stop playback.** File work while audio plays caused glitches, so it happens in silence.
- **Committing a very long arpeggiator take** can cause a brief pause in the audio.
- **The 7-note scales can clash** when two layers land on neighbouring notes. The pentatonics never do.
- **Updating the code** needs a safe-mode boot, because the drive is read-only to the computer during normal use.
- **No MIDI and no Wi-Fi**, even though the Pico 2 W has the radio.

## Future ideas

- A chord progression lane: a key or chord per bar, so loops follow a progression.
- More arpeggiator: an octave range, a note-repeat mode for drums, and saving its settings with grooves.
- A choice of sound for each sequencer track.
- Longer sequencer patterns, or chaining patterns.
- USB MIDI: clock sync with other gear, and notes in and out.
- Making long arpeggiator takes commit without the pause.

## Licence

[MIT](LICENSE)
