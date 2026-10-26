"""Extract and pin-check GPU assets from a local vendor EROFS image (Linux/WSL).

Requires dump.erofs. No mounting, device access or proprietary redistribution.
All four assets are verified before writing any output file.
"""
import argparse
import json
from pathlib import Path
import subprocess
from ios16_gpu import ROOT, digest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vendor-erofs', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    pins = json.loads((ROOT/'hardware/sm8650-gpu.json').read_text())
    assets = []
    for entry in pins['firmware']:
        data = subprocess.check_output(['dump.erofs', '--cat',
            '--path=/firmware/' + entry['name'], str(a.vendor_erofs)])
        if len(data) != entry['size'] or digest(data) != entry['sha256']:
            raise ValueError('Firmware differs from qualified ROM: ' + entry['name'])
        target = a.out/entry['name']
        if target.is_symlink() or (target.exists() and target.read_bytes() != data):
            raise ValueError('Refusing to replace different output: ' + str(target))
        assets.append((target, data))
    a.out.mkdir(parents=True, exist_ok=True)
    for target, data in assets:
        if not target.exists():
            target.write_bytes(data)
    print('Verified and extracted four local GPU assets; no firmware was uploaded')


if __name__ == '__main__':
    main()
