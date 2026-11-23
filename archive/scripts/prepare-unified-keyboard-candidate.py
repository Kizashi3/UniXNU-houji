#!/usr/bin/env python3
"""Stage the shared keyboard library and automatically discovered APPL changes locally."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')
D = N / 'ios-userland/native-keyboard-v18'
BASE = N / 'ios-userland/phone-after-native-r213/ios16-phone.hfsx'
BEFORE = '2a1948861436cc0eccba2e96c44a89b7d487d5afe708d3022a5ad5cea28ec89f'
BUILD = P / 'out/keyboard-unified-v18'


def sha(f):
    return hashlib.sha256(f.read_bytes()).hexdigest()


def main():
    assert not D.exists() and not BASE.is_symlink() and BASE.stat().st_size == 32 * 1024**3
    assert json.loads((BASE.parent / 'backup.json').read_text())['sha256'] == BEFORE
    build = json.loads((BUILD / 'build-result.json').read_text())
    audit = json.loads((BUILD / 'target-import-audit/result.json').read_text())
    assert audit['pass'] and audit['binaries'][0]['sha256'] == build['library_sha256']
    assert sha(BUILD / 'HoujiKeyboardGeometry.dylib') == build['library_sha256']
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

    incoming, items, unchanged = {}, {}, {}
    for app in build['applications']:
        for rel, expected in app['items'].items():
            incoming['/' + app['app'] + '/' + rel] = (BUILD / 'apps' / app['app'] / rel, expected)
    incoming[build['load_command']] = (BUILD / 'HoujiKeyboardGeometry.dylib',
                                      dict(before_sha256=None, sha256=build['library_sha256'], uid=0, gid=0, mode=0o755))
    attach(False, 'off')
    detach()
    attach(True, 'on')
    try:
        for rel, (src, expected) in incoming.items():
            f = mount / rel.lstrip('/')
            assert sha(src) == expected['sha256']
            if expected['before_sha256'] is None:
                assert not f.exists()
                items[rel] = dict(existed=False, **expected)
            else:
                st = f.stat()
                assert f.is_file() and not f.is_symlink() and sha(f) == expected['before_sha256']
                assert (st.st_uid, st.st_gid, st.st_mode & 0o777) == (expected['uid'], expected['gid'], expected['mode'])
                items[rel] = dict(existed=True, inode=st.st_ino, replace_shared_inode=st.st_nlink > 1, **expected)
        for rel in ['System/Library/Extensions/NativeAdrenoMetal.bundle/NativeAdrenoMetal',
                    'System/Library/Extensions/NativeAdrenoMetal.bundle/libvulkan_freedreno.dylib',
                    'System/Library/Extensions/NativeAdrenoMetal.clients', 'usr/libexec/houji-wallpaper-bootstrap',
                    'Applications/Preferences.app/HoujiKeyboardGeometry.dylib',
                    'Applications/Spotlight.app/HoujiKeyboardGeometry.dylib']:
            unchanged['/' + rel] = sha(mount / rel)
    finally:
        detach()
    attach(False, 'off')
    try:
        for rel, (src, _) in incoming.items():
            f, row = mount / rel.lstrip('/'), items[rel]
            if row['existed']:
                assert f.stat().st_ino == row['inode']
            if row.get('replace_shared_inode'):
                f.unlink()
            with f.open('wb') as stream:
                stream.write(src.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            row['inode'] = f.stat().st_ino
            if not row['existed'] or row.get('replace_shared_inode'):
                f.chmod(row['mode'])
            assert sha(f) == row['sha256']
        for rel, value in unchanged.items():
            assert sha(mount / rel.lstrip('/')) == value
        for app in build['applications']:
            for rel, value in app['untouched'].items():
                assert sha(mount / app['app'] / rel) == value
            subprocess.run(['codesign', '--verify', '--strict', str(mount / app['app'])], check=True, capture_output=True)
    finally:
        detach()
    plan = dict(image=str(image), base_image=str(BASE), base_sha256=BEFORE, image_bytes=32 * 1024**3,
                items=items, unchanged_runtime=unchanged, applications=build['applications'],
                library_sha256=build['library_sha256'], source_sha256=build['source_sha256'],
                build_result_sha256=sha(BUILD / 'build-result.json'), original_entitlements_preserved=True,
                scope=build['scope'], phone_accessed=False, desktop_selected=True, probe_only=False)
    (D / 'preparation.json').write_text(json.dumps(plan, indent=2) + '\n')
    print(json.dumps(dict(status='staged-needs-numeric-owner-finalization', applications=len(build['applications']),
                         items=len(items), new_files=sum(not r['existed'] for r in items.values()),
                         shared_inodes_isolated=sum(bool(r.get('replace_shared_inode')) for r in items.values()), phone_accessed=False), indent=2))


if __name__ == '__main__':
    main()
