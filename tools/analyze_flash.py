#!/usr/bin/env python3
"""Map a full SPI flash dump from a DigiTech Trio / Trio+.

The board uses a 16 MB Winbond W25Q128FVSG. A full dump contains the
bootloader, the MCU application, the DSP image, the style data and the
ensemble audio, so identifying the partitions is the fastest way to learn how
the update path and the boot process actually work.

Usage:
    tools/analyze_flash.py flash_dump.bin
    tools/analyze_flash.py flash_dump.bin --json > flash_map.json

Known vendor files are matched when present under firmware/ (run
tools/fetch_firmware.sh first). Detection also works without them, using
signatures embedded in the images.
"""

import argparse
import collections
import hashlib
import json
import math
import pathlib
import re
import struct
import sys

BLOCK = 4096

# The Trio+ MCU image is 40 KB and contains its device descriptor at 0x6520.
APP_DESCRIPTOR_OFFSET = 0x6520
APP_SIGNATURE = bytes.fromhex("12010002000000081012")  # bLength..idVendor

# Fallback for the exact image in this repository.
APP_HEAD = bytes.fromhex("b8160020d92e4000")


def entropy(data):
    if not data:
        return 0.0
    counts = collections.Counter(data)
    total = len(data)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def find_all(data, needle, limit=32):
    offsets = []
    start = 0
    while len(offsets) < limit:
        index = data.find(needle, start)
        if index < 0:
            break
        offsets.append(index)
        start = index + 1
    return offsets


def read_known(path):
    try:
        return pathlib.Path(path).read_bytes()
    except OSError:
        return None


def find_app(data):
    """Locate an MCU application image by its USB descriptor or reset vector."""
    found = []

    for descriptor in find_all(data, APP_SIGNATURE):
        base = descriptor - APP_DESCRIPTOR_OFFSET
        if base < 0:
            continue
        sp, reset = struct.unpack_from("<II", data, base)
        if 0x20000000 <= sp <= 0x20020000 and reset & 1 \
                and 0x400000 <= (reset & ~1) < 0x420000:
            found.append({
                "offset": base,
                "method": "usb descriptor signature",
                "sp": sp,
                "reset": reset,
            })

    for head in find_all(data, APP_HEAD):
        if all(entry["offset"] != head for entry in found):
            found.append({
                "offset": head,
                "method": "reset vector signature",
                "sp": struct.unpack_from("<I", data, head)[0],
                "reset": struct.unpack_from("<I", data, head + 4)[0],
            })

    return sorted(found, key=lambda entry: entry["offset"])


def flac_info(data, offset):
    """Parse a FLAC STREAMINFO block to report format and duration."""
    if data[offset:offset + 4] != b"fLaC":
        return None
    position = offset + 4
    info = {}
    while position + 4 <= len(data):
        header = data[position]
        last = header & 0x80
        block_type = header & 0x7F
        length = int.from_bytes(data[position + 1:position + 4], "big")
        if block_type == 0 and length >= 34:
            stream = data[position + 4:position + 4 + 34]
            bits = int.from_bytes(stream[10:18], "big")
            rate = bits >> 44
            channels = ((bits >> 41) & 0x07) + 1
            depth = ((bits >> 36) & 0x1F) + 1
            samples = bits & ((1 << 36) - 1)
            info = {
                "sample_rate": rate,
                "channels": channels,
                "bits": depth,
                "samples": samples,
                "seconds": round(samples / rate, 3) if rate else None,
            }
        position += 4 + length
        if last:
            break
    return info


def erased_blocks(data):
    states = []
    for offset in range(0, len(data), BLOCK):
        chunk = data[offset:offset + BLOCK]
        if chunk.count(0xFF) == len(chunk):
            states.append("erased")
        elif chunk.count(0x00) == len(chunk):
            states.append("zero")
        else:
            states.append("data")
    return states


