# Groovebox — Button Reference

## Global (always active)

| Button | Short press | Long press | Hold + pad |
|---|---|---|---|
| MODE | Cycle active layer / track | Switch between LOOP and SEQ modes | Jump to that layer / track (1–8) |
| TEMPO+ / TEMPO− | BPM up/down by 1 | — | — |
| SYNTH EDIT | Toggle the sound-editing overlay (SEQ mode, or LOOP mode on a melodic layer; shows `N/A ` on the looper's kit layer) | — | — |

BPM is locked (shows `LOCK`) while a synced loop is playing.

---

## SYNTH EDIT — live sound editing

Press **SYNTH EDIT** in SEQ mode, or while a melodic layer (2–8) is active in LOOP mode, to turn the pads into a parameter grid. Switching between SEQ and a melodic layer with MODE while the overlay is open retargets it live; it automatically exits only if you land on the looper's kit layer (1), since that layer has nothing of its own to edit — it just plays whatever the selected drum sound was last edited to from SEQ.

### Melodic voices (LOOP mode, layers 2–8)

| Pad | Page 1 | Page 2 |
|---|---|---|
| 1 | WAVE (sine/square/saw/triangle) | LFO rate |
| 2 | DETUNE (unison amount) | LFO depth |
| 3 | ATTACK | LFO destination (off / vibrato / tremolo) |
| 4 | DECAY | RING (ring-mod frequency, 0 = off) |
| 5 | SUSTAIN | *reserved* |
| 6 | RELEASE | *reserved* |
| 7 | CUTOFF (filter) | *reserved* |
| 8 | RESONANCE (filter) | RESET — hold ~0.6s to restore this voice's original sound |

### Drum/kit sounds (SEQ mode, editing the selected track)

A smaller, range-limited grid — no waveform swap, and shorter attack/decay ceilings than melodic voices — so edits reshape the sound rather than turning it into a sustained voice. One page only.

| Pad | Param |
|---|---|
| 1 | TUNE (pitch) |
| 2 | ATTACK |
| 3 | DECAY |
| 4 | TONE (lowpass filter) |
| 5 | SNAP (ring-mod amount, 0 = off) |
| 8 | RESET — hold ~0.6s to restore this sound's original settings |

Since the sequencer and the looper's kit layer play the exact same sounds, editing a drum here changes it everywhere it's used.

| Action | Result |
|---|---|
| Pad tap | Select that parameter (its name shows on the display) |
| RECORD | Toggle between page 1 and page 2 (melodic only) |
| TEMPO+ / TEMPO− | Step the selected parameter's value; hold to auto-repeat |

The loop/sequencer keeps playing normally while the overlay is open — it's meant for shaping a sound live while it plays.

---

## LOOP mode — display shows active layer state: `IDLE` / `ARM ` / `REC ` / `PLY ` / `DUB ` / `MUTE`

The looper has **8 independent layers** (1 drum-kit layer + 7 melodic voices), all sharing the same loop length. Use MODE to navigate between them.

### Recording

| Action | Result |
|---|---|
| RECORD (layer IDLE) | Arm recording — waiting for first pad |
| Press any pad (armed) | Starts recording; that sound placed at position 0 |
| RECORD (while recording) | Commit loop → start playback |
| RECORD (while armed) | Cancel arm |

The first layer recorded sets the **master duration**. Subsequent layers automatically commit when that duration elapses, keeping all layers in sync.

**Synced recording** (sequencer was running when you armed the first layer):
- Display shows `SREC` instead of `REC `
- Loop auto-commits at the next bar boundary after at least one full bar
- RECORD can still be pressed to commit immediately

### Overdub

| Action | Result |
|---|---|
| RECORD (layer playing) | Enter overdub — record new events while looping |
| RECORD (while overdubbing) | Commit overdub → back to playback |

### Playback control

| Button | Short press | Long press |
|---|---|---|
| PLAY/STOP | Pause / resume (resume restarts all layers from position 0) | Clear **all** layers (hold 2 s) |
| MUTE | Mute / unmute active layer | Clear active layer (hold 0.6 s) |

Unmuting a layer realigns it to the master loop position so it rejoins in phase.

---

## SEQ mode — display shows `T1P1` (track / page)

| Action | Result |
|---|---|
| Pads 0–7 | Toggle step on/off for selected track; previews the sound |
| RECORD | Toggle step page — P1 = steps 1–8, P2 = steps 9–16 |
| PLAY/STOP | Start / stop sequencer |
| SYNTH EDIT | Edit the selected track's drum/kit sound (see SYNTH EDIT above) |

### Track control

| Button | Short press | Long press |
|---|---|---|
| MODE | Cycle selected track (1–8) | Switch to LOOP mode |
| MODE + pad | Jump to that track directly | — |
| MUTE | Mute / unmute selected track | Clear all steps on selected track (hold 0.6 s) |

---

## Using both together

1. Build your pattern in SEQ mode and start it (PLAY/STOP).
2. Long-press MODE to switch to LOOP.
3. Arm and play — the loop snaps to the bar grid automatically.
4. Long-press MODE to switch back to SEQ — both keep playing.
5. Add more loop layers by cycling to an empty layer (MODE short press or MODE + pad) and recording on it.
6. If the sequencer is *not* running when you record a loop, the loop is free-form and SEQ mode is blocked until the loop is cleared.
