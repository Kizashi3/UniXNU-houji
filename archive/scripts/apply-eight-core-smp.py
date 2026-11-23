#!/usr/bin/env python3
"""Apply the pinned Darwin 22 eight-core SMP stage; refuse any unknown source state."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

P=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xnu',type=Path,required=True)
    a=parser.parse_args()
    manifest=json.loads((P/'native/smp/eight-core-manifest.json').read_text())
    states=[]
    for relative,record in manifest['files'].items():
        file=a.xnu/relative
        actual=hashlib.sha256(file.read_bytes()).hexdigest() if file.exists() else None
        if actual==record['after']: states.append('after')
        elif actual==record['before']: states.append('before')
        else: raise ValueError('Unverified XNU source: '+relative)
    if set(states)=={'after'}:
        print('Pinned SMP source already applied; all file hashes match')
        return
    if set(states)!={'before'}:
        raise ValueError('Partially applied source; restore the pinned baseline first')
    patch=P/'native/smp/xnu-smp-eight.patch'
    subprocess.run(['git','apply','--check',str(patch)],cwd=a.xnu,check=True)
    subprocess.run(['git','apply',str(patch)],cwd=a.xnu,check=True)
    for relative,record in manifest['files'].items():
        if hashlib.sha256((a.xnu/relative).read_bytes()).hexdigest()!=record['after']:
            raise ValueError('Patched source hash differs: '+relative)
    print('Applied pinned SMP source; scheduler and frequency policy unchanged')

if __name__=='__main__':main()
