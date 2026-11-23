#!/usr/bin/env python3
"""Apply the power overlay after the qualified display/SMP/desktop layers."""
from pathlib import Path
import argparse,hashlib,json,shutil
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xnu',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'native/power/manifest.json').read_text())
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None
for rel,row in manifest['files'].items():
 assert sha(Path(row['source']))==row['after'], 'Changed power source: '+rel
 assert sha(a.xnu/rel) in (row['before'],row['after']), 'Unknown XNU input: '+rel
for rel,row in manifest['files'].items():
 target=a.xnu/rel;target.parent.mkdir(parents=True,exist_ok=True)
 if sha(target)!=row['after']:shutil.copyfile(row['source'],target)
print('Power overlay hashes verified; hardware validation remains separate.')
