#!/usr/bin/env python3
"""Set numeric iOS owners on three new local files. Never accesses a phone."""
from pathlib import Path
import hashlib,json,os,subprocess,plistlib
assert os.geteuid()==0,'Run in the local sudo prompt, never give a password in chat.'
d=Path('${HOUJI_ARTIFACTS}/native-port/ios-userland/wallpaper-bootstrap-r194')
plan=json.loads((d/'preparation.json').read_text());image=d/'ios16-desktop.hfsx';m=d/'mount'
assert plan['image']==str(image) and image.stat().st_size==12884901888
assert set(plan['items'])=={'/usr/libexec/houji-wallpaper-bootstrap','/System/Library/LaunchDaemons/com.unixnu.wallpaper-bootstrap.plist','/private/var/mobile/Library/Logs/UniXNU-wallpaper.log'}
subprocess.run(['hdiutil','attach','-nobrowse','-owners','on','-imagekey','diskimage-class=CRawDiskImage','-mountpoint',str(m),str(image)],check=True)
try:
 for rel,v in plan['items'].items():
  f=m/rel.lstrip('/');assert not f.is_symlink() and f.is_file() and f.stat().st_ino==v['inode']
  assert hashlib.sha256(f.read_bytes()).hexdigest()==v['sha256']
  os.chown(f,v['uid'],v['gid']);os.chmod(f,v['mode'])
 subprocess.run(['codesign','--verify','--strict',str(m/'usr/libexec/houji-wallpaper-bootstrap')],check=True)
 os.sync()
finally:subprocess.run(['hdiutil','detach',str(m)],check=True)
subprocess.run(['hdiutil','attach','-readonly','-nobrowse','-owners','on','-imagekey','diskimage-class=CRawDiskImage','-mountpoint',str(m),str(image)],check=True)
try:
 for rel,v in plan['items'].items():
  f=m/rel.lstrip('/');st=f.stat()
  assert (st.st_uid,st.st_gid,st.st_mode&0o7777)==(v['uid'],v['gid'],v['mode'])
  assert st.st_ino==v['inode'] and hashlib.sha256(f.read_bytes()).hexdigest()==v['sha256']
 assert plistlib.loads((m/'System/Library/LaunchDaemons/com.unixnu.wallpaper-bootstrap.plist').read_bytes())['UserName']=='mobile'
finally:subprocess.run(['hdiutil','detach',str(m)],check=True)
os.chown(image,501,20)
proof={'status':'PASS','items':3,'image_detached':True,'read_only_remount_owners_on_verified':True,
 'critical_numeric_owners_modes_and_hashes_verified':True,'all_modified_inodes_preserved':True,
 'codesign_verified':True,'phone_accessed':False,'preparation_sha256':hashlib.sha256((d/'preparation.json').read_bytes()).hexdigest()}
(d/'owners-finalized.json').write_text(json.dumps(proof,indent=2)+'\n')
print('Wallpaper candidate numeric owners verified. Only local image accessed; no phone accessed.')
