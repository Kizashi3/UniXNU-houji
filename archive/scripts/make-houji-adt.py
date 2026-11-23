#!/usr/bin/env python3
"""Darwin 22 houji ADT; optional captured two-CPU prototype, no storage/GPU nodes."""
import argparse
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import zlib
import uuid
import hashlib


def nvram_proxy():
    """An empty, volatile CHRP bank; no physical NVRAM controller is exposed.

    Layout follows the BSD-licensed UniXNU Ace 5/sheng generator, reference
    18f51ec652501c62e19dd4f1035dc51daa2a3361, and Darwin 22 IONVRAMCHRPHandler.
    """
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
    return {'nvram-bank-size': struct.pack('<I', len(image)),
            'nvram-bank-count': struct.pack('<I', 1),
            'nvram-current-bank': bytes(4), 'nvram-proxy-data': bytes(image)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--ios-gui', action='store_true')
    p.add_argument('--memory-mib', type=int, choices=(256,320,2048,8192), default=256, help='Owned XNU window; AllocateAddress must reserve the whole range')
    p.add_argument('--product-adt', type=Path)
    p.add_argument('--platform-uuid', type=uuid.UUID, help='Device-bound UUIDv5; requires the houji platform UUID kernel fallback')
    p.add_argument('--cpus', type=int, choices=(1,2), default=1)
    p.add_argument('--live-fdt', type=Path, help='Pinned captured houji FDT; mandatory for the two-CPU prototype')
    a = p.parse_args()
    if a.memory_mib != 256 and not a.ios_gui:
        raise ValueError('Expanded memory window is only supported in the native GUI profile')
    if a.platform_uuid and (not a.ios_gui or a.platform_uuid.version != 5 or a.platform_uuid.variant != uuid.RFC_4122):
        raise ValueError('Platform identity requires a GUI UUIDv5 in RFC 4122 byte order')
    if a.cpus == 2:
        if not a.ios_gui or not a.live_fdt:
            raise ValueError('Two-CPU prototype requires GUI profile and captured FDT')
        import fdt
        raw = a.live_fdt.read_bytes()
        if hashlib.sha256(raw).hexdigest() != '04dad3a2a40758525e93109ef17954183500a86c7bdf77973b89e39f97723807':
            raise ValueError('Unverified SMP hardware description')
        hardware, _ = fdt.parse(raw)
        nodes = dict(hardware.walk())
        for index in (0,1):
            c = nodes['/cpus/cpu@' + ('0' if index == 0 else '100')].properties
            if (fdt.cells(c['reg']) != [0,index * 0x100] or
                fdt.strings(c['enable-method']) != ['psci'] or
                fdt.cells(c['qcom,freq-domain']) != [6,0] or
                fdt.cells(c['capacity-dmips-mhz']) != [1024] or
                fdt.cells(c['next-level-cache']) != [7]):
                raise ValueError('Captured homogeneous CPU pair differs')
        if fdt.strings(nodes['/soc/psci'].properties['method']) != ['smc']:
            raise ValueError('Captured PSCI conduit differs')
        if fdt.cells(nodes['/soc/interrupt-controller@17100000'].properties['redistributor-stride']) != [0,0x40000]:
            raise ValueError('Captured GIC redistributor stride differs')
    revision = subprocess.check_output(['git', '-C', str(a.reference), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != 'd68e05df683f863f054b0f9c063c54d2b1342b2a':
        raise ValueError('Unpinned reference')
    sys.path.insert(0, str(a.reference / 'tools'))
    import adt
    reference = runpy.run_path(str(a.reference / 'tools/mkvermeeradt.py'))
    if a.ios_gui and not a.product_adt:
        raise ValueError('GUI needs the local D22AP generic product tree')
    tree = reference['build'](ios=a.ios_gui, gui=a.ios_gui, product_adt=a.product_adt)
    def update(node, values):
        node.props = [(k, f, v) for k, f, v in node.props if k not in values]
        node.props.extend((k, 0, v) for k, v in values.items())
    update(tree, {'compatible': b'xiaomi,houji\0qcom,sm8650\0AppleARM\0',
                  'model': b'Xiaomi 14\0', 'manufacturer': b'Xiaomi\0', 'target-type': b'houji\0'})
    if a.ios_gui:
        update(tree, {'compatible': b'D22AP\0iPhone10,3\0xiaomi,houji\0qcom,sm8650\0AppleARM\0',
                      'model': b'iPhone10,3\0', 'target-type': b'D22\0',
                      'target-sub-type': b'D22AP\0', 'physical-model': b'Xiaomi 14\0'})
    chosen = next(c for c in tree.children if c.name == 'chosen')
    update(chosen, {'dram-base': bytes(8), 'dram-size': bytes(8),
                    'darwinboot-memory-size': struct.pack('<Q', a.memory_mib * 1024**2),
                    'firmware-version': b'houji-darwin22-uefi\0', **nvram_proxy()})
    if a.ios_gui:
        # The reference contains a fabricated Vermeer ECID. Do not import it.
        chosen.props = [(k, f, v) for k, f, v in chosen.props if k != 'unique-chip-id']
        if a.platform_uuid:
            update(chosen, {'houji,platform-uuid': a.platform_uuid.bytes})
    cpus = next(c for c in tree.children if c.name == 'cpus')
    if len(cpus.children) != 1 or cpus.children[0].prop('reg') != bytes(4):
        raise ValueError('Expected exactly the boot CPU, affinity 0')
    update(cpus.children[0], {'compatible': b'qcom,kryo\0ARM,v8\0'})
    if a.cpus == 2:
        props = [(k,v) for k,flags,v in cpus.children[0].props
                 if k not in ('name','AAPL,phandle','clock-frequency')]
        secondary = reference['node']('cpu1', props)
        update(secondary, {'reg': struct.pack('<I',0x100),
                           'cpu-id': struct.pack('<I',1),
                           'cluster-core-id': struct.pack('<I',1),
                           'state': b'waiting\0'})
        cpus.children.append(secondary)
        # The imported static clock-frequency is not a hardware measurement.
        cpus.children[0].props = [(k,f,v) for k,f,v in cpus.children[0].props if k != 'clock-frequency']
        armio = next(c for c in tree.children if c.name == 'arm-io')
        gic = next(c for c in armio.children if c.name == 'gic')
        update(gic, {'redistributor-stride': struct.pack('<Q',0x40000)})
        tree.children.append(reference['node']('psci', [('compatible',b'arm,psci-1.0\0'),('method',b'smc\0')]))
        update(chosen, {'houji,smp-enabled': struct.pack('<I',1)})
    fb = next(c for c in tree.children if c.name == 'sweet-fbcon')
    update(fb, {'reg': struct.pack('<QQ', 0xFC400000, 4800 * 2670),
                'width': struct.pack('<I', 1200), 'height': struct.pack('<I', 2670),
                'stride': struct.pack('<I', 4800)})
    tree.children += [reference['node']('options'), reference['node']('aliases')]
    blob = adt.serialize(tree)
    parsed, used = adt.parse(blob)
    if used != len(blob) or parsed.name != 'device-tree':
        raise ValueError('ADT did not round-trip')
    if any(name in blob for name in [b'0xd5100000', b'oneplus,', b'xiaomi,vermeer', b'ufs\0', b'gpu\0']):
        raise ValueError('Foreign hardware in the first-entry tree')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(blob)
    print(f'{len(blob)}-byte houji ADT (GUI={a.ios_gui}): {a.cpus} CPU(s); framebuffer FC400000 / 1200x2670; {a.memory_mib} MiB owned window; volatile 8 KiB CHRP bank.')


if __name__ == '__main__':
    main()
