#!/usr/bin/env python3
"""Replace two existing renderer files in a local clone; no phone is accessed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')
D = N / 'ios-userland/native-timing-v16'
BASE = N / 'ios-userland/phone-after-native-r219/ios16-phone.hfsx'
BEFORE = '067be678048d70e3e5a1b3e6d64de0dbbe75c48e4591036899de55bd94848836'
BUILD = P / 'out/adrenometal-timing-v16'
BUNDLE = 'System/Library/Extensions/NativeAdrenoMetal.bundle'


def sha(f):
    return hashlib.sha256(f.read_bytes()).hexdigest()


def main():
    assert not D.exists() and BASE.stat().st_size == 32 * 1024**3 and not BASE.is_symlink()
    backup = json.loads((BASE.parent / 'backup.json').read_text())
    assert backup['sha256'] == BEFORE and backup['every_output_chunk_matches_device']
    build = json.loads((BUILD / 'build-result.json').read_text())
    audit = json.loads((BUILD / 'target-import-audit/result.json').read_text())
    assert audit['pass'] and sha(BUILD / 'NativeAdrenoMetal.bundle/NativeAdrenoMetal') == build['plugin_sha256']
    D.mkdir(mode=0o700)
    image, mount = D / 'ios16-desktop.hfsx', D / 'mount'
    mount.mkdir()
    subprocess.run(['cp', '-c', str(BASE), str(image)], check=True)
    image.chmod(0o600)

    def attach(ro, owners):
        args = ['hdiutil', 'attach', '-nobrowse', '-owners', owners, '-imagekey',
                'diskimage-class=CRawDiskImage', '-mountpoint', str(mount)]
        if ro:
            args.append('-readonly')
        subprocess.run(args + [str(image)], check=True, capture_output=True)

    def detach():
        subprocess.run(['hdiutil', 'detach', str(mount)], check=True, capture_output=True)

    incoming = {'/' + BUNDLE + '/' + rel: BUILD / 'NativeAdrenoMetal.bundle' / rel
                for rel in ['NativeAdrenoMetal', '_CodeSignature/CodeResources']}
    unchanged = {}
    keyboard = json.loads((P / 'out/keyboard-unified-v18/build-result.json').read_text())
    for app in keyboard['applications']:
        for rel, row in app['items'].items():
            unchanged['/' + app['app'] + '/' + rel] = row['sha256']
    unchanged['/usr/lib/HoujiKeyboardGeometry.dylib'] = keyboard['library_sha256']
    items = {}
    attach(False, 'off')
    detach()  # Replay only this expendable clone's journal.
    attach(True, 'on')
    try:
        for rel, source in incoming.items():
            f = mount / rel.lstrip('/')
            st = f.stat()
            assert f.is_file() and not f.is_symlink() and st.st_nlink == 1
            assert st.st_uid == st.st_gid == 0
            items[rel] = dict(uid=st.st_uid, gid=st.st_gid, mode=st.st_mode & 0o777,
                              inode=st.st_ino, before_sha256=sha(f), sha256=sha(source))
        assert items['/' + BUNDLE + '/NativeAdrenoMetal']['before_sha256'] == 'fd967838feef4e01f0f83223c254bfc12bd5d0cf58712a76795d8190d40b9915'
        for rel in ['/' + BUNDLE + '/libvulkan_freedreno.dylib', '/' + BUNDLE + '/Info.plist',
                    '/System/Library/Extensions/NativeAdrenoMetal.clients', '/usr/libexec/houji-wallpaper-bootstrap']:
            unchanged[rel] = sha(mount / rel.lstrip('/'))
        for rel, value in unchanged.items():
            assert sha(mount / rel.lstrip('/')) == value, rel
    finally:
        detach()
    attach(False, 'off')
    try:
        for rel, source in incoming.items():
            f = mount / rel.lstrip('/')
            assert f.stat().st_ino == items[rel]['inode']
            with f.open('wb') as stream:
                stream.write(source.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
    finally:
        detach()
    attach(True, 'on')
    try:
        for rel, row in items.items():
            f = mount / rel.lstrip('/')
            st = f.stat()
            assert (st.st_uid, st.st_gid, st.st_mode & 0o777, st.st_ino) == (row['uid'], row['gid'], row['mode'], row['inode'])
            assert sha(f) == row['sha256']
        for rel, value in unchanged.items():
            assert sha(mount / rel.lstrip('/')) == value, rel
        subprocess.run(['codesign', '--verify', '--strict', str(mount / BUNDLE)], check=True, capture_output=True)
    finally:
        detach()
    plan = dict(image=str(image), base_image=str(BASE), base_sha256=BEFORE, image_bytes=32 * 1024**3,
                items=items, unchanged_files=unchanged, build_result_sha256=sha(BUILD / 'build-result.json'),
                keyboard_library_sha256=keyboard['library_sha256'], keyboard_application_count=len(keyboard['applications']),
                scope='Cached command-buffer stage timings and API wall times; mutating transfer getter removed; same translation runtime',
                phone_accessed=False, desktop_selected=True, probe_only=False)
    prep = D / 'preparation.json'
    prep.write_text(json.dumps(plan, indent=2) + '\n')
    proof = dict(status='PASS', items=2, image_detached=True, read_only_remount_owners_on_verified=True,
                 critical_numeric_owners_modes_and_hashes_verified=True, all_modified_inodes_preserved=True,
                 codesign_verified=True, phone_accessed=False, preparation_sha256=sha(prep))
    (D / 'owners-finalized.json').write_text(json.dumps(proof, indent=2) + '\n')
    image.chmod(0o400)
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
