"""
Startup: builds the hardware, then runs the groovebox (groovebox.py) -- or,
with MENU held down while it starts, something else (game.py).

The check comes before either program is imported, so only the one that
runs is ever loaded: the groovebox's modules take a lot of heap, and every
garbage collection has to walk whatever is loaded.
"""

import time
import traceback

import config

try:
    # Uncomment to run the hardware I/O test loop instead of the real app:
    # import io_test; io_test.run()

    import hw
    # Before Hardware(): it reads MENU's lines itself (see hw.held_at_startup).
    game_wanted = hw.held_at_startup(config.BTN_MENU)
    hardware = hw.Hardware()
    if game_wanted:
        import game
        game.run(hardware)
    else:
        import groovebox
        groovebox.main(hardware)
except Exception as e:
    traceback.print_exception(type(e), e, e.__traceback__)
    while (1):
        time.sleep(2)
    # import microcontroller; microcontroller.reset()
