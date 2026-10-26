#!/usr/bin/env python3
"""Minimal Xiaomi 14 / houji ADT for single-core XNU entry, with no storage/GPU nubs.

GIC windows/stride, CPU affinity and timer clock are from the captured Xiaomi 14
runtime DTB. Serializer/volatile CHRP layout follow UniXNU-sheng's generator
(BSD-2-Clause-Patent). DarwinBoot supplies the actual allocated boot window
and framebuffer in boot_args; dram-size here describes only the probe window.
"""
import argparse
from pathlib import Path
import os
import struct
import zlib
import uuid

def node(name, properties=(), children=()):
    props = [('name', name.encode() + b'\0'), *properties]
    result = struct.pack('<II', len(props), len(children))
    for key, value in props:
        if len(key.encode()) >= 32:
            raise ValueError('ADT property name is too long')
        result += struct.pack('<32sI', key.encode(), len(value))
        result += value + bytes(-len(value) % 4)
    return result + b''.join(children)

def nvram_proxy():
    def header(name, size):
        raw = bytearray(struct.pack('<BBH12s', 0x70, 0, size // 16, name))
        checksum = sum(raw)
        while checksum > 255:
            checksum = (checksum & 255) + (checksum >> 8)
        raw[1] = checksum
        return raw
    image = bytearray(8192)
    image[:16] = header(b'nvram', 32)
    image[32:48] = header(b'common', 2064)
    image[2096:2112] = header(b'free', len(image) - 2096)
    struct.pack_into('<I', image, 16, zlib.adler32(image[20:]))
    return [('nvram-bank-size', struct.pack('<I', len(image))),
            ('nvram-bank-count', struct.pack('<I', 1)),
            ('nvram-current-bank', struct.pack('<I', 0)),
            ('nvram-proxy-data', bytes(image))]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--dram-size', type=lambda s: int(s, 0), required=True)
    p.add_argument('--owned-memory-size', type=lambda s: int(s, 0), default=0x10000000)
    p.add_argument('--cpu-regs', choices=['0'], default='0')
    p.add_argument('--psci-method', choices=['smc'], default='smc')
    p.add_argument('--trust-cache', action='store_true')
    p.add_argument('--root-match-volume-uuid', type=uuid.UUID,
                   help='Match a published IOMedia volume UUID after UFS qualification')
    p.add_argument('--data-ramdisk', action='store_true',
                   help='Hand a dense APFS Data seed to the standard XNU RAMDisk path')
    args = p.parse_args()
    if args.dram_size != 0x10000000 or args.owned_memory_size != 0x10000000:
        p.error('First-entry profile requires a 256 MiB handoff window')
    u32 = lambda x: struct.pack('<I', x)
    u64 = lambda x: struct.pack('<Q', x)
    tree = node('device-tree', [
        ('model', b'Xiaomi-14-houji\0'),
        ('compatible', b'qcom,pineapple-mtp\0qcom,pineapple\0'),
        ('#address-cells', u32(2)), ('#size-cells', u32(2)),
    ], [
        node('chosen', [('random-seed', os.urandom(64)),
                        ('osenvironment', b'main\0'),
                        *([('ephemeral-storage', u32(1))] if args.data_ramdisk else []),
                        ('dram-base', u64(0x80000000)), ('dram-size', u64(args.dram_size)),
                        ('darwinboot-memory-size', u64(args.owned_memory_size)),
                        ('crypto-hash-method', b'sha2-384\0'),
                        *([('root-matching', ('<dict><key>IOProviderClass</key><string>IOMedia</string>'
                           '<key>IOPropertyMatch</key><dict><key>UUID</key><string>' +
                           str(args.root_match_volume_uuid).upper() + '</string></dict></dict>\0').encode())]
                          if args.root_match_volume_uuid else []),
                        ('amfi-only-platform-code', u32(1)), *nvram_proxy()],
             [node('memory-map', ([('RAMDisk', bytes(16))] if args.data_ramdisk else []) +
                                 ([('TrustCache', bytes(16))] if args.trust_cache else [])),
              node('manifest-properties')]),
        node('cpus', children=[node('cpu0', [('state', b'running\0'), ('reg', u32(0)),
             ('device_type', b'cpu\0'), ('compatible', b'qcom,kryo\0'),
             ('timebase-frequency', u32(19200000))])]),
        node('defaults', [('sleep-disabled', u32(1))]), node('options'),
        node('product', [('product-name', b'Xiaomi 14\0'), ('model', b'houji\0')]),
        node('arm-io', [('device_type', b'arm-io\0'), ('#address-cells', u32(2)),
                       ('#size-cells', u32(2)), ('ranges', struct.pack('<QQQ', 0, 0x17000000, 0x08000000))],
             [node('intc', [('compatible', b'arm,gic-v3\0'),
                ('reg', struct.pack('<4Q', 0x100000, 0x10000, 0x180000, 0x200000)),
                ('redistributor-stride', u64(0x40000))])]),
    ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(tree)
    print(f'houji first-entry ADT: {len(tree)} bytes; CPU0; no storage/GPU nodes')

if __name__ == '__main__':
    main()
