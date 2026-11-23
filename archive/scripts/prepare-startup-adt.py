#!/usr/bin/env python3
"""Add only the development Wi-Fi identity used by MobileGestalt startup queries.

This is a stable, locally administered unicast address, not an assertion that
the real Wi-Fi transport is implemented. All other ADT bytes remain identical
when this property is removed again.
"""
from pathlib import Path
import hashlib
import json
import sys

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')
sys.path.insert(0, str(P / '.cache/ios16-reference/vermeer/tools'))
import adt


def main():
    source = N / 'native-ios-candidate/houji-ios-gui-uuid8192-smp2.adt'
    output = source.with_name('houji-ios-gui-uuid8192-smp2-startup.adt')
    raw = source.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '3bdf42fdbdd632da1e41b069fdc5fbc7d981b32deb6b2115a2bab81dcf141624'
    assert not output.exists()
    tree, used = adt.parse(raw)
    assert used == len(raw) and adt.serialize(tree) == raw
    chosen = next(c for c in tree.children if c.name == 'chosen')
    uuid = chosen.prop('houji,platform-uuid')
    assert uuid == bytes.fromhex('f6b7985753055df19514f0a1dbe6092e')
    assert chosen.prop('mac-address-wifi0') is None
    address = bytearray(hashlib.sha256(b'houji-native-ios-development-wifi-v1' + uuid).digest()[:6])
    address[0] = (address[0] & 0xfe) | 2
    assert len(address) == 6 and address[0] & 3 == 2
    chosen.props.append(('mac-address-wifi0', 0, bytes(address)))
    result = adt.serialize(tree)
    parsed, used = adt.parse(result)
    assert used == len(result)
    verify = next(c for c in parsed.children if c.name == 'chosen')
    assert verify.prop('mac-address-wifi0') == bytes(address)
    verify.props = [(k, f, v) for k, f, v in verify.props if k != 'mac-address-wifi0']
    assert adt.serialize(parsed) == raw
    output.write_bytes(result)
    report = {'sha256': hashlib.sha256(result).hexdigest(), 'source_sha256': hashlib.sha256(raw).hexdigest(),
              'only_changed_property': '/chosen/mac-address-wifi0', 'locally_administered_unicast': True,
              'derivation': 'SHA256 of explicit development namespace and existing houji platform UUID',
              'wifi_driver_or_networking_claimed': False,
              'reference': 'tycykp/UniXNU-OnePlus-Ace5 hardware/ios16-service-repair.json at aaa100d19f6fb14e5897a7e496edf7838d4d4e9f'}
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
