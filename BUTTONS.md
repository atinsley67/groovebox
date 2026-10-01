# Groovebox — Button Reference

Pads and LEDs are numbered 1–8 here, left to right.

## Global (always active)

| Button | Short press | Long press | Hold + pad |
|---|---|---|---|
| MODE | Cycle active layer / track | Switch between LOOP and SEQ modes (0.6 s) | Jump to that layer / track (1–8) |
| PLAY/STOP | Play / pause (see below for what it controls) | Clear the active mode (hold 2 s) | — |
| UP / DOWN | Volume of the active layer (LOOP) or selected track (SEQ), 5% a step (hold to repeat) | — | — |
| MENU | Open the menu | — | — |

**Volume:** every loop layer and every sequencer track has its own volume, 0–100% (it starts at 100%). The display shows the new level for a moment (`V 80`). A layer keeps its volume when you give it a different instrument, and grooves save every volume.

**PLAY/STOP** controls:
- **Synced session** (the loop was recorded while the sequencer ran): both the loop and the sequencer, together.
- **SEQ mode otherwise:** the sequencer only.
- **LOOP mode otherwise:** the loop only.

Resuming always restarts from the top, so synced parts come back in step. Clearing every loop layer while the sequencer runs keeps the session synced: PLAY/STOP still controls both, and the next take syncs to the sequencer again.

The BPM is set in the menu (`BPM `). **It's locked** (the menu shows `LOCK`) while a synced session has any loop content (or a take is counting in or recording), and while a free-form loop has any layer playing (even when paused). **Switching to SEQ** is also blocked (`LOCK`) under that same free-form condition.

The BEAT LED pulses on each beat while the sequencer's clock runs.

---

## MENU

MENU opens the menu. It works in either mode, and the loop or pattern keeps playing while it's open. Inside the menu the controls change:

| Control | In the menu |
|---|---|
| MENU | Select: enter the highlighted item, edit the value, or run the action |
| PLAY/STOP | Back one level; at the top, close the menu |
| UP / DOWN | Move the highlight, or step a value while editing (hold to repeat) |
| MODE | Unchanged: change layer, track or mode, and the menu follows |
| Pads | Unchanged: they keep playing the active mode, and their LEDs keep showing it |
| RECORD, MUTE | Do nothing while the menu is open |

Every part of the menu is a list. The display shows the highlighted item, and UP / DOWN wrap around from the last item to the first.

### Top of the menu

| Item | Does | Available in |
|---|---|---|
| `SND ` | Edit a sound | LOOP and SEQ |
| `ASGN` | Choose the layer's instrument | LOOP only |
| `BPM ` | Set the tempo | LOOP and SEQ |
| `EXT ` | Double the loop length | LOOP only |
| `MIRR` | Copy the layer's first half over its second | LOOP only |
| `SAVE` | Save the groove | LOOP and SEQ |
| `LOAD` | Load a groove | LOOP and SEQ |

A LOOP-only item shows `N/A ` in SEQ mode, or if it can't run right now.

### BPM — tempo

MENU starts editing: UP / DOWN change the BPM by 1 (hold to repeat; range 40–300), shown as `b120`. MENU or PLAY/STOP finishes. If the tempo is locked (see *Global* above), `LOCK` shows first, then the current BPM, which can't be changed.

### SND — sound editing

What gets edited:
- **SEQ mode:** the selected track's drum sound.
- **LOOP mode:** the active layer's own instrument.

Each loop layer has its own copy of its instrument, and the sequencer has its own kit. Editing one never changes another.

The name of the sound being edited shows first, then the list of its parameters:

| Action | Result |
|---|---|
| UP / DOWN | Move through the parameters (their names show) |
| MENU on a parameter | Edit it: UP / DOWN change the value, which shows while you edit. MENU or PLAY/STOP goes back to the list |
| MENU on `RST ` | Shows `SURE`; MENU again restores this sound's original settings (PLAY/STOP cancels) |

The menu remembers which parameter you were on, separately for melodic voices and drum sounds, so a repeat tweak is one press away.

**On a kit layer** you edit the sound of the last pad you played on that layer. Play another pad to edit that one instead: its name flashes. The name also flashes when MODE moves you to another layer or track.

**Melodic voices**, in list order:

| Item | Parameter |
|---|---|
| `AMP ` | Volume |
| `WAVE` | Sine / square / saw / triangle |
| `ATK ` | Attack |
| `DEC ` | Decay |
| `SUS ` | Sustain |
| `REL ` | Release |
| `CUT ` | Filter cutoff |
| `RES ` | Filter resonance |
| `LFOR` | LFO rate |
| `LFOD` | LFO depth |
| `LDST` | LFO target: off / vibrato / tremolo / filter |
| `RING` | Ring-mod frequency (0 = off) |
| `DTUN` | Unison detune |
| `RST ` | Reset |

**Drum / kit sounds**, in list order (narrower ranges, so a drum stays a drum):

| Item | Parameter |
|---|---|
| `AMP ` | Volume |
| `TUNE` | Pitch |
| `ATK ` | Attack |
| `DEC ` | Decay |
| `TONE` | Filter |
| `SNAP` | Ring-mod amount (0 = off) |
| `RST ` | Reset |

`AMP ` is the sound's own level. The channel volume (UP / DOWN outside the menu) scales it.

### ASGN — choose a layer's instrument (LOOP only)

The list starts on the layer's current instrument: `KIT `, `BASS`, `REES`, `ACID`, `STAB`, `PLUK`, `HOOV`, `PAD `.

- **Browse:** the name shows right away. The sound switches once you stop on it for a moment, so what's already recorded plays on the new instrument live while you browse. You can also play the pads to try it.
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
- every layer and track volume

It doesn't save a recording that's still in progress, or which layer, track or page was selected. Grooves saved before channel volumes existed load with every volume at 100%.

There are 16 slots. Pick one with UP / DOWN. A `*` means the slot holds a groove:

| Display | Meaning |
|---|---|
| `S03 ` | SAVE to slot 3, which is empty |
| `S03*` | SAVE over slot 3's groove, which will be overwritten |
| `L03*` | LOAD slot 3's groove |
| `L03 ` | LOAD, slot 3 is empty (MENU shows `N/A `) |

MENU saves or loads, then shows `DONE` and returns to the top of the menu. If it fails:
- `RO  ` means the drive isn't writable (see *Storage* below).
- `FULL` means the drive is full.
- `ERR ` means the file couldn't be read.

A failed save or load changes nothing.

Loading replaces the whole session and stops playback. Press PLAY to hear it; a synced groove comes back in step with the sequencer.

Saving while playing can cause a brief timing hiccup while the file is written.

**Storage:** grooves are files in `/grooves/` on the CIRCUITPY drive (`slot1.json` … `slot16.json`). So the groovebox can write them, the drive is read-only to your computer during normal use. To copy files over, press BOOTSEL during startup to boot into safe mode.

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
| UP / DOWN | The active layer's volume | — |

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
| UP / DOWN | The selected track's volume |

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
