#!/usr/bin/env python3
"""Bind the vendored NativeRamBlock driver to the qualified IOBlockStorageDevice ABI.

The four base addresses are pinned from the storage-ABI qualification of this board's
prelink candidate (iOS 16.7 donor 2ec297ba, slide -0x1000000; Darwin 23 IOStorageFamily,
190 slots / 14 pure virtuals / 176 kernel bindings). They are stable across builds because
board.toml pins the kernelcache, slide and roots; the post-build audit step re-derives them
from the live candidate and fails on drift. This script resolves the driver object's
undefined IOBlockStorageDevice imports, emits original-bindings.S, compiles and re-archives
libNativeRamBlock.a with both objects. macOS only (xcrun).
"""
import hashlib
import json
import os
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / 'build/native-ram-block'

# Qualified candidate addresses (see scripts/audit-storage-candidate.py + CI audit step).
BINDINGS = {
    '__ZTV20IOBlockStorageDevice': 0xfffffff005c73f50,
    '__ZN20IOBlockStorageDevice10gMetaClassE': 0xfffffff006a091d0,
    '__ZN20IOBlockStorageDeviceC2EPK11OSMetaClass': 0xfffffff0045d9d98,
    '__ZN20IOBlockStorageDeviceD2Ev': 0xfffffff0045d9db8,
    # Concrete base methods the driver inherits (vtable slots it does not override).
    '__ZN20IOBlockStorageDevice4initEP12OSDictionary': 0xfffffff0045d9e30,
    '__ZNK20IOBlockStorageDevice11getPropertyEPK8OSSymbol': 0xfffffff0045d9e88,
    '__ZN20IOBlockStorageDevice13setPropertiesEP8OSObject': 0xfffffff0045d9f38,
    '__ZN20IOBlockStorageDevice11requestIdleEv': 0xfffffff0045da050,
    '__ZN20IOBlockStorageDevice7doUnmapEP26IOBlockStorageDeviceExtentjj': 0xfffffff0045da05c,
    '__ZN20IOBlockStorageDevice13doSetPriorityEP26IOBlockStorageDeviceExtentjh': 0xfffffff0045da068,
    '__ZN20IOBlockStorageDevice20doGetProvisionStatusEyyPjP35IOBlockStorageProvisionDeviceExtenty': 0xfffffff0045da08c,
}
# If a fresh audit JSON is present, prefer it (catches layout drift at link time).
audit_path = ROOT / 'build/storage-abi/interface-audit.json'
if audit_path.is_file():
    audit = json.loads(audit_path.read_text())
    fresh = {
        '__ZTV20IOBlockStorageDevice': int(audit['vtable'], 16),
        '__ZN20IOBlockStorageDevice10gMetaClassE': int(audit['original_metaclass'], 16),
        '__ZN20IOBlockStorageDeviceC2EPK11OSMetaClass': int(audit['original_protected_constructor'], 16),
        '__ZN20IOBlockStorageDeviceD2Ev': int(audit['original_base_destructor'], 16),
    }
    drift = {k: (hex(BINDINGS[k]), hex(v)) for k, v in fresh.items() if BINDINGS.get(k) != v}
    if drift:
        raise SystemExit(f'Storage ABI drift (pinned, audited): {drift}; re-qualify')

obj_path = out / 'NativeRamBlock.o'
obj = obj_path.read_bytes()
magic, cpu, subtype, kind, count, size = struct.unpack_from('<6I', obj)
if (magic, cpu, subtype, kind) != (0xfeedfacf, 0x100000c, 0, 1):
    raise SystemExit('Driver object is not ordinary ARM64')
offset = 32
symoff = stroff = None
nsyms = 0
for _ in range(count):
    cmd, length = struct.unpack_from('<II', obj, offset)
    if cmd == 2:
        symoff, nsyms, stroff, _ = struct.unpack_from('<4I', obj, offset + 8)
    offset += length
strings = obj[stroff:]
undefined = []
for i in range(nsyms):
    strx, k, _, _, value = struct.unpack_from('<IBBHQ', obj, symoff + i * 16)
    if k == 1:
        end = strings.find(b'\0', strx)
        name = strings[strx:end].decode()
        if 'IOBlockStorageDevice' in name:
            undefined.append(name)
missing = [n for n in undefined if n not in BINDINGS]
if missing:
    raise SystemExit(f'Unqualified IOBlockStorageDevice imports: {missing}')
bindings = {n: BINDINGS[n] for n in undefined}
assembly = out / 'original-bindings.S'
assembly.write_text(''.join(f'.globl {n}\n.set {n}, {v:#x}\n' for n, v in sorted(bindings.items())))
subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-Werror',
                '-Wno-incompatible-sysroot', '-c', str(assembly), '-o', str(out / 'original-bindings.o')], check=True)
archive = out / 'libNativeRamBlock.a'
archive.unlink(missing_ok=True)
subprocess.run(['xcrun', 'ar', 'rcs', str(archive), str(obj_path), str(out / 'original-bindings.o')], check=True)
(out / 'bindings.json').write_text(json.dumps(dict(
    compiled_object_sha256=hashlib.sha256(obj).hexdigest(),
    bindings={n: hex(v) for n, v in bindings.items()},
    unresolved_original_imports=0), indent=2) + '\n')
print(f'PASS: bound {len(bindings)} IOBlockStorageDevice imports: {sorted(bindings)}')