# SD card and `.tlsd` song files

The Trio+ stores songs and loops on a removable **microSDHC** card (Class 10,
8–32 GB, up to 12 songs). Each song is a `.tlsd` file: a fixed 138,032-byte
header followed by loop audio in 32 KB chunks. This format is not documented by
DigiTech; the offsets below come from the community spreadsheet
`Trio+Addresses.xlsx` in
[`giveabit/Trio-Plus-Data`](https://github.com/giveabit/Trio-Plus-Data) and
were checked against the sample files in that repository.

> `.tlsd` is the extension used by the Trio+ tools. Some older notes write
> `.tsld`; they mean the same container.

## Layout

| Region | Offset | Size | Contents |
|---|---|---|---|
| Header | `0x00000` | 138,032 B | Song name, part lengths, per-part settings |
| Per-part blocks | `0x00930` | 5 × 16,384 B | DSP/looper state per part |
| Audio | `0x21B30` | n × 32,768 B | 16-bit mono PCM at 44.1 kHz |

`0x21B30` is 138,032. The first audio chunk is often silent (all zero) because
the looper reserves it; `0x29B30` (170,800) is the first chunk with signal in
the no-overdub sample files, while an overdubbed song starts at `0x21B30`.

```
0x00000  +----------------------------+
         | header (138,032 bytes)     |
0x00930  | 5 x 16 KB part blocks      |
0x14930  |                            |
0x21B30  +----------------------------+
         | 32 KB audio chunk 1        |
0x29B30  | 32 KB audio chunk 2        |
         | ...                        |
EOF      +----------------------------+
```

## Header fields

All values are little-endian. The "offset" column is decimal, matching the
spreadsheet.

| Offset | Hex | Meaning | Observed value |
|---|---|---|---|
| 1192 | `0x4A8` | unknown | 136 |
| 1200 | `0x4B0` | unknown | 1024 |
| 1208 | `0x4B8` | unknown | 1160 |
| 1216 | `0x4C0` | per-part block size | 16384 |
| 1220 | `0x4C4` | reserved for part blocks | 81920 (5 × 16384) |
| 1224 | `0x4C8` | reserved + 1160 | 83080 |
| 1232 | `0x4D0` | unknown | 10752 |
| 1236 | `0x4D4` | unknown | 53760 |
| 1240 | `0x4D8` | header end for size arithmetic | 136840 (138032 − 1192) |
| 1248 | `0x4E0` | end of part 1, 64-bit | see below |
| 1256 | `0x4E8` | end of part 2, 64-bit | |
| 1264 | `0x4F0` | end of part 3, 64-bit | |
| 1272 | `0x4F8` | end of part 4, 64-bit | |
| 1300 | `0x514` | part 1 length in samples | |
| 1304 | `0x518` | part 2 length in samples | |
| 1308 | `0x51C` | part 3 length in samples | |
| 1312 | `0x520` | part 4 length in samples | |
| 1316 | `0x524` | part 5 length in samples | |
| 1320 | `0x528` | file size − 1192 | matches `len(file) - 1192` |
| 1328 | `0x530` | marker `0x00000303` | constant |
| 1332 | `0x534` | song name, NUL-terminated | 128-byte field |

Part end values are absolute file offsets and follow:

```
part_end[n] = 138032 + sum(part_len[0..n]) - 1192
```

For a one-part song, `part_len[0]` equals `len(file) - 138032`, and all part
ends equal `len(file) - 1192`.

## Per-part blocks

Five 16 KB blocks start at `0x930` (2352), at `2352 + 16384 × part`. The fields
mapped so far sit at a fixed offset inside each block:

| Offset in block | Meaning | Encoding |
|---|---|---|
| +15552 | last used part (block 1) | 0–4 |
| +15560 | bass mode | 0 active, 1 simple root, 3 root riff |
| +15564 | genre | 0 blues, 1 R&B, 2 rock, … |
| +16160 | style | 0 = 1, 1 = 2, 2 = 3, … |
| +16244 | alternate time | 0 off, 1 on |

These fields are provisional. They vary as expected between the sample songs
but have not been verified by changing one setting at a time on hardware.

## Tempo is not stored as BPM

This is the important finding for the MIDI-clock work.

The header has **no BPM field**. It stores each part's length in samples at
44.1 kHz. The tempo is implied by that length, the meter, and the number of
bars. The community "no audio" test files make this easy to check: each is a
single 16-beat part, so

```
BPM = 16 × 60 × 44100 / part_len[0]
```

| File | `part_len[0]` | Derived BPM |
|---|---|---|
| `Song C1 @68.6.tlsd` | 617,472 | 68.56 |
| `Song C2 @72.0.tlsd` | 587,776 | 72.03 |
| `Song C3 @71.9.tlsd` | 588,800 | 71.90 |
| `Song D1 @70.0.tlsd` | 605,184 | 69.96 |
| `Song D2 @74.0.tlsd` | 572,416 | 73.96 |

The derived values match the BPM in the filenames to the displayed precision.
But the formula only works because those files are exactly 16 beats. For a
normal song the file records how long the loop is, not what tempo the player
used. Nothing in the header changes continuously while the tempo knob moves.

Consequences:

* Reading the SD card tells you the **result** of the tempo (loop length), not
  the live musical timebase.
* A clock generator cannot poll the SD file for tempo changes; the card is only
  written when a song is saved.
* This reinforces the plan in [midi-clock.md](midi-clock.md): capture the SPI
  link or the USB HID traffic, or bridge the tempo on the host. Do not build a
  clock around the `.tlsd` header.

## Audio format

The owner's manual specifies the performance and looper engines as **24-bit /
44.1 kHz**, but the sample files decode as **16-bit signed mono PCM at
44.1 kHz**. The consistent reading is that the DSP runs at 24-bit and the SD
container stores a 16-bit copy; do not use the file format to infer the ADC or
DSP resolution. Audio is stored in 32 KB chunks, and an overdub can overwrite
the silent chunks that the looper reserved.

The manual's loop limit is **230 seconds per song part**, based on 50 BPM and
48 bars in 4/4. That matches the largest part lengths seen in the header and is
a useful sanity check when parsing unknown files.

There are no standard MIDI messages in the header, only the binary settings and
sample counts above.

## Tool

```sh
tools/tlsd_info.py song.tlsd
tools/tlsd_info.py song.tlsd --json
```

The tool prints the understood header fields, per-part lengths, where the first
non-silent audio chunk starts, and the inferred 16-beat tempo. It does not
decode audio; `The_Trio+_Tool.py` in the community repository does that.
