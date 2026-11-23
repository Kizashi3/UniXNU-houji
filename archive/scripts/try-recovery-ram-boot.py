#!/usr/bin/env python3
"""Run the pinned r26 clock/HFS check from root recovery; no userdata writes."""
import argparse,datetime,hashlib,json,re,subprocess,time,os
from pathlib import Path

N=Path('${HOUJI_ARTIFACTS}/native-port')
SDK=Path('${USER_HOME}/Library/Android/sdk/platform-tools');SERIAL='DEVICE_SERIAL'
POLICY={'kind':'native-root-calendar-check','stop_phase':2,'kernel_sha256':'c267974501e48d3ca2eb93eb7a3a5ee6ebc04a3571264ca5cc0c569463fde79c','userdata_writes':False,'log_file':'XnuLog.bin','log_data_lbas':list(range(4170,4186)),'log_run_id':'de0003061a104c7086d7c80a0e9a17f9','log_initial_sha256':'b7f5f644d5f2547ea68e34170a7f0c469c5431c41df95aff6a7bd796f6dd0498','misc_write_lba':1024,'misc_write_blocks':1,'misc_recovery_arguments':'recovery only; no wipe; preserve reserved and A/B data'}
LOG_BASE={'kind':'logfs-file-create','physical_lun':0,'block_bytes':4096,'first_lba':4096,'end_lba_exclusive':6144,'file':'UniXNU.log','existing_file':'refuse','max_text_bytes':131072}
BOOT={'boot_a':'9b8fc3be39843bc238115a73cfed7b6fc1f3de08cfb44b0b3640a3a7b3a79e95','init_boot_a':'451c6faffdb29f3e92ada242451c4a5353653868b686a0d86f4bd6d58b715879','vendor_boot_a':'d1e84f65aca1107e9ef276b84b82e84822dd50d5c9254ff8c3c4334920537107','vbmeta_a':'3ca4fc33a61748578677f09f59c7b615d6a81eed6bcd7d544f235e625a193aa8','recovery_a':'ffadfdda5ae0b08090b956f7e0f16c6f1c31cf17768a0cec8eb867f3a3b89ee7'}
# set_active=a and marking that working slot successful changed only boot_a/b
# attributes and the two GPT CRCs. Pin the separately audited bytes exactly.
RESCUED_SDE={'primary':'4eaa109badd38fdff1342e91cf4c0df17513e98c41ee1ecef692e3206a6f77d1','backup':'7c4af58b87e69968cd5086d05623bdfabda41d5f39bfcb77383eb39524299ca2'}

def expected_gpt(disk,suffix):
 name=Path(disk['device']).name
 directory='device-baseline/gpt-after-rescue-successful' if name=='sde' else 'partition-backup-20261024'
 data=(N/directory/(name+'-'+suffix+'.bin')).read_bytes()
 expected=RESCUED_SDE[suffix] if name=='sde' else disk[suffix+'_sha256']
 if len(data)%4096 or hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Pinned GPT backup differs: '+name+'-'+suffix)
 return data

def validate_metadata(metadata,image,backup):
 if len(backup)!=8388608:raise ValueError('Backup size differs')
 expected={**LOG_BASE,'backup_sha256':hashlib.sha256(backup).hexdigest()}
 if (metadata.get('device')!='houji' or metadata.get('usage')!='fastboot boot only' or
     metadata.get('physical_storage_drivers') is not True or metadata.get('test_scope')!='xnu-native-root-calendar-check' or
     metadata.get('native_storage_policy')!=POLICY or metadata.get('storage_write_policy')!=expected or
     metadata.get('sha256',{}).get('image')!=hashlib.sha256(image).hexdigest()):
  raise ValueError('Pinned r26 boot provenance differs')

