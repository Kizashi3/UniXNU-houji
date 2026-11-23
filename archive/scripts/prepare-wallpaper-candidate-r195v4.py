#!/usr/bin/env python3
"""Prepare a recoverable ExtensionKit development-cache compatibility trial.

Only an existing feature-default plist and our existing helper are edited.
Existing numeric owners, modes and inodes must survive owners-off writes.
The original signed cache is independently compared to the owner's IPSW root.
This script never accesses the phone.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')
D = N / 'ios-userland/wallpaper-bootstrap-r195v4'
BEFORE = '73e4834c882f0e12fb9003ed4c5eca41fb9875f8f248a2f43b9e15cb7a7460dc'
BASE = N / 'ios-userland/phone-after-wallpaper-v3/ios16-phone.hfsx'
FLAG = '/System/Library/FeatureFlags/Domain/ExtensionKit.plist'
HELPER = '/usr/libexec/houji-wallpaper-bootstrap'
CACHE = '/System/Library/xpc/extensions.plist'
SIG = CACHE + '.sig'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8 * 1024**2):
            h.update(block)
    return h.hexdigest()


def main():
    assert not D.exists() and not BASE.is_symlink()
    assert BASE.stat().st_size == 12884901888 and digest(BASE) == BEFORE
    assert json.loads((BASE.parent / 'backup.json').read_text())['sha256'] == BEFORE
    D.mkdir(mode=0o700)
    image = D / 'ios16-desktop.hfsx'
    subprocess.run(['/bin/cp', '-c', str(BASE), str(image)], check=True)
    os.chmod(image, 0o600)
    mount = D / 'mount'
    mount.mkdir()

    def attach(readonly, owners):
        command = ['hdiutil', 'attach', '-nobrowse', '-owners', owners,
                   '-imagekey', 'diskimage-class=CRawDiskImage', '-mountpoint', str(mount)]
        if readonly:
            command.append('-readonly')
        subprocess.run(command + [str(image)], check=True, capture_output=True)

    def detach():
        subprocess.run(['hdiutil', 'detach', str(mount)], check=True, capture_output=True)

    # Allow journal replay only on the new local clone, then capture owners-on.
    attach(False, 'off')
    detach()
    attach(True, 'on')
    items = {}
    try:
        for rel in (HELPER, FLAG):
            f = mount / rel.lstrip('/')
            assert f.is_file() and not f.is_symlink()
            st = f.stat()
            assert st.st_uid == 0 and st.st_gid == 0
            items[rel] = dict(uid=st.st_uid, gid=st.st_gid,
                              mode=st.st_mode & 0o7777, inode=st.st_ino)
        original = plistlib.loads((mount / FLAG.lstrip('/')).read_bytes())
        assert original['enforce_xpc_cache_code_signing'] == {'Enabled': True}
        cache_hashes = {}
        for rel in (CACHE, SIG):
            f = mount / rel.lstrip('/')
            reference = N / 'ios-userland/symbol-root' / rel.lstrip('/')
            assert f.read_bytes() == reference.read_bytes()
            cache_hashes[rel] = digest(f)
        assert cache_hashes[CACHE] == 'e92ee2b85cea78e17f951169c674a55d717be53e331a4b0a5a26de8221c095a4'
        assert cache_hashes[SIG] == '39a894877f31d01815758184317b90d21ad30791ec0d818c78d00a74d870ad73'
        assert 'com.apple.posterkit.provider' in plistlib.loads((mount / CACHE.lstrip('/')).read_bytes())
        (D / 'ExtensionKit.original.plist').write_bytes((mount / FLAG.lstrip('/')).read_bytes())
        (D / 'helper.original').write_bytes((mount / HELPER.lstrip('/')).read_bytes())
    finally:
        detach()
    attach(False, 'off')
    try:
        modified = dict(original)
        modified['enforce_xpc_cache_code_signing'] = {'Enabled': False}
        (mount / FLAG.lstrip('/')).write_bytes(plistlib.dumps(modified))
        (mount / HELPER.lstrip('/')).write_bytes((P / 'out/wallpaper-bootstrap/WallpaperBootstrap-v4').read_bytes())
    finally:
        detach()
    attach(True, 'on')
    try:
        actual = plistlib.loads((mount / FLAG.lstrip('/')).read_bytes())
        assert {k:v for k,v in actual.items() if k != 'enforce_xpc_cache_code_signing'} == {
            k:v for k,v in original.items() if k != 'enforce_xpc_cache_code_signing'}
        assert actual['enforce_xpc_cache_code_signing'] == {'Enabled': False}
        for rel, expected in items.items():
            f = mount / rel.lstrip('/')
            st = f.stat()
            assert (st.st_uid, st.st_gid, st.st_mode & 0o7777, st.st_ino) == (
                expected['uid'], expected['gid'], expected['mode'], expected['inode'])
            expected['sha256'] = digest(f)
        for rel, expected in cache_hashes.items():
            assert digest(mount / rel.lstrip('/')) == expected
        subprocess.run(['codesign', '--verify', '--strict', str(mount / HELPER.lstrip('/'))], check=True)
    finally:
        detach()
    preparation = dict(image=str(image), base_image=str(BASE), base_sha256=BEFORE,
        image_bytes=image.stat().st_size, items=items, probe_only=False,
        desktop_selected=True, phone_accessed=False,
        original_signed_cache_unchanged=cache_hashes,
        scope='ExtensionKit cache-only development compatibility flag; OS framework refresh with exact callback ABI; original signed cache unchanged')
    (D / 'preparation.json').write_text(json.dumps(preparation, indent=2) + '\n')
    proof = dict(status='PASS', items=2, image_detached=True,
        read_only_remount_owners_on_verified=True,
        critical_numeric_owners_modes_and_hashes_verified=True,
        all_modified_inodes_preserved=True, codesign_verified=True,
        phone_accessed=False, preparation_sha256=digest(D / 'preparation.json'))
    (D / 'owners-finalized.json').write_text(json.dumps(proof, indent=2) + '\n')
    shutil.copy2(P / 'native/wallpaper/WallpaperBootstrap.m', D / 'WallpaperBootstrap-v4.m')
    print(json.dumps(preparation, indent=2))


if __name__ == '__main__':
    main()
