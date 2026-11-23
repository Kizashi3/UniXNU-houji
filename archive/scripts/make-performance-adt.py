#!/usr/bin/env python3
"""Build a local 2..8-core SMP/native-canvas ADT from the proven r54 tree."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import struct
import sys

BASE_SHA = '22797687bb4d9e3d0df71c7034a5e7961daca563796c3f8dfa4cd97ad95f2541'
FDT_SHA = '04dad3a2a40758525e93109ef17954183500a86c7bdf77973b89e39f97723807'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--live-fdt', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cpus', type=int, choices=range(2, 9), required=True)
    parser.add_argument('--native-display', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / '.cache/ios16-reference/vermeer/tools'))
    import adt
    import fdt
    raw = args.input.read_bytes()
    hardware = args.live_fdt.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA or hashlib.sha256(hardware).hexdigest() != FDT_SHA:
        raise ValueError('Unverified successful ADT or captured hardware')
    if args.output.exists():
        raise ValueError('Output exists')
    tree, used = adt.parse(raw)
    if used != len(raw) or adt.serialize(tree) != raw:
        raise ValueError('ADT round-trip differs')
    hardware, _ = fdt.parse(hardware)
    nodes = dict(hardware.walk())
    cpus = next(node for node in tree.children if node.name == 'cpus')
    if [node.prop('reg') for node in cpus.children] != [struct.pack('<I', x) for x in (0, 0x100)]:
        raise ValueError('Unexpected base CPU topology')

    def walk(node):
        yield node
        for child in node.children:
            yield from walk(child)

    handles = [int.from_bytes(node.prop('AAPL,phandle'), 'little') for node in walk(tree)]
    next_handle = max(handles) + 1

    def update(node, values):
        node.props = [entry for entry in node.props if entry[0] not in values]
        node.props.extend((key, 0, value) for key, value in values.items())

    template = copy.deepcopy(cpus.children[1])
    records = []
    for index in range(args.cpus):
        props = nodes[f'/cpus/cpu@{index * 0x100:x}'].properties
        affinity = fdt.cells(props['reg'])
        domain = fdt.cells(props['qcom,freq-domain'])
        capacity = fdt.cells(props['capacity-dmips-mhz'])
        l2 = fdt.cells(props['next-level-cache'])
        expected_capacity = 1024 if index < 2 else 1792 if index < 7 else 1894
        if (affinity != [0, index * 0x100] or
            domain != [6, (0, 0, 3, 3, 3, 1, 1, 2)[index]] or
            capacity != [expected_capacity] or
            fdt.strings(props['enable-method']) != ['psci']):
            raise ValueError('Captured core layout differs')
        if index >= 2:
            node = copy.deepcopy(template)
            update(node, {'name': f'cpu{index}\0'.encode(),
                          'AAPL,phandle': struct.pack('<I', next_handle)})
            next_handle += 1
            cpus.children.append(node)
        node = cpus.children[index]
        update(node, {'reg': struct.pack('<I', index * 0x100),
                      'cpu-id': struct.pack('<I', index),
                      'cluster-core-id': struct.pack('<I', index),
                      'capacity-dmips-mhz': struct.pack('<I', capacity[0]),
                      'houji,freq-domain': struct.pack('<I', domain[1]),
                      'l2-cache-id': struct.pack('<I', l2[0]),
                      'l3-cache-id': struct.pack('<I', 8),
                      'state': b'running\0' if index == 0 else b'waiting\0'})
        records.append({'logical': index, 'affinity': index * 0x100,
                        'capacity_dmips_mhz': capacity[0], 'frequency_domain': domain[1],
                        'expected_arm_part': 'A520' if index < 2 else 'A720' if index < 7 else 'X4'})
    if args.native_display:
        armio = next(node for node in tree.children if node.name == 'arm-io')
        display = next(node for node in armio.children if node.name == 'disp0')
        update(display, {'canvas-width': struct.pack('<I', 1200),
                         'canvas-height': struct.pack('<I', 2670)})
    output = adt.serialize(tree)
    check, used = adt.parse(output)
    check_handles = [node.prop('AAPL,phandle') for node in walk(check)]
    if used != len(output) or len(check_handles) != len(set(check_handles)):
        raise ValueError('Invalid ADT or duplicate handles')
    args.output.write_bytes(output)
    report = {'input_sha256': BASE_SHA, 'live_fdt_sha256': FDT_SHA,
              'sha256': hashlib.sha256(output).hexdigest(), 'cores': records,
              'native_canvas': [1200, 2670] if args.native_display else [1125, 2436],
              'scheduler_mode': 'conservative SMP; capacity metadata preserved, AMP/DVFS not implemented',
              'development_board_tuple_preserved': True}
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
