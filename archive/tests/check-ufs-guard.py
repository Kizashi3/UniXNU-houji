#!/usr/bin/env python3
"""Execute the actual C allowlist and original AArch64 prologue/epilogue.

Host stubs test policy only; Unicorn tests register/stack restoration against
the pinned PE. Neither is hardware or DMA validation.
"""
import argparse
import ctypes
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm64_const import (UC_ARM64_REG_SP, UC_ARM64_REG_PC,
                                UC_ARM64_REG_X0, UC_ARM64_REG_X1,
                                UC_ARM64_REG_X8, UC_ARM64_REG_X19,
                                UC_ARM64_REG_X29, UC_ARM64_REG_X30,
                                UC_ARM64_REG_NZCV)


def nop_flow(image, lib, guarded=False, complete=True, response=0x20):
    """Execute the real retry/NOP/submit/wait/parser/cleanup ARM call chain.

    Model only the host-controller register transitions and NOP-IN DMA reply.
    Cache/barrier/delay calls use host no-ops; no driver error or completion
    function is stubbed. This cannot model real hardware timing or coherency.
    """
    load, stack, stop = 0x10000000, 0x20000000, 0x30000000
    handle, controller, mmio, trl = 0x21000000, 0x22000000, 0x23000000, 0x24000000
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(load, 0x30000); cpu.mem_write(load, image)
    for address in (stack, handle, controller, mmio, trl, stop):
        cpu.mem_map(address, 0x10000)
    cpu.mem_write(handle, struct.pack('<Q', controller))
    cpu.mem_write(controller + 8, struct.pack('<QQ', mmio, trl))
    cpu.mem_write(controller + 0x20, struct.pack('<Q', trl))
    cpu.mem_write(controller + 0x4c0, struct.pack('<I', 3))
    cpu.mem_write(mmio + 0x4060, struct.pack('<I', 1))
    sp = stack + 0x8000
    cpu.reg_write(UC_ARM64_REG_SP, sp)
    cpu.reg_write(UC_ARM64_REG_X0, handle)
    cpu.reg_write(UC_ARM64_REG_X19, 0x19191919)
    cpu.reg_write(UC_ARM64_REG_X29, 0x29292929)
    cpu.reg_write(UC_ARM64_REG_X30, stop)
    stats = {'submit': 0, 'wait': 0, 'parse': 0, 'guard': 0,
             'doorbells': 0, 'errors': [], 'cache': 0, 'barrier': 0, 'delay': 0}
    pending = []

    def read32(address):
        return struct.unpack('<I', bytes(cpu.mem_read(address, 4)))[0]

    def write32(address, value):
        cpu.mem_write(address, struct.pack('<I', value))

    def store(uc, access, address, size, value, data):
        if address in (mmio + 0x4020, mmio + 0x4064):
            # W1C: apply after the emulated store instruction completes.
            pending.append((address, read32(address) & ~value))
        if address == mmio + 0x4058:
            stats['doorbells'] += 1
            if complete:
                pending.extend([(address, 0), (mmio + 0x4064, value),
                                (mmio + 0x4020, 1)])
                # Actual 12618 layout: slot 0 command buffer at TRL+0x400,
                # NOP response offset 0x20. 11718 parses this DMA response.
                cpu.mem_write(trl + 0x420, bytes([response]) + bytes(31))

    def instruction(uc, address, size, data):
        while pending:
            target, value = pending.pop(0)
            write32(target, value)
        rva = address - load
        if rva == 0x1180c: stats['submit'] += 1
        if rva == 0x11b0c: stats['wait'] += 1
        if rva == 0x11718: stats['parse'] += 1
        if guarded and rva == 0x11834:
            stats['guard'] += 1
            request = bytes(cpu.mem_read(cpu.reg_read(UC_ARM64_REG_X1), 0xc8))
            buf = ctypes.create_string_buffer(request)
            decision = lib.allowed(buf, len(request))
            assert decision == 1
            x0 = ctypes.c_uint64(cpu.reg_read(UC_ARM64_REG_X0))
            x8 = ctypes.c_uint64(cpu.reg_read(UC_ARM64_REG_X8))
            pc = ctypes.c_uint64(address)
            lib.resume(decision, buf, load, ctypes.byref(x0), ctypes.byref(x8), ctypes.byref(pc))
            cpu.reg_write(UC_ARM64_REG_X0, x0.value)
            cpu.reg_write(UC_ARM64_REG_X8, x8.value)
            cpu.reg_write(UC_ARM64_REG_PC, pc.value)
        if rva in (0x196fc, 0x197bc, 0x197a8, 0xf950):
            if rva == 0x196fc: stats['cache'] += 1
            elif rva == 0x197bc: stats['barrier'] += 1
            elif rva == 0x197a8: stats['delay'] += 1
            else: stats['errors'].append(cpu.reg_read(UC_ARM64_REG_X1))
            cpu.reg_write(UC_ARM64_REG_PC, cpu.reg_read(UC_ARM64_REG_X30))

    cpu.hook_add(UC_HOOK_MEM_WRITE, store)
    cpu.hook_add(UC_HOOK_CODE, instruction)
    cpu.emu_start(load + 0xd078, stop, count=100000)
    assert cpu.reg_read(UC_ARM64_REG_PC) == stop, stats
    assert cpu.reg_read(UC_ARM64_REG_SP) == sp, stats
    assert cpu.reg_read(UC_ARM64_REG_X19) == 0x19191919
    assert cpu.reg_read(UC_ARM64_REG_X29) == 0x29292929
    stats['return'] = cpu.reg_read(UC_ARM64_REG_X0)
    return stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--uefi', type=Path, required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('patchufs', root / 'scripts/patch-ufs-readonly.py')
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    original = a.source.read_bytes()
    patched = patcher.patch(original)
    restored = bytearray(patched)
    for rva, word, _, _ in patcher.PATCHES:
        struct.pack_into('<I', restored, rva, word)
    assert bytes(restored) == original
    try:
        patcher.patch(patched)
    except ValueError:
        pass
    else:
        raise AssertionError('Already patched input accepted')
    header = a.uefi / 'Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe/UfsCommandGuard.h'
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        c = tmp / 'guard.c'
        c.write_text('''#include <stdint.h>
typedef uint8_t UINT8; typedef uint32_t UINT32; typedef uint64_t UINT64;
typedef uintptr_t UINTN; typedef int BOOLEAN;
#define STATIC static
#define CONST const
#define VOID void
#define TRUE 1
#define FALSE 0
''' + '#include "' + str(header) + '"\n' + '''
int allowed(const UINT8 *r, UINTN n) { return UfsCommandAllowed(r,n); }
void resume(int ok,const UINT8 *r,UINT64 b,UINT64 *x0,UINT64 *x8,UINT64 *pc) {
  UfsGuardResume(ok,r,b,x0,x8,pc);
}
''')
        so = tmp / 'guard.so'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC', str(c), '-o', str(so)], check=True)
        lib = ctypes.CDLL(str(so))
        lib.allowed.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        lib.allowed.restype = ctypes.c_int
        lib.resume.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint64,
                               *([ctypes.POINTER(ctypes.c_uint64)] * 3)]
        cases = 0

        def check(r, expected):
            nonlocal cases
            before = bytes(r)
            assert lib.allowed(ctypes.create_string_buffer(before), len(r)) == expected, before.hex()
            assert bytes(r) == before
            cases += 1

        # Unknown transaction/command/query opcodes always fail closed.
        for kind in range(256):
            r = bytearray(0xc8); r[0x48] = kind
            check(r, kind in (0, 1))
        read_ops = {0, 3, 0x12, 0x25, 0x28, 0x88, 0xa0}
        for op in range(256):
            for direction in range(4):
                r = bytearray(0xc8); r[0x48] = 1; r[0x5c] = op; r[1] = direction
                check(r, op in read_ops and direction in (0, 2))
            r[1] = 2; r[0x49] = 0x20
            check(r, False)
        for op in range(256):
            for idn in (0, 1, 2, 0xb, 0xff):
                r = bytearray(0xc8); r[0x48] = 0x16; r[0x5c] = op; r[0x5d] = idn
                check(r, op in (1, 3, 5) or (op == 6 and idn == 1))
        for off in (1, 5, 0x4a, 0x6c):
            r = bytearray(0xc8); r[0x48] = 1; r[0x5c] = 0x28
            r[off] = 0xc4 if off == 0x4a else 1
            check(r, False)
        for size in (0, 0x88, 0xc7):
            check(bytearray(size), False)
        assert not lib.allowed(None, 0xc8)
        # Explicit exceptions: capacity service action and active-only power.
        r = bytearray(0xc8); r[0x48] = 1; r[0x5c] = 0x9e; r[0x5d] = 0x10
        check(r, True); r[0x5d] = 0x11; check(r, False)
        r[0x5c] = 0x1b; r[0x5d] = 0; r[0x60] = 0x10
        check(r, True); r[0x60] = 0x30; check(r, False)
        for power in range(256):
            r[0x60] = power
            check(r, power == 0x10)

        # Run the original function to the guard position. The refusal must
        # unwind its real stack, restore callee-saved registers, return -EROFS
        # and never execute hardware submission. Allowed LDR must match ARM.
        load, stack, stop = 0x10000000, 0x20000000, 0x30000000
        for ok in (False, True):
            cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
            cpu.mem_map(load, 0x30000); cpu.mem_write(load, original)
            cpu.mem_map(stack, 0x10000); cpu.mem_map(stop, 0x1000)
            sp = stack + 0x8000; request = sp + 0x20
            r = bytearray(0xc8); r[0x48] = 1; r[0x5c] = 0x28 if ok else 0x2a
            struct.pack_into('<I', r, 0x88, 0x12345678)
            cpu.mem_write(request, bytes(r))
            cpu.reg_write(UC_ARM64_REG_SP, sp)
            cpu.reg_write(UC_ARM64_REG_X1, request)
            cpu.reg_write(UC_ARM64_REG_X0, 0x40000000)
            cpu.reg_write(UC_ARM64_REG_X19, 0x19191919)
            cpu.reg_write(UC_ARM64_REG_X29, 0x29292929)
            cpu.reg_write(UC_ARM64_REG_X30, stop)
            cpu.reg_write(UC_ARM64_REG_NZCV, 0xa0000000)
            cpu.emu_start(load + 0x1180c, load + 0x11834, count=40)
            assert cpu.reg_read(UC_ARM64_REG_SP) == sp - 0xe0
            decision = lib.allowed(ctypes.create_string_buffer(bytes(r)), len(r))
            assert bool(decision) == ok
            x0 = ctypes.c_uint64(cpu.reg_read(UC_ARM64_REG_X0))
            x8 = ctypes.c_uint64(cpu.reg_read(UC_ARM64_REG_X8))
            pc = ctypes.c_uint64(cpu.reg_read(UC_ARM64_REG_PC))
            lib.resume(decision, ctypes.create_string_buffer(bytes(r)), load,
                       ctypes.byref(x0), ctypes.byref(x8), ctypes.byref(pc))
            if ok:
                cpu.emu_start(load + 0x11834, load + 0x11838, count=1)
                assert x8.value == cpu.reg_read(UC_ARM64_REG_X8) == 0x12345678
                assert x0.value == cpu.reg_read(UC_ARM64_REG_X0)
                assert pc.value == cpu.reg_read(UC_ARM64_REG_PC)
                assert cpu.reg_read(UC_ARM64_REG_NZCV) == 0xa0000000
            else:
                cpu.reg_write(UC_ARM64_REG_X0, x0.value)
                cpu.emu_start(pc.value, stop, count=40)
                assert cpu.reg_read(UC_ARM64_REG_X0) == 0xffffffe2
                assert cpu.reg_read(UC_ARM64_REG_SP) == sp
                assert cpu.reg_read(UC_ARM64_REG_X19) == 0x19191919
                assert cpu.reg_read(UC_ARM64_REG_X29) == 0x29292929
                assert cpu.reg_read(UC_ARM64_REG_PC) == stop
        # Protect the whole completion routine from the mistaken r18 patch.
        assert patched[0x11b0c:0x11c58] == original[0x11b0c:0x11c58]
        good = nop_flow(original, lib)
        fixed = nop_flow(patched, lib, guarded=True)
        for result in (good, fixed):
            assert result['return'] == 0 and result['errors'] == [], result
            assert result['submit'] == result['wait'] == result['parse'] == result['doorbells'] == 1, result
        assert fixed['guard'] == 1
        # Reproduce the observed r18 pair of 143 failures and outer 228. This
        # catches a broken completion path even when the allowlist itself passes.
        bad = bytearray(patched)
        struct.pack_into('<I', bad, 0xb008, 0x94000691)
        struct.pack_into('<II', bad, 0x11b0c, 0x128003a0, 0xd65f03c0)
        assert hashlib.sha256(bad).hexdigest() == '3baf0ffebe109a461b3e474b31272c04b5e5a46d82ddb288f21dcd1e950f603d'
        broken = nop_flow(bytes(bad), lib, guarded=True)
        assert broken['return'] == 0xffffffe2 and broken['errors'] == [0x143, 0x143, 0x228], broken
        assert broken['submit'] == broken['wait'] == broken['doorbells'] == 2 and broken['parse'] == 0
        timeout = nop_flow(patched, lib, guarded=True, complete=False)
        assert timeout['return'] == 0xffffff9b and timeout['errors'] == [4, 0x143, 4, 0x143, 0x228], timeout
        wrong_response = nop_flow(patched, lib, guarded=True, response=0)
        assert wrong_response['return'] == 0xffffff9c and wrong_response['errors'] == [0x144, 0x144, 0x228], wrong_response
        print('NOP flow:', {'original': good, 'fixed': fixed, 'r18_reproduction': broken,
                            'real_timeout_model': timeout, 'bad_response_model': wrong_response})
    print(f'PASS: {cases} actual C policy cases; patch reversal; original ARM prologue/LDR/refusal epilogue; full submit/wait/parse/cleanup flow and r18 regression verified.')


if __name__ == '__main__':
    main()
