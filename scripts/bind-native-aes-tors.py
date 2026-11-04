#!/usr/bin/env python3
"""Bind NativeAES's base-class entry points to the kernel's own IOService code.

`drivers/NativeAES/OriginalAESABI.h` declares IOAESAccelerator purely so the kernel-side
subclass keeps Apple's instance layout and vtable order. Its constructor and destructors only
chain into IOCryptoAccelerator -> IOService, so linking them against addresses recorded from
some other kernelcache turns every NativeAES construction into a jump into unpopulated
prelink text (observed: udf at 0xfffffff004a80038 from NativeAES::MetaClass::alloc+0x30).

The kernel does carry IOService, so bind the four entry points as tail branches to it. The
recorded addresses for the remaining methods stay as they are: NativeAES overrides them.
"""
import sys
from pathlib import Path

REBIND = {
    '__ZN16IOAESAcceleratorC2EPK11OSMetaClass': '__ZN9IOServiceC2EPK11OSMetaClass',
    '__ZN16IOAESAcceleratorD0Ev': '__ZN9IOServiceD0Ev',
    '__ZN16IOAESAcceleratorD1Ev': '__ZN9IOServiceD1Ev',
    '__ZN16IOAESAcceleratorD2Ev': '__ZN9IOServiceD2Ev',
}
MARKER = '// UniXNU: base entry points bound to the kernel IOService'


def rewrite(text):
    if MARKER in text:
        return text, 0
    changed = 0
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        symbol = None
        if stripped.startswith('.set '):
            candidate = stripped[len('.set '):].split(',')[0].strip()
            if candidate in REBIND:
                symbol = candidate
        if symbol is None:
            out.append(line)
            continue
        out.extend(['.text', '.p2align 2', '.globl %s' % symbol,
                    '%s:' % symbol, '  b %s' % REBIND[symbol]])
        changed += 1
    if changed != len(REBIND):
        raise SystemExit('expected %d bindings to rewrite, found %d' % (len(REBIND), changed))
    return '\n'.join(out) + '\n' + MARKER + '\n', changed


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: bind-native-aes-tors.py <native-aes-original-bindings.S>')
    path = Path(sys.argv[1])
    updated, changed = rewrite(path.read_text())
    if changed:
        path.write_text(updated)
    print('native AES base entry points: %d rewritten, %s' % (changed, path))


main()
