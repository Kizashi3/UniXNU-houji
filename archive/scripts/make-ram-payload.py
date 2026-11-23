#!/usr/bin/env python3
"""Build and round-trip check a 64 MiB FAT RAM payload; never opens a device."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--boot-args', default='-v serial=3 debug=0x14e keepsyms=1 cpus=1')
    a = p.parse_args()
    if len(a.boot_args.encode()) > 512 or '\0' in a.boot_args or '\n' in a.boot_args:
        raise ValueError('Unexpected boot arguments')
    kernel = (a.inputs / 'kernel.macho').read_bytes()
    if struct.unpack_from('<III', kernel) != (0xfeedfacf, 0x100000c, 0):
        raise ValueError('Expected a plain ARM64 Mach-O')
    if b'HOUJI CPU:' not in kernel or any(v in kernel for v in [b'vermeer_ufs_', b'vermeer_usb_']):
        raise ValueError('Unexpected kernel profile')
    config = '''version = 1
[boot]
default = "xnu"
timeout = 5
fallback_timeout = 120
rotate = 0
[ui]
title = "Xiaomi 14 XNU first entry"
[[driver]]
path = "/Drivers/DarwinBoot.efi"
connect = true
[[entry]]
id = "xnu"
title = "Darwin 22 - one CPU - RAM only"
type = "xnu"
path = "/Payloads/kernel.macho"
args = "-v serial=3 debug=0x14e keepsyms=1 cpus=1"
[[entry]]
id = "restart"
title = "Restart to Android"
type = "action"
action = "reset"
'''
    config = config.replace('args = "-v serial=3 debug=0x14e keepsyms=1 cpus=1"',
                            'args = ' + json.dumps(a.boot_args))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('wb') as f:
        f.truncate(64 * 1024 * 1024)
    def run(tool, *args):
        subprocess.run([tool, '-i', str(a.output), *map(str, args)], check=True)
    run('mformat', '-F', '-v', 'HOUJIESP', '-N', '0x484f554a', '::')
    run('mmd', '::/EFI', '::/EFI/UniXNU', '::/Payloads', '::/Drivers')
    files = {'Payloads/kernel.macho': a.inputs / 'kernel.macho',
             'Payloads/kernel.macho.adt': a.inputs / 'houji.adt',
             'Drivers/DarwinBoot.efi': a.inputs / 'DarwinBoot.efi'}
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        (temp / 'unixnu.toml').write_text(config)
        files['EFI/UniXNU/unixnu.toml'] = temp / 'unixnu.toml'
        hashes = {}
        for name, source in files.items():
            run('mcopy', '-o', source, '::/' + name)
            destination = temp / ('roundtrip-' + source.name)
            run('mcopy', '-o', '::/' + name, destination)
            if source.read_bytes() != destination.read_bytes():
                raise ValueError('RAM payload round-trip failed: ' + name)
            hashes[name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    data = a.output.read_bytes()
    if data[71:82] != b'HOUJIESP   ' or data[82:90] != b'FAT32   ':
        raise ValueError('Unexpected FAT boot sector')
    report = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
              'crc32': f'{zlib.crc32(data):08x}', 'files': hashes,
              'contains_xnu': True, 'physical_storage': False, 'hardware_tested': False}
    a.output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
