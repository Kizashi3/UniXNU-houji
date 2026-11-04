"""Rewrite generated NativeAES bindings at write time, whatever script produces them.

The build assembles its own build-native-aes-bindings.py inside out/houji/tree and derives
absolute addresses from its audit. Those addresses point into prelink text this board never
emits, so the first NativeAES allocation jumped into a zero page. IOAESAccelerator's
constructor and destructors only chain into IOService, which the kernel ships, so replace the
four base entry points with tail branches and leave the rest of the table alone.

Installed by setting PYTHONPATH to this directory for the kernel build.
"""
import pathlib

THUNKS = {
    '__ZN16IOAESAcceleratorC2EPK11OSMetaClass': '__ZN8IOServiceC2EPK11OSMetaClass',
    '__ZN16IOAESAcceleratorD0Ev': '__ZN8IOServiceD0Ev',
    '__ZN16IOAESAcceleratorD1Ev': '__ZN8IOServiceD1Ev',
    '__ZN16IOAESAcceleratorD2Ev': '__ZN8IOServiceD2Ev',
}
MARKER = 'UniXNU: base entry points bound to the kernel IOService'


def rewrite(text):
    if MARKER in text:
        return text
    kept = [line for line in text.splitlines()
            if line.split(',')[0].strip().replace('.set ', '') not in THUNKS]
    if len(kept) == len(text.splitlines()):
        # Nothing bound by name (already emitted another way): leave the file untouched.
        return text
    kept += ['', '// ' + MARKER]
    for name, target in THUNKS.items():
        kept += ['.text', '.p2align 2', '.globl ' + name, name + ':', '  b ' + target]
    return '\n'.join(kept) + '\n'


def _install():
    original_write_text = pathlib.Path.write_text
    original_write_bytes = pathlib.Path.write_bytes

    def write_text(self, data, *args, **kwargs):
        if str(self).endswith('original-bindings.S') and isinstance(data, str):
            data = rewrite(data)
        return original_write_text(self, data, *args, **kwargs)

    def write_bytes(self, data, *args, **kwargs):
        if str(self).endswith('original-bindings.S') and isinstance(data, (bytes, bytearray)):
            data = rewrite(bytes(data).decode('utf-8', 'replace')).encode()
        return original_write_bytes(self, data, *args, **kwargs)

    pathlib.Path.write_text = write_text
    pathlib.Path.write_bytes = write_bytes


_install()
