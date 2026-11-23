#!/usr/bin/env python3
"""Create a pinned, explicitly restricted OEM UFS diagnostic copy, never flash it."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

ORIGINAL_SHA = '80a0b88654b2c962c95031723d08c9e2c2d90b86807636e3e0118f43ed2fc4a1'
# All ordinary LUN interfaces have been installed before 4a9c. Branch to the
# existing success epilogue, omitting RPMB opening, listeners, timers, protocol
# notifications, sleep registration and vendor automatic log hooks.
PATCHES = (
    (0x4a9c, 0xf00000a0, 0x14000000 | (((0x4650 - 0x4a9c) // 4) & 0x3ffffff), 'end after ordinary LUN enumeration'),
    (0x11834, 0xb9408828, 0xd4290a00, 'command allowlist BRK, handler mandatory'),
    (0xb008, 0x94000691, 0xd4290a40, 'conditional Active retry for exact NOT READY 02/04/02; normal-context thunk'),
)


def patch(data):
    if hashlib.sha256(data).hexdigest() != ORIGINAL_SHA:
        raise ValueError('Unexpected original UFSDxe SHA256')
    b = bytearray(data)
    for rva, expected, replacement, _ in PATCHES:
        if struct.unpack_from('<I', b, rva)[0] != expected:
            raise ValueError(f'Original opcode differs at {rva:x}')
        struct.pack_into('<I', b, rva, replacement)
    return bytes(b)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    b = patch(a.input.read_bytes())
    if a.output.exists():
        raise ValueError('Refuse to replace an existing diagnostic copy')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(b)
    record = {'original_sha256': ORIGINAL_SHA, 'sha256': hashlib.sha256(b).hexdigest(),
              'bytes': len(b), 'requires_houji_command_guard': True,
              'patches': [{'rva': hex(r), 'original': hex(o), 'replacement': hex(n), 'purpose': s}
                          for r, o, n, s in PATCHES], 'hardware_tested': False}
    a.output.with_suffix('.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
