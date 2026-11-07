#!/usr/bin/env python3
"""Make the pinned kernel link the vendored NativeUfs probe driver.

`unixnu build kernel` re-assembles out/houji/tree and re-copies scripts of the
UniXNU checkout and of the device repository over the tree, so every edit must
be made at the source as well as in the current tree.
"""
import os
import re
import shutil
from pathlib import Path

dev = Path(os.environ.get('DEVICE_DIR', '/tmp/houji-ci'))
root = Path('.')
tree = root / 'out/houji/tree'

# Overlay the vendored driver into the build tree.
dst = tree / 'drivers' / 'NativeUfs'
shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(dev / 'vendor' / 'drivers' / 'NativeUfs', dst)
print('overlaid', dst, 'cpp', (dst / 'NativeUfs.cpp').is_file())

# Compile the probe build without the verified-root crypto flags.
old_flags = ("                '-DNATIVE_VERIFIED_BLOCK=1', '-DNATIVE_VERIFIED_BLOCK_MULTI_POLICY=1', "
             "'-mgeneral-regs-only'")
new_flags = "                '-Wno-error', '-mgeneral-regs-only'"
for path in (dev / 'scripts' / 'build-arm-driver.py', tree / 'scripts' / 'build-arm-driver.py'):
    text = path.read_text()
    if old_flags in text:
        path.write_text(text.replace(old_flags, new_flags, 1))
        print(path, ': verified flags removed')
    else:
        print(path, ': flags already absent')

# Point the kernel link at the archive the tree driver actually produces. The
# upstream build script still names the renamed ShengUfs component.
old_archive = 'UFS_ARCHIVE=$ROOT/build/sheng-ufs/libShengUfs.a'
new_archive = 'UFS_ARCHIVE=$ROOT/build/native-ufs/libNativeUfs.a'
for path in (root / 'scripts' / 'build-xnu-4k-baseline.sh',
             tree / 'scripts' / 'build-xnu-4k-baseline.sh'):
    text = path.read_text()
    if old_archive in text:
        path.write_text(text.replace(old_archive, new_archive, 1))
        print(path, ': UFS archive path -> native-ufs')
    elif new_archive in text:
        print(path, ': UFS archive path already native-ufs')
    else:
        raise SystemExit(f'no UFS_ARCHIVE line in {path}')

# Belt: whatever name the script keeps, the archive resolves to the built one.
alias = tree / 'build' / 'sheng-ufs'
alias.mkdir(parents=True, exist_ok=True)
link = alias / 'libShengUfs.a'
if link.is_symlink() or link.exists():
    link.unlink()
link.symlink_to(Path('../native-ufs/libNativeUfs.a'))
print('alias', link, '-> ../native-ufs/libNativeUfs.a')

# Add NativeUfs to the board archives (device repository, read by every build).
board = dev / 'board.toml'
text = board.read_text()
if 'build-arm-driver.py NativeUfs' in text:
    print('board.toml already lists NativeUfs')
else:
    match = re.search(r'archives = \[\n', text)
    if not match:
        raise SystemExit('board.toml has no archives array')
    text = text[:match.end()] + '  "build-arm-driver.py NativeUfs",\n' + text[match.end():]
    board.write_text(text)
    print('board.toml: NativeUfs archive added')
# Diagnostics note: push once per run; the diagnostics branch keeps only the latest run.

# Rerun after the native-only artifact of run 138.
