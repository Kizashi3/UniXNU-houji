#!/usr/bin/env python3
"""Finalize numeric ownership in the prepared local image; never accesses a phone."""
from pathlib import Path
import hashlib,json,os,subprocess

assert os.geteuid()==0,'Use the local sudo prompt. Do not provide passwords in chat.'
d=Path('${HOUJI_ARTIFACTS}/native-port/ios-userland/wallpaper-bootstrap-r195v7')
plan=json.loads((d/'preparation.json').read_text());image=d/'ios16-desktop.hfsx';m=d/'mount'
assert plan['image']==str(image) and image.stat().st_size==12884901888 and len(plan['items'])==69
assert plan['base_sha256']=='3ce6cfced23e9b80912c09b21a4c8bcf54e6954524e517400aef986a06a2b918'
assert sum(not v['existed'] for v in plan['items'].values())==48
new_prefixes=('/Library/Wallpaper/Collections/iOS_16~iphone.wallpaperCollection/',
              '/Library/Wallpaper/Collections/Clownfish~iphone.wallpaperCollection/')
for rel,v in plan['items'].items():
 assert rel.startswith('/') and '..' not in Path(rel).parts and (v['uid'],v['gid'])==(0,0)
 assert v['existed'] or (rel.startswith(new_prefixes) and rel.endswith('.png') and v['mode']==0o644)

def attach(ro):
 args=['hdiutil','attach','-nobrowse','-owners','on','-imagekey','diskimage-class=CRawDiskImage','-mountpoint',str(m)]
 if ro:args.append('-readonly')
 subprocess.run(args+[str(image)],check=True)
def detach():subprocess.run(['hdiutil','detach',str(m)],check=True)
attach(False)
try:
 for rel,v in plan['items'].items():
  f=m/rel.lstrip('/');assert not f.is_symlink() and f.is_file() and f.stat().st_ino==v['inode']
  assert hashlib.sha256(f.read_bytes()).hexdigest()==v['sha256']
  if not v['existed']:os.chown(f,v['uid'],v['gid']);os.chmod(f,v['mode'])
 subprocess.run(['codesign','--verify','--strict',str(m/'System/Library/Extensions/NativeAdrenoMetal.bundle')],check=True)
finally:detach()
attach(True)
try:
 for rel,v in plan['items'].items():
  f=m/rel.lstrip('/');st=f.stat()
  assert (st.st_uid,st.st_gid,st.st_mode&0o7777)==(v['uid'],v['gid'],v['mode'])
  assert st.st_ino==v['inode'] and hashlib.sha256(f.read_bytes()).hexdigest()==v['sha256']
 for row in plan['deleted_archived_traces']:assert not (m/row['path'].lstrip('/')).exists()
finally:detach()
os.chown(image,501,20)
proof=dict(status='PASS',items=69,image_detached=True,read_only_remount_owners_on_verified=True,
 critical_numeric_owners_modes_and_hashes_verified=True,all_modified_inodes_preserved=True,
 codesign_verified=True,phone_accessed=False,preparation_sha256=hashlib.sha256((d/'preparation.json').read_bytes()).hexdigest())
(d/'owners-finalized.json').write_text(json.dumps(proof,indent=2)+'\n')
os.chown(d/'owners-finalized.json',501,20)
print('iOS numeric ownership finalized on the local candidate image only. No phone accessed.')
