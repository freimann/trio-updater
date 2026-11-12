# trio-updater

Reverse engineering notes and tooling for the **DigiTech Trio / Trio+** firmware
updater, with the goal of modifying the **Trio+** firmware to generate
**MIDI clock over USB**.

Status: **research phase.** Nothing has been flashed to hardware yet, and no
firmware patch is included in this repository.

---

## TL;DR of the findings

| Question | Answer |
|---|---|
| Does the updater support both units? | Yes. HID VID `0x1210`; PID `0x0042` = Trio, `0x0043` = Trio+ |
| Is firmware bundled in the installer? | No. It is downloaded from a vendor manifest at install/update time |
| Default manifest | `http://harmandbx.blob.core.windows.net/digi-trio-plus/tp-manifest.xml` |
| Can the manifest URL be changed? | Yes, in-app ("Set Manifest URL…") and via QSettings `update/manifest-url` |
| Is the update signed or encrypted? | No. Plain XOR checksums, vendor HID reports, no signature check |
| Does the device expose USB MIDI? | No. It enumerates as a single vendor HID function (class 3), 2 interrupt endpoints |
| USB port | Mini-B; used only for firmware updates and TRIO Manager |
| SD card | microSDHC, Class 10, 8–32 GB, up to 12 songs |
| Tempo control | Global playback tempo, 0.5×–2× the learned part tempo (Audiolastic) |
| MCU | Atmel/Microchip **SAM4S** Cortex-M4, LQFP-64, internal flash at `0x00400000` |
| External storage | **Winbond W25Q128FVSG**, 16 MB SPI NOR (DSP image, styles, ensemble audio) |
| DSP | **Analog Devices ADSP-21489** SHARC, with 32 MB SDRAM |
| Free space in the MCU image | 15,018 zero bytes at the tail (`0x6556`–`0x9FFF`) |

The firmware images themselves are **not** redistributed here (DigiTech/Harman
copyright). `tools/fetch_firmware.sh` downloads them from the vendor URLs and
verifies SHA-256 against `reference/artifacts.sha256`.

---

## What's in the box

```
docs/updater.md        updater app + installer analysis, manifest, device detection
docs/protocol.md       HID flash protocol (reports, commands, checksums)
docs/firmware-mp.md    Trio+ MCU image map, vectors, USB descriptors, peripherals
docs/hardware.md       PCB identification, front panel, flash/SDRAM/DSP, dump procedure
docs/sdcard.md         `.tlsd` song container, header offsets, audio layout
docs/midi-clock.md     options for generating MIDI clock, with trade-offs
reference/             manifest snapshot, artifact hashes
tools/fetch_firmware.sh    download + verify vendor firmware
tools/dsp_ldr_to_bin.py    decode DSP1.ldr (ASCII "0xNN" lines) to a raw image
tools/inspect_mp.py        parse the MCU image: vectors, descriptors, free space
tools/dump_flash.sh        read the external flash twice and compare (CH341A)
tools/analyze_flash.py     map a full 16 MB dump: partitions, blobs, free space
tools/tlsd_info.py         parse a `.tlsd` song header and part layout
```

## Quick start

```sh
# 1. Fetch vendor artifacts (~30 MB, no auth required)
tools/fetch_firmware.sh

# 2. Decode the DSP image
tools/dsp_ldr_to_bin.py firmware/trioplus/DSP1.ldr -o firmware/trioplus/DSP1.bin

# 3. Inspect the MCU image
tools/inspect_mp.py firmware/trioplus/TrioLooper_Update.bin

# 4. If you have a CH341A and a SOIC-8 clip, dump and map the external flash
tools/dump_flash.sh trio_flash.bin
tools/analyze_flash.py trio_flash.bin

# 5. Inspect a song copied from the SD card
tools/tlsd_info.py "Song C1 @68.6.tlsd"
```

## Target hardware

* **MCU:** Atmel/Microchip **SAM4S** Cortex-M4 (ARMv7E-M, Thumb-2), LQFP-64.
  Internal flash base `0x00400000`, 512-byte pages / 8 KB erase blocks.
  Image: initial SP `0x200016B8`, reset `0x00402ED9`.
  Peripherals used: SPI0 `0x40008000`, USB device (UDP) `0x40034000`,
  PIOA `0x400E0E00`, PIOC `0x400E1200`, RSTC/SUPC/WDT `0x400E14xx`, SysTick.
* **External flash:** Winbond **W25Q128FVSG**, 16 MB SPI NOR. Holds the DSP
  image, style data and ensemble audio; the 40 KB MCU application lives in the
  SAM4S internal flash instead. See [docs/hardware.md](docs/hardware.md).
* **DSP:** Analog Devices **ADSP-21489** SHARC, LQFP-176, with 32 MB Micron
  SDRAM (MT48LC16M16A2). Its image ships as an ASCII `0xNN` loader stream
  (711 KB decoded for the Trio+), not as an ELF or a binary with strings.
* **Front panel:** 5 pots, ~10 tact switches and 8 LEDs, linked by a ribbon to
  **74HC165** input and **74HC595** output shift registers. The audio microSD
  card uses the `.tlsd` format described in [docs/sdcard.md](docs/sdcard.md).

## Why MIDI clock is not a small patch

The MIDI clock source has to be the thing that knows the tempo. On the Trio+
that is almost certainly the DSP side of the SPI link, not the MCU. On top of
that, "MIDI over USB" requires adding a USB-MIDI function to a device that
currently exposes only vendor HID. See [docs/midi-clock.md](docs/midi-clock.md)
for the three realistic routes and their costs.

## Legal

This is independent interoperability research. It contains no vendor binaries,
no keys, and no code extracted from the vendor application beyond factual
observations (addresses, descriptor bytes, string literals needed to explain
the protocol). DigiTech, Trio, and Trio+ are trademarks of their respective
owners. Flashing modified firmware can brick your hardware; you do it at your
own risk.
