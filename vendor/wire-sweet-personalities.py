import sys
from pathlib import Path

root = Path('out/houji/tree/refer/xnu')
if not root.is_dir():
    print('refer/xnu missing')
    sys.exit(1)

fa = root / 'iokit/conf/files.arm64'
t = fa.read_text()
add = (
    '\niokit/Kernel/arm/SweetSurface.cpp optional iokitcpp\n'
    'iokit/Kernel/arm/SweetFramebuffer.cpp optional iokitcpp\n'
    'iokit/Kernel/arm/SweetDisplayStubs.cpp optional iokitcpp\n'
    'iokit/Kernel/arm/HoujiWeakStubs.cpp optional iokitcpp\n'
    'iokit/Kernel/arm/SweetWatchdog.cpp optional iokitcpp\n'
)
if 'SweetFramebuffer.cpp' not in t:
    fa.write_text(t.rstrip('\n') + '\n' + add)
    print('files.arm64: sweet entries added')
else:
    print('files.arm64: already wired')

kc = root / 'iokit/KernelConfigTables.cpp'
k = kc.read_text()
if 'IOCoreSurfaceRoot' not in k:
    anchor = 'const char * gIOKernelConfigTables =\n    "("\n'
    assert anchor in k, 'KCT anchor missing'
    block = (
        '    "   {",\n'
        "    \"     'IOClass'         = IOCoreSurfaceRoot;\",\n"
        "    \"     'IOProviderClass' = IOResources;\",\n"
        "    \"     'IOMatchCategory' = IOCoreSurfaceRoot;\",\n"
        '    "   },",\n'
        '    "   {",\n'
        "    \"     'IOClass'         = IOWatchdog;\",\n"
        "    \"     'IOProviderClass' = IOResources;\",\n"
        "    \"     'IOMatchCategory' = IOWatchdog;\",\n"
        '    "   },",\n'
    )
    kc.write_text(k.replace(anchor, anchor + block, 1))
    print('KernelConfigTables: personalities added')
else:
    print('KernelConfigTables: already wired')
