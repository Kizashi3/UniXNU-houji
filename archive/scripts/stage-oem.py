#!/usr/bin/env python3
"""Stage explicitly selected OEM DXEs from a local uefi-firmware-parser dump.

No download, patching or device access. Output must stay outside source control.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('dump', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--driver', action='append', required=True)
    args = p.parse_args()
    wanted = set(args.driver)
    if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name) for name in wanted):
        p.error('Invalid driver name')
    matches = {}
    for ui in args.dump.rglob('*.ui'):
        name = ui.read_bytes().decode('utf-16le').rstrip('\0')
        if name not in wanted:
            continue
        if name in matches:
            raise ValueError('Ambiguous OEM driver: ' + name)
        matches[name] = ui.parent
    if set(matches) != wanted:
        raise ValueError('Missing OEM drivers: ' + ', '.join(sorted(wanted - set(matches))))
    manifest = []
    for name, directory in sorted(matches.items()):
        guid = str(uuid.UUID(directory.name.removeprefix('file-'))).upper()
        pe = list(directory.glob('*.pe'))
        deps = list(directory.glob('*.dxe.depex'))
        if len(pe) != 1 or len(deps) > 1 or pe[0].read_bytes()[:2] != b'MZ':
            raise ValueError('Unexpected OEM section layout: ' + name)
        out = args.output / 'HoujiVendorPkg' / name
        out.mkdir(parents=True, exist_ok=True)
        binaries = []
        record = {'name': name, 'guid': guid, 'inputs': []}
        for src, suffix, kind in [(pe[0], '.efi', 'PE32')] + ([(deps[0], '.depex', 'DXE_DEPEX')] if deps else []):
            dest = out / (name + suffix)
            shutil.copyfile(src, dest)
            binaries.append(f'  {kind}|{dest.name}|*')
            record['inputs'].append({'file': str(src), 'bytes': src.stat().st_size, 'sha256': hashlib.sha256(src.read_bytes()).hexdigest()})
        inf = f'[Defines]\n  INF_VERSION = 0x0001001B\n  BASE_NAME = {name}\n  FILE_GUID = {guid}\n  MODULE_TYPE = DXE_DRIVER\n  VERSION_STRING = 1.0\n  ENTRY_POINT = EfiEntry\n\n[Binaries.AARCH64]\n' + '\n'.join(binaries) + '\n\n[Depex]\n  TRUE\n'
        (out / (name + '.inf')).write_text(inf)
        manifest.append(record)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Staged explicit OEM drivers:', ', '.join(sorted(wanted)))


if __name__ == '__main__':
    main()
