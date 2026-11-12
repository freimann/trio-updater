#!/usr/bin/env python3
"""Inspect a DigiTech Trio / Trio+ MCU firmware image.

The image is a raw, headerless ARM image mapped at 0x00400000. This script
prints the vector table, the embedded USB descriptors, the peripheral blocks
referenced by the code, and the erased tail.

Usage:
    tools/inspect_mp.py firmware/trioplus/TrioLooper_Update.bin
    tools/inspect_mp.py firmware/orig/Trio_Update.bin --json
"""

import argparse
import collections
import hashlib
import json
import pathlib
import struct
import sys

BASE = 0x400000

SYSTEM_HANDLERS = [
    "initial SP", "reset", "NMI", "hard fault", "memory manage",
    "bus fault", "usage fault", "reserved 7", "reserved 8", "reserved 9",
    "reserved 10", "SVCall", "debug monitor", "reserved 13", "PendSV", "SysTick",
]

PERIPHERALS = {
    0x40008000: ("SPI0 (DSP link)", 0x400),
    0x40034000: ("USB device (UDP)", 0x400),
    0x400E0E00: ("PIOA", 0x400),
    0x400E1400: ("RSTC / SUPC", 0x400),
    0x40090000: ("UART0", 0x400),
    0x40098000: ("UART1", 0x400),
    0x40084000: ("TWI0", 0x400),
    0x40080000: ("TC0", 0x400),
}


def peripheral_name(value):
    for base, (name, span) in PERIPHERALS.items():
        if base <= value < base + span:
            return name
    return ""


def u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def is_handler(value, image_end):
    """A plausible Thumb handler: zero, or an odd address inside the image."""
    if value == 0:
        return True
    if value & 1 == 0:
        return False
    return BASE <= (value & ~1) < image_end


def vectors(data):
    """System vectors plus IRQs, stopping at the first non-handler word.

    The words after the vector table are a USB descriptor pointer table, not
    handlers, so a fixed entry count would print garbage.
    """
    entries = [(index, u32(data, index * 4)) for index in range(16)]
    image_end = BASE + len(data)
    index = 16
    while index * 4 + 4 <= len(data):
        value = u32(data, index * 4)
        if not is_handler(value, image_end):
            break
        entries.append((index, value))
        index += 1
    return entries


def show_vectors(data):
    entries = vectors(data)
    default = collections.Counter(value for _, value in entries[16:] if value)
    filler = default.most_common(1)[0][0] if default else None

    print("vector table (%d entries: 16 system + %d IRQs)"
          % (len(entries), len(entries) - 16))
    for index, value in entries[:16]:
        name = SYSTEM_HANDLERS[index] if index < len(SYSTEM_HANDLERS) else "?"
        if value == 0:
            detail = "(unused)"
        elif index == 0:
            detail = "0x%08X" % value
        elif index == 1:
            detail = "0x%08X (Thumb entry 0x%08X)" % (value, value & ~1)
        elif value == filler:
            detail = "0x%08X (default handler)" % value
        else:
            detail = "0x%08X" % value
        print("  [%2d] %-15s %s" % (index, name, detail))

    irqs = [(index - 16, value) for index, value in entries[16:] if value]
    real = [(irq, value) for irq, value in irqs if value != filler]
    print("  IRQs: %d assigned, %d non-default" % (len(irqs), len(real)))
    for irq, value in real:
        print("    IRQ %-3d 0x%08X" % (irq, value))


def find_device_descriptor(data, vendor=0x1210):
    found = []
    start = 0
    while True:
        index = data.find(b"\x12\x01", start)
        if index < 0:
            break
        start = index + 1
        if index + 18 > len(data):
            continue
        if u16(data, index + 8) != vendor:
            continue
        found.append({
            "offset": index,
            "address": BASE + index,
            "vid": u16(data, index + 8),
            "pid": u16(data, index + 10),
            "bcd_usb": u16(data, index + 2),
            "bcd_device": u16(data, index + 12),
            "max_packet0": data[index + 7],
            "raw": data[index:index + 18].hex(),
        })
    return found


def find_config_descriptor(data):
    found = []
    start = 0
    while True:
        index = data.find(b"\x09\x02", start)
        if index < 0:
            break
        start = index + 1
        if index + 9 > len(data):
            continue
        total = u16(data, index + 2)
        if not 9 <= total <= 255 or index + total > len(data):
            continue
        interface = index + data[index]
        if data[interface + 1] != 0x04:
            continue
        found.append({
            "offset": index,
            "address": BASE + index,
            "total_length": total,
            "interfaces": data[index + 4],
            "interface_class": data[interface + 5],
            "interface_subclass": data[interface + 6],
            "interface_protocol": data[interface + 7],
            "endpoints": data[interface + 4],
            "raw": data[index:index + total].hex(),
        })
    return found


def find_hid_report_descriptor(data):
    found = []
    start = 0
    while True:
        index = data.find(b"\x06\xff\xff", start)
        if index < 0:
            break
        start = index + 1
        end = data.find(b"\xc0", index)
        if end < 0 or end - index > 256:
            continue
        found.append({
            "offset": index,
            "address": BASE + index,
            "length": end - index + 1,
            "raw": data[index:end + 1].hex(),
        })
    return found


