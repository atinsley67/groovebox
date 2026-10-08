"""
Groovebox — main entry point.

Main loop responsibilities:
  1. Scan hardware for button events.
  2. Drive the drift-free tempo clock (TICK / BEAT events) when playing.
  3. Dispatch events to the active (focused) mode, the menu, or the
     channel view.
  4. Run sync coordinator: looper + sequencer dual-play and snap-to-bar logic.
  5. Call synth_engine.update() each iteration for pending note-off releases.

Function keys (BUTTONS.md has the player's version). Every key does one
thing, on press -- no long presses; only UP/DOWN repeat while held:
  LOOP/SEQ   — switch the global mode, showing its own view
  PLAY/STOP  — the transport, menu open or not
  MENU       — open the menu; "select" in it; confirm an armed CLEAR
  RECORD     — the active mode's; "back" in the menu (closing it from root)
  UP/DOWN    — the active channel's volume ("V 80"); move / step in the menu
  VIEW       — the pads: the mode's own view <-> the channel view
  KEY MODE   — what a pad press does: in the channel view, select <->
               mute; in LOOP's own view, play <-> arpeggiate (the active
               layer's arp)
  MUTE       — the active mode's (mute the selected channel)
  CLEAR      — arm clearing the selected channel; CLEAR again: every
               channel in the mode. MENU confirms; any other function key
               cancels and does nothing else; so does _CLEAR_TIMEOUT.
               Pads keep playing (a channel-view tap cancels it, though).

Lights: draw_lights() redraws the pads (the active view, from pad_views.py)
and every function key's color, up to 60 times a second and straight after
any key event. The views are LOOP's keyboard, SEQ's steps, and the channel
view: loop layers on pads 0-7, sequencer tracks on 8-15. In the channel
view, KEY MODE select (always the mode on entering): a tap selects that
channel -- switching LOOP/SEQ if it's on the other side -- and goes
straight back to that mode's own view. KEY MODE mute: a tap mutes /
unmutes that channel and stays. Its pads never reach the modes.

The arp (arp.py): with the active layer's arp on, LOOP's pad presses go
to it instead of the looper, and what it plays goes on to the looper as
exact presses (looper.handle_event's exact=True), after looper.update each
frame -- so a note due on a take's first beat lands once recording has
started. A release goes wherever its press went (arp_pads). It follows the
tempo clock's ticks, and stop_arp() silences it before anything changes
what the looper's pads mean: a layer or mode change, KEY MODE, CLEAR, a
groove load.

AUTO (arranger.py; the menu's AUT item switches it): mutes and unmutes
channels on phrase boundaries to vary the groove. This loop feeds it the
phrase clock -- each bar of the tempo clock (before that bar's first step
fires), or a freeform loop's passes -- and flashes the word it returns
with each change.

MENU overlay (menu.py): while open, MENU and UP/DOWN go to it and RECORD is
its "back". The pads keep going to the active mode (or the channel view),
which keeps the LEDs -- the menu holds only the text. LOOP/SEQ, PLAY/STOP,
VIEW and KEY MODE work as usual; MUTE and CLEAR do nothing. Its BPM item
calls back into set_bpm / tempo_locked, and SAVE / LOAD into
capture_groove / apply_groove below, since BPM and sync mode live here.

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

import config
# The heap census (config.TIMING_PROBE): what each stage of boot leaves live
# for every garbage collection to walk -- code, sound tables, voices, and
# (in apply_groove) a loaded groove. See timing_probe.census.
if config.TIMING_PROBE:
    from timing_probe import census
    census("boot")
    import sound_presets   # noqa: F401 -- on its own, to measure its tables
    census("sound tables")

import clock
import palette
from config import (DEFAULT_BPM, STEPS_PER_BAR, NUM_LOOP_LAYERS, NUM_TRACKS,
                    MODE_LOOPER, MODE_SEQUENCER, NUM_MODES, MODE_NAMES,
                    BTN_MODE, BTN_RECORD, BTN_PLAY_STOP, BTN_INC, BTN_DEC,
                    BTN_MENU, BTN_MUTE, BTN_VIEW, BTN_KEY_MODE, BTN_CLEAR)
from event_types import BTN_DOWN, BTN_UP, PAD_DOWN, PAD_UP, TICK, BEAT

from hw           import Hardware
from synth_engine import SynthEngine
from display      import DisplayManager
from looper       import LooperMode
from sequencer    import SequencerMode
from menu         import MenuMode
from pad_views    import KeyboardView, StepView, ChannelView
from arranger     import Arranger
from arp          import Arpeggiator
import startup

if config.TIMING_PROBE:
    census("imports")

_BEAT_PULSE_DURATION  = 0.06 # seconds: how long PLAY/STOP flashes bright per quarter note
_FLASH_HOLD           = 1.0  # seconds: how long the volume readout stays up after the last change
_LOCK_FLASH_HOLD      = 0.8  # seconds: how long LOCK / BUSY / DONE show
_VOLUME_REPEAT_DELAY  = 0.4  # seconds: how long UP/DOWN must be held before auto-repeat kicks in
_VOLUME_REPEAT_INTERVAL = 0.1 # seconds between auto-repeat steps while held
_VOLUME_STEP          = 5    # % per UP/DOWN step
_CLEAR_TIMEOUT        = 3.0  # seconds an armed CLEAR waits for MENU
_CLEAR_BLINK_HZ       = 4.0  # the armed CLEAR key's blink
_ARMED_BLINK_HZ       = 2.5  # RECORD's blink while armed / counting in
_FRAME_INTERVAL       = 1 / 60  # seconds between light redraws (the pixels' own send rate)

# Function keys lit white while held.
_PRESS_LIT = (BTN_MENU, BTN_INC, BTN_DEC, BTN_VIEW)


def step_duration(bpm):
    """16th-note duration in seconds."""
    return 60.0 / (bpm * 4)


def main():
    hw    = Hardware()
    if config.TIMING_PROBE:
        census("hardware")
    synth = SynthEngine()
    if config.TIMING_PROBE:
        census("voices")
    disp  = DisplayManager(hw.i2c)

    startup.run(hw, disp)
    if config.TIMING_PROBE:
        import timing_probe
        hw = timing_probe.TimingProbe(hw, disp)

    seq        = SequencerMode(synth, disp)
    looper     = LooperMode(synth, disp, seq)
    arp        = Arpeggiator(NUM_LOOP_LAYERS, step_duration(DEFAULT_BPM))
    keyboard   = KeyboardView(looper, arp)
    steps      = StepView(seq)
    channels   = ChannelView(looper, seq)
    arranger   = Arranger(looper, seq)

    modes      = [looper, seq]
    mode_index = MODE_LOOPER
    active     = modes[mode_index]
    active.enter()

    menu_active = False

    # ── Sync coordinator ──────────────────────────────────────────────────────
    sync_mode = "none"

    # Global transport, driven by the PLAY/STOP button -- see toggle_transport
    # for exactly when it controls the sequencer, the loop, or both together
    # (only sync_mode == "snap" links them; the clock otherwise only ever
    # starts from sequencer focus). seq.playing and looper.transport_playing
    # are the source of truth (no separate mirror var here); both start
    # stopped.

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

    # AUTO's phrase clock: bars of the tempo clock since it last started
    # (-1 before the first), or a freeform loop's passes (looper.pass_index).
    bar_index = -1
    last_pass = -1

    def arrange(word, now):
        """Flash AUTO's word for a change, if any -- not over an armed
        CLEAR's label."""
        if word and not clear_scope:
            flash(word, now, _LOCK_FLASH_HOLD)

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
        arp.set_step_dur(step_dur)

    # ── The arp ───────────────────────────────────────────────────────────────
    # Pads pressed into the arp: their releases are its too, even if it's
    # been switched off since.
    arp_pads = set()

    def arp_takes_pads():
        return (not channel_view_on and active is looper and
                arp.is_on(looper.active_idx))

    def play_arp(events):
        for etype, pad, t in events:
            looper.handle_event((etype, pad), t, exact=True)

    def stop_arp(now):
        """Silence the arp, while the looper's pads still mean what they
        did when it played them."""
        play_arp(arp.stop(now))

    # Text flash (volume readout, LOCK, an armed CLEAR) over the active
    # mode's display: it holds the text (disp.hold_text) until flash_until,
    # while the mode keeps the LEDs.
    flash_until = 0.0

    def flash(text, now, hold=_FLASH_HOLD):
        nonlocal flash_until
        disp.hold_text(True)
        disp.show(text)
        flash_until = now + hold

    def end_flash():
        """Hand the text back to the menu or the active mode."""
        nonlocal flash_until
        flash_until = 0.0
        if menu_active:
            menu.refresh_display()
        else:
            disp.hold_text(False)
            active.refresh_display()

    # Beat LED pulse
    beat_led_until = 0.0

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

    # ── LOOP / SEQ ────────────────────────────────────────────────────────────
    def switch_mode(target_index, now):
        """Make modes[target_index] the active mode. Returns False (and
        flashes LOCK) when that's blocked: a playing freeform loop keeps SEQ
        locked out."""
        nonlocal mode_index, active
        if target_index == mode_index:
            return True
        target_mode = modes[target_index]
        if sync_mode == "freeform" and looper.is_playing and target_mode is seq:
            # Holds the text so the still-active looper's own
            # refresh_display() (fired continuously by playback -- wraps,
            # pad flashes) can't paint over this before the hold expires.
            flash("LOCK", now, _LOCK_FLASH_HOLD)
            return False
        stop_arp(now)
        if sync_mode == "snap" and looper.is_playing:
            mode_index = target_index
            active = modes[mode_index]
            # The new active mode takes over the LEDs (and the text, unless
            # the menu or a flash holds it).
            looper.set_display_owner(active is looper)
            seq.set_display_owner(active is seq)
        else:
            active.exit()
            mode_index = target_index
            active = modes[mode_index]
            active.enter()
        if menu_active:
            # The menu stays open across the switch; it keeps the text and
            # just retargets to the new active mode.
            menu.refresh_display()
        else:
            disp.show(MODE_NAMES[mode_index])
        return True

    # ── PLAY / STOP ───────────────────────────────────────────────────────────
    def toggle_transport(now):
        if sync_mode == "snap":
            # Loop and sequencer are explicitly linked for this session --
            # PLAY/STOP always controls both together, regardless of which
            # one currently has focus.
            playing = not seq.playing
            seq.set_playing(playing)
            looper.set_playing(playing, now)
        elif active is seq:
            # Not linked: the shared tempo clock (and the BEAT LED it
            # drives) only ever starts from sequencer focus.
            seq.set_playing(not seq.playing)
        else:
            # Not linked, LOOP has focus (freeform, or nothing recorded
            # yet): PLAY/STOP only concerns the loop, so it can never wake
            # the clock and accidentally lock an empty or freeform loop into
            # a synced session the next time a layer is armed.
            looper.set_playing(not looper.transport_playing, now)

    # ── CLEAR ─────────────────────────────────────────────────────────────────
    clear_scope    = None   # None (not armed), "channel" or "all"
    clear_armed_at = 0.0
    clear_until    = 0.0    # the armed clear times out here

    def selected_channel():
        return looper.active_idx if active is looper else seq.selected_track

    def arm_clear(scope, now):
        nonlocal clear_scope, clear_armed_at, clear_until
        if clear_scope is None:
            clear_armed_at = now
        clear_scope = scope
        clear_until = now + _CLEAR_TIMEOUT
        flash("CLRA" if scope == "all" else f"CLR{selected_channel() + 1}",
              now, _CLEAR_TIMEOUT)

    def end_clear():
        nonlocal clear_scope
        clear_scope = None
        end_flash()

    def confirm_clear(now):
        nonlocal clear_scope
        if active is looper:
            stop_arp(now)
        if clear_scope == "all":
            active.clear_all()
        elif active is looper:
            looper.clear_layer(looper.active_idx)
        else:
            seq.clear_track(seq.selected_track)
        clear_scope = None
        flash("DONE", now, _LOCK_FLASH_HOLD)

    # ── The channel view ──────────────────────────────────────────────────────
    channel_view_on = False
    key_mode_mute   = False   # KEY MODE: False = select, True = mute
    # Pads pressed into the channel view: their releases are its too, even
    # if the view has closed since (a select closes it on the press).
    view_pads = set()

    def set_channel_view(on):
        nonlocal channel_view_on, key_mode_mute
        if on == channel_view_on:
            return
        channel_view_on = on
        key_mode_mute   = False   # every visit starts in select

    def channel_tap(pad, now):
        """A pad tapped in the channel view."""
        if pad >= NUM_LOOP_LAYERS + NUM_TRACKS:
            return
        if pad < NUM_LOOP_LAYERS:
            target, n = MODE_LOOPER, pad
        else:
            target, n = MODE_SEQUENCER, pad - NUM_LOOP_LAYERS
        mode = modes[target]
        if key_mode_mute:
            mode.toggle_mute(n)
            return
        if mode is looper and not looper.can_select(n):
            flash("BUSY", now, _LOCK_FLASH_HOLD)   # another layer is recording
            return
        if not switch_mode(target, now):
            return
        if mode is looper and n != looper.active_idx:
            stop_arp(now)
        mode.select_channel(n)
        set_channel_view(False)
        if menu_active:
            menu.refresh_display()

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
        stop_arp(now)
        seq.set_playing(False)
        looper.set_playing(False, now)
        # Before v3 a drum's DEC did nothing and six kit sounds were
        # different sounds -- see sound_presets.upgrade_v2_kit_params.
        synth.restore_sounds(data.get("sounds", {}),
                             legacy_kit=data.get("v", 1) < 3)
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
        if config.TIMING_PROBE:
            census("groove loaded")

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
                    tempo_locked=tempo_locked, arranger=arranger, arp=arp)

    def open_menu():
        nonlocal menu_active, flash_until, vol_held_dir
        # The menu takes the text over from any volume flash, and an
        # UP/DOWN still held for volume auto-repeat would otherwise keep
        # stepping it under the menu.
        vol_held_dir = 0
        flash_until  = 0.0
        disp.hold_text(True)
        menu.enter()
        menu_active = True

    def close_menu():
        nonlocal menu_active, flash_until
        menu.exit()
        menu_active = False
        flash_until = 0.0
        disp.hold_text(False)
        active.refresh_display()

    # ── Lights ────────────────────────────────────────────────────────────────
    held_keys = set()   # function keys held down right now
    lights_at = 0.0     # next draw_lights()

    def draw_lights(now):
        """The pads (the active view) and every function key's light."""
        if channel_view_on:
            disp.set_pad_frame(channels.frame(now))
        elif active is looper:
            disp.set_pad_frame(keyboard.frame(now))
        else:
            disp.set_pad_frame(steps.frame(now))

        # PLAY/STOP: flashing on the beat while the tempo clock runs; steady
        # for a freeform loop playing (no clock); off when stopped.
        if seq.playing:
            play = palette.BEAT if now < beat_led_until else palette.PLAYING
        elif looper.transport_playing and looper.is_playing:
            play = palette.PLAYING
        else:
            play = palette.OFF
        disp.set_key_color(BTN_PLAY_STOP, play)

        # RECORD: solid while recording / overdubbing, blinking while armed
        # or counting in -- whichever mode has focus.
        status = looper.record_status
        if status == "rec":
            record = palette.RECORDING
        elif status == "armed" and int(now * _ARMED_BLINK_HZ * 2) % 2 == 0:
            record = palette.RECORDING
        else:
            record = palette.OFF
        disp.set_key_color(BTN_RECORD, record)

        if active is looper:
            muted = looper.channel_status(looper.active_idx) == "muted"
        else:
            muted = seq.selected_muted
        disp.set_key_color(BTN_MUTE, palette.MUTED if muted else palette.OFF)

        disp.set_key_color(BTN_MODE, palette.LOOP_MODE if active is looper
                           else palette.SEQ_MODE)

        if channel_view_on:
            key_mode = palette.KEY_MUTE if key_mode_mute else palette.KEY_SELECT
        elif active is looper and arp.is_on(looper.active_idx):
            key_mode = palette.KEY_ARP
        else:
            key_mode = palette.OFF
        disp.set_key_color(BTN_KEY_MODE, key_mode)

        clear_on = clear_scope and int((now - clear_armed_at) * _CLEAR_BLINK_HZ * 2) % 2 == 0
        disp.set_key_color(BTN_CLEAR, palette.ARMED_CLEAR if clear_on else palette.OFF)

        for button in _PRESS_LIT:
            disp.set_key_color(button, palette.PRESSED if button in held_keys
                               else palette.OFF)

    if config.TIMING_PROBE:
        draw_lights = hw.timed_draw(draw_lights)

    disp.show(MODE_NAMES[mode_index])
    if config.TIMING_PROBE:
        # The probe's ALLOC line: what each part of a pass allocates.
        hw.track("loop ev", looper, "handle_event", 3)
        hw.track("seq ev", seq, "handle_event", 2)
        hw.track("loop", looper, "update", 1)
        hw.track("seq", seq, "update", 1)
        hw.track("arp", arp, "update", 1)
        hw.track("menu", menu, "update", 1)
        hw.track("synth", synth, "update", 1)
        hw.track("disp", disp, "update", 1)
        census("ready")

    # What the active mode (or the menu) gets from each pass's events: one
    # list, emptied every pass rather than made anew -- the main loop
    # allocates as little as it can, since garbage brings on the
    # collections that stall the audio.
    filtered = []

    while True:
        now    = clock.now()
        events = hw.scan()
        if events:
            lights_at = 0.0   # show a press straight away

        # ── Route each event: pads, then function keys ────────────────────────
        if filtered:
            filtered.clear()
        for event in events:
            etype, data, event_time = event
            if etype == BTN_DOWN:
                held_keys.add(data)
            elif etype == BTN_UP:
                held_keys.discard(data)

            # ── Pads: the channel view's, or the active mode's ────────────────
            if etype == PAD_DOWN and channel_view_on:
                view_pads.add(data)
                if clear_scope:
                    end_clear()
                channel_tap(data, now)
            elif etype == PAD_UP and data in view_pads:
                view_pads.discard(data)
            # ── ...or the arp's ───────────────────────────────────────────────
            elif etype == PAD_DOWN and arp_takes_pads():
                arp_pads.add(data)
                arp.press(data, event_time, looper.active_idx,
                          looper.count_in_start)
            elif etype == PAD_UP and data in arp_pads:
                arp_pads.discard(data)
                arp.release(data, event_time)
            elif etype in (PAD_DOWN, PAD_UP):
                filtered.append(event)

            # ── Releases: only UP/DOWN's matters (it ends auto-repeat). The
            #    menu gets it too, to pair with the press it saw ─────────────
            elif etype != BTN_DOWN:
                if data in (BTN_INC, BTN_DEC):
                    vol_held_dir = 0
                    if menu_active:
                        filtered.append(event)

            # ── An armed CLEAR takes the next function key ────────────────────
            elif clear_scope:
                if data == BTN_MENU:
                    confirm_clear(now)
                elif data == BTN_CLEAR:
                    arm_clear("all" if clear_scope == "channel" else "channel", now)
                else:
                    end_clear()   # cancelled; the key does nothing else

            elif data == BTN_MODE:
                if switch_mode((mode_index + 1) % NUM_MODES, now):
                    set_channel_view(False)

            elif data == BTN_PLAY_STOP:
                toggle_transport(now)

            elif data == BTN_MENU:
                if menu_active:
                    filtered.append(event)
                else:
                    open_menu()

            elif data == BTN_RECORD:
                if menu_active:
                    if menu.back(event_time):
                        close_menu()
                else:
                    filtered.append(event)

            elif data in (BTN_INC, BTN_DEC):
                if menu_active:
                    filtered.append(event)
                else:
                    vol_held_dir  = 1 if data == BTN_INC else -1
                    vol_repeat_at = now + _VOLUME_REPEAT_DELAY
                    step_volume(vol_held_dir, now)

            elif data == BTN_VIEW:
                set_channel_view(not channel_view_on)

            elif data == BTN_KEY_MODE:
                if channel_view_on:
                    key_mode_mute = not key_mode_mute
                    flash("MUT " if key_mode_mute else "SEL ", now, _LOCK_FLASH_HOLD)
                elif active is looper:
                    layer = looper.active_idx
                    on = not arp.is_on(layer)
                    if not on:
                        stop_arp(now)
                    arp.set_on(layer, on)
                    flash("ARP " if on else "KEYS", now, _LOCK_FLASH_HOLD)

            elif data == BTN_CLEAR:
                if not menu_active:
                    arm_clear("channel", now)

            elif not menu_active:
                filtered.append(event)   # MUTE: the active mode's

        # ── Sync coordinator: detect looper arm while sequencer is playing ────
        # (RECORD only reaches `filtered` with the menu closed.)
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
        # Pads always go to the active mode, menu open or not; with the
        # menu open, every function key in `filtered` is the menu's.
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

        # ── An armed CLEAR left waiting gives up ──────────────────────────────
        if clear_scope and now >= clear_until:
            end_clear()

        # ── Restore display after a volume / LOCK flash ───────────────────────
        if flash_until and now >= flash_until:
            end_flash()

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
            bar_index   = -1
        elif seq_was_playing and not seq.playing:
            arp.unsync()
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
                if step == 0:
                    # A new bar. AUTO's mutes go first, so a channel it
                    # brings back plays this downbeat (and one it drops
                    # doesn't).
                    bar_index += 1
                    arrange(arranger.on_unit(bar_index, "bar"), now)
                tick_evt = (TICK, step)
                seq.handle_event(tick_evt, tick_at)
                if looper.clock_needed:
                    looper.handle_event(tick_evt, tick_at)
                arp.sync(tick_at, step_dur)

                if step % 4 == 0:
                    beat_evt = (BEAT, beat_count)
                    seq.handle_event(beat_evt, now)
                    beat_count += 1
                    beat_led_until = now + _BEAT_PULSE_DURATION

                step = (step + 1) % STEPS_PER_BAR

        # ── Per-mode continuous update ──────────────────────────────────────
        if looper.transport_playing:
            looper.update(now)
            # A freeform loop (no tempo clock): AUTO counts its passes.
            if not seq.playing and looper.pass_index != last_pass:
                last_pass = looper.pass_index
                if last_pass >= 0:
                    arrange(arranger.on_unit(last_pass, "pass"), now)
        seq.update(now)
        # After looper.update: a take it just started gets a note due at
        # its first beat.
        play_arp(arp.update(now))
        if menu_active:
            menu.update(now)

        # ── Synth auto-release housekeeping ──────────────────────────────────
        synth.update(now)

        # ── Lights, drawn last so they show this pass's state ─────────────────
        if now >= lights_at:
            lights_at = now + _FRAME_INTERVAL
            draw_lights(now)
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
