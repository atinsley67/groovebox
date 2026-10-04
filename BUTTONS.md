# Groovebox — Button Reference

## Layout

All 16 keys of the 4x4 grid are pads, numbered 1–16 here, row by row from the top left (pads 1–4 on the top row, 13–16 on the bottom row). What they do depends on the view (see *VIEW — the channel view* below); in each mode's own view, what each pad plays is under *LOOP mode* and *SEQ mode*.

The function keys, as the 2x5 block stands:

| | Left | Right |
|---|---|---|
| Row 1 | LOOP/SEQ | PLAY/STOP |
| Row 2 | MENU | UP |
| Row 3 | RECORD | DOWN |
| Row 4 | VIEW | KEY MODE |
| Row 5 | MUTE | CLEAR |

Every key does one thing, the moment you press it. There are no long presses; only UP / DOWN repeat while held.

Every key has a light:
- **Pads:** blue while sounding (or, in SEQ mode, while their step is on). The channel view has its own colors.
- **RECORD:** red while recording.
- **PLAY/STOP:** dim green while playing, flashing bright green on each beat while the sequencer runs.
- **KEY MODE:** in the channel view, white for select and grey for mute.
- **CLEAR:** blinks orange while a clear waits for you to confirm it.

The layout can be changed in `config.py` (`FUNC_LAYOUT`); see `HARDWARE.md`.

## The function keys

| Key | Menu closed | Menu open |
|---|---|---|
| LOOP/SEQ | Switch between LOOP and SEQ modes | Same; the menu follows |
| PLAY/STOP | Play / pause (see below for what it controls) | Same |
| MENU | Open the menu; confirm a CLEAR | Select |
| RECORD | Record (see *LOOP mode*) | Back one level; at the top, close the menu |
| UP / DOWN | Volume of the active layer (LOOP) or selected track (SEQ), 5% a step | Move the highlight, or step a value |
| VIEW | Switch the pads between the mode's own view and the channel view | Same |
| KEY MODE | In the channel view: what a pad tap does (select / mute) | Same |
| MUTE | Mute / unmute the active layer or selected track | Nothing |
| CLEAR | Clear the active layer or selected track, or everything (see below) | Nothing |

**Volume:** every loop layer and every sequencer track has its own volume, 0–100% (it starts at 100%). The display shows the new level for a moment (`V 80`). A layer keeps its volume when you give it a different instrument, and grooves save every volume.

**PLAY/STOP** controls:
- **Synced session** (the loop was recorded while the sequencer ran): both the loop and the sequencer, together.
- **SEQ mode otherwise:** the sequencer only.
- **LOOP mode otherwise:** the loop only.

Resuming always restarts from the top, so synced parts come back in step. Clearing every loop layer while the sequencer runs keeps the session synced: PLAY/STOP still controls both, and the next take syncs to the sequencer again.

The BPM is set in the menu (`BPM `). **It's locked** (the menu shows `LOCK`) while a synced session has any loop content (or a take is counting in or recording), and while a free-form loop has any layer playing (even when paused). **Switching to SEQ** is also blocked (`LOCK`) under that same free-form condition.

### CLEAR

CLEAR never clears straight away:

1. **CLEAR** picks the active layer (LOOP) or selected track (SEQ). The display shows `CLR3` (channel 3), and CLEAR blinks orange.
2. **CLEAR again** switches to every layer, or every track (`CLRA`). Pressing it again goes back to the one channel.
3. **MENU** confirms (`DONE`). Clearing a track also unmutes it.

