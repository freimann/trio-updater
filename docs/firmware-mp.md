# Trio+ MCU firmware

Artifact: `TrioLooper_Update.bin`, 40,960 bytes (`0x0000`–`0xA000`), raw
headerless ARM image. SHA-256 in `reference/artifacts.sha256`.

This is the **internal** SAM4S application image (flash base `0x00400000`),
not a dump of the external 16 MB Winbond. See
[hardware.md](hardware.md) for the two-flash arrangement.

## Trio and Trio+ images

Both products ship a 40,960-byte MCU image with the same entry point and
linker base, so the two are close relatives:

| | Trio | Trio+ |
|---|---|---|
| Artifact | `Trio_Update.bin` | `TrioLooper_Update.bin` |
| Size | 40,960 B | 40,960 B |
| Initial SP | `0x20001798` | `0x200016B8` |
| Reset | `0x00402ED9` | `0x00402ED9` |
| USB PID | `0x0042` | `0x0043` |
| Device descriptor | `0x00405FE0` | `0x00406520` |
| Configuration descriptor | `0x00405FA0` | `0x004064E0` |
| Free tail | 16,362 zero bytes | 15,018 zero bytes |

The images differ in 12,889 bytes, mostly strings, USB descriptors and
product-specific tables rather than the SPI/USB driver core. The Trio+ map
below is the one used by this project; the Trio image parses the same way.

## Image map

Loaded at `0x00400000`, so file offset `N` maps to `0x400000 + N`.

| Offset | VA | Contents |
|---|---|---|
| `0x0000` | `0x400000` | Vector table (initial SP, reset, 16 system + IRQ entries) |
| `0x0100` | `0x400100` | Code |
| `0x2ED8` | `0x402ED8` | Reset handler |
| `0x6494` | `0x406494` | HID report descriptor (53 bytes) |
| `0x64E0` | `0x4064E0` | Configuration descriptor (41 bytes) |
| `0x6520` | `0x406520` | Device descriptor (18 bytes) |
| `0x6555` | `0x406555` | Last non-zero byte |
| `0x6556`–`0x9FFF` | | Erased / free: **15,018 bytes** |

Initial state:

| Field | Value |
|---|---|
| Initial SP | `0x200016B8` |
| Reset vector | `0x402ED9` (Thumb, entry `0x402ED8`) |
| Default handlers | `0x402ED5` (a `b .` infinite loop) |

The adjacent original-Trio image is structurally identical but has
SP `0x20001798`, a different USB PID, and slightly different code, which makes
for a useful diff target.

## Peripherals referenced by the image

| Block | Base | Notes |
|---|---|---|
| SPI0 | `0x40008000` | DSP link and external flash; most-referenced peripheral in the image |
| USB device (UDP) | `0x40034000` | Interrupt-driven, ISR below |
| PIOA | `0x400E0E00` | GPIO / pin mux / chip selects |
| PIOC | `0x400E1200` | GPIO |
| RSTC / SUPC / WDT | `0x400E1400` | Reset, supply and watchdog |
| PMC / EFC | `0x400E0400` / `0x400E0A00` | Clocking / internal-flash controller |

SysTick is enabled (vector `0x00403F21`). The image does **not** reference the
on-chip ADC, PWM or USART blocks, so the front-panel pots are not read by the
MCU's ADC.

The base address `0x00400000` is the SAM4S internal-flash base, which makes
the part an Atmel/Microchip **SAM4S** Cortex-M4 (ARMv7E-M, Thumb-2), not a
SAM3S. The 40 KB length is exactly five 8 KB erase blocks.

## USB ISR

The USB interrupt is IRQ 34, vector index 50, handler `0x401900`. It inspects
device status and mask registers at offsets `+0x18`, `+0x1C`, `+0x20` from
`0x40034000`.

The image also contains USB request/descriptor tables around
`0x406460`–`0x406540`, including a jump table of small Thumb stubs.

