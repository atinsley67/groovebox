"""
Groovebox — main entry point.

Main loop responsibilities:
  1. Scan hardware for button events.
  2. Drive the drift-free tempo clock (TICK / BEAT events) when playing.
  3. Dispatch events to the active (focused) mode.
  4. Run sync coordinator: looper + sequencer dual-play and snap-to-bar logic.
  5. Call synth_engine.update() each iteration for pending note-off releases.

MODE button gesture handling (intercepted here, not passed to modes):
  Short press alone  — cycle active layer / track within current mode
  Long press alone   — switch global mode (looper ↔ sequencer)
  Hold + pad press   — jump directly to that layer / track

Sync modes (sync_mode variable):
  "none"     — no loop recorded yet; modes are fully independent
  "snap"     — sequencer was playing when looper started recording; both play
               simultaneously; BPM changes blocked to prevent drift
  "freeform" — looper recorded without sequencer; sequencer mode entry blocked
"""

import time
import traceback

import config
from config import (DEFAULT_BPM, STEPS_PER_BAR,
                    MODE_LOOPER, NUM_MODES, MODE_NAMES,
                    BTN_MODE, BTN_RECORD, BTN_PLAY_STOP, BTN_TEMPO_UP, BTN_TEMPO_DN,
                    BTN_SYNTH_EDIT, NUM_KIT_LAYERS)
from event_types import BTN_DOWN, BTN_UP, PAD_DOWN, TICK, BEAT

from hw          import Hardware
from synth_engine import SynthEngine
from display     import DisplayManager
from looper      import LooperMode
from sequencer   import SequencerMode
from synth_edit  import SynthEditMode
import startup

_MODE_LONG_PRESS      = 0.6  # seconds: hold BTN_MODE with no pad to switch global mode
_PLAY_STOP_LONG_PRESS = 2.0  # seconds: hold PLAY/STOP to clear the active mode
_BEAT_PULSE_DURATION  = 0.06 # seconds: how long LED_BEAT stays lit per quarter note
_BPM_DISPLAY_HOLD     = 1.0  # seconds: how long the BPM/LOCK readout stays up after the last change
_TEMPO_REPEAT_DELAY   = 0.4  # seconds: how long TEMPO_UP/DN must be held before auto-repeat kicks in
_TEMPO_REPEAT_INTERVAL = 0.1 # seconds between auto-repeat bumps while held


def step_duration(bpm):
    """16th-note duration in seconds."""
    return 60.0 / (bpm * 4)


