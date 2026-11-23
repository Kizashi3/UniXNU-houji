#!/usr/bin/env python3
"""Install the pinned 12 GiB HFSX volume in existing userdata; destroys Android data.

Authorized for this houji by the owner. Never resizes GPT, erases calibration,
changes active slots, or formats another partition. Record every device command.
"""
import argparse,datetime,hashlib,importlib.util,json,os,re,subprocess,time
from pathlib import Path

N=Path('${HOUJI_ARTIFACTS}/native-port')
SDK=Path('${USER_HOME}/Library/Android/sdk/platform-tools');SERIAL='DEVICE_SERIAL'
IMAGE=N/'ios-userland/full-root-12g/ios16-full.hfsx'
IMAGE_SHA='c49c2349a088af4888e3fda1ad08e0593e7eba70516d8b1c8177e78c7ab55385'
IMAGE_BYTES=12884901888
USERDATA_BYTES=515465261056

def main():
 os.umask(0o077)
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--adb-port',type=int,choices=(5037,5038,5047),required=True);a=p.parse_args()
 with IMAGE.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
 if IMAGE.stat().st_size!=IMAGE_BYTES or actual!=IMAGE_SHA:raise ValueError('HFSX source differs')
 manifest=json.loads((N/'recovery-backup-20261024/manifest.json').read_text())
 for item in manifest['items']:
  file=N/'recovery-backup-20261024'/(item['partition']+'.img')
  with file.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
  if file.stat().st_size!=item['bytes'] or digest!=item['sha256']:raise ValueError('Critical backup differs: '+item['partition'])
 print('Pinned 12 GiB HFSX and all 37 critical partition backups verified.',flush=True)
 output=N/'native-root-install-r1';output.mkdir(mode=0o700,exist_ok=False)
 journal=output/'commands.jsonl'
 def run(args,binary=False,timeout=60):
  command=list(map(str,args));r=subprocess.run(command,capture_output=True,timeout=timeout)
  record={'time':datetime.datetime.now().astimezone().isoformat(),'args':command,'code':r.returncode,'stderr':r.stderr.decode(errors='replace')}
  record.update({'bytes':len(r.stdout),'sha256':hashlib.sha256(r.stdout).hexdigest()} if binary else {'stdout':r.stdout.decode(errors='replace')})
  with journal.open('a') as f:f.write(json.dumps(record)+'\n')
  if r.returncode or (binary and r.stderr):raise RuntimeError(record)
  return r.stdout if binary else r.stdout.decode()+r.stderr.decode()
 def root(c,binary=False):return run([SDK/'adb','-P',a.adb_port,'-s',SERIAL,'exec-out',c],binary)
 if root('id -u; getprop ro.product.device; getprop ro.houji.native_rescue; getprop ro.boot.slot_suffix').splitlines()!=['0','houji','1','_a']:raise RuntimeError('Rescue identity differs')
 if any(line.split()[1]=='/data' for line in root('cat /proc/mounts').splitlines()):raise RuntimeError('userdata is mounted')
 if root('readlink -f /dev/block/by-name/userdata; blockdev --getsize64 /dev/block/by-name/userdata').splitlines()!=['/dev/block/sda33',str(USERDATA_BYTES)]:raise RuntimeError('userdata geometry differs')
 spec=importlib.util.spec_from_file_location('trial',Path(__file__).with_name('try-recovery-ram-boot.py'));trial=importlib.util.module_from_spec(spec);spec.loader.exec_module(trial)
 for name,sha in trial.BOOT.items():
  if root('sha256sum /dev/block/by-name/'+name).split()!=[sha,'/dev/block/by-name/'+name]:raise RuntimeError('Boot partition changed: '+name)
 for disk in json.loads((N/'partition-backup-20261024/manifest.json').read_text())['disks']:
  for suffix,skip in [('primary',0),('backup',disk['backup_start_lba'])]:
   expected=trial.expected_gpt(disk,suffix)
   if root(f'dd if={disk["device"]} bs=4096 skip={skip} count={len(expected)//4096} status=none',True)!=expected:raise RuntimeError('GPT changed: '+disk['device']+'-'+suffix)
 before=root('dd if=/dev/block/by-name/userdata bs=4096 count=4 status=none',True)
 (output/'userdata-first16k-before.bin').write_bytes(before)
 (output/'install.json').write_text(json.dumps({'source':str(IMAGE),'sha256':IMAGE_SHA,'bytes':IMAGE_BYTES,'partition':'userdata','physical_lun':0,'first_lba':2260480,'last_lba_exclusive':5406208,'gpt_resize':False,'android_data_destroyed':True,'status':'preflight passed; not yet flashed'},indent=2)+'\n')
 run([SDK/'adb','-P',a.adb_port,'-s',SERIAL,'reboot','bootloader'])
 for _ in range(80):
  if SERIAL in run([SDK/'fastboot','devices']):break
  time.sleep(.5)
 else:raise RuntimeError('No fastboot')
 if 'product: houji' not in run([SDK/'fastboot','-s',SERIAL,'getvar','product']):raise RuntimeError('Fastboot model differs')
 if 'current-slot: a' not in run([SDK/'fastboot','-s',SERIAL,'getvar','current-slot']):raise RuntimeError('Slot differs')
 size=run([SDK/'fastboot','-s',SERIAL,'getvar','partition-size:userdata'])
 match=re.search(r'partition-size:userdata:\s*(0x[0-9a-fA-F]+)',size)
 if not match or int(match[1],16)!=USERDATA_BYTES:raise RuntimeError('Fastboot userdata size differs')
 maximum=run([SDK/'fastboot','-s',SERIAL,'getvar','max-download-size'])
 print('Writing the pinned iOS volume to userdata in <=256 MiB sparse transfers.',flush=True)
 # Stream output to the local transcript so transfer progress remains visible.
 command=list(map(str,[SDK/'fastboot','-s',SERIAL,'-S','256M','flash','userdata',IMAGE]))
 with (output/'flash.txt').open('w') as f:
  process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
  for line in process.stdout:f.write(line);f.flush();print(line,end='',flush=True)
  code=process.wait()
 with journal.open('a') as f:f.write(json.dumps({'time':datetime.datetime.now().astimezone().isoformat(),'args':command,'code':code,'output':'flash.txt'})+'\n')
 if code:raise RuntimeError('userdata flash failed; device remains in Fastboot')
 record=json.loads((output/'install.json').read_text());record.update(status='flash succeeded; full device readback pending',flashed_at=datetime.datetime.now().astimezone().isoformat());(output/'install.json').write_text(json.dumps(record,indent=2)+'\n')
 print(run([SDK/'fastboot','-s',SERIAL,'reboot','recovery']),flush=True)

if __name__=='__main__':main()
