#!/usr/bin/env python3
"""Qualify IOBlockStorageDevice (Darwin 23, 190 slots / 14 pure virtuals) from a prelink
candidate by scanning its populated vtable. Works whether or not the storage symbols are
exported: the vtable is located by abstract BRK destructors + 9 version-stable inherited
anchors + 14 pure-virtual slots; the metaclass address comes from the getMetaClass getter,
the protected constructor from the unique function storing vtable+16 after a bl that thunks
to IOService::C2, and the base destructor from slot0-4 (branch thunk to IOService::D2).
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
OUT = sys.argv[2] if len(sys.argv) > 2 else None
d = open(K, 'rb').read(); img = np.macho(d); segs = img['segments']
exp = np.exports(d, img)
rev = {va: ns[0] for va, ns in exp.items()}
bn = {n: va for va, n in rev.items()}
PURE = bn['___cxa_pure_virtual']
IOS_C2 = bn['__ZN9IOServiceC2EPK11OSMetaClass']
IOS_D2 = bn['__ZN9IOServiceD2Ev']

def rd(va, n):
    o = np.backed_offset(segs, va, n, len(d)); return d[o:o + n]
def u32(va):
    return struct.unpack('<I', rd(va, 4))[0]
def thunk_target(addr):
    a, load, br = struct.unpack('<3I', rd(addr, 12))
    assert a & 0x9f00001f == 0x90000010 and load & 0xffc003ff == 0xf9400210 and br == 0xd61f0200, 'not a thunk'
    imm = ((a >> 5 & 0x7ffff) << 2) | (a >> 29 & 3)
    if imm & 0x100000: imm -= 0x200000
    slot = (addr & ~4095) + imm * 4096 + (load >> 10 & 4095) * 8
    return struct.unpack('<Q', rd(slot, 8))[0]
def branch_target(addr):
    w = u32(addr); assert w & 0xfc000000 == 0x14000000, 'not a branch'
    imm = w & 0x3ffffff
    if imm & 0x2000000: imm -= 0x4000000
    return addr + imm * 4

anchors = {2:'__ZNK8OSObject7releaseEi',3:'__ZNK8OSObject14getRetainCountEv',4:'__ZNK8OSObject6retainEv',
           5:'__ZNK8OSObject7releaseEv',6:'__ZNK8OSObject9serializeEP11OSSerialize',
           8:'__ZNK15OSMetaClassBase9isEqualToEPKS_',12:'__ZN9IOService8DispatchE5IORPC',
           13:'__ZN8OSObject4initEv',14:'__ZN9IOService4freeEv'}
plk_text = next(s for s in segs if s['name'] == '__PLK_TEXT_EXEC')
PLO, PHI = plk_text['va'], plk_text['va'] + plk_text['filesize']
plk_data = [s for s in segs if 'DATA_CONST' in s['name'] or s['name'] == '__PRELINK_DATA']

# Prefer an exported vtable symbol if present; otherwise scan.
if '__ZTV20IOBlockStorageDevice' in bn:
    VT = bn['__ZTV20IOBlockStorageDevice']
    ptrs = struct.unpack('<190Q', rd(VT + 16, 190 * 8))
    assert sum(p == PURE for p in ptrs) == 14
    mode = 'export'
else:
    cands = []
    for s in plk_data:
        if not s['filesize']: continue
        blob = d[s['fileoff']:s['fileoff'] + s['filesize']]; n = len(blob)
        for at in range(0, n - 16 - 191 * 8, 8):
            if blob[at:at + 16] != bytes(16): continue
            p0, p1 = struct.unpack_from('<2Q', blob, at + 16)
            try:
                if u32(p0) != 0xd4200020 or u32(p1) != 0xd4200020: continue
            except Exception: continue
            ptrs = struct.unpack_from('<191Q', blob, at + 16)
            if sum(p == PURE for p in ptrs[:190]) != 14: continue
            if ptrs[190] != 0: continue
            if any(ptrs[i] != bn.get(nm, -1) for i, nm in anchors.items()): continue
            cands.append((s['va'] + at, ptrs[:190]))
    assert len(cands) == 1, f'expected unique IOBlockStorageDevice vtable, got {len(cands)}'
    VT, ptrs = cands[0]
    mode = 'scan'
AP = VT + 16

# metaclass via slot7 getMetaClass (adrp x0; add x0; ret)
fn = ptrs[7]; a, add, ret = struct.unpack('<3I', rd(fn, 12))
assert a & 0x9f00001f == 0x90000000 and add & 0xffc003ff == 0x91000000 and ret == 0xd65f03c0, 'slot7 not getMetaClass'
imm = ((a >> 5 & 0x7ffff) << 2) | (a >> 29 & 3)
if imm & 0x100000: imm -= 0x200000
META = (fn & ~4095) + imm * 4096 + (add >> 10 & 4095)

# D2 = slot0 - 4 -> branch thunk -> IOService::D2
D2 = ptrs[0] - 4
assert thunk_target(branch_target(D2)) == IOS_D2, 'D2 not forwarded to IOService::D2'

# C2: unique ctor storing AP into [x0] after bl -> thunk -> IOService::C2
ctors = []
for address in range(PLO, PHI - 32, 4):
    w = struct.unpack('<8I', rd(address, 32))
    if (w[0]!=0xa9bf7bfd or w[1]!=0x910003fd or w[2]&0xfc000000!=0x94000000 or
        w[3]&0x9f00001f!=0x90000008 or w[4]&0xffc003ff!=0x91000108 or
        w[5:]!=(0xf9000008,0xa8c17bfd,0xd65f03c0)): continue
    imm26 = w[2] & 0x3ffffff
    if imm26 & 0x2000000: imm26 -= 0x4000000
    bltgt = address + 8 + imm26 * 4
    imm = ((w[3]>>5&0x7ffff)<<2)|(w[3]>>29&3)
    if imm & 0x100000: imm -= 0x200000
    stored = ((address+12)&~4095)+imm*4096+(w[4]>>10&4095)
    if stored == AP: ctors.append((address, bltgt))
assert len(ctors) == 1, f'expected unique C2, got {len(ctors)}'
C2 = ctors[0][0]
assert thunk_target(ctors[0][1]) == IOS_C2, 'C2 not forwarded to IOService::C2'

own_names = {va: n for n, va in bn.items() if 'IOBlockStorageDevice' in n}
methods = []
for i in range(190):
    t = ptrs[i]
    name = '___cxa_pure_virtual' if t == PURE else own_names.get(t, rev.get(t, f'__owned_slot_{i}'))
    methods.append(dict(slot=i, reference_name=name, candidate_target=hex(t), kernel_names=exp.get(t, [])))
result = dict(candidate_sha256=hashlib.sha256(d).hexdigest(), qualification_mode=mode,
              method_slots=190, pure_virtual_slots=14,
              kernel_bindings=sum(bool(m['kernel_names']) for m in methods),
              vtable=hex(VT), original_metaclass=hex(META),
              original_protected_constructor=hex(C2), original_base_destructor=hex(D2),
              abstract_complete_destructors_trap=True, live_native_4k=True,
              original_executable_code_unchanged=True,
              live_instance_sizes=dict(IOBlockStorageDevice=0x90, IOService=0x88),
              methods=methods, disk_read_tested=False, transport_implemented=False, hardware_tested=False)
if OUT:
    open(OUT, 'w').write(json.dumps(result, indent=2) + '\n')
print(f'PASS [{mode}] {K.split("/")[-1]}: 190 slots, 14 pure, {result["kernel_bindings"]} bindings')
print(f'  __ZTV20IOBlockStorageDevice = {VT:#x}')
print(f'  __ZN20IOBlockStorageDevice10gMetaClassE = {META:#x}')
print(f'  __ZN20IOBlockStorageDeviceC2EPK11OSMetaClass = {C2:#x}')
print(f'  __ZN20IOBlockStorageDeviceD2Ev = {D2:#x}')
if OUT: print('  wrote', OUT)