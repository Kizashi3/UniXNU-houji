#!/usr/bin/env python3
"""Apply the measured-refresh diagnostic layer after surface-use/lifetime layers."""
from pathlib import Path
import argparse,hashlib,json,shutil

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--xnu',type=Path,required=True)
    a=p.parse_args()
    source=Path(__file__).resolve().parents[1]/'native/display/refresh-runtime'
    manifest=json.loads((source/'manifest.json').read_text())
    target=a.xnu/'iokit/Kernel/arm/SweetFramebuffer.cpp'
    sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
    assert sha(source/'SweetFramebuffer.cpp')==manifest['after_sha256']
    assert sha(source/'before-SweetFramebuffer.cpp')==manifest['before_sha256']
    assert sha(target) in (manifest['before_sha256'],manifest['after_sha256']), 'Unknown display source; preserve it'
    if sha(target)!=manifest['after_sha256']:shutil.copyfile(source/'SweetFramebuffer.cpp',target)
    print('Display refresh/default and observation layer hashes verified; actual cadence requires device logs.')

if __name__=='__main__':main()
