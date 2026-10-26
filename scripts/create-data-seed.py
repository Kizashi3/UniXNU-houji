"""Create the upstream APFS Data seed from a verified read-only OS attachment."""
import argparse
from pathlib import Path
import plistlib
import subprocess
import sys

p=argparse.ArgumentParser()
p.add_argument('--unixnu',type=Path,required=True)
p.add_argument('--dmg',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
args=p.parse_args()
mount=args.unixnu.resolve()/'.cache/firmware/target-volumes/os-mount'
mount.mkdir(parents=True,exist_ok=True)
attached=plistlib.loads(subprocess.check_output(['hdiutil','attach','-readonly','-nobrowse',
    '-mountpoint',str(mount),'-plist',str(args.dmg.resolve())]))
entities=attached['system-entities']
device=entities[0]['dev-entry']
try:
    volumes=[e for e in entities if e.get('mount-point')==str(mount)]
    if len(volumes)!=1: raise SystemExit('Expected one OS volume attachment')
    info=plistlib.loads(subprocess.check_output(['diskutil','info','-plist',volumes[0]['dev-entry']]))
    if info.get('Writable') is not False or info.get('BusProtocol')!='Disk Image':
        raise SystemExit('OS attachment is not a read-only disk image')
    subprocess.run([sys.executable,str(args.unixnu.resolve()/'scripts/prepare-owner-data-fixture.py'),
                    '--output',str(args.output.resolve())],check=True)
finally:
    subprocess.run(['hdiutil','detach',device],check=True)