def group_blocks(states):
    groups = []
    start = 0
    for index in range(1, len(states) + 1):
        if index == len(states) or states[index] != states[start]:
            groups.append({
                "offset": start * BLOCK,
                "length": (index - start) * BLOCK,
                "kind": states[start],
            })
            start = index
    return groups


def split_regions(groups, boundaries):
    """Split a region at known blob boundaries so partitions stay distinct."""
    result = []
    for group in groups:
        start = group["offset"]
        end = start + group["length"]
        cuts = sorted({start, end} | {b for b in boundaries if start < b < end})
        for left, right in zip(cuts, cuts[1:]):
            piece = dict(group)
            piece["offset"] = left
            piece["length"] = right - left
            result.append(piece)
    return result


def blob_needle(blob):
    """Pick a distinctive window so similar images do not cross-match.

    The two DSP loader files both start with thousands of "0x00" lines, so a
    prefix match would report the wrong product.
    """
    if len(blob) <= 512:
        return blob, 0
    for candidate in (len(blob) // 4, len(blob) // 2, len(blob) - 512):
        window = blob[candidate:candidate + 512]
        if window.count(0) + window.count(0xFF) < len(window) // 2:
            return window, candidate
    offset = len(blob) // 4
    return blob[offset:offset + 512], offset


def find_ascii_loader(data):
    """Find runs of ASCII DSP-loader lines, e.g. "0x00\\r\\n" repeated.

    A loader stream is thousands of adjacent lines, so each 64-line window
    overlaps its neighbours. Merge matches that are close together and report
    only the start of each run.
    """
    pattern = re.compile(rb"(?:0x[0-9A-Fa-f]{2}\r\n){64}")
    starts = []
    last_end = -1
    for match in pattern.finditer(data):
        if match.start() - last_end > 4096:
            starts.append(match.start())
        last_end = match.end()
    return starts[:16]


def analyze(data, firmware_dir):
    known = {
        "mp": ("Trio+ MP application", read_known(firmware_dir / "trioplus/TrioLooper_Update.bin")),
        "mp_orig": ("Trio MP application", read_known(firmware_dir / "orig/Trio_Update.bin")),
        "dsp": ("Trio+ DSP loader (ASCII)", read_known(firmware_dir / "trioplus/DSP1.ldr")),
        "dsp_orig": ("Trio DSP loader (ASCII)", read_known(firmware_dir / "orig/DSP1.ldr")),
        "styles": ("Trio+ style data", read_known(firmware_dir / "trioplus/TrioPlusStyleData.bin")),
        "ensemble": ("Trio+ ensemble audio", read_known(firmware_dir / "trioplus/EnsembleAudio.flac")),
    }

    hits = []
    for key, (label, blob) in known.items():
        if not blob:
            continue
        needle, needle_offset = blob_needle(blob)
        for position in find_all(data, needle):
            offset = position - needle_offset
            if offset < 0:
                continue
            hits.append({
                "offset": offset,
                "length": len(blob),
                "label": label,
                "key": key,
                "exact": data[offset:offset + len(blob)] == blob,
            })

    # One hit per offset, preferring an exact match.
    deduped = {}
    for hit in hits:
        previous = deduped.get(hit["offset"])
        if previous is None or (hit["exact"] and not previous["exact"]):
            deduped[hit["offset"]] = hit
    hits = sorted(deduped.values(), key=lambda item: item["offset"])

    # Signature-based fallbacks that do not need the vendor files.
    apps = find_app(data)
    flacs = []
    for offset in find_all(data, b"fLaC"):
        info = flac_info(data, offset)
        if info:
            flacs.append({"offset": offset, "info": info})
    loaders = find_ascii_loader(data)

    groups = group_blocks(erased_blocks(data))

    boundaries = set()
    for hit in hits:
        boundaries.add(hit["offset"])
        if hit["exact"]:
            boundaries.add(hit["offset"] + hit["length"])
    for app in apps:
        boundaries.add(app["offset"])
    for flac in flacs:
        boundaries.add(flac["offset"])
    for offset in loaders:
        boundaries.add(offset)

    groups = split_regions(groups, boundaries)
    for group in groups:
        chunk = data[group["offset"]:group["offset"] + group["length"]]
        group["entropy"] = max(0.0, round(entropy(chunk), 2)) \
            if group["kind"] == "data" else 0.0
        group["annotations"] = [
            hit["label"] for hit in hits if hit["offset"] == group["offset"]
        ]
        for app in apps:
            if app["offset"] == group["offset"]:
                group["annotations"].append("MP application (%s)" % app["method"])
        for flac in flacs:
            if flac["offset"] == group["offset"]:
                info = flac["info"]
                group["annotations"].append(
                    "FLAC %d Hz/%d ch/%d bit"
                    % (info["sample_rate"], info["channels"], info["bits"])
                )
        if group["offset"] in loaders:
            group["annotations"].append("ASCII DSP loader")

    return {
        "path": None,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "known_blobs": hits,
        "applications": apps,
        "flac": flacs,
        "ascii_loaders": loaders,
        "regions": groups,
    }


def human(report):
    print("flash image  %s" % report["path"])
    print("size         %d bytes (%s)" % (report["size"], human_size(report["size"])))
    print("sha256       %s" % report["sha256"])
    print()

    print("identified blobs")
    if not report["known_blobs"]:
        print("  (vendor files not found; run tools/fetch_firmware.sh for exact matching)")
    for hit in sorted(report["known_blobs"], key=lambda item: item["offset"]):
        state = "exact" if hit["exact"] else "partial"
        print("  0x%08X  %-32s %10s  %s"
              % (hit["offset"], hit["label"], human_size(hit["length"]), state))
    for app in report["applications"]:
        print("  0x%08X  %-32s %10s  SP 0x%08X reset 0x%08X"
              % (app["offset"], "MP application", "40 KB", app["sp"], app["reset"]))
    for flac in report["flac"]:
        info = flac["info"]
        print("  0x%08X  %-32s %10s  %d Hz, %d ch, %d bit, %.1f s"
              % (flac["offset"], "FLAC audio", "", info["sample_rate"],
                 info["channels"], info["bits"], info["seconds"] or 0))
    for offset in report["ascii_loaders"]:
        print("  0x%08X  %-32s %10s  (0xNN lines)" % (offset, "ASCII loader stream", ""))
    print()

    print("region map (4 KB blocks)")
    print("  %-10s %-10s %-8s %-6s %s" % ("start", "end", "size", "entropy", "contents"))
    for region in report["regions"]:
        if region["kind"] == "erased" and region["length"] < 64 * 1024:
            continue
        notes = ", ".join(region["annotations"])
        if region["kind"] == "erased":
            notes = notes or "erased (free)"
        elif region["kind"] == "zero":
            notes = notes or "zero-filled"
        else:
            notes = notes or "data"
        print("  0x%08X 0x%08X %-8s %-6.2f %s"
              % (region["offset"], region["offset"] + region["length"],
                 human_size(region["length"]), region["entropy"], notes))

    free = sum(region["length"] for region in report["regions"] if region["kind"] == "erased")
    print()
    print("erased: %s of %s (%.1f%% free)"
          % (human_size(free), human_size(report["size"]), 100.0 * free / report["size"]))


def human_size(value):
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return ("%d %s" % (value, unit)) if unit == "B" else ("%.1f %s" % (value, unit))
        value /= 1024.0
    return str(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=pathlib.Path)
    parser.add_argument("--firmware-dir", type=pathlib.Path, default=pathlib.Path("firmware"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    data = args.dump.read_bytes()
    if len(data) not in (16 * 1024 * 1024, 4 * 1024 * 1024, 8 * 1024 * 1024):
        print("warning: %d bytes is not a common SPI flash size" % len(data),
              file=sys.stderr)

    report = analyze(data, args.firmware_dir)
    report["path"] = str(args.dump)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