Any other function key cancels, and does nothing else (so PLAY/STOP won't also stop playback). Doing nothing for 3 seconds cancels too. The pads keep playing while CLEAR waits; tapping a pad in the channel view cancels it.

---

## VIEW — the channel view

VIEW switches the pads between the mode's own view (playing notes in LOOP, steps in SEQ) and the **channel view**, which shows every channel at once:

| | |
|---|---|
| Pads 1–8 (top two rows) | Loop layers 1–8 |
| Pads 9–16 (bottom two rows) | Sequencer tracks 1–8 |

| Color | Means |
|---|---|
| Off | Empty |
| Dim blue | Has something in it |
| Dim grey | Muted |
| Bright blue flash | A note just played on it |
| Red | Recording or overdubbing (blinking: armed or counting in) |
| Slow pulse | The selected channel |

In the channel view, the pads don't play anything. **KEY MODE** picks what a tap does; the view always opens in select, and the KEY MODE key shows which:
- **Select (white):** the tap chooses that layer or track and takes you straight back to its own view, ready to play. Choosing a track from LOOP (or a layer from SEQ) switches modes too. If that's blocked, `LOCK` shows; choosing another layer while one is recording shows `BUSY`. Either way you stay in the channel view.
- **Mute (grey):** the tap mutes or unmutes that channel, and you stay in the view, so you can mix a groove live.

---

## MENU

MENU opens the menu. It works in either mode, and the loop or pattern keeps playing while it's open. Inside the menu the controls change:

| Control | In the menu |
|---|---|
| MENU | Select: enter the highlighted item, edit the value, or run the action |
| RECORD | Back one level; at the top, close the menu |
| UP / DOWN | Move the highlight, or step a value while editing (hold to repeat) |
| PLAY/STOP, LOOP/SEQ, VIEW, KEY MODE | Unchanged; the menu follows a change of mode, layer or track |
| Pads | Unchanged: they keep playing the active mode (or the channel view), and their lights keep showing it |
| MUTE, CLEAR | Do nothing while the menu is open |

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

MENU starts editing: UP / DOWN change the BPM by 1 (hold to repeat; range 40–300), shown as `b120`. MENU or RECORD finishes. If the tempo is locked (see *The function keys* above), `LOCK` shows first, then the current BPM, which can't be changed.

### SND — sound editing

What gets edited:
- **SEQ mode:** the selected track's drum sound.
- **LOOP mode:** the active layer's own instrument.

Each loop layer has its own copy of its instrument, and the sequencer has its own kit. Editing one never changes another.

The name of the sound being edited shows first, then the list of its parameters:

| Action | Result |
|---|---|
| UP / DOWN | Move through the parameters (their names show) |
| MENU on a parameter | Edit it: UP / DOWN change the value, which shows while you edit. MENU or RECORD goes back to the list |
| MENU on `RST ` | Shows `SURE`; MENU again restores this sound's original settings (RECORD cancels) |

The menu remembers which parameter you were on, separately for melodic voices and drum sounds, so a repeat tweak is one press away.

**On a kit layer** you edit the sound of the last pad you played on that layer. Play another pad to edit that one instead: its name flashes. The name also flashes when you choose another layer or track.

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
- **Keep or undo:** MENU keeps the choice. RECORD puts the original instrument back, with its sound edits intact.
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

It doesn't save a recording that's still in progress, or which layer or track was selected. Grooves saved before channel volumes existed load with every volume at 100%. Grooves saved before the 16-pad grid sound the same as before: their melodic notes move to the pads that play those notes now.

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

RECORD lights red while recording, and PLAY/STOP green while the loop is audibly playing.

There are **8 layers**, all sharing one loop length. Choose one in the channel view (VIEW, then tap its pad); you can't change layer mid-recording.

### What the pads play

**A kit layer:** a different drum sound on each pad.

| | | | |
|---|---|---|---|
| 1 `KICK` | 2 `DNBK` | 3 `CHH ` | 4 `OHH ` |
| 5 `SNRE` | 6 `CLAP` | 7 `COWB` | 8 `WOOD` |
| 9 `LTOM` | 10 `MTOM` | 11 `HTOM` | 12 `RIM ` |
| 13 `SHKR` | 14 `CONG` | 15 `RIDE` | 16 `CRSH` |

(House kick, DnB kick, closed and open hi-hat, snare, clap, cowbell, woodblock; low, mid and high tom, rimshot, shaker, conga, ride, crash.)

**A melodic layer:** three octaves of a minor pentatonic scale, lowest at the bottom left. Notes rise along each row, left to right, then continue on the row above, so pad 13 is the root and pad 4 is the root three octaves up. The roots fall on a diagonal: pads 13, 10, 7 and 4. Every voice uses the same key, so any layers played together stay in tune.

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

| Key | Does |
|---|---|
| MUTE | Mute / unmute the active layer (it rejoins in time) |
| CLEAR | Clear the active layer; CLEAR twice: **all** layers (MENU confirms) |
| PLAY/STOP | Pause / resume |
| UP / DOWN | The active layer's volume |

---

## SEQ mode

The display shows the selected track (`T1` … `T8`). Tracks 1–8 play the kit's first 8 sounds (`KICK` … `WOOD`, pads 1–8 of a kit layer).

| Action | Result |
|---|---|
| Pads 1–16 | Toggle that step of the bar (pad 1 = step 1, read row by row) for the selected track, and preview its sound |
| RECORD | Nothing |
| PLAY/STOP | Start / stop the sequencer |
| MUTE | Mute / unmute the selected track |
| CLEAR | Clear the selected track's steps; CLEAR twice: **all** tracks (MENU confirms) |
| UP / DOWN | The selected track's volume |

Choose a track in the channel view (VIEW, then tap its pad on the bottom two rows).

The pad lights show the selected track's steps for the whole bar, and the step being played is always lit.

---

## Using both together

1. Build a pattern in SEQ mode and start it with PLAY/STOP.
2. Press LOOP/SEQ to switch to LOOP.
3. Press RECORD. The loop counts in to the next bar and records in time with the sequencer.
4. Press RECORD to finish. The loop ends on a bar line, and both keep playing.
5. Add more layers: choose an empty layer in the channel view (VIEW, then its pad) and record on it.
6. Press LOOP/SEQ to go back to SEQ at any time (or choose a track in the channel view). Both keep playing, and PLAY/STOP now controls both.

If the sequencer *isn't* running when you record the first layer, the loop is free-form. SEQ mode and the tempo stay locked until you clear it (CLEAR twice, then MENU, in LOOP mode) or mute every layer.
