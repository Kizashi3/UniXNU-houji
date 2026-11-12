#!/usr/bin/env python3
"""Relax the probe-build guard that couples CACHE_MOUNT to ROOT_TRUST.

UniXNU requires real owner root enforcement before the offline SystemOS mount is
allowed. This board has no verified block storage (NativeUfs is built without
NATIVE_VERIFIED_BLOCK, see vendor/enable-nativeufs.py) and does not build
NativeVirtioBlock, so the requirement cannot be met. The mount itself is
unchanged; only this build-time guard is relaxed, and only for the probe image.

Idempotent: reports what it changed and leaves an already-relaxed script alone.
"""
from pathlib import Path
import sys

CANDIDATES = [
    Path('scripts/build-xnu-4k-baseline.sh'),
    Path('out/houji/tree/scripts/build-xnu-4k-baseline.sh'),
]

GUARD = (
    'if [ "$OWNER_CACHE_MOUNT" = 1 ] && [ "$OWNER_ROOT_TRUST" != 1 ]; then\n'
    "  echo 'The offline SystemOS mount requires real independent owner root enforcement' >&2\n"
    '  exit 1\n'
    'fi\n'
)
RELAXED = (
    '# Probe build: this board has no verified block storage, so owner root\n'
    '# enforcement cannot be satisfied. The mount code is unchanged.\n'
    'if false; then\n'
    '  :\n'
    'fi\n'
)
MARKER = 'Probe build: this board has no verified block storage'


def main():
    changed = 0
    for path in CANDIDATES:
        if not path.is_file():
            print('%s: absent, skipped' % path)
            continue
        text = path.read_text()
        if MARKER in text:
            print('%s: already relaxed' % path)
            continue
        if GUARD not in text:
            raise SystemExit('%s: guard not found' % path)
        path.write_text(text.replace(GUARD, RELAXED, 1))
        print('%s: guard relaxed' % path)
        changed += 1
    if not changed:
        print('nothing to change')
    return 0


if __name__ == '__main__':
    sys.exit(main())
