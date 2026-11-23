#!/usr/bin/env python3
"""Bind the read-only RAM driver to the exact payload being packed."""
import argparse
import hashlib
import json
from pathlib import Path
import zlib


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--payload', type=Path, required=True)
    p.add_argument('--uefi', type=Path, required=True)
    a = p.parse_args()
    data = a.payload.read_bytes()
    metadata = json.loads(a.payload.with_suffix('.json').read_text())
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != 0x4000000 or metadata['sha256'] != digest:
        raise ValueError('Payload size/hash differs from its build record')
    if data[71:90] != b'HOUJIESP   FAT32   ':
        raise ValueError('Not the houji FAT RAM payload')
    crc = zlib.crc32(data)
    if metadata['crc32'] != f'{crc:08x}':
        raise ValueError('CRC record differs')
    header = a.uefi / 'Platforms/Xiaomi/houjiPkg/Drivers/HoujiRamDiskDxe/PayloadIdentity.h'
    header.write_text('// Generated from RAM payload SHA256 ' + digest + '\n'
                      f'#define HOUJI_PAYLOAD_BYTES 0x{len(data):x}U\n'
                      f'#define HOUJI_PAYLOAD_CRC32 0x{crc:08x}U\n')
    print('RAM driver bound to payload', digest)


if __name__ == '__main__':
    main()
