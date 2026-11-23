#!/usr/bin/env python3
"""Resolve the last SWEET user-thread samples against the owner's iOS16 cache."""
import argparse,concurrent.futures,json,os,re,subprocess
from pathlib import Path

N=Path('${HOUJI_ARTIFACTS}/native-port')
CLI=N/'host-tools/ipsw-3.1.739/ipsw'
CACHE=N/'ios-userland/symbol-root/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64'

def main():
 os.umask(0o077)
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--log',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--max-addresses',type=int,default=80);a=p.parse_args()
 if not 1<=a.max_addresses<=160:raise ValueError('Address budget differs')
 samples={};current=None
 for line in a.log.read_text(errors='replace').splitlines():
  h=re.search(r'SMP ([A-Za-z0-9_.-]+)\[(\d+)\] slide (0x[0-9a-f]+) mh (0x[0-9a-f]+)',line)
  if h:
   current={'name':h[1],'pid':int(h[2]),'slide':int(h[3],16),'main_header':int(h[4],16),'threads':[]};samples[h[1]]=current;continue
  t=re.search(r'SMP ([A-Za-z0-9_.-]+) t(\d+) pc (0x[0-9a-f]+) lr (0x[0-9a-f]+) sp (0x[0-9a-f]+) bt(.*)',line)
  if t and current and t[1]==current['name']:
   addresses=[int(t[3],16),int(t[4],16)]+[int(x,16) for x in re.findall(r'0x[0-9a-f]+',t[6])]
   current['threads'].append({'thread':int(t[2]),'addresses':addresses,'unslid_cache_addresses':[x-current['slide'] for x in addresses if 0x180000000<=x-current['slide']<0x22ade8000]})
 if not samples:raise ValueError('No complete process stack samples in log')
 # Main threads and their callers first; resolve each distinct address once.
 addresses=[]
 for depth in range(8):
  for sample in samples.values():
   for thread in sample['threads']:
    values=thread['unslid_cache_addresses']
    if depth<len(values) and values[depth] not in addresses:addresses.append(values[depth])
 addresses=addresses[:a.max_addresses];a.output.mkdir(parents=True,mode=0o700,exist_ok=False)
 def resolve(address):
  args=[str(CLI),'--no-color','--config',str(CLI.parent/'empty-config.yaml'),'dyld','a2s','--cache',str(CLI.parent/'ios16-dsc.a2s'),'--image',str(CACHE),hex(address)]
  r=subprocess.run(args,capture_output=True,text=True,timeout=90)
  return hex(address),{'code':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:resolved=dict(pool.map(resolve,addresses))
 (a.output/'samples.json').write_text(json.dumps(samples,indent=2)+'\n');(a.output/'symbols.json').write_text(json.dumps(resolved,indent=2)+'\n')
 lines=[]
 for sample in samples.values():
  lines.append(f"{sample['name']}[{sample['pid']}] slide={sample['slide']:#x}")
  for thread in sample['threads']:
   lines.append('  thread '+str(thread['thread']))
   for address in thread['unslid_cache_addresses'][:10]:
    match=resolved.get(hex(address));result=(match['stdout'].strip().replace('\n',' | ') if match and match['code']==0 else 'unresolved')
    lines.append(f'    {address:#x}: {result}')
 (a.output/'summary.txt').write_text('\n'.join(lines)+'\n')
 print(json.dumps({'processes':list(samples),'addresses':len(addresses),'resolved':sum(x['code']==0 for x in resolved.values()),'output':str(a.output)},indent=2))

if __name__=='__main__':main()
