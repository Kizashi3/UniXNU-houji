#!/usr/bin/env python3
"""Restore only original Settings files on a fresh post-trial root clone."""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

N = Path('${HOUJI_ARTIFACTS}/native-port')
D = N / 'ios-userland/native-keyboard-restore-v15'
BASE = N / 'ios-userland/phone-after-native-r211/ios16-phone.hfsx'
ORIGINAL = N / 'ios-userland/phone-after-native-r210/inspect-root'
TRIAL = N / 'ios-userland/native-keyboard-v15'
APP = '/Applications/Preferences.app/'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-backup-sha256', required=True)
    args = parser.parse_args()
    backup = json.loads((BASE.parent / 'backup.json').read_text())
    assert backup['sha256'] == args.expected_backup_sha256
    assert backup['every_output_chunk_matches_device'] and backup['phone_chunk_index_stable']
    assert not BASE.is_symlink() and BASE.stat().st_size == 32 * 1024**3 and not D.exists()
    trial = json.loads((TRIAL / 'preparation.json').read_text())
    # The original Apple resource envelope uses obsolete omit rules. Check its
    # code signature separately, then compare EVERY restored app resource with
    # the immutable preimage rather than replacing the original signature.
    subprocess.run(['codesign', '--verify', '--ignore-resources', str(ORIGINAL / APP.lstrip('/'))], check=True, capture_output=True)
    restored = [APP + 'Preferences', APP + '_CodeSignature/CodeResources']
    removed = APP + 'HoujiKeyboardGeometry.dylib'
    for rel in restored:
        assert sha(ORIGINAL / rel.lstrip('/')) == trial['items'][rel]['before_sha256']
    D.mkdir(mode=0o700)
    image, mount = D / 'ios16-desktop.hfsx', D / 'mount'
    mount.mkdir()
    subprocess.run(['cp', '-c', str(BASE), str(image)], check=True)
    image.chmod(0o600)

    def attach(ro, owners):
        cmd = ['hdiutil', 'attach', '-nobrowse', '-owners', owners, '-imagekey',
               'diskimage-class=CRawDiskImage', '-mountpoint', str(mount)]
        if ro:
            cmd.append('-readonly')
        subprocess.run(cmd + [str(image)], check=True, capture_output=True)

    def detach():
        subprocess.run(['hdiutil', 'detach', str(mount)], check=True, capture_output=True)

    attach(False, 'off')
    detach()
    items = {}
    attach(True, 'on')
    try:
        for rel in restored + [removed]:
            path = mount / rel.lstrip('/')
            st = path.stat()
            old = trial['items'][rel]
            assert not path.is_symlink() and (st.st_uid, st.st_gid, st.st_mode & 0o777) == (old['uid'], old['gid'], old['mode'])
            assert sha(path) == old['sha256']
            items[rel] = dict(uid=st.st_uid, gid=st.st_gid, mode=st.st_mode & 0o777,
                              inode=st.st_ino, before_sha256=sha(path),
                              sha256=old.get('before_sha256'), deleted=rel == removed)
    finally:
        detach()
    attach(False, 'off')
    try:
        for rel in restored:
            path = mount / rel.lstrip('/')
            with path.open('wb') as stream:
                stream.write((ORIGINAL / rel.lstrip('/')).read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
        path = mount / removed.lstrip('/')
        assert sha(path) == trial['items'][removed]['sha256']
        path.unlink()
    finally:
        detach()
    attach(True, 'on')
    try:
        for rel in restored:
            path = mount / rel.lstrip('/')
            row = items[rel]
            st = path.stat()
            assert (st.st_uid, st.st_gid, st.st_mode & 0o777, st.st_ino) == (row['uid'], row['gid'], row['mode'], row['inode'])
            assert sha(path) == row['sha256']
        assert not (mount / removed.lstrip('/')).exists()
        for rel, digest in trial['unchanged_runtime'].items():
            assert sha(mount / rel.lstrip('/')) == digest
        for rel, digest in trial['unchanged_app_files'].items():
            assert sha(mount / APP.lstrip('/') / rel) == digest
        original_app = ORIGINAL / APP.lstrip('/')
        restored_app = mount / APP.lstrip('/')
        assert {str(f.relative_to(restored_app)): sha(f) for f in restored_app.rglob('*') if f.is_file()} == {str(f.relative_to(original_app)): sha(f) for f in original_app.rglob('*') if f.is_file()}
        subprocess.run(['codesign', '--verify', '--ignore-resources', str(restored_app)], check=True, capture_output=True)
    finally:
        detach()
    plan = dict(image=str(image), base_image=str(BASE), base_sha256=backup['sha256'], image_bytes=32 * 1024**3,
                items=items, unchanged_runtime=trial['unchanged_runtime'], probe_only=False, desktop_selected=True,
                scope='Restore original Settings executable/signature; remove failed v15 library; retain post-trial user data and logs', phone_accessed=False)
    prep = D / 'preparation.json'
    prep.write_text(json.dumps(plan, indent=2) + '\n')
    proof = dict(status='PASS', items=3, image_detached=True, read_only_remount_owners_on_verified=True,
                 critical_numeric_owners_modes_and_hashes_verified=True, restored_inodes_preserved=True,
                 codesign_verified=True, signature_check='code pages; all app resources byte-identical to original snapshot', phone_accessed=False, preparation_sha256=sha(prep))
    (D / 'owners-finalized.json').write_text(json.dumps(proof, indent=2) + '\n')
    image.chmod(0o400)
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
