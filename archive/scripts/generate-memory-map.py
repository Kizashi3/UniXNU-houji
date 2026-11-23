#!/usr/bin/env python3
"""Generate the houji UEFI map from this device's captured xbl_config FDT.

OEM HOB selector values are not EDK2's enum values. Translate explicitly and
reject an unfamiliar selector rather than copying the numeric fields into C.
"""
import argparse
import hashlib
from pathlib import Path
from fdt import cells, embedded, strings


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("input", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    data = args.input.read_bytes()
    records = []
    for _, _, root in embedded(data):
        for path, node in root.walk():
            if path not in {"/soc/memorymap", "/soc/registermap"}:
                continue
            for child in node.children:
                v = child.properties
                reg = cells(v["reg"])
                if len(reg) != 4:
                    raise ValueError("Unexpected memory geometry")
                label = strings(v["MemLabel"])[0]
                if not label or len(label) >= 32 or '"' in label:
                    raise ValueError("Invalid memory label")
                base = reg[0] << 32 | reg[1]
                size = reg[2] << 32 | reg[3]
                if not size or base % 4096 or size % 4096:
                    raise ValueError("Invalid memory alignment")
                hob = int.from_bytes(v["BuildHob"], "big")
                if hob == 9 and label == "NOMAP":
                    continue
                hob_name = {0: "AddMem", 4: "NoHob", 5: "AddDev", 10: "AddMem"}.get(hob)
                attr = int.from_bytes(v["CacheAttributes"], "big")
                attr_name = {2: "WRITE_BACK", 0x22: "WRITE_BACK_XN", 0x20: "WRITE_THROUGH_XN", 0x25: "UNCACHED_UNBUFFERED_XN", 9: "NS_DEVICE"}.get(attr)
                if hob_name is None or attr_name is None:
                    raise ValueError("Unqualified OEM map selector: " + label)
                resource = int.from_bytes(v["ResourceType"], "big")
                resource_attr = int.from_bytes(v["ResourceAttribute"], "big")
                mem_type = int.from_bytes(v["MemoryType"], "big")
                if hob == 10 and resource != 5:
                    raise ValueError("Unexpected protected region type")
                # Keep the first MiB of the stock FD reserved; this SM8650 shim
                # follows giulia's qualified A7100000/3MiB placement within it.
                if label == "UEFI_FD":
                    if (base, size) != (0xA7000000, 0x400000):
                        raise ValueError("Unexpected stock UEFI FD window")
                    # PlatformPeiLib finds OEM scheduler/DTB HOB callbacks by
                    # this exact region name. Keep its first MiB untouched.
                    records.append(("FD_Reserved", base, 0x100000, "AddMem", resource, resource_attr, 0, "WRITE_BACK"))
                    base, size = 0xA7100000, 0x300000
                records.append((label, base, size, hob_name, resource, resource_attr, mem_type, attr_name))
    labels = [x[0] for x in records]
    if len(set(labels)) != len(labels) or "Display_Reserved" not in labels:
        raise ValueError("Missing or duplicate map entries")
    display = next(x for x in records if x[0] == "Display_Reserved")
    if display[1:3] != (0xFC400000, 0x2B00000):
        raise ValueError("This revision is qualified only for the captured houji splash window")
    for i, left in enumerate(records):
        for right in records[i + 1:]:
            if max(left[1], right[1]) < min(left[1] + left[2], right[1] + right[2]):
                raise ValueError("Overlapping UEFI regions: " + left[0] + " / " + right[0])
    lines = ['// SPDX-License-Identifier: BSD-2-Clause-Patent', '// Generated from captured houji xbl_config, SHA256 ' + hashlib.sha256(data).hexdigest(), '#include <Library/MemoryMapLib.h>', '', 'STATIC EFI_MEMORY_REGION_DESCRIPTOR gMemoryDescriptor[] = {']
    for name, base, size, hob, resource, flags, mem, attr in records:
        lines.append(f'  {{"{name}", 0x{base:08X}, 0x{size:08X}, {hob}, {resource}, 0x{flags:X}, {mem}, {attr}}},')
    lines += ['};', '', 'VOID GetMemoryMap (OUT EFI_MEMORY_REGION_DESCRIPTOR **Map, OUT UINT8 *Count)', '{', '  *Map = gMemoryDescriptor;', '  *Count = ARRAY_SIZE (gMemoryDescriptor);', '}', '']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text('\n'.join(lines))
    print(f'{len(records)} non-overlapping memory regions -> {args.output}')


if __name__ == '__main__':
    main()
