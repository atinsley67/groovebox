# NeoKey bring-up

Switching the groovebox from the breadboard buttons to the NeoKey 4x4 pad grid and 2x5 function block. The app behaves exactly as before: 8 musical pads on the grid's top two rows, the same controls, and the status LEDs moved onto the keys. `config.HARDWARE` switches between the two setups, so you can always go back to `"breadboard"`.

## 1. Library

Copy `neopixel.mpy` from the Adafruit CircuitPython library bundle (matching your CircuitPython version) into the Pico's `lib/`. Keep `adafruit_aw9523` there too if you want to switch back to the breadboard; the NeoKey setup doesn't load it.

## 2. Wiring

Rows and columns are the lines as labelled on each NeoKey piece. Wire them as named; the code swaps them for keypad itself (an RP2350 workaround). Don't add pull-up or pull-down resistors to the matrix lines.

Each piece's lines run in order along the Pico's left header, so each piece's ribbon plugs onto one stretch of it:

| Pico header pin | Pad grid ribbon | | Pico header pin | Function block ribbon |
|---|---|---|---|---|
| 1 (GP0) | row 0 | | 12 (GP9) | row 0 |
| 2 (GP1) | row 1 | | 13 (GND) | pixel GND |
| 3 (GND) | pixel GND | | 14 (GP10) | row 1 |
| 4 (GP2) | row 2 | | 15 (GP11) | column 0 |
| 5 (GP3) | row 3 | | 16 (GP12) | column 1 |
| 6 (GP4) | column 0 | | 17 (GP13) | column 2 |
| 7 (GP5) | column 1 | | 18 (GND) | (spare ground; leave unconnected) |
| 8 (GND) | (spare ground; leave unconnected) | | 19 (GP14) | column 3 |
| 9 (GP6) | column 2 | | 20 (GP15) | column 4 |
| 10 (GP7) | column 3 | | | |
| 11 (GP8) | pixel data, through a 330–470 Ω resistor near the first pixel | | | |

The rest come from the Pico's right side:

| Connection | Pico pin |
|---|---|
| Function block pixel data | GP22 (header pin 29), through a 330–470 Ω resistor near the first pixel |
| Pixel 5 V, both pieces | VBUS (header pin 40), through the diode below |
| I2C display, I2S DAC | Unchanged (GP16–GP20) |
| Spare | GP21, GP26, GP27, GP28 |

Pixel power, as decided in the plan:
- VBUS → 1N4007 (striped end toward the strips) → the + pin of both pieces. With loose wires, solder the diode inline in the 5 V wire under heat-shrink, then split to the two pieces after it.
- Ground: each piece's pixel GND conductor in its ribbon (header pins 3 and 13 above).
- 100 µF across + and − where power enters the pad grid (mind the polarity).

Before cutting a Dupont ribbon, note which colour goes to which header pin. Hot glue or tape the ribbon to each piece near the solder joints, so tugging the cable can't pull a pad off.

After snapping, check that each piece's pixel chain still links from row to row, and bridge it with a wire if not. The pixel walk in step 4 shows this.

## 3. First boot: the I/O test

1. Copy to the Pico: `code.py`, `config.py`, `hw.py`, `hw_neokey.py`, `keymap.py`, `pixels.py`, `palette.py`, `display.py`, `startup.py`, `io_test.py`.
2. In `config.py` on the Pico, set `HARDWARE = "neokey"`.
3. In `code.py`, uncomment the `import io_test; io_test.run()` line.

If it stops at startup with an error naming a `config.` table, that table is mistyped (each must list every number exactly once).

## 4. Calibrate the layout tables

The tables in `config.py` are written as you look at each piece, top row first. The defaults are guesses.

1. **Pixel walk** (runs first). Each pixel lights white in turn while the display shows its number: `P  0` to `P 15` on the pad grid, then `F  0` to `F  9` on the function block. Write each number where it lit up → `PAD_PIXELS` and `FUNC_PIXELS`.
2. **Keys** (the display then shows `KEYS`). Pressing a key shows its key number: `PK 5` for the pad grid, `FK 3` for the function block. Write each number where its key is → `PAD_KEYS` and `FUNC_KEYS`.
3. **Check.** Copy the corrected `config.py` over and run the test again:
   - Releasing a key now shows what it is: `PD 1` to `PD16` for pads (row by row from the top left), the button name for function keys, `----` for the two spares.
   - The pixel under each key should light while you hold it. A different one lighting means a wrong `PIXELS` entry.
   - Pad 1 plays a tone.

To move function keys around, edit `FUNC_LAYOUT` only. It's just which button goes where; the other tables stay put.

## 5. The app

Comment the `io_test` line in `code.py` back out, then check:

- **Pads:** the top two rows play, and each lights blue while sounding. The other 8 pads do nothing yet.
- **Status keys:** RECORD lights red while recording. PLAY/STOP is dim green while playing and flashes bright green on each beat while the sequencer runs.
- **Chords:** several pads at once, and MODE + pad.
- **Double triggers:** if a single press ever plays twice, raise `KEY_DEBOUNCE_THRESHOLD` to 3.
- **Timing feel:** free-form recording should land where you played. `KEY_TIME_ADJUST` corrects for the scan delay.
- **Colors:**
  - Steady, no flicker or wrong colors. Flicker or wrong colors point at the pixel data voltage: check the series resistors and the diode, or lower the brightness.
  - If red and green come out swapped, tell me (it's the pixel color order).
  - `PIXEL_BRIGHTNESS` sets the overall cap. `palette.DIM` sets how dim the "playing" green is next to the beat flash.
- **Timing:** set `TIMING_PROBE = True`, play the usual session, and compare with `baseline-display-fix.txt`.
