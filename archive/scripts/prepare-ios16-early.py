#!/usr/bin/env python3
"""Prepare a storage-free Darwin 22 single-core patch set for houji.

Only the reference's first 18 patches and its two early CPU/VM fixes are used.
The full Ace 5 iOS profile includes UFS/USB integration and is not booted here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REFERENCE = 'd68e05df683f863f054b0f9c063c54d2b1342b2a'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    revision = subprocess.check_output(['git', '-C', str(a.reference), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != REFERENCE:
        raise ValueError('Reference revision changed; inspect it before preparing patches')
    subprocess.run([sys.executable, str(a.reference / 'tools/prepare_vermeer.py'),
                    str(a.reference / 'xnu/patches'), str(a.out)], check=True)
    patches = sorted(a.out.glob('*.patch'))
    if len(patches) != 20 or any(a.out.glob('*.sh')):
        raise ValueError('Unexpected early profile contents')
    replacements = [('0xb8000000', '0xfc400000'), ('1440u', '1200u'),
                    ('3200u', '2670u'), ('5760', '4800'), ('3168', '2638'),
                    ('xiaomi,sweet', 'xiaomi,houji'), ('arm,cortex-a510', 'qcom,kryo'),
                    ('VERMEER CPU:', 'HOUJI CPU:'),
                    ('ARM Cortex-A510 (vermeer boot CPU)', 'SM8650 houji boot CPU'),
                    ('matched Cortex-A510 provider', 'matched SM8650 boot CPU provider'),
                    ('strlcpy(name, "sweet",', 'strlcpy(name, "houji",'),
                    ('strlcpy(name, "Redmi Note 10 Pro",', 'strlcpy(name, "Xiaomi 14",')]
    manifest = []
    for patch in patches:
        text = patch.read_text(errors='surrogateescape')
        for old, new in replacements:
            text = text.replace(old, new)
        if any(value in text for value in ['0x9c000000', '0xb8000000', '0xd5100000', 'vermeer_ufs_', 'sweet_ufs_', 'vermeer_usb_', 'sweet_usb_']):
            raise ValueError('Foreign hardware or storage source in ' + patch.name)
        patch.write_text(text, errors='surrogateescape')
        manifest.append({'file': patch.name, 'sha256': hashlib.sha256(patch.read_bytes()).hexdigest()})
    (a.out / 'houji-profile.json').write_text(json.dumps({
        'reference_revision': revision, 'profile': 'houji-ios16-early', 'cpu_count': 1,
        'darwin': 22, 'storage_drivers': False, 'usb_drivers': False,
        'framebuffer': {'base': '0xfc400000', 'width': 1200, 'height': 2670, 'stride': 4800},
        'patches': manifest, 'compiled': False, 'hardware_tested': False,
    }, indent=2) + '\n')
    print('Prepared 20 early patches: houji framebuffer, one CPU, no storage/USB drivers.')


if __name__ == '__main__':
    main()
