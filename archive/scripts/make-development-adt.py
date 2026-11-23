#!/usr/bin/env python3
"""Add the official UniXNU development-board tuple to the pinned GUI ADT.

Only a local ADT copy is written. No production identity, ECID, activation
record, device partition or executable is changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

BASE_SHA = 'bda9f4407bd3d89de5acc9e0b97830d6876d9a08b57128b5140ebef6e77d61fc'
VALUES = {
    'certificate-production-status': 0,
    'effective-production-status-ap': 0,
    'certificate-security-mode': 1,
    'effective-security-mode-sep': 1,
}
SOURCE = ('https://github.com/UniXNU/UniXNU/blob/'
          'bd127c008cdc584b83cf00eaea269e4f1adf3cc8/docs/zh/guide/skip-setup.md')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError('Expected the proven r52 GUI ADT')
    if args.output.exists() or args.output.with_suffix('.json').exists():
        raise ValueError('Output already exists')
    sys.path.insert(0, str(args.reference / 'tools'))
    import adt
    tree, consumed = adt.parse(raw)
    if consumed != len(raw) or adt.serialize(tree) != raw:
        raise ValueError('ADT does not round-trip exactly')
    chosen = [node for node in tree.children if node.name == 'chosen']
    if len(chosen) != 1:
        raise ValueError('Expected one chosen node')
    chosen = chosen[0]
    if any(key in VALUES for key, _, value in chosen.props):
        raise ValueError('Expected missing development-board tuple')
    before = list(chosen.props)
    chosen.props.extend((key, 0, struct.pack('<I', value))
                        for key, value in VALUES.items())
    output = adt.serialize(tree)
    parsed, consumed = adt.parse(output)
    if consumed != len(output):
        raise ValueError('Output ADT not completely parsed')
    result_chosen = next(node for node in parsed.children if node.name == 'chosen')
    for key, value in VALUES.items():
        if result_chosen.prop(key) != struct.pack('<I', value):
            raise ValueError('Output tuple differs')
    result_chosen.props = [entry for entry in result_chosen.props if entry[0] not in VALUES]
    if adt.serialize(parsed) != raw:
        raise ValueError('Unrelated ADT content changed')
    chosen.props = before
    if adt.serialize(tree) != raw:
        raise ValueError('Source ADT changed')
    args.output.write_bytes(output)
    report = {'source': SOURCE, 'input_sha256': BASE_SHA,
              'output_sha256': hashlib.sha256(output).hexdigest(),
              'chosen_added_u32_le': VALUES,
              'all_other_adt_bytes_preserved_after_removal': True,
              'ecid_added': False, 'activation_records_written': False,
              'device_accessed': False}
    args.output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
