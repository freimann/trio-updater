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
| Free space in the MCU image | ~15 KB erased tail (`0x6555`–`0xA000`) |

The firmware images themselves are **not** redistributed here (DigiTech/Harman
copyright). `tools/fetch_firmware.sh` downloads them from the vendor URLs and
verifies SHA-256 against `reference/artifacts.sha256`.

---

## What's in the box

```
docs/updater.md        updater app + installer analysis, manifest, device detection
docs/protocol.md       HID flash protocol (reports, commands, checksums)
docs/firmware-mp.md    Trio+ MCU image map, vectors, USB descriptors, peripherals
docs/midi-clock.md     options for generating MIDI clock, with trade-offs
reference/             manifest snapshot, artifact hashes
tools/fetch_firmware.sh    download + verify vendor firmware
tools/dsp_ldr_to_bin.py    decode DSP1.ldr (ASCII "0xNN" lines) to a raw image
tools/inspect_mp.py        parse the MCU image: vectors, descriptors, free space
```

## Quick start

```sh
# 1. Fetch vendor artifacts (~30 MB, no auth required)
tools/fetch_firmware.sh

# 2. Decode the DSP image
tools/dsp_ldr_to_bin.py firmware/trioplus/DSP1.ldr -o firmware/trioplus/DSP1.bin

# 3. Inspect the MCU image
tools/inspect_mp.py firmware/trioplus/TrioLooper_Update.bin
```

## Target hardware

* **MCU:** Atmel/Microchip SAM3S-class Cortex-M3 (ARMv7-M, Thumb-2).
  Image base `0x00400000`, initial SP `0x200016B8`, reset `0x00402ED9`.
  Peripherals identified in the image: USB device (UDP) `0x40034000`,
  SPI `0x40008000`, PIOA `0x400E0E00`, RSTC/SUPC `0x400E1400`.
* **DSP:** separate processor behind the SPI link. Its image is opaque
  (high entropy, no strings, no header) and the ISA/toolchain is unidentified.

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
