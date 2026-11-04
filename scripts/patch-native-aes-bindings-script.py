#!/usr/bin/env python3
"""Make build-native-aes-bindings.py bind the four base entry points to the kernel IOService.

The generated bindings carry absolute addresses recorded from another kernelcache. In this
board's prelink set those addresses fall in kext text the image never emits, so the first
NativeAES allocation jumped into a zero page. IOAESAccelerator's constructor and destructors
only chain into IOService, and the kernel ships IOService, so emit tail branches instead.

Works for both script paths: the recorded .S fallback and the audit-generated bindings.
"""
import sys
from pathlib import Path

MARKER = 'UniXNU: base entry points bound to the kernel IOService'
THUNKS = {
    '__ZN16IOAESAcceleratorC2EPK11OSMetaClass': '__ZN9IOServiceC2EPK11OSMetaClass',
    '__ZN16IOAESAcceleratorD0Ev': '__ZN9IOServiceD0Ev',
    '__ZN16IOAESAcceleratorD1Ev': '__ZN9IOServiceD1Ev',
    '__ZN16IOAESAcceleratorD2Ev': '__ZN9IOServiceD2Ev',
}

HELPER = '''THUNKS = {
    '__ZN16IOAESAcceleratorC2EPK11OSMetaClass': '__ZN9IOServiceC2EPK11OSMetaClass',
    '__ZN16IOAESAcceleratorD0Ev': '__ZN9IOServiceD0Ev',
    '__ZN16IOAESAcceleratorD1Ev': '__ZN9IOServiceD1Ev',
    '__ZN16IOAESAcceleratorD2Ev': '__ZN9IOServiceD2Ev',
}


def bind_local_tors(path):
    """Replace the recorded base entry points with tail branches into the kernel IOService."""
    text = Path(path).read_text()
    if 'UniXNU: base entry points bound' in text:
        return
    kept = [line for line in text.splitlines()
            if line.split(',')[0].strip().replace('.set ', '') not in THUNKS]
    kept += ['', '// UniXNU: base entry points bound to the kernel IOService']
    for name, target in THUNKS.items():
        kept += ['.text', '.p2align 2', '.globl %s' % name, '%s:' % name, '  b %s' % target]
    Path(path).write_text('\\n'.join(kept) + '\\n')

'''


def patch(path):
    text = path.read_text()
    if 'def bind_local_tors(' in text:
        return 'already patched'
    anchor = "recorded = ROOT / 'scripts/data/native-aes-original-bindings.S'\n"
    if text.count(anchor) != 1:
        raise SystemExit('%s: recorded anchor matched %d times' % (path, text.count(anchor)))
    text = text.replace(anchor, anchor + HELPER, 1)

    recorded_compile = """    subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-Werror', '-Wno-incompatible-sysroot', '-c', recorded,
                    '-o', out / 'original-bindings.o'], check=True)"""
    recorded_local = """    local = out / 'original-bindings.S'
    local.write_bytes(recorded.read_bytes())
    bind_local_tors(local)
    subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-Werror', '-Wno-incompatible-sysroot', '-c', local,
                    '-o', out / 'original-bindings.o'], check=True)"""
    if text.count(recorded_compile) != 1:
        raise SystemExit('%s: recorded compile anchor matched %d times'
                         % (path, text.count(recorded_compile)))
    text = text.replace(recorded_compile, recorded_local, 1)

    write_anchor = "source.write_text(''.join(f'.globl {name}\\n.set {name}, {address:#x}\\n' for name, address in sorted(bindings.items())))\n"
    if text.count(write_anchor) != 1:
        raise SystemExit('%s: audit write anchor matched %d times' % (path, text.count(write_anchor)))
    text = text.replace(write_anchor, write_anchor + 'bind_local_tors(source)\n', 1)
    path.write_text(text)
    return 'patched'


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: patch-native-aes-bindings-script.py <build-native-aes-bindings.py> [...]')
    for name in sys.argv[1:]:
        path = Path(name)
        print('%s: %s' % (path, patch(path)))


main()
