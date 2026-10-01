# Groovebox — Button Reference

Pads and LEDs are numbered 1–8 here, left to right.

## Global (always active)

| Button | Short press | Long press | Hold + pad |
|---|---|---|---|
| MODE | Cycle active layer / track | Switch between LOOP and SEQ modes (0.6 s) | Jump to that layer / track (1–8) |
| PLAY/STOP | Play / pause (see below for what it controls) | Clear the active mode (hold 2 s) | — |
| TEMPO+ / TEMPO− | BPM up / down by 1 (hold to repeat; range 40–300) | — | — |
| MENU | Open the menu | — | — |

**PLAY/STOP** controls:
- **Synced session** (the loop was recorded while the sequencer ran): both the loop and the sequencer, together.
- **SEQ mode otherwise:** the sequencer only.
- **LOOP mode otherwise:** the loop only.

Resuming always restarts from the top, so synced parts come back in step. Clearing every loop layer while the sequencer runs keeps the session synced: PLAY/STOP still controls both, and the next take syncs to the sequencer again.

**BPM is locked** (the display shows `LOCK`) while a synced session has any loop content (or a take is counting in or recording), and while a free-form loop has any layer playing (even when paused). **Switching to SEQ** is also blocked (`LOCK`) under that same free-form condition.

The BEAT LED pulses on each beat while the sequencer's clock runs.

---

## MENU

MENU opens the menu. It works in either mode, and the loop or pattern keeps playing while it's open. Inside the menu the controls change:

| Control | In the menu |
|---|---|
| MENU | Enter / run the highlighted item; confirm |
| PLAY/STOP | Back to the top of the menu; at the top, close the menu |
| TEMPO+ / TEMPO− | Move the highlight, or step a value (hold to repeat) |
| Pads | Jump straight to an item / parameter / slot |
| MODE | Unchanged: change layer, track or mode, and the menu follows |
| RECORD | Only used in SOUND (see below) |

Pads don't play sounds, TEMPO doesn't change the BPM, and MUTE does nothing while the menu is open.

### Top of the menu

| Pad | Item | Available in |
|---|---|---|
| 1 | `SND ` — edit a sound | LOOP and SEQ |
| 2 | `ASGN` — choose the layer's instrument | LOOP only |
| 3 | `EXT ` — double the loop length | LOOP only |
| 4 | `MIRR` — copy the layer's first half over its second | LOOP only |
| 5 | `SAVE` — save the groove | LOOP and SEQ |
| 6 | `LOAD` — load a groove | LOOP and SEQ |

A LOOP-only item shows `N/A ` in SEQ mode, or if it can't run right now.

### SND — sound editing

What gets edited:
- **SEQ mode:** the selected track's drum sound.
- **LOOP mode:** the active layer's own instrument.

Each loop layer has its own copy of its instrument, and the sequencer has its own kit. Editing one never changes another.

| Action | Result |
|---|---|
| Pad | Select a parameter (its name shows) |
| TEMPO+ / TEMPO− | Change it (the value shows briefly) |
| MENU on `RST ` | Restore this sound's original settings |
| RECORD | Melodic voice: switch page 1 / 2 (the RECORD LED means page 1, the PLAY LED page 2). Kit layer: step to the next of its 8 sounds (its name flashes) |

On a kit layer, editing starts on the last pad you played on that layer.

**Melodic voices**

| Pad | Page 1 | Page 2 |
|---|---|---|
| 1 | `AMP ` volume | `LFOR` LFO rate |
| 2 | `WAVE` sine / square / saw / triangle | `LFOD` LFO depth |
| 3 | `ATK ` attack | `LDST` LFO target: off / vibrato / tremolo / filter |
| 4 | `DEC ` decay | `RING` ring-mod frequency (0 = off) |
| 5 | `SUS ` sustain | `DTUN` unison detune |
| 6 | `REL ` release | — |
| 7 | `CUT ` filter cutoff | — |
| 8 | `RES ` filter resonance | `RST ` reset |

**Drum / kit sounds** (one page, with narrower ranges so a drum stays a drum)

| Pad | Parameter |
|---|---|
| 1 | `AMP ` volume |
| 2 | `TUNE` pitch |
| 3 | `ATK ` attack |
| 4 | `DEC ` decay |
| 5 | `TONE` filter |
| 6 | `SNAP` ring-mod amount (0 = off) |
| 8 | `RST ` reset |

### ASGN — choose a layer's instrument (LOOP only)

| Pad | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| Instrument | `KIT ` | `BASS` | `REES` | `ACID` | `STAB` | `PLUK` | `HOOV` | `PAD ` |

- **Browse:** the name shows right away. The sound switches once you stop on it for a moment, so what's already recorded plays on the new instrument live while you browse.
- **Keep or undo:** MENU keeps the choice. PLAY/STOP puts the original instrument back, with its sound edits intact.
- **Defaults:** layer 1 is `KIT `, and layers 2–8 are `BASS` through `PAD ` in order.

