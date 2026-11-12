# Hardware

Board: `HPM165_D TRIO PLUS MAIN` (silkscreen), barcode `V16022411613`.
The PCB photos show a board revision from February 2016 and a separate
front-panel board connected by a 2×13 ribbon cable.

## Main devices

| Ref | Device | Package | Role |
|---|---|---|---|
| U2 | Atmel/Microchip **SAM4S**-class Cortex-M4 | LQFP-64 | USB HID, UI, SPI master, update logic. Marking obscured. |
| U3 | **Winbond W25Q128FVSG** | SOIC-8, 208 mil | 128 Mbit / **16 MB** SPI NOR. Date code 1541. |
| U4 | **Micron MT48LC16M16A2P-6A:G** | TSOP-II 54 | 256 Mbit / **32 MB** SDRAM, next to the DSP. |
| U5 | **Analog Devices ADSP-21489** (SHARC) | LQFP-176 (KSWZ-4B) | Audio/looper DSP. |
| J8 | 2x5 through-hole header, unpopulated | 2.54 mm | Purpose to be determined (MCU JTAG or flash programming). |
| — | microSDHC slot | — | User loops / songs, 8–32 GB Class 10. |
| — | Mini-USB B | — | Device HID port / TRIO Manager. |

### Why the MCU is a SAM4S, not a SAM3S

The MCU firmware image is linked at `0x00400000`. That is the SAM4S internal
flash base (SAM3S and SAM3U use `0x00000000` / `0x00080000`). The peripheral
addresses also match SAM4S:

* PMC `0x400E0400`, EFC `0x400E0A00`
* SPI0 `0x40008000`, UDP `0x40034000`
* PIOA `0x400E0E00`, PIOC `0x400E1200`
* RSTC `0x400E1400`, SUPC `0x400E1410`, WDT `0x400E1450`

A SAM4S in LQFP-64 has 256 KB (SAM4S4), 512 KB (SAM4S8) or 1 MB (SAM4S16) of
internal flash, 128 KB SRAM, and a 512-byte flash page / 8 KB erase block.
The 40 KB update image is exactly **five 8 KB erase blocks**, which is why the
updater transfers that length.

## Two flash memories, two different jobs

This distinction matters for the project:

* **Internal SAM4S flash** (`0x00400000`) holds the 40 KB MCU application that
  the updater sends as the `MP` component. It implements USB HID, the update
  protocol and the SPI link. It is not in the 16 MB dump.
* **External W25Q128** holds the large payloads: the DSP boot image, style
  data and ensemble audio, plus settings. The updater sends these as `DSP`,
  `Styles` and `Ensemble`; the MCU writes them over SPI.

The sizes line up almost exactly with a 16 MB part:

| Payload | Size |
|---|---|
| DSP loader, ASCII `0xNN` lines | 4,266,216 B (4.07 MiB) |
| Style data | 1,981,568 B (1.89 MiB) |
| Ensemble audio (FLAC) | 8,869,694 B (8.46 MiB) |
| **Total** | **15,117,478 B (14.4 MiB)** |

That leaves roughly 1.6 MB for a staging area, settings and the DSP boot
header — or, if the DSP image is stored decoded (711 KB), about 4.4 MB free.
Either way, the dump will show which.

## Architecture

```
            USB (HID, vendor)
                   |
              +---------+        SPI0          +------------------+
              |  SAM4S  |<-------------------->|   ADSP-21489     |
              |  MCU    |        (master)      |   SHARC DSP      |
              +---------+                      +------------------+
                   |                              |          |
                   | SPI0 (same bus, CS lines)    |          |
                   v                              v          v
            +--------------+                +--------+  +---------+
            | W25Q128FVSG  |                | SDRAM  |  | audio   |
            | 16 MB NOR    |                | 32 MB  |  | codecs  |
            +--------------+                +--------+  +---------+
```

The MCU image uses SPI0 heavily (register offsets `+0x04/+0x08/+0x0C/+0x10/
+0x14`), PIOA/PIOC for chip selects and GPIO, RSTC/SUPC, and SysTick (the
SysTick vector is populated at `0x00403F21`). It does **not** reference the
on-chip ADC, PWM or USART blocks. The front-panel buttons and LEDs are handled
by shift registers, but the five pots are analog and their ADC is not yet
identified (see below).

## Front-panel board

The front panel is a second PCB behind the knobs, wired to the main board by a
2×13 ribbon cable. Components visible on it:

