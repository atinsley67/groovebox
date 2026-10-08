# Groovebox hardware

A Raspberry Pi Pico 2 W running CircuitPython 10, with:
- an Adafruit NeoKey 5x6 Ortho Snap-Apart, snapped into a **4x4 pad grid** and a **2x5 function block**, with a NeoPixel under every key
- an I2S DAC (Adafruit UDA1334A or similar)
- an Adafruit quad 14-segment display (HT16K33) on I2C

All pins are set in [`config.py`](../config.py). Change them there if you rewire.

## Parts

| Part | Notes |
|---|---|
| Raspberry Pi Pico 2 W | Running [CircuitPython 10](https://circuitpython.org/board/raspberry_pi_pico2_w/). Nothing uses the Wi-Fi yet, so a plain Pico 2 should work too (untested) |
| [NeoKey 5x6 Ortho Snap-Apart](https://www.adafruit.com/product/5157) | Snapped into a 4x4 and a 2x5 piece, with 4 keys left over. Each key has a Kailh hot-swap socket and a NeoPixel |
| 26 MX-compatible key switches and keycaps | Not included with the NeoKey. Clear or translucent keycaps let the light through. Kailh Low Profile switches don't fit |
| [UDA1334A I2S stereo DAC](https://www.adafruit.com/product/3678) | Line-level out on a 3.5 mm jack: headphones or powered speakers |
| [Quad alphanumeric display with I2C backpack](https://www.adafruit.com/product/2157) | 0.54" 14-segment, HT16K33. Comes in several colours; any will do |
| [STEMMA QT to male header cable](https://www.adafruit.com/product/4209) | Connects the display to the proto board. Or solder 4 Dupont wires to the backpack's header pins instead |
| A Pico proto board ([like these](https://www.amazon.com/dp/B08YN3HXX2)) | Solderable expansion board that the Pico, the DAC and the wiring sit on. Plain perfboard works too |
| Dupont-style cable | For the two key pieces: the pad grid needs 11 wires (4 rows, 4 columns, pixel data, + and ground), the function block 10 (5 + 2 matrix lines, pixel data, + and ground). Plug them onto headers, or solder them straight to the pieces and/or the proto board |
| 1N4007 diode | Drops the pixel power to ~4.3 V (see *Pixel power*) |
| A front panel and enclosure | Mine has a 3D-printed front panel (not in the repo yet), plus whatever screws, standoffs and other bits your enclosure needs |
| A USB cable | Everything runs from USB |

Optional, and not used in the original build: two 330–470 Ω resistors and a 100 µF capacitor (10 V or more) for the NeoPixels, if they ever flicker (see *Wiring*).

## Wiring

Each piece is a key matrix: one set of lines on the anode side of its diodes (`*_ROW_PINS` in config) and one on the cathode side (`*_COL_PINS`). The code hands them to the key scanner swapped, a workaround for an RP2350 bug. Don't add pull-up or pull-down resistors to the matrix lines.

| Connection | Config name | Pins |
|---|---|---|
| Pad grid rows | `PAD_ROW_PINS` | GP2, GP3, GP4, GP5 |
| Pad grid columns | `PAD_COL_PINS` | GP7, GP8, GP0, GP1 |
| Pad grid NeoPixel data | `PAD_PIXEL_PIN` | GP6 |
| Function block, anode side (its 5 labelled columns) | `FUNC_ROW_PINS` | GP12, GP13, GP14, GP15, GP22 |
| Function block, cathode side (its 2 labelled rows) | `FUNC_COL_PINS` | GP10, GP11 |
| Function block NeoPixel data | `FUNC_PIXEL_PIN` | GP9 |
| Display I2C SDA / SCL | `I2C_SDA` / `I2C_SCL` | GP16 / GP17 |
| DAC data / bit clock / word select | `I2S_*` | GP18 / GP19 / GP20 |
| Spare | | GP21, GP26, GP27, GP28 |

The function block's diodes run the other way from the pad grid's, relative to the board labels. That's why its labelled rows and columns are swapped in config.

**Pixel data** goes to each piece's DIN pad (the start of its chain), not DOUT. The original build wires it straight from the Pico.

**Pixel power** (USB only):
- VBUS → 1N4007 (striped end toward the pixels) → the + pin of both pieces. The diode drops the pixels to ~4.3 V, so the Pico's 3.3 V data signal is within their spec.
- Ground to both pieces.

Running on battery or another supply would mean rethinking this.

**If the pixels flicker or show wrong colours** (the original build doesn't need these): add a 330–470 Ω resistor in series with each data line, near that piece's first pixel, and a 100 µF capacitor across + and − where power enters the pad grid (mind the polarity).

## Libraries on the Pico

`lib/` needs `adafruit_ht16k33`, `adafruit_bus_device` and `neopixel`, from the Adafruit library bundle for CircuitPython 10.x. CircuitPython has `neopixel_write` and `adafruit_pixelbuf` built in, so don't copy those.

## Calibrating the layout

`config.py`'s layout tables say where each key and pixel sits, written as you look at each piece (top row first):
- `PAD_KEYS` and `FUNC_KEYS` hold key numbers.
- `PAD_PIXELS` and `FUNC_PIXELS` hold pixel indices.
- `FUNC_LAYOUT` says which button each function key is. It's free to rearrange without recalibrating, as long as each of the 10 buttons appears exactly once.

Pad n is the n-th key reading row by row from the top left (pads 1–4 are the top row). Kit sounds and sequencer steps follow that order. Melodic notes are derived from it, lowest at the bottom left (`keymap.NOTE_OF_PAD`), so they follow a remounted grid automatically. A mistyped table stops startup with an error naming it.

To recalibrate (after rewiring, or remounting a piece), uncomment the `io_test` line in `code.py`:
1. **Pixel walk.** Each pixel lights white in turn while the display shows its number: `P  0` to `P 15` on the pad grid, then `F  0` to `F  9` on the function block. Note where each one lights → the `PIXELS` tables.
2. **Keys.** Pressing a key shows its number, `PK 5` or `FK 3` → the `KEYS` tables. Releasing it shows what config makes of it:
   - `PD 1` to `PD16` for a pad
   - the button's name for a function key
   - `----` for an unassigned key

   The pixel under the key lights while it's held, so a wrong light means a wrong `PIXELS` entry. Pad 1 plays a tone.

Comment the line back out to return to the app.

## Tuning

| Setting | What it does |
|---|---|
| `KEY_DEBOUNCE_THRESHOLD` | Raise to 3 if a single press ever plays twice |
| `KEY_SCAN_INTERVAL` | Time between key scans (4 ms). Lower is snappier but less tolerant of switch bounce |
| `KEY_TIME_ADJUST` | Shifts recorded presses earlier to cover the scan delay. Follows from the two settings above |
| `PIXEL_BRIGHTNESS` | Overall pixel brightness cap (USB power budget) |
| `palette.py` | The key colours, and `DIM`, the "state" brightness level |
| `I2C_FREQUENCY` | 400 kHz. Set to 100000 if the display glitches |

## Troubleshooting

- **No display text and no lights at all:** the code stopped at startup. Open the serial console; the error is printed there. A missing `neopixel` library is the usual cause.
- **A whole piece ignores key presses:** its diodes may run the other way. Swap that piece's `ROW` and `COL` pin lists in config, then recalibrate its `KEYS` table.
- **A piece's pixels stay dark:** check that its data goes to DIN (and the series resistor, if you added one), and look for ~4.3 V across its + and −.
- **Flickering or wrong colours:** the pixel data voltage margin. Check the diode, lower the brightness, or add the optional resistors and capacitor (see *Wiring*).

## Timing

`config.TIMING_PROBE = True` prints main-loop timing to the serial console every 5 s; [`timing_probe.py`](../timing_probe.py) explains each field. It also prints a `HEAP` line at each stage of boot and after a groove loads: memory in use and how long a garbage collection takes at that point, so a slow collection can be traced to code, sound tables, voices or recorded loops.

Read its GC times as relative, not absolute: the probe's own bookkeeping can make collections slower than they are with it off.