def find_free_tail(data):
    last = max((i for i, byte in enumerate(data) if byte), default=-1)
    return {
        "last_nonzero_offset": last,
        "last_nonzero_address": BASE + last if last >= 0 else None,
        "free_bytes": len(data) - last - 1,
    }


def peripheral_references(data, start=0x100):
    """Recover peripheral addresses from movw/movt pairs and literal pools.

    Peripheral bases are almost never stored as literal 32-bit words; they are
    split across a MOVW/MOVT pair, so this needs a real Thumb decoder. Capstone
    is an optional dependency: without it the scan is skipped.
    """
    try:
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB
        from capstone.arm import ARM_OP_IMM, ARM_OP_MEM, ARM_OP_REG, ARM_REG_PC
    except ImportError:
        return None

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    md.detail = True

    found = []
    pending = {}
    offset = start
    while offset < len(data):
        insn = next(md.disasm(data[offset:offset + 4], BASE + offset, count=1), None)
        if insn is None:
            offset += 2
            continue
        operands = insn.operands
        if insn.mnemonic == "movw" and len(operands) == 2 \
                and operands[0].type == ARM_OP_REG and operands[1].type == ARM_OP_IMM:
            pending[insn.reg_name(operands[0].reg)] = operands[1].imm & 0xFFFF
        elif insn.mnemonic == "movt" and len(operands) == 2 \
                and operands[0].type == ARM_OP_REG and operands[1].type == ARM_OP_IMM:
            name = insn.reg_name(operands[0].reg)
            if name in pending:
                found.append((pending.pop(name) | ((operands[1].imm & 0xFFFF) << 16),
                              insn.address))
        elif insn.mnemonic == "ldr" and len(operands) == 2 \
                and operands[1].type == ARM_OP_MEM and operands[1].mem.base == ARM_REG_PC:
            address = insn.address + 4 + operands[1].mem.disp - BASE
            if 0 <= address <= len(data) - 4:
                found.append((u32(data, address), insn.address))
        offset += insn.size

    counts = collections.Counter()
    for value, _ in found:
        if 0x40000000 <= value < 0x40100000 or 0xE0000000 <= value < 0xE0100000:
            counts[value] += 1
    return [
        {
            "address": value,
            "hits": hits,
            "name": peripheral_name(value),
        }
        for value, hits in counts.most_common()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=pathlib.Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    data = args.image.read_bytes()
    report = {
        "path": str(args.image),
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "base": BASE,
        "device_descriptors": find_device_descriptor(data),
        "config_descriptors": find_config_descriptor(data),
        "hid_report_descriptors": find_hid_report_descriptor(data),
        "free_tail": find_free_tail(data),
        "peripherals": peripheral_references(data),
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    print("image    %s" % report["path"])
    print("size     %d bytes (0x%X)" % (report["size"], report["size"]))
    print("sha256   %s" % report["sha256"])
    print("base     0x%08X" % BASE)
    print()

    show_vectors(data)
    print()

    print("USB device descriptor(s)")
    for entry in report["device_descriptors"]:
        print("  @0x%05X / 0x%08X  VID 0x%04X PID 0x%04X  USB %X.%02X  dev %X.%02X  EP0 %d"
              % (entry["offset"], entry["address"], entry["vid"], entry["pid"],
                 entry["bcd_usb"] >> 8, entry["bcd_usb"] & 0xFF,
                 entry["bcd_device"] >> 8, entry["bcd_device"] & 0xFF,
                 entry["max_packet0"]))
        print("    %s" % entry["raw"])
    print()

    print("USB configuration descriptor(s)")
    for entry in report["config_descriptors"]:
        print("  @0x%05X / 0x%08X  length %d, %d interface(s)"
              % (entry["offset"], entry["address"], entry["total_length"],
                 entry["interfaces"]))
        print("    interface class 0x%02X subclass 0x%02X protocol 0x%02X"
              % (entry["interface_class"], entry["interface_subclass"],
                 entry["interface_protocol"]))
        print("    %s" % entry["raw"])
    print()

    print("HID report descriptor(s)")
    for entry in report["hid_report_descriptors"]:
        print("  @0x%05X / 0x%08X  %d bytes"
              % (entry["offset"], entry["address"], entry["length"]))
        print("    %s" % entry["raw"])
    print()

    free = report["free_tail"]
    print("erased tail")
    print("  last non-zero byte at 0x%05X (0x%08X)"
          % (free["last_nonzero_offset"], free["last_nonzero_address"]))
    print("  %d bytes free to end of image" % free["free_bytes"])
    print()

    print("peripheral constants (recovered from MOVW/MOVT and literal pools)")
    if report["peripherals"] is None:
        print("  capstone not installed - skipped (pip install capstone)")
    else:
        for entry in report["peripherals"][:20]:
            name = entry["name"] or "?"
            print("  0x%08X  x%-2d  %s" % (entry["address"], entry["hits"], name))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
