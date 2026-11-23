#!/usr/bin/env python3
"""Stage the refreshed metal2vulkan runtime and retained iOS16 adapters on a local clone.

Edits three existing inodes only. Numeric ownership and signatures are checked
again through an owners-enabled read-only mount; this script never opens ADB.
"""
import hashlib,json,os,plistlib,shutil,subprocess
from pathlib import Path
P=Path(__file__).resolve().parents[1]
N=Path('${HOUJI_ARTIFACTS}/native-port')
D=N/'ios-userland/native-sync-v11'
BASE=N/'ios-userland/phone-after-runtime-r201/ios16-phone.hfsx'
BEFORE='fddb1ecc98ce9995854f8b43c1b769a74dd9a55a82a5bab4e0135dfe124a119d'
BUILD=P/'out/adrenometal-sync-v11'
BUNDLE='System/Library/Extensions/NativeAdrenoMetal.bundle'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  while b:=f.read(8*1024**2):h.update(b)
 return h.hexdigest()
def main():
 assert not D.exists() and not BASE.is_symlink() and BASE.stat().st_size==32*1024**3
 assert json.loads((BASE.parent/'backup.json').read_text())['sha256']==BEFORE
 audit=json.loads((BUILD/'target-import-audit/result.json').read_text());assert audit['pass']
 incoming={f'/{BUNDLE}/NativeAdrenoMetal':BUILD/'NativeAdrenoMetal.bundle/NativeAdrenoMetal',
  f'/{BUNDLE}/_CodeSignature/CodeResources':BUILD/'NativeAdrenoMetal.bundle/_CodeSignature/CodeResources',
  '/usr/libexec/houji-wallpaper-bootstrap':P/'out/wallpaper-display-v6/WallpaperBootstrap'}
 for p in incoming.values():assert p.is_file() and not p.is_symlink()
 for row in audit['binaries']:assert sha(P/row['binary'])==row['sha256']
 D.mkdir(mode=0o700);image=D/'ios16-desktop.hfsx';mount=D/'mount';mount.mkdir()
 subprocess.run(['cp','-c',str(BASE),str(image)],check=True);image.chmod(0o600)
 def attach(ro,owners):
  cmd=['hdiutil','attach','-nobrowse','-owners',owners,'-imagekey','diskimage-class=CRawDiskImage','-mountpoint',str(mount)]
  if ro:cmd.append('-readonly')
  subprocess.run(cmd+[str(image)],check=True,capture_output=True)
 def detach():subprocess.run(['hdiutil','detach',str(mount)],check=True,capture_output=True)
 items={};unchanged={}
 # Replay the journal only on this expendable clone.
 attach(False,'off');detach();attach(True,'on')
 try:
  for rel,src in incoming.items():
   p=mount/rel.lstrip('/');st=p.stat();assert p.is_file() and not p.is_symlink() and st.st_uid==st.st_gid==0
   items[rel]=dict(uid=st.st_uid,gid=st.st_gid,mode=st.st_mode&0o777,inode=st.st_ino,before_sha256=sha(p),sha256=sha(src))
  for rel in ['Info.plist','libvulkan_freedreno.dylib']:unchanged[rel]=sha(mount/BUNDLE/rel)
 finally:detach()
 attach(False,'off')
 try:
  for rel,src in incoming.items():
   p=mount/rel.lstrip('/');assert p.stat().st_ino==items[rel]['inode']
   with p.open('wb') as f:f.write(src.read_bytes());f.flush();os.fsync(f.fileno())
 finally:detach()
 attach(True,'on')
 try:
  for rel,row in items.items():
   p=mount/rel.lstrip('/');st=p.stat()
   assert (st.st_uid,st.st_gid,st.st_mode&0o777,st.st_ino)==(row['uid'],row['gid'],row['mode'],row['inode']) and sha(p)==row['sha256']
  for rel,digest in unchanged.items():assert sha(mount/BUNDLE/rel)==digest
  for p in [mount/BUNDLE,mount/'usr/libexec/houji-wallpaper-bootstrap']:subprocess.run(['codesign','--verify','--strict',str(p)],check=True,capture_output=True)
 finally:detach()
 plan=dict(image=str(image),base_image=str(BASE),base_sha256=BEFORE,image_bytes=32*1024**3,items=items,unchanged_bundle_files=unchanged,scope='metal2vulkan 0dfdbcd with retained iOS16/native ASTC adapters; forward caller resource residency and explicit scope barriers; same Turnip and display helper; visual correctness pending hardware',phone_accessed=False,desktop_selected=True,probe_only=False)
 prep=D/'preparation.json';prep.write_text(json.dumps(plan,indent=2)+'\n')
 proof=dict(status='PASS',items=3,image_detached=True,read_only_remount_owners_on_verified=True,critical_numeric_owners_modes_and_hashes_verified=True,all_modified_inodes_preserved=True,codesign_verified=True,phone_accessed=False,preparation_sha256=sha(prep))
 (D/'owners-finalized.json').write_text(json.dumps(proof,indent=2)+'\n');image.chmod(0o400);print(json.dumps(proof,indent=2))
if __name__=='__main__':main()
