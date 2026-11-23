#!/usr/bin/env python3
"""Cross-check generated C regions using libfdt's fdtget, independently of fdt.py."""
import argparse
from pathlib import Path
import re
import struct
import subprocess
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('xbl_config', type=Path)
    p.add_argument('memory_map', type=Path)
    a = p.parse_args()
    regions = {}
    with tempfile.TemporaryDirectory() as temp:
        data = a.xbl_config.read_bytes()
        at = 0
        while (at := data.find(b'\xd0\x0d\xfe\xed', at)) >= 0:
            size = struct.unpack_from('>I', data, at + 4)[0]
            dtb = Path(temp) / f'{at}.dtb'
            dtb.write_bytes(data[at:at + size])
            at += 4
            for parent in ['/soc/memorymap', '/soc/registermap']:
                children = subprocess.run(['fdtget', '-l', str(dtb), parent], capture_output=True, text=True)
                if children.returncode:
                    continue
                for child in children.stdout.splitlines():
                    path = parent + '/' + child
                    def read(prop, kind='x'):
                        return subprocess.check_output(['fdtget', '-t', kind, str(dtb), path, prop], text=True).strip()
                    name = read('MemLabel', 's')
                    hob = int(read('BuildHob'), 16)
                    if name == 'NOMAP' and hob == 9:
                        continue
                    cells = [int(x, 16) for x in read('reg').split()]
                    assert len(cells) == 4
                    base, length = cells[0] << 32 | cells[1], cells[2] << 32 | cells[3]
                    resource, flags, memory = [int(read(x), 16) for x in ['ResourceType', 'ResourceAttribute', 'MemoryType']]
                    attr = {2: 'WRITE_BACK', 0x22: 'WRITE_BACK_XN', 0x20: 'WRITE_THROUGH_XN', 0x25: 'UNCACHED_UNBUFFERED_XN', 9: 'NS_DEVICE'}[int(read('CacheAttributes'), 16)]
                    hob = {0: 'AddMem', 4: 'NoHob', 5: 'AddDev', 10: 'AddMem'}[hob]
                    if name == 'UEFI_FD':
                        assert (base, length) == (0xA7000000, 0x400000)
                        regions['FD_Reserved'] = (base, 0x100000, hob, resource, flags, 0, attr)
                        base, length = 0xA7100000, 0x300000
                    assert name not in regions
                    regions[name] = (base, length, hob, resource, flags, memory, attr)
    actual = {}
    for row in re.findall(r'\{"([^"]+)", ([^}]+)\}', a.memory_map.read_text()):
        fields = [x.strip() for x in row[1].split(',')]
        assert len(fields) == 7 and row[0] not in actual
        actual[row[0]] = tuple(int(v, 0) if i in (0, 1, 3, 4, 5) else v for i, v in enumerate(fields))
    assert len(regions) == 41 and actual == regions, 'Generated map differs from the OEM FDT'
    print('libfdt independently confirmed all 41 memory regions and attributes.')


if __name__ == '__main__':
    main()