def main():
 os.umask(0o077)
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',type=Path,required=True);p.add_argument('--label',required=True);p.add_argument('--adb-port',type=int,choices=(5037,5038,5047),required=True);p.add_argument('--backup',type=Path,required=True);a=p.parse_args()
 if not re.fullmatch('[a-z0-9-]+',a.label):raise ValueError('Label differs')
 image=a.image.read_bytes();backup=a.backup.read_bytes();meta=json.loads(a.image.with_suffix('.json').read_text());validate_metadata(meta,image,backup)
 journal=N/(a.label+'-trial.jsonl')
 def run(args,timeout=40,binary=False):
  r=subprocess.run(list(map(str,args)),capture_output=True,timeout=timeout)
  record={'time':datetime.datetime.now().astimezone().isoformat(),'args':list(map(str,args)),'code':r.returncode,'stderr':r.stderr.decode(errors='replace')}
  if binary:record.update(bytes=len(r.stdout),sha256=hashlib.sha256(r.stdout).hexdigest())
  else:record['stdout']=r.stdout.decode(errors='replace')
  with journal.open('a') as f:f.write(json.dumps(record)+'\n')
  if r.returncode or (binary and r.stderr):raise RuntimeError(record)
  return r.stdout if binary else r.stdout.decode()+r.stderr.decode()
 def root(c,binary=False):return run([SDK/'adb','-P',a.adb_port,'-s',SERIAL,'exec-out',c],binary=binary)
 if root('id -u; getprop ro.product.device; getprop ro.houji.native_rescue; getprop ro.boot.slot_suffix').splitlines()!=['0','houji','1','_a']:raise RuntimeError('Expected root recovery identity absent')
 for name,sha in BOOT.items():
  if root('sha256sum /dev/block/by-name/'+name).split()!=[sha,'/dev/block/by-name/'+name]:raise RuntimeError('Boot partition changed: '+name)
 for disk in json.loads((N/'partition-backup-20261024/manifest.json').read_text())['disks']:
  for suffix,skip in [('primary',0),('backup',disk['backup_start_lba'])]:
   saved=expected_gpt(disk,suffix)
   raw=root(f'dd if={disk["device"]} bs=4096 skip={skip} count={len(saved)//4096} status=none',True)
   if raw!=saved:raise RuntimeError('GPT differs from pinned audited backup: '+disk['device']+'-'+suffix)
 if root('/tmp/houji-logfs-read',True)!=backup:raise RuntimeError('Direct logfs bytes changed')
 if root('if [ -e /dev/logfs/UniXNU.log ]; then echo EXISTS; else echo ABSENT; fi').strip()!='ABSENT':raise RuntimeError('UEFI log already exists')
 if hashlib.sha256(root('cat /dev/logfs/XnuLog.bin',True)).hexdigest()!=POLICY['log_initial_sha256']:raise RuntimeError('Native log initialization differs')
 misc=root('cat /dev/block/by-name/misc',True)
 if len(misc)!=4194304 or misc!=root('cat /dev/block/by-name/misc',True):raise RuntimeError('Fresh misc backup unstable')
 dest=N/'device-baseline'/('misc-before-'+a.label+'.bin')
 with dest.open('xb') as f:f.write(misc)
 print('Pinned recovery, five boot partitions, 12 GPT ranges, direct FAT backup and native log verified.',flush=True)
 run([SDK/'adb','-P',a.adb_port,'-s',SERIAL,'reboot','bootloader'])
 for _ in range(80):
  if SERIAL in run([SDK/'fastboot','devices']):break
  time.sleep(.5)
 else:raise RuntimeError('No fastboot')
 if 'product: houji' not in run([SDK/'fastboot','-s',SERIAL,'getvar','product']):raise RuntimeError('Fastboot model changed')
 if 'current-slot: a' not in run([SDK/'fastboot','-s',SERIAL,'getvar','current-slot']):raise RuntimeError('Slot changed')
 print(run([SDK/'fastboot','-s',SERIAL,'boot',a.image],60),flush=True)
if __name__=='__main__':main()
