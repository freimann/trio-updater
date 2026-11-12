#!/usr/bin/env python3
"""Inspect a DigiTech Trio+ `.tlsd` song file.

The `.tlsd` container is what the Trio+ writes to its SD card. It is a fixed
138,032-byte header followed by loop audio in 32 KB chunks. This tool prints
the header fields that are understood, the per-part lengths, and the audio
layout. It does not decode audio.

The offset names come from the community `Trio+Addresses.xlsx` and were
spot-checked against the sample files in `giveabit/Trio-Plus-Data`.

Usage:
    tools/tlsd_info.py song.tlsd
    tools/tlsd_info.py song.tlsd --json
"""

import argparse
import json
import pathlib
import struct
import sys

HEADER = 138032
CHUNK = 32768
RATE = 44100

# Little-endian 32-bit fields at the start of the header.
FIELDS = [
    (1192, "unknown_1192"),
    (1200, "unknown_1200"),
    (1208, "unknown_1208"),
    (1216, "part_block_size"),
    (1220, "reserved_audio"),
    (1224, "reserved_end"),
    (1232, "unknown_1232"),
    (1236, "unknown_1236"),
    (1240, "header_end"),
    (1248, "part_end_1"),
    (1256, "part_end_2"),
    (1264, "part_end_3"),
    (1272, "part_end_4"),
    (1300, "part_len_1"),
    (1304, "part_len_2"),
    (1308, "part_len_3"),
    (1312, "part_len_4"),
    (1316, "part_len_5"),
    (1320, "file_size_minus_1192"),
]

NAME_OFFSET = 1332
NAME_LENGTH = 128
LAST_PART_OFFSET = 17904
PART_INFO_BASE = 2352
PART_INFO_SIZE = 16384


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def read_name(data):
    raw = data[NAME_OFFSET:NAME_OFFSET + NAME_LENGTH].split(b"\0")[0]
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", "replace")


def first_audio_chunk(data):
    """Return (offset, silent) for the first 32 KB chunk that is not empty.

    Audio starts at 138,032 when overdubs exist, and at 170,800 when the first
    32 KB block is still silent. An all-zero song has no audio at all.
    """
    for offset in range(HEADER, len(data), CHUNK):
        chunk = data[offset:offset + CHUNK]
        if chunk.count(0) + chunk.count(0xFF) < len(chunk):
            return offset, False
    return HEADER, True


def analyze(data):
    if len(data) < HEADER:
        raise ValueError("file is smaller than the 138,032-byte header")

    fields = {name: u32(data, offset) for offset, name in FIELDS}

    # Parts are five consecutive dwords; 0x514 is the first one.
    parts = [u32(data, 1300 + 4 * index) for index in range(5)]
    part_seconds = [round(value / RATE, 4) if value else 0.0 for value in parts]

    audio_start = HEADER if any(parts[1:]) else 170800
    if len(data) <= HEADER:
        audio_start = HEADER
        audio = 0
        silent = True
    else:
        audio = len(data) - HEADER
        audio_start, silent = first_audio_chunk(data)

    # The empty templates are exactly 16 beats long. If part 1 behaves like a
    # whole 16-beat song, its length in samples implies the tempo. This is an
    # inference, not a stored BPM field.
    tempo_hint = None
    if parts[0]:
        tempo_hint = round(16.0 * 60.0 * RATE / parts[0], 2)

    return {
        "size": len(data),
        "name": read_name(data),
        "fields": fields,
        "parts": [
            {"length": value, "seconds": seconds, "chunks": round(value / CHUNK, 3)}
            for value, seconds in zip(parts, part_seconds)
        ],
        "part_1_16_beat_tempo": tempo_hint,
        "audio_bytes": audio,
        "audio_start": audio_start,
        "silent": silent,
        "chunks": round(audio / CHUNK, 3) if audio else 0,
        "last_part_flag": data[LAST_PART_OFFSET] if len(data) > LAST_PART_OFFSET else None,
    }


def human(report):
    print("file         %s" % report["path"])
    print("size         %d bytes" % report["size"])
    print("song name    %s" % (report["name"] or "(empty)"))
    print("audio        %d bytes at 0x%X (%s chunks of 32 KB)"
          % (report["audio_bytes"], report["audio_start"], report["chunks"]))
    if report["silent"]:
        print("             no non-zero audio chunks (song carries no audio)")
    print()

    print("header fields")
    for offset, name in FIELDS:
        value = report["fields"][name]
        print("  0x%04X  %-22s %10d" % (offset, name, value))
    print()

    print("parts")
    for index, part in enumerate(report["parts"], 1):
        state = "empty" if part["length"] == 0 else ""
        print("  part %d  %10d samples  %9.3f s  %7.3f chunks  %s"
              % (index, part["length"], part["seconds"], part["chunks"], state))

    hint = report["part_1_16_beat_tempo"]
    if hint:
        print()
        print("part 1 as 16 beats -> %.2f BPM (inference; tempo is not a stored BPM field)" % hint)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    data = args.file.read_bytes()
    try:
        report = analyze(data)
    except ValueError as error:
        print("error: %s" % error, file=sys.stderr)
        return 1
    report["path"] = str(args.file)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
