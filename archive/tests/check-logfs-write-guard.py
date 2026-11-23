#!/usr/bin/env python3
"""Test the actual C write boundary and actual OEM WRITE(10) request builder."""
import argparse
import ctypes
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn.arm64_const import (UC_ARM64_REG_SP, UC_ARM64_REG_PC,
    UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
    UC_ARM64_REG_X4, UC_ARM64_REG_X5)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uefi', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    a = p.parse_args()
    original = a.source.read_bytes()
    assert hashlib.sha256(original).hexdigest() == '80a0b88654b2c962c95031723d08c9e2c2d90b86807636e3e0118f43ed2fc4a1'
    header = a.uefi / 'Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe/UfsLogWriteGuard.h'
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / 'guard.c'
        source.write_text('''#include <stdint.h>
typedef uint8_t UINT8; typedef uint32_t UINT32; typedef uintptr_t UINTN;
typedef int BOOLEAN;
#define STATIC static
#define CONST const
#define TRUE 1
#define FALSE 0
''' + '#include "' + str(header) + '"\n' + '''
int allowed(const UINT8 *r,UINTN n,int armed) {return UfsLogWriteAllowed(r,n,armed);}
''')
        so = root / 'guard.so'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', str(source), '-o', str(so)], check=True)
        lib = ctypes.CDLL(str(so))
        lib.allowed.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
        def allowed(r, armed=True, size=0xc8):
            return bool(lib.allowed(ctypes.create_string_buffer(bytes(r)), size, armed))
        def request(lba, blocks):
            r = bytearray(0xc8); r[1] = 1; r[0x48] = 1; r[0x49] = 0x20
            r[0x5c] = 0x2a
            struct.pack_into('>I', r, 0x5e, lba)
            struct.pack_into('>H', r, 0x63, blocks)
            struct.pack_into('<I', r, 0x54, blocks * 4096)
            struct.pack_into('<I', r, 0x88, blocks * 4096)
            return r
        cases = 0
        for lba in (*range(0x2000), 0xffffffff):
            for blocks in (0, 1, 2, 0x800, 0x801, 0xffff):
                r = request(lba, blocks)
                wanted = 0x1000 <= lba < 0x1800 and 0 < blocks <= 0x1800-lba
                assert allowed(r) == wanted, (lba, blocks)
                assert not allowed(r, False)
                cases += 2
        good = request(0x1000, 1)
        for field in (1, 5, 0x48, 0x49, 0x4a, 0x5c, 0x5d, 0x62, 0x65, 0x6c):
            for value in range(256):
                r = bytearray(good); r[field] = value
                wanted = value == good[field] or (field == 0x5d and value == 8)
                assert allowed(r) == wanted, (hex(field), value)
                cases += 1
        for field in (*range(0x54, 0x58), *range(0x88, 0x8c), *range(0x66, 0x6c)):
            r = bytearray(good); r[field] ^= 1
            assert not allowed(r)
        assert not lib.allowed(None, 0xc8, 1)
        for size in (0, 0x88, 0xc7): assert not allowed(good, size=size)
        flush = bytearray(0xc8); flush[0x48] = 1; flush[0x5c] = 0x35
        assert allowed(flush) and not allowed(flush, False)
        for field in (1, 5, 0x49, 0x4a, *range(0x5d, 0x6d), 0x54, 0x88):
            r = bytearray(flush); r[field] = 1
            assert not allowed(r), hex(field)
        # Run the pinned actual WRITE builder through actual f6bc/12618 and
        # 1180c prologue, stopping before the guard's original instruction.
        for lba, blocks, fua, asynchronous, wanted in (
            (0x1000, 1, 0, 0, True), (0x17ff, 1, 1, 0, True),
            (0xfff, 1, 0, 0, False), (0x17ff, 2, 0, 0, False),
            (0x1800, 1, 0, 0, False),
        ):
            load, stack, trl, data = 0x10000000, 0x20000000, 0x30000000, 0x40000000
            cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
            cpu.mem_map(load, 0x30000); cpu.mem_write(load, original)
            for address in (stack, trl, data): cpu.mem_map(address, 0x10000)
            handle, ctl = load + 0x22978, load + 0x22ac0
            cpu.mem_write(handle, struct.pack('<QBBBBI', ctl, 0xf0, 0, 0, 0, 0x105189ab))
            cpu.mem_write(ctl + 0x10, struct.pack('<Q', trl))
            cpu.mem_write(ctl + 0x20, struct.pack('<Q', trl))
            cpu.mem_write(ctl + 0x4c4, bytes([fua]))
            cpu.reg_write(UC_ARM64_REG_SP, stack + 0x8000)
            for reg, value in ((UC_ARM64_REG_X0, handle), (UC_ARM64_REG_X1, data),
                (UC_ARM64_REG_X2, lba), (UC_ARM64_REG_X3, blocks),
                (UC_ARM64_REG_X4, data if asynchronous else 0), (UC_ARM64_REG_X5, 0)):
                cpu.reg_write(reg, value)
            cpu.emu_start(load + 0xc1d4, load + 0x11834, count=10000)
            assert cpu.reg_read(UC_ARM64_REG_PC) == load + 0x11834
            r = bytes(cpu.mem_read(cpu.reg_read(UC_ARM64_REG_X1), 0xc8))
            assert allowed(r) == wanted, r.hex()
            assert not allowed(r, False)
            print('OEM builder:', hex(lba), blocks, 'FUA', fua, 'async', asynchronous, 'allowed', wanted)
        print(f'PASS: {cases} C cases, request length consistency, zero-count/overflow/other-LUN refusal, exact flush, and 5 actual ARM WRITE request builders. No hardware write claimed.')


if __name__ == '__main__': main()
