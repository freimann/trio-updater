#!/bin/sh
# Read the W25Q128FVSG SPI flash of a Trio / Trio+ with a CH341A programmer.
#
# Safety:
#   * The flash is 3.3 V. Many CH341A clones put 5 V on the data lines; use a
#     3.3 V-modded programmer or a level shifter. Measure VCC before connecting
#     the chip.
#   * In-circuit reads work only if the MCU does not drive the SPI bus. Prefer
#     desoldering, or hold the MCU in reset. Always read twice and compare.
#
# Usage:  tools/dump_flash.sh [output.bin]
set -eu

OUT="${1:-trio_flash.bin}"

if ! command -v flashrom >/dev/null 2>&1; then
    echo "flashrom not found. Install it with:  brew install flashrom" >&2
    exit 1
fi

echo ">> read 1/2 -> $OUT.1"
flashrom -p ch341a_spi -r "$OUT.1"

echo ">> read 2/2 -> $OUT.2"
flashrom -p ch341a_spi -r "$OUT.2"

if cmp -s "$OUT.1" "$OUT.2"; then
    mv "$OUT.1" "$OUT"
    rm -f "$OUT.2"
    echo ">> stable read: $OUT"
else
    echo "!! reads differ - reseat the clip, lower the SPI clock, or desolder" >&2
    exit 2
fi

shasum -a 256 "$OUT"
echo
echo "Next: tools/analyze_flash.py $OUT"
