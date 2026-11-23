#!/usr/bin/env python3
"""Enable the original Metal frontend for the observed wallpaper callers only.

One existing external clients file changes; no code or bundle seal changes.
Four named processes match the four existing provider slots. No wildcard.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess

N = Path('${HOUJI_ARTIFACTS}/native-port')
D = N / 'ios-userland/wallpaper-bootstrap-r195v5'
BASE = N / 'ios-userland/phone-after-wallpaper-v4/ios16-phone.hfsx'
BEFORE = '1c1753757114df5458c0b1994fe66454ed50d1532b1f85af7842585d3c32016d'
REL = '/System/Library/Extensions/NativeAdrenoMetal.clients'
CLIENTS = b'backboardd\nPosterBoard\nCollectionsPoster\nAegirPoster\n'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8*1024**2):
            h.update(block)
    return h.hexdigest()


def main():
    assert not D.exists() and not BASE.is_symlink()
    assert BASE.stat().st_size == 12884901888 and sha(BASE) == BEFORE
    assert json.loads((BASE.parent/'backup.json').read_text())['sha256'] == BEFORE
    D.mkdir(mode=0o700)
    image = D/'ios16-desktop.hfsx'
    subprocess.run(['/bin/cp','-c',str(BASE),str(image)],check=True)
    os.chmod(image,0o600)
    mount = D/'mount'
    mount.mkdir()

    def attach(readonly,owners):
        args=['hdiutil','attach','-nobrowse','-owners',owners,'-imagekey',
              'diskimage-class=CRawDiskImage','-mountpoint',str(mount)]
        if readonly: args.append('-readonly')
        subprocess.run(args+[str(image)],check=True,capture_output=True)

    def detach():
        subprocess.run(['hdiutil','detach',str(mount)],check=True,capture_output=True)

    attach(False,'off');detach();attach(True,'on')
    try:
        f=mount/REL.lstrip('/');st=f.stat()
        assert not f.is_symlink() and f.read_bytes()==b'backboardd\n'
        assert (st.st_uid,st.st_gid,st.st_mode&0o7777)==(0,0,0o644)
        item=dict(uid=0,gid=0,mode=0o644,inode=st.st_ino)
        (D/'NativeAdrenoMetal.clients.original').write_bytes(f.read_bytes())
        bundle=mount/'System/Library/Extensions/NativeAdrenoMetal.bundle'
        sealed={str(p.relative_to(bundle)):sha(p) for p in bundle.rglob('*') if p.is_file()}
        for exe,rel in (
            ('PosterBoard','Applications/PosterBoard.app'),
            ('CollectionsPoster','System/Library/PrivateFrameworks/WallpaperKit.framework/PlugIns/CollectionsPoster.appex'),
            ('AegirPoster','System/Library/CoreServices/AegirProxyApp.app/PlugIns/AegirPoster.appex')):
            assert plistlib.loads((mount/rel/'Info.plist').read_bytes())['CFBundleExecutable']==exe
        flag=plistlib.loads((mount/'System/Library/FeatureFlags/Domain/ExtensionKit.plist').read_bytes())
        assert flag['enforce_xpc_cache_code_signing']=={'Enabled':False}
    finally:detach()
    attach(False,'off')
    try:(mount/REL.lstrip('/')).write_bytes(CLIENTS)
    finally:detach()
    attach(True,'on')
    try:
        f=mount/REL.lstrip('/');st=f.stat()
        assert (st.st_uid,st.st_gid,st.st_mode&0o7777,st.st_ino)==(0,0,0o644,item['inode'])
        assert f.read_bytes()==CLIENTS;item['sha256']=sha(f)
        assert {str(p.relative_to(bundle)):sha(p) for p in bundle.rglob('*') if p.is_file()}==sealed
        subprocess.run(['codesign','--verify','--strict',str(bundle)],check=True)
    finally:detach()
    plan=dict(image=str(image),base_image=str(BASE),base_sha256=BEFORE,image_bytes=image.stat().st_size,
        items={REL:item},probe_only=False,desktop_selected=True,phone_accessed=False,
        sealed_frontend_unchanged=sealed,clients=CLIENTS.decode().splitlines(),
        scope='Existing named-client file only; four existing provider slots; no wildcard, code or kernel rebuild')
    (D/'preparation.json').write_text(json.dumps(plan,indent=2)+'\n')
    proof=dict(status='PASS',items=1,image_detached=True,read_only_remount_owners_on_verified=True,
        critical_numeric_owners_modes_and_hashes_verified=True,all_modified_inodes_preserved=True,
        codesign_verified=True,phone_accessed=False,preparation_sha256=sha(D/'preparation.json'))
    (D/'owners-finalized.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(plan,indent=2))


if __name__=='__main__':main()
