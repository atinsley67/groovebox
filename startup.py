"""
Startup animation: LED sweep + scrolling marquee on the alphanumeric display.
Runs once before the main loop starts. Pressing any pad/button skips it.
"""

import time

MARQUEE_TEXT        = "GROOVEBOX"
LED_STEP_DELAY      = 0.035  # per-LED sweep speed
MARQUEE_FRAME_DELAY = 0.12   # per-frame scroll speed


def _skip_requested(hw):
    return len(hw.scan()) > 0


def run(hw, disp):
    """Play the boot animation. Returns immediately if any button/pad is pressed."""
    # ── LED sweep: chase up through all 16 LEDs, then flash, then clear ────────
    for i in range(16):
        disp.set_led(i, True)
        time.sleep(LED_STEP_DELAY)
        if _skip_requested(hw):
            disp.clear_leds()
            disp.clear()
            return

    time.sleep(0.08)
    disp.clear_leds()

    # ── Marquee: scroll text across the 4-char alphanumeric display ────────────
    padded = "    " + MARQUEE_TEXT + "    "
    for start in range(len(padded) - 3):
        disp.show(padded[start:start + 4])
        time.sleep(MARQUEE_FRAME_DELAY)
        if _skip_requested(hw):
            disp.clear()
            return

    disp.clear()
