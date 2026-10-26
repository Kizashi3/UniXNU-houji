"""Attach the verified APFS Data seed to a copy of a qualified XNU FAT payload.

This integrates loader handoff, not automatic /private/var mounting. Preserves
the original kernel and baseline payload; writes a new payload and UEFI identity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import zlib

ROOT=Path(__file__).resolve().parents[1]
def digest(path):
    with path.open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def require(ok,message):
    if not ok: raise SystemExit(message)

p=argparse.ArgumentParser()
p.add_argument('--base',type=Path,required=True)
p.add_argument('--seed',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--identity',type=Path,required=True)
args=p.parse_args()
base=json.loads((args.base/'payload.json').read_text())
seed=json.loads((ROOT/'hardware/data-seed.json').read_text())
require(digest(args.base/'payload.img')==base['payload_sha256'],'Base payload hash mismatch')
require(args.seed.stat().st_size==seed['bytes'] and digest(args.seed)==seed['sha256'],'Data seed hash/size mismatch')
require(not args.out.exists(),'Refusing to overwrite existing output directory')
args.out.mkdir(parents=True)
output=args.out/'payload.img'
shutil.copyfile(args.base/'payload.img',output)
with tempfile.TemporaryDirectory() as directory:
    temp=Path(directory)
    for path in ['Payloads/kernel.macho','unixnu.toml']:
        subprocess.run(['mcopy','-i',str(output),f'::/EFI/UniXNU/{path}',str(temp/Path(path).name)],check=True)
    kernel=temp/'kernel.macho'
    require(digest(kernel)==base['payload_kernel_sha256'],'Embedded kernel hash mismatch')
    with kernel.open('rb') as f: image=f.read()
    ncmd=struct.unpack_from('<I',image,16)[0];at=32;regions=[]
    for _ in range(ncmd):
        cmd,size=struct.unpack_from('<II',image,at)
        require(size>=8 and at+size<=len(image),'Invalid Mach-O command')
        if cmd==0x19:
            va,vm_size=struct.unpack_from('<QQ',image,at+24)
            if vm_size: regions.append((va,va+vm_size))
        at+=size
    span=max(end for _,end in regions)-min(start for start,_ in regions)
    adt=temp/'kernel.macho.adt'
    subprocess.run([sys.executable,str(ROOT/'scripts/make-giulia-adt.py'),
        '--output',str(adt),'--dram-size','0x10000000','--data-ramdisk'],check=True)
    align=lambda n,a:(n+a-1)//a*a
    used=align(align(align(span,16384)+4096+adt.stat().st_size,4096)+align(seed['bytes'],4096),16384)
    require(used<=0x10000000-0x200000,'Data seed exceeds the DarwinBoot allocation window')
    cfg=temp/'unixnu.toml';text=cfg.read_text();parsed=tomllib.loads(text)
    entry=next(e for e in parsed['entry'] if e['id']=='xnu')
    require('initrd' not in entry,'Base payload already has an initrd')
    marker='path = "Payloads/kernel.macho"\n'
    require(text.count(marker)==1,'Unexpected boot configuration')
    text=text.replace(marker,marker+'initrd = "Payloads/scratch-data.img"\n')
    text=text.replace('Ace 5 XNU first entry (no system volume)','Ace 5 XNU + APFS Data handoff')
    cfg.write_text(text)
    for source,dest in [(cfg,'unixnu.toml'),(adt,'Payloads/kernel.macho.adt'),(args.seed,'Payloads/scratch-data.img')]:
        subprocess.run(['mcopy','-o','-i',str(output),str(source),f'::/EFI/UniXNU/{dest}'],check=True)
    adt_sha=digest(adt)
report=dict(base,data_ramdisk_sha256=seed['sha256'],data_volume_uuid=seed['volume_uuid_reported_by_diskutil'],
    adt_sha256=adt_sha,payload_sha256=digest(output),payload_bytes=output.stat().st_size,
    handoff_used_bytes=used,data_transport='dense RAMDisk',data_mounted=False,hardware_tested=False,
    purpose='XNU with APFS Data seed handoff; system root not yet mounted')
(args.out/'payload.json').write_text(json.dumps(report,indent=2)+'\n')
crc=0
with output.open('rb') as f:
    while chunk:=f.read(1<<20): crc=zlib.crc32(chunk,crc)
identity={'base_kernel_run':39511969648,'data_seed_run':seed['run_id'],
    'payload_bytes':report['payload_bytes'],'payload_crc32':f'{crc:08x}',
    'payload_sha256':report['payload_sha256'],'kernel_sha256':report['payload_kernel_sha256'],
    'data_sha256':seed['sha256'],'purpose':report['purpose']}
args.identity.write_text(json.dumps(identity,indent=2)+'\n')
print(json.dumps(report,indent=2))
