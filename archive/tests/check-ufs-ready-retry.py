#!/usr/bin/env python3
"""Check exact Sense gating, failure propagation, real OEM Active CDB and BL."""
import argparse
import ctypes
import hashlib
from pathlib import Path
import struct
import subprocess
import tempfile

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn.arm64_const import (UC_ARM64_REG_SP, UC_ARM64_REG_X0,
                                UC_ARM64_REG_X1, UC_ARM64_REG_X30,
                                UC_ARM64_REG_PC)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--uefi', type=Path, required=True)
    a = p.parse_args()
    original = a.source.read_bytes()
    assert hashlib.sha256(original).hexdigest() == '80a0b88654b2c962c95031723d08c9e2c2d90b86807636e3e0118f43ed2fc4a1'
    header = a.uefi / 'Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe/UfsReadyRetry.h'
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        c = root / 'retry.c'
        c.write_text('''#include <stdint.h>
typedef uint8_t UINT8; typedef uint32_t UINT32; typedef uint64_t UINT64;
typedef int32_t INT32; typedef uintptr_t UINTN; typedef int BOOLEAN;
#define STATIC static
#define CONST const
#define VOID void
#define EFIAPI
#define TRUE 1
#define FALSE 0
''' + '#include "' + str(header) + '"\n' + '''
int needs(const UINT8 *s, UINTN n) { return UfsSenseNeedsActive(s,n); }
int valid(UINT64 b, UINT64 n, UINT64 h) { return UfsReadyHandleValid(b,n,h); }
INT32 retry(UINTN h,const UINT8 *s,HOUJI_UFS_READY_FN r,HOUJI_UFS_POWER_FN p) {
  return UfsReadyRetry(h,s,r,p,0);
}
''')
        so = root / 'retry.so'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', str(c), '-o', str(so)], check=True)
        lib = ctypes.CDLL(str(so))
        lib.needs.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        lib.valid.argtypes = [ctypes.c_uint64] * 3
        sense = bytearray.fromhex('700002000000000a0000000004020000')
        assert lib.needs(ctypes.create_string_buffer(bytes(sense)), 16)
        assert not lib.needs(None, 16)
        assert not lib.needs(ctypes.create_string_buffer(bytes(sense)), 13)
        for field, wanted in ((2, 2), (12, 4), (13, 2)):
            for value in range(256):
                s = bytearray(sense); s[field] = value
                expect = (value & 15) == wanted if field == 2 else value == wanted
                assert bool(lib.needs(ctypes.create_string_buffer(bytes(s)), 16)) == expect
        image = ctypes.create_string_buffer(0x25000)
        base = ctypes.addressof(image); handle = base + 0x22978
        h = struct.pack('<QBBBBI', base + 0x22ac0, 0xf0, 0, 0xd0, 0, 0x105189ab)
        ctypes.memmove(handle, h, 16)
        assert lib.valid(base, 0x25000, handle)
        for invalid in (base, handle + 1, base + 0x22ab8, base + 0x25000):
            assert not lib.valid(base, 0x25000, invalid)
        for offset in (0, 8, 9, 10, 12):
            bad = bytearray(h); bad[offset] ^= 1
            ctypes.memmove(handle, bytes(bad), 16)
            assert not lib.valid(base, 0x25000, handle)
        ctypes.memmove(handle, h, 16)
        assert not lib.valid(base, 0x24fff, handle)
        ready_type = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_size_t)
        power_type = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_size_t, ctypes.c_uint32)
        lib.retry.argtypes = [ctypes.c_size_t, ctypes.c_void_p, ready_type, power_type]
        lib.retry.restype = ctypes.c_int32
        # Sense is written by Ready during the call, then read by actual C.
        for first, scsi_sense, power_result, second, expected, expected_calls in (
            (0, sense, 0, 0, 0, ['ready']),
            (-5, bytes(16), 0, 0, -5, ['ready']),
            (-5, sense, 0, 0, 0, ['ready', 'active1', 'ready']),
            (-5, sense, -6, 0, -6, ['ready', 'active1']),
            (-5, sense, 0, -10, -10, ['ready', 'active1', 'ready']),
        ):
            buf = ctypes.create_string_buffer(16)
            calls = []

            @ready_type
            def ready(h):
                assert h == 123
                is_first = not calls
                calls.append('ready')
                ctypes.memmove(buf, bytes(scsi_sense), 16)
                return first if is_first else second

            @power_type
            def power(h, mode):
                assert h == 123 and mode == 1
                calls.append('active1')
                return power_result

            assert lib.retry(123, buf, ready, power) == expected
            assert calls == expected_calls, calls
    # Execute original CB78 through its actual CDB builder, stopping at the
    # common SCSI routine. This verifies the active field is 0x10, not 0x01.
    load, stack = 0x10000000, 0x20000000
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(load, 0x30000); cpu.mem_write(load, original)
    cpu.mem_map(stack, 0x10000)
    handle = load + 0x22978
    cpu.mem_write(handle, struct.pack('<QBBBBI', load + 0x22ac0, 0xf0, 0, 0xd0, 0, 0x105189ab))
    cpu.reg_write(UC_ARM64_REG_SP, stack + 0x8000)
    cpu.reg_write(UC_ARM64_REG_X0, handle)
    cpu.reg_write(UC_ARM64_REG_X1, 1)
    cpu.emu_start(load + 0xcb78, load + 0xf6bc, count=2000)
    assert cpu.reg_read(UC_ARM64_REG_PC) == load + 0xf6bc
    cdb = bytes(cpu.mem_read(cpu.reg_read(UC_ARM64_REG_X1), 16))
    context = bytes(cpu.mem_read(cpu.reg_read(UC_ARM64_REG_X0), 0x18))
    assert cdb == bytes.fromhex('1b000000100000000000000000000000'), cdb.hex()
    assert context[8:10] == b'\xd0\x00'
    cpu.reg_write(UC_ARM64_REG_X0, handle)
    cpu.emu_start(load + 0xb008, load + 0xca4c, count=1)
    assert cpu.reg_read(UC_ARM64_REG_X30) == load + 0xb00c
    assert cpu.reg_read(UC_ARM64_REG_X0) == handle
    print('PASS: exact Sense gating, pinned handle validation, success/failure callback order, original Active CDB 0x10 and BL link semantics. Hardware power transition remains untested.')


if __name__ == '__main__':
    main()