def main():
    hw    = Hardware()
    synth = SynthEngine()
    disp  = DisplayManager(hw.i2c)

    startup.run(hw, disp)

    seq        = SequencerMode(synth, disp)
    looper     = LooperMode(synth, disp, seq)
    synth_edit = SynthEditMode(synth, disp, looper, seq, lambda: active)

    modes      = [looper, seq]
    mode_index = MODE_LOOPER
    active     = modes[mode_index]
    active.enter()

    synth_edit_active = False

    # ── Sync coordinator ──────────────────────────────────────────────────────
    sync_mode = "none"

    # Global transport, driven by the PLAY/STOP button -- see its handler
    # below for exactly when it controls the sequencer, the loop, or both
    # together (only sync_mode == "snap" links them; the clock otherwise
    # only ever starts from sequencer focus). seq.playing and
    # looper.transport_playing are the source of truth (no separate mirror
    # var here); both start stopped.
    play_stop_pressed_at = 0.0

    bpm      = DEFAULT_BPM
    step_dur = step_duration(bpm)
    seq.step_dur = step_dur

    # Clock state
    step         = 0
    beat_count   = 0
    last_tick_at = time.monotonic()
    seq_was_playing = False   # edge-detects seq.playing to reset the clock on resume

    # BPM flash
    bpm_display_until = 0.0

    # Beat LED pulse
    beat_led_until = 0.0

    # MODE gesture state
    mode_btn_pressed_at = 0.0
    mode_held           = False   # True while BTN_MODE is physically down
    mode_pad_consumed   = False   # True if a pad was pressed while MODE was held

    # TEMPO hold-to-repeat state
    tempo_held_dir  = 0     # 0 = neither held, +1 = TEMPO_UP held, -1 = TEMPO_DN held
    tempo_repeat_at = 0.0   # next scheduled auto-repeat bump, while tempo_held_dir != 0

    disp.show(MODE_NAMES[mode_index])

    while True:
        now    = time.monotonic()
        events = hw.scan()

        # ── Filter and intercept global buttons ───────────────────────────────
        filtered = []
        for event in events:
            etype, data, event_time = event

            # ── MODE button: full gesture handling ────────────────────────────
            if etype == BTN_DOWN and data == BTN_MODE:
                mode_btn_pressed_at = now
                mode_held           = True
                mode_pad_consumed   = False
                # Not forwarded to active mode

            elif etype == BTN_UP and data == BTN_MODE:
                mode_held = False
                if mode_pad_consumed:
                    # Already acted on pad press; nothing more to do.
                    mode_pad_consumed = False

                elif now - mode_btn_pressed_at >= _MODE_LONG_PRESS:
                    # Long press: switch global mode
                    target_index = (mode_index + 1) % NUM_MODES
                    target_mode  = modes[target_index]

                    if sync_mode == "freeform" and looper.is_playing and target_mode is seq:
                        # Suppress the still-active looper's own refresh_display()
                        # (fired continuously by playback -- wraps, pad flashes)
                        # so it doesn't paint over this flash before the hold
                        # expires; restored below once bpm_display_until fires.
                        active.set_display_owner(False)
                        disp.show("LOCK")
                        bpm_display_until = now + 0.8

                    elif sync_mode == "snap" and looper.is_playing:
                        mode_index = target_index
                        active = modes[mode_index]
                        if synth_edit_active:
                            # Overlay stays open across the switch; it keeps the
                            # display, it just retargets to the new active mode.
                            looper.set_display_owner(False)
                            seq.set_display_owner(False)
                            synth_edit.refresh_display()
                        else:
                            looper.set_display_owner(active is looper)
                            seq.set_display_owner(active is seq)
                            active.refresh_display()
                            disp.show(MODE_NAMES[mode_index])

                    else:
                        active.exit()
                        mode_index = target_index
                        active = modes[mode_index]
                        active.enter()
                        if synth_edit_active:
                            # enter() just claimed the display; hand it back to
                            # the still-open overlay instead of showing mode name.
                            active.set_display_owner(False)
                            synth_edit.refresh_display()
                        else:
                            disp.show(MODE_NAMES[mode_index])

                else:
                    # Short press: cycle active layer / track
                    active.cycle_channel()
                    if synth_edit_active:
                        synth_edit.refresh_display()

            # ── Pad while MODE held: jump to layer / track ────────────────────
            elif etype == PAD_DOWN and mode_held:
                active.select_channel(data)
                mode_pad_consumed = True
                # Suppress: don't trigger synth or record step
                if synth_edit_active:
                    synth_edit.refresh_display()

            # ── PLAY/STOP button: global transport ────────────────────────────
            elif etype == BTN_DOWN and data == BTN_PLAY_STOP:
                play_stop_pressed_at = now
                # Not forwarded to active mode

            elif etype == BTN_UP and data == BTN_PLAY_STOP:
                if now - play_stop_pressed_at >= _PLAY_STOP_LONG_PRESS:
                    active.clear_all()
                elif sync_mode == "snap":
                    # Loop and sequencer are explicitly linked for this
                    # session -- PLAY/STOP always controls both together,
                    # regardless of which one currently has focus.
                    playing = not seq.playing
                    seq.set_playing(playing)
                    looper.set_playing(playing, now)
                elif active is seq:
                    # Not linked: the shared tempo clock (and the BEAT LED
                    # it drives) only ever starts from sequencer focus.
                    seq.set_playing(not seq.playing)
                else:
                    # Not linked, LOOP has focus (freeform, or nothing
                    # recorded yet): PLAY/STOP only concerns the loop, so
                    # it can never wake the clock and accidentally lock an
                    # empty or freeform loop into a synced session the
                    # next time a layer is armed.
                    looper.set_playing(not looper.transport_playing, now)

            # ── SYNTH EDIT button: toggle the sound-editing overlay ──────────
            elif etype == BTN_DOWN and data == BTN_SYNTH_EDIT:
                if synth_edit_active:
                    synth_edit.exit()
                    if active is looper:
                        looper.set_display_owner(True)
                    else:
                        seq.set_display_owner(True)
                    synth_edit_active = False
                    active.refresh_display()
                elif not (active is looper and looper.active_idx < NUM_KIT_LAYERS):
                    if active is looper:
                        looper.set_display_owner(False)
                    else:
                        seq.set_display_owner(False)
                    synth_edit.enter()
                    synth_edit_active = True
                else:
                    active.set_display_owner(False)
                    disp.show("N/A ")
                    bpm_display_until = now + 0.4

            # ── Tempo buttons: BPM, unless SYNTH EDIT owns them right now ─────
            elif etype == BTN_DOWN and data == BTN_TEMPO_UP:
                if synth_edit_active:
                    filtered.append(event)
                elif sync_mode == "snap" or (sync_mode == "freeform" and looper.is_playing):
                    # Same rule as blocking a switch to SEQ mid-freeform-loop
                    # (see BTN_MODE above): BPM drives only the sequencer's
                    # clock, which a playing freeform loop was never anchored
                    # to, so changing it here would do nothing audible --
                    # block it and flash LOCK instead of a no-op BPM readout.
                    active.set_display_owner(False)
                    disp.show("LOCK")
                    bpm_display_until = now + _BPM_DISPLAY_HOLD
                else:
                    active.set_display_owner(False)
                    bpm = min(bpm + 1, 300)
                    step_dur = step_duration(bpm)
                    seq.step_dur = step_dur
                    disp.show_bpm(bpm)
                    bpm_display_until = now + _BPM_DISPLAY_HOLD
                    tempo_held_dir  = 1
                    tempo_repeat_at = now + _TEMPO_REPEAT_DELAY

            elif etype == BTN_DOWN and data == BTN_TEMPO_DN:
                if synth_edit_active:
                    filtered.append(event)
                elif sync_mode == "snap" or (sync_mode == "freeform" and looper.is_playing):
                    active.set_display_owner(False)
                    disp.show("LOCK")
                    bpm_display_until = now + _BPM_DISPLAY_HOLD
                else:
                    active.set_display_owner(False)
                    bpm = max(bpm - 1, 40)
                    step_dur = step_duration(bpm)
                    seq.step_dur = step_dur
                    disp.show_bpm(bpm)
                    bpm_display_until = now + _BPM_DISPLAY_HOLD
                    tempo_held_dir  = -1
                    tempo_repeat_at = now + _TEMPO_REPEAT_DELAY

            # ── Tempo buttons: release -- consumed here so the active mode
            #    never sees it (its own unconditional refresh_display() on
            #    any event would stomp the BPM/LOCK readout we just showed).
            #    Still forwarded while SYNTH EDIT owns the buttons, to keep
            #    it paired with the BTN_DOWN it already receives.
            elif etype == BTN_UP and data in (BTN_TEMPO_UP, BTN_TEMPO_DN):
                if synth_edit_active:
                    filtered.append(event)
                tempo_held_dir = 0

            else:
                filtered.append(event)

        # ── SYNTH EDIT: auto-exit only if we've landed on the looper's kit layer ──
        if synth_edit_active and active is looper and looper.active_idx < NUM_KIT_LAYERS:
            synth_edit.exit()
            looper.set_display_owner(True)
            synth_edit_active = False
            active.refresh_display()

        # ── Sync coordinator: detect looper arm while sequencer is playing ────
        if not synth_edit_active:
            for event in filtered:
                etype, data, event_time = event
                if etype == BTN_DOWN and data == BTN_RECORD:
                    if active is looper and looper.is_idle:
                        if seq.playing:
                            sync_mode = "snap"
                            looper.set_snap_mode(True)
                        else:
                            sync_mode = "freeform"
                            looper.set_snap_mode(False)

        # ── Dispatch remaining events to active mode (or the SYNTH EDIT overlay) ─
        # Each event is dispatched with its own true press/release time
        # (event_time), not this frame's `now` -- see hw.scan().
        for event in filtered:
            etype, data, event_time = event
            mode_event = (etype, data)
            if synth_edit_active:
                synth_edit.handle_event(mode_event, event_time)
            else:
                active.handle_event(mode_event, event_time)

        # ── TEMPO hold-to-repeat ────────────────────────────────────────────────
        if tempo_held_dir and now >= tempo_repeat_at:
            tempo_repeat_at = now + _TEMPO_REPEAT_INTERVAL
            if tempo_held_dir > 0:
                bpm = min(bpm + 1, 300)
            else:
                bpm = max(bpm - 1, 40)
            step_dur = step_duration(bpm)
            seq.step_dur = step_dur
            active.set_display_owner(False)
            disp.show_bpm(bpm)
            bpm_display_until = now + _BPM_DISPLAY_HOLD

        # ── Restore display after BPM / LOCK flash ────────────────────────────
        if bpm_display_until and now >= bpm_display_until:
            bpm_display_until = 0.0
            if synth_edit_active:
                synth_edit.refresh_display()
            else:
                # Also un-suppresses the ownership the flash claimed above
                # (set_display_owner(True) refreshes on its own), letting
                # the mode's own continuous updates paint again.
                active.set_display_owner(True)

        # ── Sync coordinator: frame checks ────────────────────────────────────
        if looper.was_cleared:
            sync_mode = "none"

        # ── Drive tempo clock ─────────────────────────────────────────────────
        # Gated on the sequencer's own playing state, not the looper's --
        # a freeform loop has nothing to do with the shared tempo clock
        # (BEAT LED included), and looper.clock_needed can only ever be
        # true when seq.playing is too (beat-quantized countdowns only
        # happen in a synced session, where the two are kept in lockstep).
        # A resume always restarts the clock at step 0, mirroring
        # looper.set_playing's own resume-at-position-0 for every committed
        # layer -- so a synced session's loop and sequencer always come
        # back perfectly aligned, instead of the sequencer continuing from
        # wherever mid-step it happened to be paused while the loop resumes
        # phase-perfect, which is what used to knock the two out of sync.
        # last_tick_at is backdated by a full step_dur (rather than set to
        # `now`) so the TICK(0) check just below fires immediately, this
        # same frame -- matching looper.set_playing's own immediate fire of
        # any event recorded at loop position 0.0 (elapsed=0 the instant
        # play_start is reset). Setting last_tick_at = now would leave
        # TICK(0) firing a full step late, so the loop's beat-1 hits would
        # land a step ahead of the sequencer's every time you pause/resume.
        if seq.playing and not seq_was_playing:
            step         = 0
            last_tick_at = now - step_dur
        seq_was_playing = seq.playing

        if seq.playing:
            if now - last_tick_at >= step_dur:
                last_tick_at += step_dur

                tick_evt = (TICK, step)
                seq.handle_event(tick_evt, now)
                if looper.clock_needed:
                    looper.handle_event(tick_evt, now)

                if step % 4 == 0:
                    beat_evt = (BEAT, beat_count)
                    seq.handle_event(beat_evt, now)
                    beat_count += 1
                    beat_led_until = now + _BEAT_PULSE_DURATION

                step = (step + 1) % STEPS_PER_BAR

        # ── Per-mode continuous update ──────────────────────────────────────
        if looper.transport_playing:
            looper.update(now)
        seq.update(now)
        if synth_edit_active:
            synth_edit.update(now)

        # ── Synth auto-release housekeeping ──────────────────────────────────
        synth.update()

        # ── Beat LED pulse (independent of mode display; drawn last so a mode's
        #    own LED refresh above never stomps it) ────────────────────────────
        disp.set_led(config.LED_BEAT, now < beat_led_until)


try:
    # Uncomment to run the hardware I/O test loop instead of the real app:
    # import io_test; io_test.run()
  
    main()
except Exception as e:
    traceback.print_exception(type(e), e, e.__traceback__)
    while (1):
        time.sleep(2)
    # import microcontroller; microcontroller.reset()
