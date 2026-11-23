#!/usr/bin/env python3
import hashlib,json,concurrent.futures,subprocess,plistlib
from pathlib import Path
N=Path('${HOUJI_ARTIFACTS}/native-port');D=N/'ios-userland/native-screen-v12';CHUNK=134217728;BEFORE='b89b9d9357b02eb4368edcf5a0645e595e6c427b25874c38176c112ab9a48e56'
def fingerprint(f):
 s=f.stat();return dict(device=s.st_dev,inode=s.st_ino,size=s.st_size,mtime_ns=s.st_mtime_ns)
def main():
 prep=D/'preparation.json';plan=json.loads(prep.read_text());proof=json.loads((D/'owners-finalized.json').read_text());assert proof['status']=='PASS' and proof['items']==3 and proof['preparation_sha256']==hashlib.sha256(prep.read_bytes()).hexdigest()
 paths={k:Path(plan['base_image' if k=='before' else 'image']) for k in ['before','after']}
 mounted=plistlib.loads(subprocess.check_output(['hdiutil','info','-plist']));assert not any(x.get('image-path') in map(str,paths.values()) for x in mounted['images'])
 def scan(k):
  f=paths[k];assert not f.is_symlink() and f.stat().st_size==256*CHUNK and (f.stat().st_mode&0o777)==0o400
  start=fingerprint(f);h=hashlib.sha256();chunks=[]
  with f.open('rb') as stream:
   for i in range(256):
    data=stream.read(CHUNK);assert len(data)==CHUNK;h.update(data);chunks.append(hashlib.sha256(data).hexdigest())
   assert not stream.read(1)
  assert fingerprint(f)==start;return h.hexdigest(),chunks,start
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:values=dict(zip(paths,pool.map(scan,paths)))
 assert values['before'][0]==BEFORE
 rows=[dict(index=i,before=values['before'][1][i],after=values['after'][1][i]) for i in range(256)];changed=[r['index'] for r in rows if r['before']!=r['after']];assert 1<=len(changed)<=24
 out=dict(bytes=256*CHUNK,chunk_bytes=CHUNK,before_image=str(paths['before']),after_image=str(paths['after']),before_sha256=BEFORE,after_sha256=values['after'][0],chunks=rows,changed_chunks=changed,preparation_sha256=hashlib.sha256(prep.read_bytes()).hexdigest(),owners_proof_sha256=hashlib.sha256((D/'owners-finalized.json').read_bytes()).hexdigest(),host_fingerprints={k:values[k][2] for k in paths},probe_only=False,desktop_selected=True,phone_accessed=False,host_verification='one full pass per immutable image; fresh hash of every written chunk at install; all 256 device chunks checked before/after')
 f=D/'delta.json';assert not f.exists();f.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(dict(after=out['after_sha256'],changed=changed,plan_sha256=hashlib.sha256(f.read_bytes()).hexdigest()),indent=2))
if __name__=='__main__':main()