| Part | Type | Role |
|---|---|---|
| VR1–VR5 | 10 kΩ potentiometers | Five continuous controls |
| SW1–SW10 | tact switches | Transport, part select, tempo tap, etc. |
| 8 LEDs | panel indicators | Part / transport state |
| U4, U5, U11 (and one more) | **74HC165D** | Parallel-in, serial-out input shift registers |
| U9, U10 | **74HC595** (`HG595`) | Serial-in, parallel-out output latches for the LEDs |

So the MCU scans buttons and drives LEDs over a shift-register chain, which is
consistent with the SPI0/PIO usage in its image. The pots are not in that
chain. The ADSP-21489 has no on-chip ADC and the SAM4S ADC registers are not
referenced by the MCU image, so there is either an external SPI ADC on the main
board or the pots are read by a part of the design that has not been traced.
This must be settled with a continuity check and a scope before choosing where
to tap tempo.

## SD card

The microSD slot on the main board holds the user's songs. The owner's manual
specifies **microSDHC, Class 10, 8–32 GB**, and up to **12 songs** per card.
Each song is a `.tlsd` container: a 138 KB header plus audio in 32 KB chunks.
The header stores part lengths in samples, not a BPM value, so the card cannot
provide a live tempo. See [sdcard.md](sdcard.md) for the offsets and
`tools/tlsd_info.py` for a parser.

## Owner's-manual constraints

The manual (63 pages, July 2017) adds several facts that matter for the clock
work:

* **USB is a Mini-B port**, used only for firmware updates and TRIO Manager.
  There is no MIDI mode, no audio interface and no class-compliant MIDI
  descriptor mentioned anywhere.
* **Tempo is a global playback control**, not a per-part stored value. The
  TEMPO knob's centre detent is the learned tempo (1×), full clockwise is 2×
  and full counter-clockwise is 0.5×. AUDIOLASTIC time-stretching is active
  whenever the knob is away from centre.
* **ALT TIME** chooses a half/double interpretation of the current part, when
  the learned material supports it.
* **Maximum loop time is 230 seconds per song part**, derived from 50 BPM and
  48 bars in 4/4. That is a useful upper bound on the `.tlsd` part length.
* The audio path is specified as **24-bit / 44.1 kHz**, but the SD container
  decodes as 16-bit samples. Treat the card copy as 16-bit and do not infer the
  DSP/ADC resolution from it.

The manual is not redistributed here. It is a DigiTech/Harman document; use the
copy supplied with the unit or the vendor download.

## Dumping the W25Q128

The part is 3.3 V. Use `tools/dump_flash.sh` (reads twice and compares) or:

```sh
brew install flashrom
flashrom -p ch341a_spi -r trio_flash_1.bin
flashrom -p ch341a_spi -r trio_flash_2.bin
cmp trio_flash_1.bin trio_flash_2.bin
tools/analyze_flash.py trio_flash_1.bin
```

### Programmer notes

* A **CH340A** is a USB-to-serial bridge, not a flash programmer. The common
  cheap SPI programmer is the **CH341A** (the black USB stick with a ZIF
  socket). `flashrom -p ch341a_spi` is the right backend for that one.
* Many CH341A clones drive the data lines at 5 V even though the flash is
  3.3 V. Measure VCC and IO before connecting the chip, and use a 3.3 V mod or
  a level shifter. 5 V on a W25Q128 is out of spec.
* In-circuit reads only work if nothing else drives the SPI bus. The board is
  unpowered during the read (the programmer back-powers the 3.3 V rail through
  the flash), so the MCU is usually high-Z, but a clip can still be marginal.
  Read twice; if the two dumps differ, reseat the clip, lower the clock, or
  desolder the flash.
* If **J8** turns out to be a flash programming header, it is the cleanest
  connection. Check continuity from its pins to U3 pins 1–8 (CS, DO, WP, GND,
  DI, CLK, HOLD, VCC). If instead J8 maps to the SAM4S JTAG/SWD pins, keep it
  for the MCU: a J-Link or ST-Link there can read the internal flash and debug
  the running firmware, which the CH341A cannot do.

## What the dump will and will not answer

Answers:

* How the DSP image is stored (ASCII loader vs decoded binary) and where.
* Where styles and ensemble audio live, and how much space is actually free.
* Whether the MCU stages the 40 KB `MP` image in external flash during an
  update (if the image appears in the dump, it does).
* Settings/calibration blocks and any redundant copies.

Does not answer:

* The MCU bootloader/self-update behaviour — that code is in internal flash.
* The tempo source — that needs a bus capture (SPI) or MCU debugging.

## Next steps

1. Dump U3 and run `tools/analyze_flash.py`.
2. Buzz out J8 against U3 and the SAM4S JTAG pins.
3. Capture SPI0 during boot and while turning the tempo control.
