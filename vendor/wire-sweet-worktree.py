"""Wire the Sweet display translation units into the tree the build actually
compiles (.cache/xnu-work)."""
from pathlib import Path

WORK = Path('.cache/xnu-work')
if not WORK.is_dir():
    raise SystemExit('wire-sweet-worktree: .cache/xnu-work missing')

fa = WORK / 'iokit/conf/files.arm64'
t = fa.read_text()
entries = [
    'iokit/Kernel/arm/SweetSurface.cpp optional iokitcpp',
    'iokit/Kernel/arm/SweetFramebuffer.cpp optional iokitcpp',
    'iokit/Kernel/arm/SweetDisplayStubs.cpp optional iokitcpp',
    'iokit/Kernel/arm/HoujiWeakStubs.cpp optional iokitcpp',
]
missing = [e for e in entries if Path(e.split()[0]).name not in t]
if missing:
    fa.write_text(t.rstrip('\n') + '\n\n' + '\n'.join(missing) + '\n')
    print('work files.arm64: added', [e.split('/')[-1].split()[0] for e in missing])
else:
    print('work files.arm64: already wired')

kc = WORK / 'iokit/KernelConfigTables.cpp'
k = kc.read_text()
anchor = 'const char * gIOKernelConfigTables =\n    "("\n'
if anchor not in k:
    raise SystemExit('wire-sweet-worktree: KernelConfigTables anchor missing')
lines = []
if 'IOCoreSurfaceRoot' not in k:
    lines += [
        '    "   {"',
        "    \"     'IOClass'         = IOCoreSurfaceRoot;\"",
        "    \"     'IOProviderClass' = IOResources;\"",
        "    \"     'IOMatchCategory' = IOCoreSurfaceRoot;\"",
        '    "   },"',
    ]
if lines:
    kc.write_text(k.replace(anchor, anchor + ''.join(l + '\n' for l in lines), 1))
    print('work KernelConfigTables: personalities added')
else:
    print('work KernelConfigTables: already wired')
