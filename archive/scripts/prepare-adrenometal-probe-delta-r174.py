#!/usr/bin/env python3
"""Prepare the bounded r168 probe delta after numeric-owner verification."""
import hashlib
import json
import plistlib
import subprocess
from pathlib import Path

N = Path('${HOUJI_ARTIFACTS}/native-port')
D = N / 'ios-userland/adrenometal-desktop-r174'
BEFORE = '3562340b498bd5e06fac86a0f6debe4a9af943bbd30436fa87d6e0a20dca9f5d'
CHUNK = 134217728


def main():
    preparation = D / 'preparation.json'
    plan = json.loads(preparation.read_text())
    owners = json.loads((D / 'owners-finalized.json').read_text())
    assert owners['status'] == 'PASS' and owners['items'] == 1
    assert all(owners[k] for k in ('read_only_remount_owners_on_verified',
        'critical_numeric_owners_modes_and_hashes_verified', 'all_modified_inodes_preserved', 'codesign_verified', 'image_detached'))
    assert owners['preparation_sha256'] == hashlib.sha256(preparation.read_bytes()).hexdigest()
    assert not owners['phone_accessed'] and not plan['probe_only'] and plan['desktop_selected']
    before = N / 'ios-userland/phone-after-desktop-r173/ios16-phone.hfsx'
    after = D / 'ios16-desktop.hfsx'
    assert plan['base_image'] == str(before) and plan['image'] == str(after)
    assert plan['base_sha256'] == BEFORE and plan['image_bytes'] == 96 * CHUNK
    mounted = plistlib.loads(subprocess.check_output(['hdiutil', 'info', '-plist']))
    assert not any(x.get('image-path') in (str(before), str(after)) for x in mounted['images'])
    chunks = [{'index': i} for i in range(96)]
    digests = {}
    headers = {}
    for name, image in (('before', before), ('after', after)):
        assert not image.is_symlink() and image.stat().st_size == 96 * CHUNK
        whole = hashlib.sha256()
        with image.open('rb') as stream:
            for row in chunks:
                data = stream.read(CHUNK)
                assert len(data) == CHUNK
                if row['index'] == 0:
                    headers[name] = data[:4096]
                whole.update(data)
                row[name] = hashlib.sha256(data).hexdigest()
            assert not stream.read(1)
        digests[name] = whole.hexdigest()
    assert digests['before'] == BEFORE
    for offset, length in ((1024, 4), (1064, 8), (1128, 8)):
        assert headers['before'][offset:offset+length] == headers['after'][offset:offset+length]
    changed = [row['index'] for row in chunks if row['before'] != row['after']]
    assert 1 <= len(changed) <= 32
    result = {'bytes': 96 * CHUNK, 'chunk_bytes': CHUNK,
        'before_image': str(before), 'after_image': str(after),
        'before_sha256': BEFORE, 'after_sha256': digests['after'],
        'changed_chunks': changed, 'chunks': chunks,
        'preparation_sha256': hashlib.sha256(preparation.read_bytes()).hexdigest(),
        'owners_proof_sha256': hashlib.sha256((D / 'owners-finalized.json').read_bytes()).hexdigest(),
        'probe_only': False, 'desktop_selected': True, 'phone_accessed': False}
    output = D / 'delta.json'
    assert not output.exists()
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'delta': str(output), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'before': BEFORE, 'after': digests['after'], 'changed_chunks': changed}, indent=2))


if __name__ == '__main__':
    main()
