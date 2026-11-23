#!/usr/bin/env python3
"""Make a verified incremental host snapshot; phone userdata is opened read-only."""
import argparse,datetime,hashlib,json,os,re,subprocess,time
from pathlib import Path
N=Path('${HOUJI_ARTIFACTS}/native-port')
ADB='${USER_HOME}/Library/Android/sdk/platform-tools/adb'
HELPER=N/'native-ios-candidate/root-chunk-read'
HELPER_SHA='6ddf56c560d466ca1fc7d66cb436846e8713f1429d9038a9019c916bad7f676b'
CHUNK=128*1024**2
SIZE=96*CHUNK
REMOTE='/tmp/houji-root-chunk-read'

def hashes(path):
 whole=hashlib.sha256();parts=[]
 with path.open('rb') as stream:
  for _ in range(96):
   data=stream.read(CHUNK)
   if len(data)!=CHUNK:raise ValueError('Truncated base snapshot')
   whole.update(data);parts.append(hashlib.sha256(data).hexdigest())
  if stream.read(1):raise ValueError('Oversized snapshot')
 return whole.hexdigest(),parts

def main():
 os.umask(0o077)
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--adb-port',type=int,choices=(5037,5038,5047),required=True);p.add_argument('--base',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--max-changed-chunks',type=int,default=24);a=p.parse_args();started=time.monotonic()
 if not 1<=a.max_changed_chunks<=96:raise ValueError('Changed chunk budget outside fixed 12 GiB volume')
 if a.base.is_symlink() or a.base.stat().st_size!=SIZE:raise ValueError('Unexpected base image')
 saved=json.loads((a.base.parent/'backup.json').read_text());base_sha,base_chunks=hashes(a.base)
 if saved['bytes']!=SIZE or base_sha!=saved['sha256']:raise ValueError('Base snapshot digest differs')
 with a.base.open('rb') as f:header=f.read(4096)
 if header[1024:1028]!=b'HX\x00\x05' or header[1064:1072]!=bytes.fromhex('0000100000300000') or header[1128:1136]!=bytes.fromhex('1e38300864ba2b7b'):raise ValueError('Base HFSX identity differs')
 if hashlib.sha256(HELPER.read_bytes()).hexdigest()!=HELPER_SHA:raise ValueError('Read-only helper differs')
 adb=[ADB,'-P',str(a.adb_port),'-s','DEVICE_SERIAL']
 def root(cmd):
  r=subprocess.run(adb+['exec-out',cmd],capture_output=True,check=True,timeout=90)
  if r.stderr:raise RuntimeError(r.stderr.decode(errors='replace'))
  return r.stdout
 if root('id -u; getprop ro.product.device; getprop ro.houji.native_rescue; getprop ro.boot.slot_suffix').splitlines()!=[b'0',b'houji',b'1',b'_a']:raise RuntimeError('Expected root recovery absent')
 if any(x.split()[1]==b'/data' for x in root('cat /proc/mounts').splitlines()):raise RuntimeError('userdata is mounted')
 subprocess.run(adb+['push',str(HELPER),REMOTE],check=True,capture_output=True);root('chmod 755 '+REMOTE)
 if root('sha256sum '+REMOTE).split()!=[HELPER_SHA.encode(),REMOTE.encode()]:raise RuntimeError('Staged helper digest differs')
 a.output.mkdir(parents=True,mode=0o700,exist_ok=False)
 def index(label):
  command='set -e -o pipefail; i=0; while [ "$i" -lt 96 ]; do printf "%s " "$i"; '+REMOTE+' "$i" | sha256sum; i=$((i+1)); done'
  data=root(command);lines=data.splitlines();result=[]
  if len(lines)!=96:raise RuntimeError('Incomplete device hash index')
  for i,line in enumerate(lines):
   match=re.fullmatch(rb'([0-9]+) ([0-9a-f]{64})  -',line)
   if not match or int(match[1])!=i or match[2]==hashlib.sha256(b'').hexdigest().encode():raise RuntimeError('Invalid device chunk index')
   result.append(match[2].decode())
  (a.output/(label+'.txt')).write_bytes(data);return result
 before=index('phone-before');changed=[i for i in range(96) if before[i]!=base_chunks[i]]
 print(f'Verified base; {len(changed)} changed chunks ({len(changed)*128} MiB raw). Phone userdata remains read-only.',flush=True)
 if len(changed)>a.max_changed_chunks:raise RuntimeError('Too much changed; retain index and use a full snapshot')
 path=a.output/'ios16-phone.hfsx.partial';subprocess.run(['/bin/cp','-c',str(a.base),str(path)],check=True);os.chmod(path,0o600)
 if path.samefile(a.base):raise RuntimeError('Snapshot clone aliases base inode')
 with path.open('r+b') as target:
  for i in changed:
   with (a.output/f'chunk-{i}.stderr').open('wb') as err:
    sender=subprocess.Popen(adb+['exec-out',f'set -e -o pipefail; {REMOTE} {i} | lz4 -1 -q -c'],stdout=subprocess.PIPE,stderr=err)
    decoder=subprocess.Popen(['/opt/homebrew/bin/lz4','-d','-q','-c'],stdin=sender.stdout,stdout=subprocess.PIPE,stderr=err);sender.stdout.close();data=decoder.communicate(timeout=90)[0];code=sender.wait(timeout=10)
   if decoder.returncode or code or len(data)!=CHUNK or hashlib.sha256(data).hexdigest()!=before[i] or (a.output/f'chunk-{i}.stderr').stat().st_size:raise RuntimeError(f'Chunk {i} failed validation')
   if i==0 and any(data[start:start+length]!=header[start:start+length] for start,length in ((1024,4),(1064,8),(1128,8))):raise RuntimeError('Device HFSX identity changed')
   target.seek(i*CHUNK);target.write(data)
  target.flush();os.fsync(target.fileno())
 after=index('phone-after')
 if after!=before:raise RuntimeError('Device changed during snapshot')
 sha,actual=hashes(path)
 if actual!=before:raise RuntimeError('Reconstructed snapshot differs from live device chunks')
 final=a.output/'ios16-phone.hfsx';path.rename(final);os.chmod(final,0o400)
 report={'bytes':SIZE,'sha256':sha,'base_image':str(a.base),'base_sha256':base_sha,'chunk_bytes':CHUNK,'changed_chunks':changed,'phone_chunk_index_stable':True,'every_output_chunk_matches_device':True,'phone_userdata_writes_requested':False,'helper_staged_in':'recovery tmpfs only','seconds':time.monotonic()-started,'captured_at':datetime.datetime.now().astimezone().isoformat()}
 (a.output/'backup.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