### EXT / MIRR — loop length (LOOP only)

- **EXT** doubles the loop length for every layer. The new second half is silent, ready to fill.
- **MIRR** replaces the active layer's second half with a copy of its first half.

Both show `DONE`, or `N/A ` if there's no loop yet or something is being recorded or overdubbed.

### SAVE / LOAD — grooves

A groove saves everything:
- the BPM
- the sequencer pattern and mutes
- every recorded loop layer, muted or not
- each layer's instrument
- all sound edits

It doesn't save a recording that's still in progress, or which layer, track or page was selected.

There are 8 slots, one per pad. Pick one with the pads or TEMPO+/−:

| Display | Meaning |
|---|---|
| `SAV3` | SAVE, slot 3 is empty |
| `OVR3` | SAVE, slot 3 already has a groove, which will be overwritten |
| `LOD3` | LOAD, slot 3 has a groove |
| `EMP3` | LOAD, slot 3 is empty (MENU shows `N/A `) |

MENU saves or loads, then shows `DONE` and returns to the top of the menu. If it fails:
- `RO  ` means the drive isn't writable (see *Storage* below).
- `FULL` means the drive is full.
- `ERR ` means the file couldn't be read.

A failed save or load changes nothing.

Loading replaces the whole session and stops playback. Press PLAY to hear it; a synced groove comes back in step with the sequencer.

Saving while playing can cause a brief timing hiccup while the file is written.

**Storage:** grooves are files in `/grooves/` on the CIRCUITPY drive (`slot1.json` … `slot8.json`). So the groovebox can write them, the drive is read-only to your computer during normal use. To copy files over, press BOOTSEL during startup to boot into safe mode.

---

## LOOP mode

The display shows the active layer (`L1` … `L8`) when it's empty or playing. Otherwise it shows the layer's state:

| Display | State |
|---|---|
| `ARM ` | Armed, waiting |
| `ARM3` `ARM2` `ARM1` | Counting in |
| `REC ` | Recording (`SREC` when synced to the sequencer) |
| `DUB ` | Overdubbing |
| `MUTE` | Muted |

The RECORD LED is lit while recording, and the PLAY LED while the loop is audibly playing.

There are **8 layers**, all sharing one loop length. Use MODE to move between them; you can't change layer mid-recording.

### Recording

| Situation | Press RECORD, then… |
|---|---|
| **First layer, sequencer stopped** (free-form) | `ARM ` — your first pad press starts recording. Press RECORD again to finish: that sets the loop length and playback starts. |
| **First layer, sequencer playing** (synced) | Counts in `ARM3`–`ARM1` to the next bar, then records bar after bar (`SREC`). Press RECORD to stop: recording carries on to the end of the current bar, so the loop is always whole bars. |
| **Any later layer** | Counts in to the top of the existing loop, records exactly one loop length, then commits by itself. Pressing RECORD early stops capturing, but the layer keeps the full loop length. |

- RECORD during `ARM` or a count-in cancels it.
- A pad pressed during `ARM1` counts as landing on beat 1.
- In a synced session, recorded notes snap to the 1/16 grid. You still hear each note the moment you play it; only the playback timing is tidied.
- Melodic notes keep the length you held them for.

### Overdub

| Action | Result |
|---|---|
| RECORD (layer playing) | Overdub: add notes while it loops (`DUB `) |
| RECORD (overdubbing) | Back to playback |

RECORD does nothing on a muted layer.

### Layer control

| Button | Short press | Long press |
|---|---|---|
| MUTE | Mute / unmute the active layer (it rejoins in time) | Clear the active layer (hold 0.6 s) |
| PLAY/STOP | Pause / resume | Clear **all** layers (hold 2 s) |

---

## SEQ mode

The display shows `T1P1`: the track and the step page.

| Action | Result |
|---|---|
| Pads 1–8 | Toggle that step for the selected track, and preview its sound |
| RECORD | Switch step page: P1 = steps 1–8, P2 = steps 9–16 |
| PLAY/STOP | Start / stop the sequencer (hold 2 s: clear all tracks) |
| MODE | Cycle the selected track (MODE + pad jumps to it) |
| MUTE | Mute / unmute the selected track (hold 0.6 s: clear its steps) |

The pad LEDs show the selected track's steps on the current page, and the step being played is always lit.

---

## Using both together

1. Build a pattern in SEQ mode and start it with PLAY/STOP.
2. Long-press MODE to switch to LOOP.
3. Press RECORD. The loop counts in to the next bar and records in time with the sequencer.
4. Press RECORD to finish. The loop ends on a bar line, and both keep playing.
5. Add more layers: move to an empty layer (MODE, or MODE + pad) and record on it.
6. Long-press MODE to go back to SEQ at any time. Both keep playing, and PLAY/STOP now controls both.

If the sequencer *isn't* running when you record the first layer, the loop is free-form. SEQ mode and the tempo stay locked until you clear it (hold PLAY/STOP for 2 s in LOOP mode) or mute every layer.
