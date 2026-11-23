#!/usr/bin/env python3
"""Stage reference-derived iOS16 clients/PNG resources and bounded Metal logs.

Only a local clone is edited. The complete, immutable device preimage retains
all removed historical trace files. A separate owner finalizer and pinned delta
are required before installation. Firmware, kernel, Rust and Turnip stay fixed.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess

P=Path(__file__).resolve().parents[1]
N=Path('${HOUJI_ARTIFACTS}/native-port')
D=N/'ios-userland/wallpaper-bootstrap-r195v7'
BASE=N/'ios-userland/phone-after-wallpaper-v6/ios16-phone.hfsx'
BEFORE='3ce6cfced23e9b80912c09b21a4c8bcf54e6954524e517400aef986a06a2b918'
RES=N/'ios-userland/wallpaper-resources-v7-corrected'
BUILD=P/'out/adrenometal-apps-v7'
BUNDLE='System/Library/Extensions/NativeAdrenoMetal.bundle'
CLIENTS='System/Library/Extensions/NativeAdrenoMetal.clients'
# Names verified against this owner's iOS16 image. WidgetRenderer_Default and
# iOS18-only providers from the reference are deliberately absent. MobileSlideShow
# is the owner's additional reported black-screen application, recorded as such.
NAMES=['backboardd','iconservicesagent','PosterBoard','SBRendererService',
       'AegirPoster','CollectionsPoster','PhotosPosterProvider',
       'GradientPosterExtension','EmojiPosterExtension','ExtragalacticPoster',
       'PridePosterExtension','MobileSlideShow']


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(8*1024**2):h.update(block)
    return h.hexdigest()


def main():
    assert not D.exists() and not BASE.is_symlink()
    assert BASE.stat().st_size==12884901888 and sha(BASE)==BEFORE
    assert json.loads((BASE.parent/'backup.json').read_text())['sha256']==BEFORE
    resources=json.loads((RES/'manifest.json').read_text())
    audit=json.loads((BUILD/'target-import-audit/result.json').read_text())
    assert audit['pass'] and audit['binaries'][0]['sha256']==sha(BUILD/'NativeAdrenoMetal.bundle/NativeAdrenoMetal')
    assert len(resources['images'])==48 and len(resources['modified_existing'])==18
    D.mkdir(mode=0o700);image=D/'ios16-desktop.hfsx';mount=D/'mount';mount.mkdir()
    subprocess.run(['/bin/cp','-c',str(BASE),str(image)],check=True);os.chmod(image,0o600)
    def attach(ro,owners):
        cmd=['hdiutil','attach','-nobrowse','-owners',owners,'-imagekey',
             'diskimage-class=CRawDiskImage','-mountpoint',str(mount)]
        if ro:cmd.append('-readonly')
        subprocess.run(cmd+[str(image)],check=True,capture_output=True)
    def detach():subprocess.run(['hdiutil','detach',str(mount)],check=True,capture_output=True)
    items={};deleted=[];incoming={}
    attach(False,'off')
    try:
        # These original root-owned log directories are intentionally private.
        # Read their inventory with owners disabled, then inspect public asset
        # metadata separately with numeric ownership enabled.
        for f in sorted((mount/'private/var/db/diagnostics').rglob('*.tracev3')):
            assert f.is_file() and not f.is_symlink()
            deleted.append(dict(path='/'+str(f.relative_to(mount)),sha256=sha(f),bytes=f.stat().st_size))
        assert len(deleted)==73 and sum(x['bytes'] for x in deleted)==166139184
    finally:detach()
    attach(True,'on')
    try:
        for rel in ('NativeAdrenoMetal','_CodeSignature/CodeResources'):
            incoming['/'+BUNDLE+'/'+rel]=(BUILD/'NativeAdrenoMetal.bundle'/rel).read_bytes()
        incoming['/'+CLIENTS]=('\n'.join(NAMES)+'\n').encode()
        assert (mount/CLIENTS).read_bytes()==b'backboardd\nPosterBoard\nCollectionsPoster\nAegirPoster\n'
        assert sha(mount/BUNDLE/'NativeAdrenoMetal')=='1de426a048a8c14295a2b5e3f14c908a8ef80d1ec3b66cd0f4f9e4663e0b66ed'
        for row in resources['modified_existing']:
            f=mount/row['path'].lstrip('/');assert sha(f)==row['before_sha256']
            incoming[row['path']]=(RES/row['path'].lstrip('/')).read_bytes()
        for rel,data in incoming.items():
            f=mount/rel.lstrip('/');st=f.stat()
            assert f.is_file() and not f.is_symlink() and (st.st_uid,st.st_gid)==(0,0)
            items[rel]=dict(uid=st.st_uid,gid=st.st_gid,mode=st.st_mode&0o7777,
                            inode=st.st_ino,existed=True,before_sha256=sha(f),sha256=hashlib.sha256(data).hexdigest())
        for row in resources['images']:
            rel=row['path'];f=mount/rel.lstrip('/')
            assert not f.exists() and f.parent.is_dir() and not f.parent.is_symlink()
            assert sha(mount/row['source'].lstrip('/'))==row['source_sha256']
            data=(RES/rel.lstrip('/')).read_bytes();assert hashlib.sha256(data).hexdigest()==row['sha256']
            incoming[rel]=data;items[rel]=dict(uid=0,gid=0,mode=0o644,existed=False,sha256=row['sha256'])
        framework=plistlib.loads((mount/'System/Library/FeatureFlags/Domain/ExtensionKit.plist').read_bytes())
        assert framework['enforce_xpc_cache_code_signing']['Enabled'] is False
    finally:detach()
    attach(False,'off')
    try:
        for row in deleted:
            f=mount/row['path'].lstrip('/');assert sha(f)==row['sha256'];f.unlink()
        for rel,data in incoming.items():
            f=mount/rel.lstrip('/');f.write_bytes(data)
            if not items[rel]['existed']:os.chmod(f,0o644);items[rel]['inode']=f.stat().st_ino
        space=shutil.disk_usage(mount);assert space.free>=180*1024**2
    finally:detach()
    plan=dict(image=str(image),base_image=str(BASE),base_sha256=BEFORE,image_bytes=image.stat().st_size,
        items=items,deleted_archived_traces=deleted,deleted_bytes=sum(x['bytes'] for x in deleted),
        free_bytes_after_staging=space.free,reference_clients=NAMES,
        references=['https://github.com/markakash/UniXNU-ishtar/blob/901611d6e51b2f84f7755f72ba3762c816727395/gpu/NativeAdrenoMetal.clients',resources['reference']],
        resources_manifest_sha256=sha(RES/'manifest.json'),build_audit_sha256=sha(BUILD/'target-import-audit/result.json'),
        probe_only=False,desktop_selected=True,phone_accessed=False,
        scope='iOS16-compatible named clients, original wallpaper HEIC decoded to PNG, per-client bounded initialization logs; historical tracev3 retained in full immutable preimage')
    (D/'preparation.json').write_text(json.dumps(plan,indent=2)+'\n')
    print(json.dumps(dict(candidate=str(D),items=len(items),new_PNGs=48,animations=18,
        archived_trace_bytes=plan['deleted_bytes'],free_bytes=space.free,phone_accessed=False),indent=2))


if __name__=='__main__':main()
