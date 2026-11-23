#!/usr/bin/env python3
"""Apply the opt-in houji platform UUID fallback to a pinned local GUI XNU tree."""
import argparse,hashlib,json,subprocess
from pathlib import Path

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xnu',type=Path,required=True);a=p.parse_args()
 source=Path(__file__).resolve().parents[1]/'native/platform-uuid';manifest=json.loads((source/'manifest.json').read_text());target=a.xnu/'iokit/Kernel/IOPlatformExpert.cpp'
 digest=lambda:hashlib.sha256(target.read_bytes()).hexdigest()
 if digest()==manifest['after_sha256']:print('Platform UUID fallback already present');return
 if digest()!=manifest['before_sha256']:raise ValueError('Unrecognized IOPlatformExpert source')
 patch=source/'houji-platform-uuid.patch'
 subprocess.run(['git','-C',str(a.xnu),'apply','--check',str(patch)],check=True)
 subprocess.run(['git','-C',str(a.xnu),'apply',str(patch)],check=True)
 if digest()!=manifest['after_sha256']:raise RuntimeError('Patched IOPlatformExpert digest differs')
 print('Platform UUID fallback installed; no ECID or activation properties changed')
if __name__=='__main__':main()
