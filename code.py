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
  (All three keep working while the MENU overlay is open; it retargets.)

UP/DOWN with the menu closed: step the active channel's volume (the active
loop layer in LOOP, the selected track in SEQ), held = auto-repeat; the
level flashes on the display ("V 80").

MENU overlay (menu.py): BTN_MENU opens it; while open, MENU is "select",
PLAY/STOP is "back" (closing it from root) instead of the transport, and
UP/DOWN move through it. The pads keep playing the active mode (which
keeps the LEDs -- the menu holds only the text); RECORD and MUTE do
nothing. Its BPM item calls back into set_bpm / tempo_locked, and SAVE /
LOAD into capture_groove / apply_groove below, since BPM and sync mode
live here.

Sync modes (sync_mode variable):
  "none"     — no loop recorded yet; modes are fully independent
  "snap"     — sequencer was playing when looper started recording; both play
               simultaneously and PLAY/STOP controls both; BPM changes blocked
               to prevent drift while any loop content exists. Clearing every
               layer keeps "snap" if the sequencer is still running (the link
               stays, BPM unlocks until the next synced take is armed)
  "freeform" — looper recorded without sequencer; sequencer mode entry blocked
"""

import time
import traceback

import clock
import config
from config import (DEFAULT_BPM, STEPS_PER_BAR,
                    MODE_LOOPER, NUM_MODES, MODE_NAMES,
                    BTN_MODE, BTN_RECORD, BTN_PLAY_STOP, BTN_INC, BTN_DEC,
                    BTN_MENU)
from event_types import BTN_DOWN, BTN_UP, PAD_DOWN, PAD_UP, TICK, BEAT

from hw          import Hardware
from synth_engine import SynthEngine
from display     import DisplayManager
from looper      import LooperMode
from sequencer   import SequencerMode
from menu        import MenuMode
import startup

_MODE_LONG_PRESS      = 0.6  # seconds: hold BTN_MODE with no pad to switch global mode
_PLAY_STOP_LONG_PRESS = 2.0  # seconds: hold PLAY/STOP to clear the active mode
_BEAT_PULSE_DURATION  = 0.06 # seconds: how long LED_BEAT stays lit per quarter note
_FLASH_HOLD           = 1.0  # seconds: how long the volume readout stays up after the last change
_LOCK_FLASH_HOLD      = 0.8  # seconds: how long a blocked mode switch shows LOCK
_VOLUME_REPEAT_DELAY  = 0.4  # seconds: how long UP/DOWN must be held before auto-repeat kicks in
_VOLUME_REPEAT_INTERVAL = 0.1 # seconds between auto-repeat steps while held
_VOLUME_STEP          = 5    # % per UP/DOWN step


def step_duration(bpm):
    """16th-note duration in seconds."""
    return 60.0 / (bpm * 4)


def main():
    hw    = Hardware()
    synth = SynthEngine()
    disp  = DisplayManager(hw.i2c)

    startup.run(hw, disp)
    if config.TIMING_PROBE:
        import timing_probe
        hw = timing_probe.TimingProbe(hw, disp)

    seq        = SequencerMode(synth, disp)
    looper     = LooperMode(synth, disp, seq)

    modes      = [looper, seq]
    mode_index = MODE_LOOPER
    active     = modes[mode_index]
    active.enter()

    menu_active = False

    # ── Sync coordinator ──────────────────────────────────────────────────────
    sync_mode = "none"

    # Global transport, driven by the PLAY/STOP button -- see its handler
    # below for exactly when it controls the sequencer, the loop, or both
    # together (only sync_mode == "snap" links them; the clock otherwise
    # only ever starts from sequencer focus). seq.playing and
    # looper.transport_playing are the source of truth (no separate mirror
    # var here); both start stopped.
    play_stop_pressed_at = 0.0
    # Set when a PLAY/STOP press was handled by the menu as "back": its
    # release must be swallowed too, or a back that closes the menu (on
    # press) would have its release read as a transport short press.
    play_stop_swallow_up = False

    bpm      = DEFAULT_BPM
    step_dur = step_duration(bpm)
    seq.step_dur = step_dur

    # Clock state. Tick n of the current run is due at
    # tick_anchor + n * step_dur -- computed by multiplication, never by
    # adding step_dur onto the previous tick: CircuitPython's ~22-bit floats
    # round every addition, and at most tempos that rounding is the same
    # every step, so an accumulated clock slowly drifts off the loop (whose
    # own positions are play_start + n * loop_duration). Re-anchored on
    # resume and on every BPM change.
    step         = 0
    beat_count   = 0
    tick_anchor  = 0.0
    tick_count   = 0       # ticks fired since tick_anchor
    seq_was_playing = False   # edge-detects seq.playing to reset the clock on resume

    def set_bpm(new_bpm):
        """Change tempo without a jump: the next tick lands one *new* step
        after the last one that fired."""
        nonlocal bpm, step_dur, tick_anchor, tick_count
        if tick_count > 0:
            tick_anchor += (tick_count - 1) * step_dur   # the last tick fired
            tick_count   = 1
        bpm      = max(40, min(300, new_bpm))
        step_dur = step_duration(bpm)
        seq.step_dur = step_dur

    # Text flash (volume readout, LOCK) over the active mode's display: it
    # holds the text (disp.hold_text) until flash_until, while the mode
    # keeps the LEDs.
    flash_until = 0.0

    def flash(text, now, hold=_FLASH_HOLD):
        nonlocal flash_until
        disp.hold_text(True)
        disp.show(text)
        flash_until = now + hold

    # Beat LED pulse
    beat_led_until = 0.0

    # MODE gesture state
    mode_btn_pressed_at = 0.0
    mode_held           = False   # True while BTN_MODE is physically down
    mode_pad_consumed   = False   # True if a pad was pressed while MODE was held

    # UP/DOWN volume hold-to-repeat state
    vol_held_dir  = 0     # 0 = neither held, +1 = UP held, -1 = DOWN held
    vol_repeat_at = 0.0   # next scheduled auto-repeat step, while vol_held_dir != 0

    def step_volume(direction, now):
        """Step the active channel's volume (the active loop layer, or the
        selected sequencer track) and flash the new level."""
        if active is looper:
            layer = looper.active_idx
            synth.set_channel_volume(layer, synth.channel_volume(layer) + direction * _VOLUME_STEP)
            volume = synth.channel_volume(layer)
        else:
            track = seq.selected_track
            synth.set_track_volume(track, synth.track_volume(track) + direction * _VOLUME_STEP)
            volume = synth.track_volume(track)
        flash(f"V{volume:3d}", now)

    # ── Grooves: the menu's SAVE / LOAD (file I/O lives in groove.py) ─────────
    def capture_groove():
        return {
            "bpm":    bpm,
            "sync":   sync_mode,
            "seq":    seq.snapshot(),
            "loop":   looper.snapshot(),
            "sounds": synth.snapshot_sounds(),
        }

    def apply_groove(data, now):
        """Replace the whole session with a loaded groove. The transport is
        stopped first, so PLAY afterwards starts everything from the top --
        a synced groove's loop and sequencer come back lockstepped the same
        way they do on any resume."""
        nonlocal sync_mode
        seq.set_playing(False)
        looper.set_playing(False, now)
        synth.restore_sounds(data.get("sounds", {}))
        seq.restore(data.get("seq", {}))
        # After restore_sounds: converting a v1 groove's notes needs to
        # know which layers are melodic.
        looper.restore(data.get("loop", {}), v1_notes=data.get("v") == 1)
        set_bpm(int(data.get("bpm", DEFAULT_BPM)))
        # A synced loop was recorded against this exact BPM; restoring
        # "snap" re-locks the BPM so the two can't drift apart.
        sync_mode = data.get("sync", "none")
        if looper.is_idle or sync_mode not in ("snap", "freeform"):
            sync_mode = "none"
        looper.set_snap_mode(sync_mode == "snap")

    def tempo_locked():
        """BPM changes (the menu's BPM item) are blocked whenever a loop
        depends on the current tempo: a synced session with loop content
        (or a take armed/in progress -- is_idle covers both), or a playing
        freeform loop (BPM only drives the sequencer's clock, which a
        freeform loop was never anchored to, so a change would do nothing
        audible)."""
        return ((sync_mode == "snap" and not looper.is_idle) or
                (sync_mode == "freeform" and looper.is_playing))

    menu = MenuMode(synth, disp, looper, seq, lambda: active,
                    capture_groove=capture_groove, apply_groove=apply_groove,
                    get_bpm=lambda: bpm, set_bpm=set_bpm,
                    tempo_locked=tempo_locked)

    def close_menu():
        nonlocal menu_active, flash_until
        menu.exit()
        menu_active = False
        flash_until = 0.0
        disp.hold_text(False)
        active.refresh_display()

    disp.show(MODE_NAMES[mode_index])

    while True:
        now    = clock.now()
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
                        # Holds the text so the still-active looper's own
                        # refresh_display() (fired continuously by playback --
                        # wraps, pad flashes) can't paint over this before the
                        # hold expires; released below once flash_until fires.
                        flash("LOCK", now, _LOCK_FLASH_HOLD)

                    elif sync_mode == "snap" and looper.is_playing:
                        mode_index = target_index
                        active = modes[mode_index]
                        # The new active mode takes over the LEDs (and the
                        # text, unless the menu or a flash holds it).
                        looper.set_display_owner(active is looper)
                        seq.set_display_owner(active is seq)
                        if menu_active:
                            # Overlay stays open across the switch; it keeps the
                            # text, it just retargets to the new active mode.
                            menu.refresh_display()
                        else:
                            disp.show(MODE_NAMES[mode_index])

                    else:
                        active.exit()
                        mode_index = target_index
                        active = modes[mode_index]
                        active.enter()
                        if menu_active:
                            menu.refresh_display()
                        else:
                            disp.show(MODE_NAMES[mode_index])

                else:
                    # Short press: cycle active layer / track
                    active.cycle_channel()
                    if menu_active:
                        menu.refresh_display()

            # ── Pad while MODE held: jump to layer / track ────────────────────
            elif etype == PAD_DOWN and mode_held:
                active.select_channel(data)
                mode_pad_consumed = True
                # Suppress: don't trigger synth or record step
                if menu_active:
                    menu.refresh_display()

            # ── PLAY/STOP button: global transport, or "back" in the menu ─────
            elif etype == BTN_DOWN and data == BTN_PLAY_STOP:
                if menu_active:
                    # Acts on press -- the menu has no long press, and the
                    # transport's 2 s clear must never fire from in here.
                    play_stop_swallow_up = True
                    if menu.back(event_time):
                        close_menu()
                else:
                    play_stop_pressed_at = now
                # Not forwarded to active mode

            elif etype == BTN_UP and data == BTN_PLAY_STOP:
                if play_stop_swallow_up or menu_active:
                    # Release of a menu "back" (or of a press begun before
                    # the menu opened): never a transport action.
                    play_stop_swallow_up = False
                elif now - play_stop_pressed_at >= _PLAY_STOP_LONG_PRESS:
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

            # ── MENU button: open the overlay; "select" once it's open ───────
            elif etype == BTN_DOWN and data == BTN_MENU:
                if menu_active:
                    filtered.append(event)
                else:
                    # The menu takes the text over from any volume flash,
                    # and an UP/DOWN still held for volume auto-repeat
                    # would otherwise keep stepping it under the menu.
                    vol_held_dir = 0
                    flash_until  = 0.0
                    disp.hold_text(True)
                    menu.enter()
                    menu_active = True

            # ── UP/DOWN: channel volume, unless the menu owns them right now ──
            elif etype == BTN_DOWN and data in (BTN_INC, BTN_DEC):
                if menu_active:
                    filtered.append(event)
                else:
                    vol_held_dir  = 1 if data == BTN_INC else -1
                    vol_repeat_at = now + _VOLUME_REPEAT_DELAY
                    step_volume(vol_held_dir, now)

            # ── UP/DOWN release -- consumed here so the active mode never
            #    sees it. Still forwarded while the menu owns the buttons,
            #    to keep it paired with the BTN_DOWN it already receives.
            elif etype == BTN_UP and data in (BTN_INC, BTN_DEC):
                if menu_active:
                    filtered.append(event)
                vol_held_dir = 0

            else:
                filtered.append(event)

        # ── Sync coordinator: detect looper arm while sequencer is playing ────
        if not menu_active:
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

        # ── Dispatch remaining events to active mode (or the menu overlay) ───
        # Each event is dispatched with its own true press/release time
        # (event_time), not this frame's `now` -- see hw.scan().
        # Pads always go to the active mode, menu open or not; the menu gets
        # every other event and ignores RECORD / MUTE.
        for event in filtered:
            etype, data, event_time = event
            mode_event = (etype, data)
            if menu_active and etype not in (PAD_DOWN, PAD_UP):
                menu.handle_event(mode_event, event_time)
            else:
                active.handle_event(mode_event, event_time)

        # ── UP/DOWN volume hold-to-repeat ─────────────────────────────────────
        if vol_held_dir and now >= vol_repeat_at:
            vol_repeat_at = now + _VOLUME_REPEAT_INTERVAL
            step_volume(vol_held_dir, now)

        # ── Restore display after a volume / LOCK flash ───────────────────────
        if flash_until and now >= flash_until:
            flash_until = 0.0
            if menu_active:
                menu.refresh_display()
            else:
                # Hand the text back, letting the mode's own continuous
                # updates paint it again.
                disp.hold_text(False)
                active.refresh_display()

        # ── Sync coordinator: frame checks ────────────────────────────────────
        if looper.was_cleared:
            # Every layer cleared (or a first-layer arm cancelled): with the
            # sequencer still running, stay linked so PLAY/STOP keeps
            # controlling it from LOOP focus too, and the next take syncs to
            # it anyway. Otherwise nothing is left to link.
            sync_mode = "snap" if seq.playing else "none"
            looper.set_snap_mode(sync_mode == "snap")

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
        # The anchor is `now` itself, so TICK(0) fires immediately, this
        # same frame -- matching looper.set_playing's own immediate fire of
        # any event recorded at loop position 0.0 (elapsed=0 the instant
        # play_start is reset to the same `now`).
        if seq.playing and not seq_was_playing:
            step        = 0
            tick_anchor = now
            tick_count  = 0
        seq_was_playing = seq.playing

        if seq.playing:
            tick_at = tick_anchor + tick_count * step_dur
            if now >= tick_at:
                tick_count += 1

                # Dispatched with the time the tick was *due*, not this
                # frame's `now` (which is late by however long the frame
                # took): a synced take's loop_start is anchored to the
                # TICK(0) that starts it, so it lands exactly on the
                # sequencer's grid instead of a frame behind it.
                tick_evt = (TICK, step)
                seq.handle_event(tick_evt, tick_at)
                if looper.clock_needed:
                    looper.handle_event(tick_evt, tick_at)

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
        if menu_active:
            menu.update(now)

        # ── Synth auto-release housekeeping ──────────────────────────────────
        synth.update()

        # ── Beat LED pulse (independent of mode display; drawn last so a mode's
        #    own LED refresh above never stomps it) ────────────────────────────
        disp.set_led(config.LED_BEAT, now < beat_led_until)
        disp.update(now)   # NeoKey: send changed pixels (rate-limited)


try:
    # Uncomment to run the hardware I/O test loop instead of the real app:
    # import io_test; io_test.run()
  
    main()
except Exception as e:
    traceback.print_exception(type(e), e, e.__traceback__)
    while (1):
        time.sleep(2)
    # import microcontroller; microcontroller.reset()
