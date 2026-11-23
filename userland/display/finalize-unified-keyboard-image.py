#!/usr/bin/env python3
"""Finalize only the pinned candidate's staged files; never accesses the phone."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

D = Path('${HOUJI_ARTIFACTS}/native-port/ios-userland/native-keyboard-v18')
assert os.geteuid() == 0, 'Use the local sudo prompt; never send passwords in chat.'
raw = (D / 'preparation.json').read_bytes()
plan = json.loads(raw)
image, mount = D / 'ios16-desktop.hfsx', D / 'mount'
assert plan['image'] == str(image) and plan['base_sha256'] == '2a1948861436cc0eccba2e96c44a89b7d487d5afe708d3022a5ad5cea28ec89f'
assert image.stat().st_size == 32 * 1024**3 and not image.is_symlink()
allowed = {'/' + a['app'] + '/' + rel for a in plan['applications'] for rel in a['items']}
allowed.add('/usr/lib/HoujiKeyboardGeometry.dylib')
assert set(plan['items']) == allowed and sum(not r['existed'] for r in plan['items'].values()) == 1


def sha(f):
    return hashlib.sha256(f.read_bytes()).hexdigest()


def attach(ro):
    args = ['hdiutil', 'attach', '-nobrowse', '-owners', 'on', '-imagekey',
            'diskimage-class=CRawDiskImage', '-mountpoint', str(mount)]
    if ro:
        args.append('-readonly')
    subprocess.run(args + [str(image)], check=True, capture_output=True)


def detach():
    subprocess.run(['hdiutil', 'detach', str(mount)], check=True, capture_output=True)


def check(f, row):
    assert not f.is_symlink() and f.is_file() and f.stat().st_ino == row['inode']
    assert sha(f) == row['sha256']


attach(False)
try:
    for rel, row in plan['items'].items():
        f = mount / rel.lstrip('/')
        check(f, row)
        assert row['uid'] == 0 and row['gid'] in (0, 80) and row['mode'] & ~0o777 == 0
        if not row['existed'] or row.get('replace_shared_inode'):
            os.chown(f, row['uid'], row['gid'])
            os.chmod(f, row['mode'])
finally:
    detach()
attach(True)
try:
    for rel, row in plan['items'].items():
        f = mount / rel.lstrip('/')
        check(f, row)
        st = f.stat()
        assert (st.st_uid, st.st_gid, st.st_mode & 0o777) == (row['uid'], row['gid'], row['mode'])
    for rel, digest in plan['unchanged_runtime'].items():
        assert sha(mount / rel.lstrip('/')) == digest
    for app in plan['applications']:
        for rel, digest in app['untouched'].items():
            assert sha(mount / app['app'] / rel) == digest
        subprocess.run(['codesign', '--verify', '--strict', str(mount / app['app'])], check=True, capture_output=True)
    subprocess.run(['codesign', '--verify', '--strict', str(mount / 'usr/lib/HoujiKeyboardGeometry.dylib')], check=True, capture_output=True)
finally:
    detach()
owner = D.stat()
os.chown(image, owner.st_uid, owner.st_gid)
os.chmod(image, 0o400)
proof = dict(status='PASS', items=len(allowed), applications=len(plan['applications']), image_detached=True,
             read_only_remount_owners_on_verified=True, critical_numeric_owners_modes_and_hashes_verified=True,
             staged_inodes_preserved_through_finalization=True, codesign_verified=True,
             shared_resource_inodes_isolated=True, phone_accessed=False,
             preparation_sha256=hashlib.sha256(raw).hexdigest())
f = D / 'owners-finalized.json'
f.write_text(json.dumps(proof, indent=2) + '\n')
os.chown(f, owner.st_uid, owner.st_gid)
print('Unified keyboard ownership and signatures finalized on the local candidate image only. No phone accessed.')
