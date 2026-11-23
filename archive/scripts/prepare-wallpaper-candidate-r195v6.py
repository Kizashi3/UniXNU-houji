#!/usr/bin/env python3
"""Install only a bounded cache fallback in the existing signed Metal bundle.

The executable and existing resource seal change, numeric owners/inodes stay.
Rust, Turnip, framework enablement, kernel and boot firmware are unchanged.
No phone access; a separately pinned delta handles the device installation.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

P=Path(__file__).resolve().parents[1]
N=Path('${HOUJI_ARTIFACTS}/native-port')
D=N/'ios-userland/wallpaper-bootstrap-r195v6'
BASE=N/'ios-userland/phone-after-wallpaper-v5/ios16-phone.hfsx'
BEFORE='f4493e1b514e359a00566a7ac9f15abefc0450ea1ec7922042c086b142597051'
BUILD=P/'out/adrenometal-wallpaper-cache-v6'
PREFIX='/System/Library/Extensions/NativeAdrenoMetal.bundle'
CHANGED=('NativeAdrenoMetal','_CodeSignature/CodeResources')


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(8*1024**2):h.update(block)
    return h.hexdigest()


def main():
    assert not D.exists() and not BASE.is_symlink()
    assert BASE.stat().st_size==12884901888 and sha(BASE)==BEFORE
    assert json.loads((BASE.parent/'backup.json').read_text())['sha256']==BEFORE
    audit=json.loads((BUILD/'target-import-audit/result.json').read_text())
    exe=BUILD/'NativeAdrenoMetal.bundle/NativeAdrenoMetal'
    assert audit['pass'] and audit['binaries'][0]['sha256']==sha(exe)
    D.mkdir(mode=0o700);image=D/'ios16-desktop.hfsx';mount=D/'mount';mount.mkdir()
    subprocess.run(['/bin/cp','-c',str(BASE),str(image)],check=True);os.chmod(image,0o600)

    def attach(readonly,owners):
        cmd=['hdiutil','attach','-nobrowse','-owners',owners,'-imagekey',
             'diskimage-class=CRawDiskImage','-mountpoint',str(mount)]
        if readonly:cmd.append('-readonly')
        subprocess.run(cmd+[str(image)],check=True,capture_output=True)

    def detach():subprocess.run(['hdiutil','detach',str(mount)],check=True,capture_output=True)

    attach(False,'off');detach();attach(True,'on');items={}
    try:
        root=mount/PREFIX.lstrip('/');incoming=BUILD/'NativeAdrenoMetal.bundle'
        for rel in CHANGED:
            f=root/rel;st=f.stat()
            assert f.is_file() and not f.is_symlink() and (st.st_uid,st.st_gid)==(0,0)
            items[PREFIX+'/'+rel]=dict(uid=st.st_uid,gid=st.st_gid,mode=st.st_mode&0o7777,inode=st.st_ino)
            backup=D/'original'/rel;backup.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,backup)
        assert sha(root/'NativeAdrenoMetal')=='545e94ee41ec3fcf5e68d9b94280675748c83c5253c469dc92c89bb2f2984413'
        fixed={str(f.relative_to(root)):sha(f) for f in root.rglob('*') if f.is_file() and str(f.relative_to(root)) not in CHANGED}
        assert all(sha(incoming/rel)==value for rel,value in fixed.items())
        cache=mount/'private/var/mobile/Library/Caches';st=cache.stat()
        assert not cache.is_symlink() and (st.st_uid,st.st_mode&0o7777)==(501,0o700)
        assert (mount/'System/Library/Extensions/NativeAdrenoMetal.clients').read_bytes()==b'backboardd\nPosterBoard\nCollectionsPoster\nAegirPoster\n'
        crash=mount/'private/var/mobile/Library/Logs/CrashReporter'
        index={}
        for f in crash.iterdir():
            if f.is_file():
                index[f.name]=sha(f)
                if any(x in f.name.lower() for x in ('photos','mobileslide','poster')):
                    q=D/'reports-before'/f.name;q.parent.mkdir(exist_ok=True);shutil.copy2(f,q)
        (D/'crash-file-index.json').write_text(json.dumps(index,indent=2)+'\n')
    finally:detach()
    attach(False,'off')
    try:
        for rel in CHANGED:(mount/PREFIX.lstrip('/')/rel).write_bytes((incoming/rel).read_bytes())
    finally:detach()
    attach(True,'on')
    try:
        root=mount/PREFIX.lstrip('/')
        for rel,v in items.items():
            f=mount/rel.lstrip('/');st=f.stat()
            assert (st.st_uid,st.st_gid,st.st_mode&0o7777,st.st_ino)==(v['uid'],v['gid'],v['mode'],v['inode'])
            v['sha256']=sha(f)
        assert all(sha(root/rel)==value for rel,value in fixed.items())
        subprocess.run(['codesign','--verify','--strict',str(root)],check=True)
    finally:detach()
    plan=dict(image=str(image),base_image=str(BASE),base_sha256=BEFORE,image_bytes=image.stat().st_size,
        items=items,probe_only=False,desktop_selected=True,phone_accessed=False,
        unchanged_bundle_files=fixed,cache_parent_numeric_owner=501,cache_parent_mode=0o700,
        build_audit_sha256=sha(BUILD/'target-import-audit/result.json'),
        scope='Observed no-cachedir failure: per-process owned mobile cache fallback and first-problem marker; exact same Rust/Turnip/kernel/firmware')
    (D/'preparation.json').write_text(json.dumps(plan,indent=2)+'\n')
    proof=dict(status='PASS',items=2,image_detached=True,read_only_remount_owners_on_verified=True,
        critical_numeric_owners_modes_and_hashes_verified=True,all_modified_inodes_preserved=True,
        codesign_verified=True,phone_accessed=False,preparation_sha256=sha(D/'preparation.json'))
    (D/'owners-finalized.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(plan,indent=2))


if __name__=='__main__':main()
