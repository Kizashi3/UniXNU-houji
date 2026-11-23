#!/usr/bin/env python3
"""Set numeric ownership on one new local iOS library; no phone access."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

D = Path('${HOUJI_ARTIFACTS}/native-port/ios-userland/native-keyboard-v15')
assert os.geteuid() == 0, 'Use the local sudo prompt; never send passwords in chat.'
plan = json.loads((D / 'preparation.json').read_text())
image, mount = D / 'ios16-desktop.hfsx', D / 'mount'
allowed = {'/Applications/Preferences.app/Preferences',
           '/Applications/Preferences.app/_CodeSignature/CodeResources',
           '/Applications/Preferences.app/HoujiKeyboardGeometry.dylib'}
assert plan['image'] == str(image) and image.stat().st_size == 32 * 1024**3
assert plan['base_sha256'] == '2e391762dfb8e9fd78c902c5f245a8595ecf81ca0ab091e11924e205a5cd4ec7'
assert set(plan['items']) == allowed and sum(not r['existed'] for r in plan['items'].values()) == 1


def attach(ro):
    cmd = ['hdiutil', 'attach', '-nobrowse', '-owners', 'on', '-imagekey',
           'diskimage-class=CRawDiskImage', '-mountpoint', str(mount)]
    if ro:
        cmd.append('-readonly')
    subprocess.run(cmd + [str(image)], check=True)


def detach():
    subprocess.run(['hdiutil', 'detach', str(mount)], check=True)


def check(path, row):
    assert not path.is_symlink() and path.is_file() and path.stat().st_ino == row['inode']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']


attach(False)
try:
    for rel, row in plan['items'].items():
        path = mount / rel.lstrip('/')
        check(path, row)
        assert (row['uid'], row['gid']) == (0, 80) and row['mode'] in (0o664, 0o755, 0o775)
        if not row['existed']:
            assert rel.endswith('/HoujiKeyboardGeometry.dylib')
            os.chown(path, 0, 80)
            os.chmod(path, row['mode'])
finally:
    detach()
attach(True)
try:
    for rel, row in plan['items'].items():
        path = mount / rel.lstrip('/')
        check(path, row)
        st = path.stat()
        assert (st.st_uid, st.st_gid, st.st_mode & 0o777) == (row['uid'], row['gid'], row['mode'])
    for rel, digest in plan['unchanged_runtime'].items():
        assert hashlib.sha256((mount / rel.lstrip('/')).read_bytes()).hexdigest() == digest
    for rel, digest in plan['unchanged_app_files'].items():
        assert hashlib.sha256((mount / 'Applications/Preferences.app' / rel).read_bytes()).hexdigest() == digest
    for path in (mount / 'Applications/Preferences.app', mount / 'Applications/Preferences.app/HoujiKeyboardGeometry.dylib'):
        subprocess.run(['codesign', '--verify', '--strict', str(path)], check=True)
finally:
    detach()
proof = dict(status='PASS', items=3, image_detached=True, read_only_remount_owners_on_verified=True,
             critical_numeric_owners_modes_and_hashes_verified=True, all_modified_inodes_preserved=True,
             codesign_verified=True, phone_accessed=False,
             preparation_sha256=hashlib.sha256((D / 'preparation.json').read_bytes()).hexdigest())
owner = D.stat()
os.chown(image, owner.st_uid, owner.st_gid)
os.chmod(image, 0o400)
proof_path = D / 'owners-finalized.json'
proof_path.write_text(json.dumps(proof, indent=2) + '\n')
os.chown(proof_path, owner.st_uid, owner.st_gid)
print('Keyboard library ownership finalized on the local candidate image only. No phone accessed.')
