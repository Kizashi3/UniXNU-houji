#!/usr/bin/env python3
"""Read back the installed 12 GiB userdata prefix from root houji recovery."""
import argparse,datetime,hashlib,json,os,subprocess
from pathlib import Path

N=Path('${HOUJI_ARTIFACTS}/native-port')
SDK=Path('${USER_HOME}/Library/Android/sdk/platform-tools');SERIAL='DEVICE_SERIAL'
EXPECTED='c49c2349a088af4888e3fda1ad08e0593e7eba70516d8b1c8177e78c7ab55385'

def main():
 os.umask(0o077)
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--adb-port',type=int,choices=(5037,5038,5047),required=True);a=p.parse_args()
 journal=N/'native-root-install-r1/readback.jsonl'
 def root(c,timeout=40):
  r=subprocess.run([str(SDK/'adb'),'-P',str(a.adb_port),'-s',SERIAL,'exec-out',c],capture_output=True,timeout=timeout)
  with journal.open('a') as f:f.write(json.dumps({'time':datetime.datetime.now().astimezone().isoformat(),'command':c,'code':r.returncode,'bytes':len(r.stdout),'sha256':hashlib.sha256(r.stdout).hexdigest(),'stderr':r.stderr.decode(errors='replace')})+'\n')
  if r.returncode or r.stderr:raise RuntimeError('Readback command failed: '+c)
  return r.stdout
 if root('id -u; getprop ro.product.device; getprop ro.houji.native_rescue').splitlines()!=[b'0',b'houji',b'1']:raise RuntimeError('Recovery identity differs')
 if any(line.split()[1]==b'/data' for line in root('cat /proc/mounts').splitlines()):raise RuntimeError('userdata is mounted')
 if root('readlink -f /dev/block/by-name/userdata; blockdev --getsize64 /dev/block/by-name/userdata').splitlines()!=[b'/dev/block/sda33',b'515465261056']:raise RuntimeError('userdata geometry differs')
 page=root('dd if=/dev/block/by-name/userdata bs=4096 count=1 status=none')
 source=N/'ios-userland/full-root-12g/ios16-full.hfsx'
 with source.open('rb') as f:expected_page=f.read(4096)
 if page!=expected_page:raise RuntimeError('HFSX first page differs')
 (N/'native-root-install-r1/userdata-first4k-after.bin').write_bytes(page)
 helper=N/'native-ios-candidate/root-direct-read'
 expected_helper=hashlib.sha256(helper.read_bytes()).hexdigest()
 if root('sha256sum /tmp/houji-root-read').decode().split()!=[expected_helper,'/tmp/houji-root-read']:raise RuntimeError('Read-only direct helper differs')
 print('HFSX header matches; hashing exactly the installed 12 GiB with O_DIRECT.',flush=True)
 digest=root('set -o pipefail; /tmp/houji-root-read | sha256sum',300).decode().split()
 if len(digest)!=2 or digest[0]!=EXPECTED:raise RuntimeError('Full installed volume hash differs: '+str(digest))
 f=N/'native-root-install-r1/install.json';m=json.loads(f.read_text());m.update(status='PASS: complete 12 GiB O_DIRECT device readback matches pinned HFSX source',readback_sha256=digest[0],readback_verified_at=datetime.datetime.now().astimezone().isoformat());f.write_text(json.dumps(m,indent=2)+'\n')
 print('PASS: complete installed HFSX SHA256 '+digest[0],flush=True)

if __name__=='__main__':main()
