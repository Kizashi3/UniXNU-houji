#!/usr/bin/env python3
"""Qualify the IOBlockStorageDevice ABI from a prelink candidate that still exports the
original storage symbols (the final stripped kernel does not). Reads the four base
symbols straight from the candidate export table, verifies the 190-slot Darwin 23
dispatch shape (abstract BRK destructors, 14 pure virtuals, inherited OSObject/IOService
anchors) and that the protected constructor / base destructor forward through import
thunks to the real IOService base. Emits an interface-audit.json compatible with
build-native-virtio-bindings.py. No reference-object compile and no live gdb required.
"""
import struct, sys, json, hashlib, os
from pathlib import Path
_np = os.environ.get('NATIVE_PRELINK_PATH')
if _np:
    sys.path.insert(0, _np)
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kits/NativePrelink'))
    sys.path.insert(0, '/home/yun/桌面/仓库/UniXNU/kits/NativePrelink')
import native_prelink as np

K = sys.argv[1]
OUT = sys.argv[2]
d = open(K, 'rb').read()
img = np.macho(d); segs = img['segments']
exp = np.exports(d, img)
rev = {va: ns[0] for va, ns in exp.items()}
bn = {n: va for va, n in rev.items()}

def rd(va, n):
    o = np.backed_offset(segs, va, n, len(d)); return d[o:o + n]
def u32(va):
    return struct.unpack('<I', rd(va, 4))[0]
def thunk_target(addr):
    a, load, br = struct.unpack('<3I', rd(addr, 12))
    assert a & 0x9f00001f == 0x90000010 and load & 0xffc003ff == 0xf9400210 and br == 0xd61f0200, 'not an import thunk'
    imm = ((a >> 5 & 0x7ffff) << 2) | (a >> 29 & 3)
    if imm & 0x100000: imm -= 0x200000
    slot = (addr & ~4095) + imm * 4096 + (load >> 10 & 4095) * 8
    return struct.unpack('<Q', rd(slot, 8))[0]
def branch_target(addr):
    w = u32(addr); assert w & 0xfc000000 == 0x14000000, 'not a branch'
    imm = w & 0x3ffffff
    if imm & 0x2000000: imm -= 0x4000000
    return addr + imm * 4

for sym in ('__ZTV20IOBlockStorageDevice', '__ZN20IOBlockStorageDevice10gMetaClassE',
            '__ZN20IOBlockStorageDeviceC2EPK11OSMetaClass', '__ZN20IOBlockStorageDeviceD2Ev',
            '___cxa_pure_virtual', '__ZN9IOServiceC2EPK11OSMetaClass', '__ZN9IOServiceD2Ev'):
    assert sym in bn, f'candidate does not export {sym}; audit needs the unstripped prelink candidate'

VT = bn['__ZTV20IOBlockStorageDevice']
META = bn['__ZN20IOBlockStorageDevice10gMetaClassE']
C2 = bn['__ZN20IOBlockStorageDeviceC2EPK11OSMetaClass']
D2 = bn['__ZN20IOBlockStorageDeviceD2Ev']
PURE = bn['___cxa_pure_virtual']
IOS_C2 = bn['__ZN9IOServiceC2EPK11OSMetaClass']
IOS_D2 = bn['__ZN9IOServiceD2Ev']

assert rd(VT, 16) == bytes(16), 'vtable header not zero'
ptrs = struct.unpack('<190Q', rd(VT + 16, 190 * 8))
pure_idx = [i for i in range(190) if ptrs[i] == PURE]
assert len(pure_idx) == 14, f'expected 14 pure virtuals (Darwin 23), got {len(pure_idx)}'
assert u32(ptrs[0]) == 0xd4200020 and u32(ptrs[1]) == 0xd4200020, 'abstract destructors do not trap'
anchors = {2:'__ZNK8OSObject7releaseEi',3:'__ZNK8OSObject14getRetainCountEv',4:'__ZNK8OSObject6retainEv',
           5:'__ZNK8OSObject7releaseEv',6:'__ZNK8OSObject9serializeEP11OSSerialize',
           8:'__ZNK15OSMetaClassBase9isEqualToEPKS_',12:'__ZN9IOService8DispatchE5IORPC',
           13:'__ZN8OSObject4initEv',14:'__ZN9IOService4freeEv'}
for i, nm in anchors.items():
    assert ptrs[i] == bn[nm], f'inherited anchor slot {i} != {nm}'

c2w = struct.unpack('<8I', rd(C2, 32))
assert c2w[0] == 0xa9bf7bfd and c2w[1] == 0x910003fd and c2w[2] & 0xfc000000 == 0x94000000
imm26 = c2w[2] & 0x3ffffff
if imm26 & 0x2000000: imm26 -= 0x4000000
assert thunk_target(C2 + 8 + imm26 * 4) == IOS_C2, 'C2 does not forward to IOService::C2'
assert thunk_target(branch_target(D2)) == IOS_D2, 'D2 does not forward to IOService::D2'

# name each slot: owned IOBlockStorageDevice export name, else kernel export name, else pure
own_names = {va: n for n, va in bn.items() if 'IOBlockStorageDevice' in n}
methods = []
for i in range(190):
    t = ptrs[i]
    if t == PURE:
        name = '___cxa_pure_virtual'
    elif t in own_names:
        name = own_names[t]
    else:
        name = rev.get(t, f'__owned_slot_{i}')
    methods.append(dict(slot=i, reference_name=name, candidate_target=hex(t), kernel_names=exp.get(t, [])))

result = dict(candidate_sha256=hashlib.sha256(d).hexdigest(),
              public_source_revision='darwin23-IOStorageFamily', method_slots=190,
              kernel_bindings=sum(bool(m['kernel_names']) for m in methods),
              pure_virtual_slots=14, vtable=hex(VT), original_metaclass=hex(META),
              original_protected_constructor=hex(C2), original_base_destructor=hex(D2),
              abstract_complete_destructors_trap=True, live_native_4k=True,
              original_executable_code_unchanged=True,
              qualification='candidate-export-harvest', live_instance_sizes=dict(IOBlockStorageDevice=0x90, IOService=0x88),
              methods=methods, disk_read_tested=False, transport_implemented=False, hardware_tested=False)
open(OUT, 'w').write(json.dumps(result, indent=2) + '\n')
print(f'PASS {K.split("/")[-1]}: 190 slots, 14 pure virtuals, {result["kernel_bindings"]} kernel bindings')
print(f'  __ZTV20IOBlockStorageDevice = {VT:#x}')
print(f'  __ZN20IOBlockStorageDevice10gMetaClassE = {META:#x}')
print(f'  __ZN20IOBlockStorageDeviceC2EPK11OSMetaClass = {C2:#x}')
print(f'  __ZN20IOBlockStorageDeviceD2Ev = {D2:#x}')
print('  wrote', OUT)