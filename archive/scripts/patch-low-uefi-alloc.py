#!/usr/bin/env python3
"""Install the houji-only DXE allocation limit on a pinned Mu core source."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uefi', type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / 'native/high-memory'
    manifest = json.loads((source / 'manifest.json').read_text())
    replacement = (source / manifest['replacement_file']).read_bytes()
    if hashlib.sha256(replacement).hexdigest() != manifest['replacement_sha256']:
        raise ValueError('Allocation patch changed')
    target = args.uefi / manifest['page_source']
    current = target.read_bytes()
    digest = hashlib.sha256(current).hexdigest()
    if digest == manifest['after_sha256']:
        print('Pinned low-address allocation limit already installed')
        return
    if digest != manifest['before_sha256']:
        raise ValueError('Unexpected Mu DXE allocator')
    needle = manifest['needle'].encode()
    if current.count(needle) != 1:
        raise ValueError('Allocator patch location differs')
    updated = current.replace(needle, replacement)
    if hashlib.sha256(updated).hexdigest() != manifest['after_sha256']:
        raise ValueError('Patched allocator digest differs')
    target.write_bytes(updated)
    print('Installed houji-conditional automatic allocation limit; AllocateAddress unchanged')


if __name__ == '__main__':
    main()
