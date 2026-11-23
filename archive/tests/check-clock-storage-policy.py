#!/usr/bin/env python3
"""Test actual BSP policy C against a relocated PE, then its original ARM path."""
import argparse
import ctypes
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_X30, UC_ARM64_REG_X0


def relocated(source, base):
    data = bytearray(source)
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    optional = pe + 24
    assert struct.unpack_from('<Q', data, optional + 24)[0] == 0
    rva, size = struct.unpack_from('<II', data, optional + 112 + 5 * 8)
    offset = rva
    while offset < rva + size:
        page, length = struct.unpack_from('<II', data, offset)
        assert length >= 8 and length % 2 == 0 and offset + length <= rva + size
        for entry in range(offset + 8, offset + length, 2):
            value = struct.unpack_from('<H', data, entry)[0]
            kind, slot = value >> 12, page + (value & 0xfff)
            if kind == 0:
                continue
            assert kind == 10 and slot + 8 <= len(data)
            old = struct.unpack_from('<Q', data, slot)[0]
            struct.pack_into('<Q', data, slot, old + base)
        offset += length
    return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--uefi', type=Path, required=True)
    a = p.parse_args()
    source = a.source.read_bytes()
    assert hashlib.sha256(source).hexdigest() == 'f498e08bf978b36af750a3958c83b788d39f786069d31d6483d4df66d4ce69ba'
    header = a.uefi / 'Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe/ClockStoragePolicy.h'
    pe = struct.unpack_from('<I', source, 0x3c)[0]
    sections = pe + 24 + struct.unpack_from('<H', source, pe+20)[0]
    count = struct.unpack_from('<H', source, pe+6)[0]
    allowed = set(range(0x2bc50, 0x2bc5c))
    for slot in allowed:
        assert any((lambda row: row[1] <= slot < row[1] + row[0] and row[4] & 0x80000000)(
            (*struct.unpack_from('<IIII', source, sections+i*40+8), struct.unpack_from('<I', source, sections+i*40+36)[0])) for i in range(count))
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        c = root / 'policy.c'
        c.write_text('''#include <stdint.h>
typedef uint8_t UINT8; typedef uint32_t UINT32; typedef uint64_t UINT64;
typedef uintptr_t UINTN; typedef int BOOLEAN;
#define STATIC static
#define CONST const
#define TRUE 1
#define FALSE 0
''' + '#include "' + str(header) + '"\n' + '''
int apply(UINT8 *image, UINTN bytes, BOOLEAN enabled) { return ClockStoragePolicy(image,bytes,enabled); }
''')
        lib = root / 'policy.so'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', str(c), '-o', str(lib)], check=True)
        apply = ctypes.CDLL(str(lib)).apply
        apply.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        apply.restype = ctypes.c_int
        buf = ctypes.create_string_buffer(len(source))
        base = ctypes.addressof(buf)
        before = bytes(relocated(source, base))
        buf.raw = before
        assert apply(buf, len(source), 0) == 1 and buf.raw == before
        assert apply(buf, len(source), 1) == 1
        after = buf.raw
        assert after[0x2bc50:0x2bc5c] == bytes(12)
        assert all(x == y or i in allowed for i, (x, y) in enumerate(zip(before, after)))
        assert apply(buf, len(source), 1) == 0 and buf.raw == after
        for slot, fmt in ((0x2bc50, '<Q'), (0x2bc58, '<I'), (0x2bb98, '<Q'), (0x2bba0, '<Q')):
            bad = bytearray(before)
            struct.pack_into(fmt, bad, slot, 3)
            buf.raw = bytes(bad)
            assert apply(buf, len(source), 1) == 0 and buf.raw == bytes(bad)
        buf.raw = before
        assert apply(buf, len(source)-1, 1) == 0 and buf.raw == before
        assert apply(None, len(source), 1) == 0
        buf.raw = source
        assert apply(buf, len(source), 1) == 0 and buf.raw == source
    # Execute the original InitCESTA with the new absent-list policy. This
    # validates its actual NULL-list path without invoking camera/PCIe MMIO.
    load = 0x10000000
    image = relocated(source, load)
    image[0x2bc50:0x2bc5c] = bytes(12)
    struct.pack_into('<Q', image, 0x35818, load + 0x2bba8)
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(load, 0x40000)
    cpu.mem_write(load, bytes(image))
    cpu.mem_map(0x20000000, 0x10000)
    cpu.reg_write(UC_ARM64_REG_SP, 0x20008000)
    cpu.reg_write(UC_ARM64_REG_X30, 0x30000000)
    visited = []
    cpu.hook_add(UC_HOOK_CODE, lambda uc, pc, size, user: visited.append(pc-load))
    cpu.emu_start(load+0xa6f4, 0x30000000, count=60)
    assert cpu.reg_read(UC_ARM64_REG_X0) == 0
    assert 0xa82c in visited and 0xa840 in visited
    assert not any(pc in visited for pc in (0xa730, 0xa768, 0xa7a8, 0xa810))
    print(f'PASS: default unchanged; policy changes only 12 writable BSP bytes; mismatch/null/size/repeat guards reject without writes; original InitCESTA follows its absent-list return path in {len(visited)} ARM instructions.')


if __name__ == '__main__':
    main()
