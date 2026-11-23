#!/usr/bin/env python3
"""Apply the iOS16 surface-use layer after the qualified display/power layers."""
from pathlib import Path
import argparse,hashlib,json,shutil
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--xnu',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1];source=root/'native/display/surface-use-runtime'
manifest=json.loads((source/'manifest.json').read_text())
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else None
target=a.xnu/'iokit/Kernel/arm'
for name,row in manifest['files'].items():
    assert sha(source/name)==row['after'],'Changed surface overlay: '+name
    assert sha(target/name) in (row['before'],row['after']),'Unknown XNU surface input: '+name
for name,row in manifest['files'].items():
    if sha(target/name)!=row['after']:shutil.copyfile(source/name,target/name)
helper=root/'native/display/SurfaceUseCount.h'
assert sha(helper)==sha(source/helper.name),'Changed atomic-count helper'
assert not (target/helper.name).exists() or sha(target/helper.name)==sha(helper)
shutil.copyfile(helper,target/helper.name)
print('Surface-use and fresh-zero cache layer hashes verified; visual hardware result remains separate.')
