#!/usr/bin/env python3
"""Stage the Settings-only keyboard trial on a clone of the verified r210 root."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')
D = N / 'ios-userland/native-keyboard-v15'
BASE = N / 'ios-userland/phone-after-native-r210/ios16-phone.hfsx'
BEFORE = '2e391762dfb8e9fd78c902c5f245a8595ecf81ca0ab091e11924e205a5cd4ec7'
BUILD = P / 'out/keyboard-compat-v15'
APP = 'Applications/Preferences.app'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not D.exists() and not BASE.is_symlink() and BASE.stat().st_size == 32 * 1024**3
    assert json.loads((BASE.parent / 'backup.json').read_text())['sha256'] == BEFORE
    build = json.loads((BUILD / 'build-result.json').read_text())
    audit = json.loads((BUILD / 'target-import-audit/result.json').read_text())
    assert audit['pass'] and build['original_entitlements_preserved']
    assert len(audit['binaries']) == 1 and sha(P / audit['binaries'][0]['binary']) == audit['binaries'][0]['sha256']
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

    items, runtime = {}, {}
    attach(False, 'off')
    detach()
    attach(True, 'on')
    try:
        assert sha(mount / APP / 'Preferences') == build['original_executable_sha256']
        for rel, digest in build['changed_files'].items():
            path = mount / APP / rel
            assert sha(BUILD / 'Preferences.app' / rel) == digest
            if path.exists():
                st = path.stat()
                assert not path.is_symlink() and path.is_file() and (st.st_uid, st.st_gid) == (0, 80)
                items['/' + APP + '/' + rel] = dict(existed=True, before_sha256=sha(path),
                    uid=st.st_uid, gid=st.st_gid, mode=st.st_mode & 0o777, inode=st.st_ino, sha256=digest)
            else:
                assert rel == 'HoujiKeyboardGeometry.dylib'
                items['/' + APP + '/' + rel] = dict(existed=False, uid=0, gid=80, mode=0o755, sha256=digest)
        for rel in ['System/Library/Extensions/NativeAdrenoMetal.bundle/NativeAdrenoMetal',
                    'System/Library/Extensions/NativeAdrenoMetal.bundle/libvulkan_freedreno.dylib',
                    'System/Library/Extensions/NativeAdrenoMetal.clients', 'usr/libexec/houji-wallpaper-bootstrap']:
            runtime['/' + rel] = sha(mount / rel)
        for rel, digest in build['unchanged_files'].items():
            assert sha(mount / APP / rel) == digest
    finally:
        detach()
    attach(False, 'off')
    try:
        for rel, row in items.items():
            path = mount / rel.lstrip('/')
            if row['existed']:
                assert path.stat().st_ino == row['inode']
            with path.open('wb') as stream:
                stream.write((BUILD / 'Preferences.app' / path.relative_to(mount / APP)).read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            row['inode'] = path.stat().st_ino
            if not row['existed']:
                path.chmod(row['mode'])
            assert sha(path) == row['sha256']
        subprocess.run(['codesign', '--verify', '--strict', str(mount / APP)], check=True, capture_output=True)
        for rel, digest in runtime.items():
            assert sha(mount / rel.lstrip('/')) == digest
    finally:
        detach()
    plan = dict(image=str(image), base_image=str(BASE), base_sha256=BEFORE, image_bytes=32 * 1024**3,
                items=items, unchanged_runtime=runtime, unchanged_app_files=build['unchanged_files'],
                scope=build['scope'], phone_accessed=False, desktop_selected=True, probe_only=False,
                original_entitlements_preserved=True, build_result_sha256=sha(BUILD / 'build-result.json'))
    (D / 'preparation.json').write_text(json.dumps(plan, indent=2) + '\n')
    print(json.dumps(dict(status='staged-needs-numeric-owner-finalization', items=len(items),
                         new_files=sum(not r['existed'] for r in items.values()), phone_accessed=False), indent=2))


if __name__ == '__main__':
    main()
