import sys
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('out/houji/tree/refer/xnu')
if not root.is_dir():
    print('refer/xnu missing')
    sys.exit(1)

fa = root / 'iokit/conf/files.arm64'
t = fa.read_text()
entries = [
    'iokit/Kernel/arm/SweetSurface.cpp optional iokitcpp',
    'iokit/Kernel/arm/SweetFramebuffer.cpp optional iokitcpp',
    'iokit/Kernel/arm/SweetDisplayStubs.cpp optional iokitcpp',
    'iokit/Kernel/arm/HoujiWeakStubs.cpp optional iokitcpp',
    'iokit/Kernel/arm/SweetWatchdog.cpp optional iokitcpp',
]
missing = [e for e in entries if Path(e.split()[0]).name not in t]
if missing:
    fa.write_text(t.rstrip('\n') + '\n\n' + '\n'.join(missing) + '\n')
    print('files.arm64: added', [e.split('/')[-1].split()[0] for e in missing])
else:
    print('files.arm64: already wired')

kc = root / 'iokit/KernelConfigTables.cpp'
k = kc.read_text()
anchor = 'const char * gIOKernelConfigTables =\n    "("\n'
assert anchor in k, 'KCT anchor missing'
lines = []
if 'IOCoreSurfaceRoot' not in k:
    lines += [
        '    "   {"',
        "    \"     'IOClass'         = IOCoreSurfaceRoot;\"",
        "    \"     'IOProviderClass' = IOResources;\"",
        "    \"     'IOMatchCategory' = IOCoreSurfaceRoot;\"",
        '    "   },"',
    ]
if 'IOWatchdog' not in k:
    lines += [
        '    "   {"',
        "    \"     'IOClass'         = IOWatchdog;\"",
        "    \"     'IOProviderClass' = IOResources;\"",
        "    \"     'IOMatchCategory' = IOWatchdog;\"",
        '    "   },"',
    ]
if lines:
    block = ''.join(l + '\n' for l in lines)
    kc.write_text(k.replace(anchor, anchor + block, 1))
    print('KernelConfigTables: personalities added')
else:
    print('KernelConfigTables: already wired')
