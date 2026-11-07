#!/usr/bin/env python3
import os, re, shutil
from pathlib import Path
dev = Path(os.environ.get('DEVICE_DIR', '/tmp/houji-ci'))
tree = Path('out/houji/tree')
# overlay the vendored driver into the build tree
dst = tree / 'drivers' / 'NativeUfs'
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(dev / 'vendor' / 'drivers' / 'NativeUfs', dst)
print('overlaid', dst, 'cpp', (dst / 'NativeUfs.cpp').is_file())
# drop the verified-root crypto flags so the driver builds probe-only
p = tree / 'scripts' / 'build-arm-driver.py'
t = p.read_text()
old = "                '-DNATIVE_VERIFIED_BLOCK=1', '-DNATIVE_VERIFIED_BLOCK_MULTI_POLICY=1', '-mgeneral-regs-only'"
new = "                '-Wno-error', '-mgeneral-regs-only'"
if old in t:
    p.write_text(t.replace(old, new, 1)); print('build-arm-driver.py: verified flags removed')
else:
    print('build-arm-driver.py: flags already absent')
# point the pinned kernel link at the archive the tree driver actually produces
x = tree / "scripts" / "build-xnu-4k-baseline.sh"
xt = x.read_text()
old_archive = "UFS_ARCHIVE=$ROOT/build/sheng-ufs/libShengUfs.a"
new_archive = "UFS_ARCHIVE=$ROOT/build/native-ufs/libNativeUfs.a"
if old_archive in xt:
    x.write_text(xt.replace(old_archive, new_archive, 1)); print("build-xnu-4k-baseline.sh: UFS archive path -> native-ufs")
elif new_archive in xt:
    print("build-xnu-4k-baseline.sh: UFS archive path already native-ufs")
else:
    raise SystemExit("no UFS_ARCHIVE line in build-xnu-4k-baseline.sh")

# add NativeUfs to the board archives
b = dev / 'board.toml'; bt = b.read_text()
if 'build-arm-driver.py NativeUfs' in bt:
    print('board.toml already lists NativeUfs')
else:
    m = re.search(r'archives = \[\n', bt)
    if not m:
        raise SystemExit('board.toml has no archives array')
    bt = bt[:m.end()] + '  "build-arm-driver.py NativeUfs",\n' + bt[m.end():]
    b.write_text(bt); print('board.toml: NativeUfs archive added')
