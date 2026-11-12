#!/bin/sh
# Download the vendor Trio/Trio+ firmware artifacts and verify them.
#
# The images are NOT redistributed in this repository (DigiTech/Harman
# copyright), so this script pulls them from the original vendor URLs listed in
# the update manifest.
#
# Usage:  tools/fetch_firmware.sh
#         MANIFEST_URL=http://... tools/fetch_firmware.sh
set -eu

cd "$(dirname "$0")/.."

MANIFEST_URL="${MANIFEST_URL:-http://harmandbx.blob.core.windows.net/digi-trio-plus/tp-manifest.xml}"
MANIFEST="reference/tp-manifest.xml"

mkdir -p reference firmware/trioplus firmware/orig

if [ ! -f "$MANIFEST" ]; then
    echo ">> fetching manifest"
    curl -fsSL --max-time 60 -o "$MANIFEST" "$MANIFEST_URL"
fi
echo ">> manifest: $MANIFEST ($(shasum -a 256 "$MANIFEST" | cut -d' ' -f1))"

# Extract <Component ... URL="..."/> entries into "url<TAB>target" pairs.
python3 - "$MANIFEST" <<'PY' > /tmp/trio-fetch-list.$$
import re
import sys
import os

xml = open(sys.argv[1], "r", encoding="utf-8", errors="replace").read()
seen = set()
for m in re.finditer(r'URL="([^"]+)"', xml):
    url = m.group(1)
    if url in seen:
        continue
    seen.add(url)
    base = url.rsplit("/", 1)[-1]
    # Keep the vendor's product folder so both DSP images can coexist.
    parts = url.split("/")
    product = parts[-2] if len(parts) >= 2 else ""
    if product == "TrioPlus":
        target = os.path.join("firmware/trioplus", base)
    elif product == "OriginalTrio":
        target = os.path.join("firmware/orig", base)
    elif base.lower().startswith("trio") and base.lower().endswith((".exe", ".dmg")):
        # Updater installers: skip, this repository is about firmware.
        continue
    else:
        print("skip (unknown product): %s" % url, file=sys.stderr)
        continue
    print("%s\t%s" % (url, target))
PY

LIST=/tmp/trio-fetch-list.$$
trap 'rm -f "$LIST"' EXIT

if [ ! -s "$LIST" ]; then
    echo "!! no firmware URLs found in manifest" >&2
    exit 1
fi

# Quote the URL: the vendor serves a file with spaces in its name.
while IFS="$(printf '\t')" read -r url target; do
    if [ -f "$target" ]; then
        echo ">> have $target"
        continue
    fi
    echo ">> GET $url"
    curl -fsSL --max-time 300 --retry 2 -o "$target.part" "$url"
    mv "$target.part" "$target"
done < "$LIST"

# Decode the ASCII DSP loader image so the checksum file validates fully.
if [ -f firmware/trioplus/DSP1.ldr ]; then
    tools/dsp_ldr_to_bin.py firmware/trioplus/DSP1.ldr \
        -o firmware/trioplus/DSP1.bin
fi

echo
echo ">> verifying SHA-256"
grep -E '  (firmware|reference)/' reference/artifacts.sha256 | shasum -a 256 -c -
