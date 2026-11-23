#!/usr/bin/env python3
"""Check exact OEM staging, real provider GUIDs and no storage-driver closure."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import uuid


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--staged', type=Path, required=True)
    p.add_argument('--previous', type=Path, required=True)
    p.add_argument('--env', type=Path, required=True)
    a = p.parse_args()
    record = json.loads((a.staged / 'manifest.json').read_text())
    previous = json.loads(a.previous.read_text())
    modules = record['modules']
    assert record['profile'] == 'storage-services'
    assert modules[:14] == previous['modules']
    assert [m['name'] for m in modules[-2:]] == ['HALIOMMU', 'ICBDxe']
    assert len(modules) == 16 and all(not m['patched'] for m in modules)
    assert not any('ufs' in m['name'].lower() for m in modules)
    for m in modules:
        assert hashlib.sha256((a.staged / (m['name'] + '.efi')).read_bytes()).hexdigest() == m['sha256']
    expected = [('HALIOMMU', 'b1f87ae01b46daea3bd738c1452c606ab755e73b78d6c79d2e41e899d8fdcb45',
                 '54b6d3b4-5d33-4f91-8600-6c41d5deb19a', 0x151c),
                ('ICBDxe', '8170090777e8a1076e4228c14f591411b2688903e01e3ae72ccd5b2d1b1107f7',
                 '5824f9de-17d2-4b1f-a5fe-5eb77fa53093', 0x1474)]
    for name, digest, provider, call in expected:
        b = (a.staged / (name + '.efi')).read_bytes()
        m = next(m for m in modules if m['name'] == name)
        assert m['sha256'] == digest and m['provides'] == provider
        assert b[0xb068:0xb078] == uuid.UUID(provider).bytes_le
        assert struct.unpack_from('<I', b, call)[0] == 0xd63f0100
    env_guid = '0389b776-625f-11eb-83be-c741a913de34'
    hal = (a.staged / 'HALIOMMU.efi').read_bytes()
    env = a.env.read_bytes()
    assert hal[0xb098:0xb0a8] == env[0xf1c8:0xf1d8] == uuid.UUID(env_guid).bytes_le
    assert struct.unpack_from('<I', env, 0x2c5c)[0] == 0xd63f0100
    assert env_guid in modules[-2]['requirements']
    s = importlib.util.spec_from_file_location('stage', Path(__file__).resolve().parents[1] / 'scripts/stage-oem-services.py')
    stage = importlib.util.module_from_spec(s)
    s.loader.exec_module(stage)
    for malformed in (b'\x07\x08', b'\x02\x00\x08', b'\x03\x08', b'\x06\x08\x08'):
        try:
            stage.conjunction(malformed)
        except ValueError:
            pass
        else:
            raise AssertionError('Malformed DEPEX accepted')
    print('PASS: original 14 modules unchanged; two original providers/Env dependency verified; exact DEPEX gates retained; no UFS driver staged.')


if __name__ == '__main__':
    main()
