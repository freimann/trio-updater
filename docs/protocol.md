# HID flash protocol

Everything below was recovered from the flasher routines that the vendor
statically linked into `TrioUpdater.exe` (they still contain their `printf`
debug messages). It is **not** taken from a USB capture — no hardware was
attached during this analysis. Treat it as a strong hypothesis pending a
capture.

## Transport

* Vendor HID, VID `0x1210`.
* Report size: **65 bytes** per transfer (`0x41`), i.e. report ID `0x00` plus
  64 payload bytes. The OUT endpoint is 64 bytes, interrupt, interval 5.
* Responses are read as 64 bytes (`hid_read_timeout(dev, buf, 0x40, timeout)`).

## Report layout

| Offset | Size | Meaning |
|---|---|---|
| 0 | 1 | Report ID = `0x00` |
| 1–3 | 3 | Command (`DB 03 xx`) |
| 4–8 | 5 | Header/arguments (see per-command notes) |
| 9–64 | 56 | Data payload |

The 9-byte header size is confirmed by the MP flasher: it starts filling data
at buffer offset 9 and zero-fills up to offset 64, giving 56 data bytes per
packet.

## Commands

The command is stored as a 32-bit little-endian word at offset 0, so the byte
sequence on the wire is `00 DB 03 xx`:

| Word | Bytes | Purpose |
|---|---|---|
| `0x00DB0304` | `00 DB 03 04` | Write MP (MCU) image |
| `0x00DB0302` | `00 DB 03 02` | Write DSP image |
| `0x00DB0312` | `00 DB 03 12` | Ready/version query |
| `0x00DB0315` | `00 DB 03 15` | Terminate / commit |
| `0x00DB0715` | `00 DB 07 15` | Terminate variant used by the styles path |

The update flow for a component is: ready query → one or more write packets →
terminating packet carrying the checksum → reboot.

## Ready query (`0x00DB0312`)

Packet as constructed by `FUN_004011d0`:

```
00 DB 03 12 00 03 00 00 00 0B 00 00 ... 00
```

Response validation:

* `response[2] == 0x13`
* `response[8] == 0x0B`
* `response[10]` = reported component version

Anything else is treated as an error (`return 6`), a timeout is
`return 0x0C`, and a short/zero read is `return 0x0C`.

## MP write packet (`0x00DB0304`)

From `FUN_00401d40`:

```
00 DB 03 04 00 38 00 00 00 <56 data bytes>
```

`0x3800` is written as a 16-bit value at offset 4. Its meaning is not confirmed
(possibly a flags/segment word); the encoder is otherwise straightforward, and
the payload is simply the file streamed in 56-byte chunks with the last packet
zero-padded.

The DSP path (`FUN_00401460`, command `0x00DB0302`) has the same shape with a
different header constant. The Ensemble and Styles paths use longer payloads and
their own terminating words.

## Integrity: checksums only, no signatures

* The app prints `Checksum = %8.8X` (32-bit) and `Checksum = %4.4X` (16-bit).
* The value is computed by the app in plain code and sent in the terminating
  packet.
* There is no public-key signature, no per-device key, no challenge-response,
  and no encrypted payload anywhere in the update path.

Practical consequence: a modified image only has to satisfy the same XOR
checksum and the bootloader's own sanity checks. This does **not** mean it is
safe — the bootloader may still validate the vector table, image length, or a
header field whose semantics are unknown.

## What is still unknown

* Exact checksum accumulation (XOR width/word order) — the debug format strings
  show the width but not the loop.
* Whether the bootloader enforces image length, entry-point range, or a header
  CRC in addition to the app-supplied checksum.
* Whether a failed update is recoverable without a hardware programmer. The
  stock updater can re-flash a stock image **if** the device still enumerates.