## USB identity and descriptors

Device descriptor (`0x406520`):

```
12 01 00 02 00 00 00 08  10 12 43 00  00 01 00 00  00 01
```

| Field | Value |
|---|---|
| bcdUSB | 2.00 |
| bDeviceClass/Sub/Proto | 0 / 0 / 0 (class at interface level) |
| bMaxPacketSize0 | 8 |
| idVendor | `0x1210` (DigiTech) |
| idProduct | `0x0043` (Trio+; original Trio = `0x0042`) |
| bcdDevice | 1.00 |
| Strings | none (all string indices 0) |
| bNumConfigurations | 1 |

Configuration descriptor (`0x4064E0`, `wTotalLength = 0x29`):

```
09 02 29 00 01 01 00 C0 32
09 04 00 00 02 03 00 00 00
09 21 11 01 00 01 22 35 00
07 05 81 03 40 00 05
07 05 02 03 40 00 05
```

* **One interface, class 3 (HID)**, subclass 0, protocol 0.
* Endpoint `0x81` IN, interrupt, 64 B, interval 5.
* Endpoint `0x02` OUT, interrupt, 64 B, interval 5.
* HID descriptor: bcdHID 1.11, one report descriptor, length `0x35` (53 B).
* Bus powered, 100 mA (`0xC0`, `0x32`).

**No USB-MIDI (class 1) and no USB-audio function.** There is no alternate
setting, no bulk endpoint, and no second interface to repurpose.

Report descriptor (`0x406494`):

```
06 FF FF        Usage Page (Vendor 0xFFFF)
09 01           Usage (1)
A1 01           Collection (Application)
  09 02 09 03   Usage 2, Usage 3
  15 00 26 FF 00  Logical Min 0, Logical Max 255
  75 08 95 40     Report Size 8, Report Count 64
  81 02           Input (Data,Var,Abs)        -> 64-byte IN
  09 04 09 05     Usage 4, Usage 5
  15 00 26 FF 00  Logical Min 0, Logical Max 255
  75 08 95 40     Report Size 8, Report Count 64
  91 02           Output (Data,Var,Abs)       -> 64-byte OUT
  09 06 09 07     Usage 6, Usage 7
  15 00 26 FF 00  Logical Min 0, Logical Max 255
  75 08 95 04     Report Size 8, Report Count 4
  B1 02           Feature (Data,Var,Abs)      -> 4-byte FEATURE
C0              End Collection
```

There is no report ID prefix, so every report is exactly 64 bytes on the wire
plus the `0x00` report ID byte the vendor tool prepends when calling `hid_write`.

## What the MCU does and does not own

* Owns: USB stack, HID command handling, external-flash programming, SPI
  master, UI.
* Does *not* obviously own: tempo/BPM. The tempo is a DSP-side concept; the MCU
  most likely forwards transport/tempo events over SPI. This needs confirmation
  before any clock-generation patch can be designed.

## Free space and the update mechanism

15,018 zero bytes at the end of the image is plenty for a USB-MIDI
implementation *in principle*. Constraints and open questions:

* SAM4S internal flash has 512-byte pages and 8 KB erase blocks. The 40 KB
  image is exactly five erase blocks, so keeping the image at 40 KB keeps the
  erase/write pattern identical.
* The image is linked at the flash base (`0x00400000`) and contains no separate
  bootloader. The update code is in the same image, so the application most
  likely stages the new image in SRAM (128 KB) and programs its own flash from
  a RAM routine. That is consistent with the updater's "Reboot Failure" message
  but has not been observed on hardware.
* Whether the updater writes all 40 KB unconditionally or uses a length field
  is not confirmed. A patched image should therefore stay within 40 KB and keep
  a valid vector table and checksum.

Any patch must keep the image length and layout the update path expects, or the
unit will not boot after the update. A J8/JTAG recovery path is strongly
recommended before testing.
