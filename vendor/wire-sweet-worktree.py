"""Wire the Sweet display translation units into the tree the build actually
compiles (.cache/xnu-work), not the refer/xnu working tree.

The kernel build script populates .cache/xnu-work with
    git clone --shared refer/xnu .cache/xnu-work     # HEAD only
and then re-applies only the patch files under $ROOT/patches/xnu/*.patch.
Direct edits made to refer/xnu by earlier helper scripts are not patch files,
so they never reach xnu-work. This helper runs against xnu-work and is
idempotent, so it can be invoked on every build pass.
"""
from pathlib import Path

WORK = Path('.cache/xnu-work')
if not WORK.is_dir():
    raise SystemExit('wire-sweet-worktree: .cache/xnu-work missing')

fa = WORK / 'iokit/conf/files.arm64'
t = fa.read_text()
add = (
    '\niokit/Kernel/arm/SweetSurface.cpp optional iokitcpp\n'
    'iokit/Kernel/arm/SweetFramebuffer.cpp optional iokitcpp\n'
    'iokit/Kernel/arm/SweetDisplayStubs.cpp optional iokitcpp\n'
    'iokit/Kernel/arm/HoujiWeakStubs.cpp optional iokitcpp\n'
)
if 'SweetFramebuffer.cpp' not in t:
    fa.write_text(t.rstrip('\n') + '\n' + add)
    print('work files.arm64: sweet translation units added')
else:
    print('work files.arm64: already wired')

kc = WORK / 'iokit/KernelConfigTables.cpp'
k = kc.read_text()
if "'IOMatchCategory' = IOCoreSurfaceRoot" not in k:
    anchor = 'const char * gIOKernelConfigTables =\n    "("\n'
    if anchor not in k:
        raise SystemExit('wire-sweet-worktree: KernelConfigTables anchor missing')
    block = (
        '    "   {"\n'
        "    \"     'IOClass'         = IOCoreSurfaceRoot;\"\n"
        "    \"     'IOProviderClass' = IOResources;\"\n"
        "    \"     'IOMatchCategory' = IOCoreSurfaceRoot;\"\n"
        '    "   },"\n'
        '    "   {"\n'
        "    \"     'IOClass'         = AppleCLCD;\"\n"
        "    \"     'IOProviderClass' = IOService;\"\n"
        "    \"     'IONameMatch'     = 'houji,display';\"\n"
        '    "   },"\n'
    )
    kc.write_text(k.replace(anchor, anchor + block, 1))
    print('work KernelConfigTables: personalities added')
else:
    print('work KernelConfigTables: already wired')
