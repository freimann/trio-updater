#!/usr/bin/env python3
"""Decode a DigiTech DSP loader file (DSP1.ldr) into a raw binary image.

The vendor ships the DSP image as CRLF-separated ASCII lines, each containing a
byte as "0xNN". That is 6 bytes of text per byte of payload, which is why the
Trio+ DSP file is 4.3 MB but only 711 KB decoded.

Usage:
    tools/dsp_ldr_to_bin.py firmware/trioplus/DSP1.ldr
    tools/dsp_ldr_to_bin.py firmware/trioplus/DSP1.ldr -o out.bin
"""

import argparse
import hashlib
import pathlib
import re
import sys

LINE = re.compile(rb"^0x([0-9A-Fa-f]{2})$")


def decode(raw: bytes) -> bytes:
    out = bytearray()
    bad = []
    for number, line in enumerate(raw.split(b"\n"), 1):
        line = line.rstrip(b"\r")
        if not line:
            continue
        match = LINE.match(line)
        if not match:
            bad.append((number, line[:32]))
            continue
        out.append(int(match.group(1), 16))
    if bad:
        for number, sample in bad[:10]:
            print(f"line {number}: unexpected content {sample!r}", file=sys.stderr)
        raise SystemExit(f"{len(bad)} malformed line(s); refusing to write output")
    return bytes(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("-o", "--output", type=pathlib.Path)
    args = parser.parse_args()

    raw = args.input.read_bytes()
    data = decode(raw)
    output = args.output or args.input.with_suffix(".bin")
    output.write_bytes(data)

    print(f"decoded {args.input} -> {output}")
    print(f"  text   {len(raw):>10,} bytes")
    print(f"  binary {len(data):>10,} bytes")
    print(f"  sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
