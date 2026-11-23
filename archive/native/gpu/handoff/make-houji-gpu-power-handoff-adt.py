#!/usr/bin/env python3
"""Reserve one zero scalar slot in the proven houji ADT; candidate only.

No UEFI or device access. Removing the added property and restoring its node's
property count must reproduce the complete input byte for byte.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

PROPERTY = 'houji,gpu-power-handoff'
RECORD_BYTES = 1376
SOURCE_SHA256 = '8e7171047186064d9dab59fdf8cce78b657661364356977f020880f515f1ae4b'
DEFAULT_INPUT = Path('${HOUJI_ARTIFACTS}/native-port/native-ios-candidate/houji-ios-gui-uuid8192-smp8-fullscreen.adt')
MAX_BYTES, MAX_DEPTH, MAX_PROPERTIES = 1048576, 64, 256


def strict_name(value, property_name=False):
    if not value or b'\0' not in value:
        raise ValueError('Missing name terminator')
    text, tail = value.split(b'\0', 1)
    if not text or any(c < 0x21 or c > 0x7e or c == ord('/') for c in text):
        raise ValueError('Noncanonical name')
    if (any(tail) if property_name else bool(tail)):
        raise ValueError('Trailing bytes in name')
    return text.decode('ascii')


def parse(raw):
    """Strict, bounded wire reader. Offsets refer directly to original bytes."""
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('ADT size limit')
    nodes, offset = [], 0

    def node(depth):
        nonlocal offset
        if depth > MAX_DEPTH or len(raw) - offset < 8:
            raise ValueError('Node bounds/depth')
        start = offset
        count, children = struct.unpack_from('<II', raw, offset)
        offset += 8
        if count > MAX_PROPERTIES or count > (len(raw) - offset) // 36:
            raise ValueError('Property count')
        props, seen, name = [], set(), None
        for _ in range(count):
            if len(raw) - offset < 36:
                raise ValueError('Property header')
            header = offset
            key = strict_name(raw[offset:offset + 32], True)
            if key in seen:
                raise ValueError('Duplicate property')
            seen.add(key)
            length, = struct.unpack_from('<I', raw, offset + 32)
            offset += 36
            if length & 0x80000000:
                raise ValueError('Property flags')
            padded = (length + 3) & ~3
            if padded > len(raw) - offset or any(raw[offset + length:offset + padded]):
                raise ValueError('Property bounds/padding')
            value = raw[offset:offset + length]
            if key == 'name':
                if length > 256:
                    raise ValueError('Node name length')
                name = strict_name(value)
            props.append({'key': key, 'header': header, 'offset': offset,
                          'bytes': length, 'value': value, 'end': offset + padded})
            offset += padded
        if name is None or (depth == 0 and name != 'device-tree'):
            raise ValueError('Node name/root')
        if children > (len(raw) - offset) // 8:
            raise ValueError('Child count')
        result = {'start': start, 'depth': depth, 'name': name, 'props': props,
                  'props_end': offset, 'children': []}
        nodes.append(result)
        for _ in range(children):
            result['children'].append(node(depth + 1))
        result['end'] = offset
        return result

    root = node(0)
    if offset != len(raw):
        raise ValueError('Trailing ADT data')
    chosen = [n for n in nodes if n['name'] == 'chosen']
    if len(chosen) != 1 or chosen[0]['depth'] != 1:
        raise ValueError('Exactly one /chosen required')
    return root, nodes, chosen[0]


def generate(raw):
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError('Input is not the pinned eight-core/fullscreen ADT')
    _, nodes, chosen = parse(raw)
    if any(p['key'] == PROPERTY for n in nodes for p in n['props']):
        raise ValueError('Handoff property already exists')
    if len(chosen['props']) == MAX_PROPERTIES:
        raise ValueError('No property capacity')
    property_bytes = PROPERTY.encode('ascii').ljust(32, b'\0')
    property_bytes += struct.pack('<I', RECORD_BYTES) + bytes(RECORD_BYTES)
    insertion = chosen['props_end']
    output = bytearray(raw[:insertion] + property_bytes + raw[insertion:])
    struct.pack_into('<I', output, chosen['start'], len(chosen['props']) + 1)
    _, verify_nodes, verify_chosen = parse(output)
    slots = [(n, p) for n in verify_nodes for p in n['props'] if p['key'] == PROPERTY]
    if len(slots) != 1 or slots[0][0] is not verify_chosen:
        raise ValueError('Generated property placement differs')
    slot = slots[0][1]
    if slot['bytes'] != RECORD_BYTES or any(slot['value']):
        raise ValueError('Generated slot is not exactly zero/1376')
    restored = bytearray(output[:slot['header']] + output[slot['end']:])
    struct.pack_into('<I', restored, verify_chosen['start'], len(verify_chosen['props']) - 1)
    if restored != raw:
        raise ValueError('Other ADT bytes changed')
    return bytes(output), {'source_sha256': SOURCE_SHA256,
        'sha256': hashlib.sha256(output).hexdigest(), 'source_bytes': len(raw),
        'bytes': len(output), 'property': '/chosen/' + PROPERTY,
        'slot_offset': slot['offset'], 'slot_bytes': RECORD_BYTES, 'slot_flags': 0,
        'slot_all_zero': True, 'remove_property_exact_input_roundtrip': True,
        'other_properties_and_padding_byte_identical': True,
        'candidate_only_not_integrated': True, 'uefi_pointers_in_property': False,
        'record_qualification': 'Caller must hph_decode the 1376-byte scalar record before hpa_bind.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report_path = args.report or args.output.with_suffix(args.output.suffix + '.json')
    if args.output.exists() or report_path.exists() or args.output.resolve() == report_path.resolve():
        raise ValueError('Output/report already exists or aliases')
    result, report = generate(args.input.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation never overwrites a candidate or the original tree.
    with args.output.open('xb') as stream:
        stream.write(result)
    with report_path.open('x') as stream:
        stream.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
