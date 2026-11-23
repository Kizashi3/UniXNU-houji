#!/usr/bin/env python3
"""Compare the actual C trace stepper with AArch64 execution in Unicorn.

This checks the instrumented control flow, not Clock hardware behavior or the
firmware exception-entry assembly. A separate on-device BRK self-test gates it.
"""
import argparse
import ctypes
import hashlib
import importlib.util
from pathlib import Path
import random
import struct
import subprocess
import tempfile

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X8, UC_ARM64_REG_X30, UC_ARM64_REG_PC, UC_ARM64_REG_NZCV


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--uefi', type=Path, required=True)
    a = p.parse_args()
    spec = importlib.util.spec_from_file_location('patch_clock', Path(__file__).resolve().parents[1] / 'scripts/patch-clock-trace.py')
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    source = a.source.read_bytes()
    diagnostic, sites, header = patch.create(source)
    board = a.uefi / 'Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe'
    assert header == (board / 'ClockTraceSites.inc').read_text()
    assert len(sites) == 57 and len({s['rva'] for s in sites}) == 57
    restored = bytearray(diagnostic)
    for site in sites:
        assert struct.unpack_from('<I', diagnostic, site['rva'])[0] == patch.BRK_OPCODE
        struct.pack_into('<I', restored, site['rva'], site['opcode'])
    assert bytes(restored) == source
    wrong = bytearray(source)
    wrong[0x1000] ^= 1
    try:
        patch.create(wrong)
    except ValueError:
        pass
    else:
        raise AssertionError('Wrong source accepted')
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        c = temp / 'step.c'
        c.write_text('''#include <stdint.h>
typedef uint32_t UINT32; typedef uint64_t UINT64; typedef int64_t INT64;
typedef int BOOLEAN;
#define STATIC static
#define TRUE 1
#define FALSE 0
''' + '#include "' + str(board / 'ClockTraceStep.h') + '"\n' + '''
int execute(UINT32 op, UINT64 pc, UINT64 r0, UINT64 r8, UINT64 *next, UINT64 *lr) {
 return ClockTraceStep(op,pc,r0,r8,next,lr);
}
''')
        library = temp / 'step.so'
        subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-shared', '-fPIC', str(c), '-o', str(library)], check=True)
        step = ctypes.CDLL(str(library)).execute
        step.argtypes = [ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
                         ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
        step.restype = ctypes.c_int
        cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        cpu.mem_map(0x10000000, 0x400000)
        rng = random.Random(8650)
        cases = [(s['opcode'], 0x10100000+s['rva']) for s in sites]
        # Include signed immediate boundaries, CB(N)Z X0 and both directions.
        cases += [(op, 0x10200000) for op in (0x94000001, 0x97FFFFFF,
                  0x34000020, 0x35FFFFE0, 0xB4000020, 0xB5FFFFE0,
                  0x347FFFE0, 0x34800000)]
        total = 0
        for op, pc in cases:
            for r0 in (0, 1, 0xFFFFFFFF, 0x100000000, 0x8000000000000000, rng.getrandbits(64)):
                lr = rng.getrandbits(64)
                target = 0x10180000
                flags = rng.randrange(16) << 28
                next_pc, new_lr = ctypes.c_uint64(0xBAD), ctypes.c_uint64(lr)
                assert step(op, pc, r0, target, ctypes.byref(next_pc), ctypes.byref(new_lr)) == 1
                cpu.mem_write(pc, struct.pack('<I', op))
                cpu.reg_write(UC_ARM64_REG_X0, r0)
                cpu.reg_write(UC_ARM64_REG_X8, target)
                cpu.reg_write(UC_ARM64_REG_X30, lr)
                cpu.reg_write(UC_ARM64_REG_NZCV, flags)
                cpu.ctl_remove_cache(pc, pc + 4)
                try:
                    cpu.emu_start(pc, 0, count=1)
                except Exception as error:
                    raise AssertionError((hex(op), hex(pc), hex(r0), hex(cpu.reg_read(UC_ARM64_REG_PC)))) from error
                assert cpu.reg_read(UC_ARM64_REG_PC) == next_pc.value, (hex(op), hex(r0))
                assert cpu.reg_read(UC_ARM64_REG_X30) == new_lr.value
                assert cpu.reg_read(UC_ARM64_REG_X0) == r0
                assert cpu.reg_read(UC_ARM64_REG_X8) == target
                assert cpu.reg_read(UC_ARM64_REG_NZCV) == flags
                total += 1
        for op, r8 in ((0xD65F03C0, 0), (patch.BRK_OPCODE, 0),
                       (0xD63F0120, 0x10180000), (0x34000021, 0),
                       (0xD63F0100, 0), (0xD63F0100, 3)):
            next_pc, lr = ctypes.c_uint64(0xBAD), ctypes.c_uint64(0xCAFE)
            assert step(op, 0x10100000, 0, r8, ctypes.byref(next_pc), ctypes.byref(lr)) == 0
            assert (next_pc.value, lr.value) == (0xBAD, 0xCAFE)
    print(f'PASS: {total} original-instruction executions match the actual C stepper; unsupported cases rejected; {len(sites)}-site patch reverses exactly to {hashlib.sha256(source).hexdigest()}.')


if __name__ == '__main__':
    main()
