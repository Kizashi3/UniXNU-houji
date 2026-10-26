"""Package an audited diagnostic kernel without changing Data or the ADT."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zlib

p=argparse.ArgumentParser()
p.add_argument('--base',type=Path,required=True)
p.add_argument('--kernel',type=Path,required=True)
p.add_argument('--audit',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--identity',type=Path,required=True)
a=p.parse_args()
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
r=json.loads((a.base/'payload.json').read_text());audit=json.loads(a.audit.read_text())
if sha(a.base/'payload.img')!=r['payload_sha256']:raise SystemExit('Base payload mismatch')
if audit['original_sha256']!=r['payload_kernel_sha256'] or sha(a.kernel)!=audit['patched_sha256']:
    raise SystemExit('Kernel probe audit mismatch')
if a.out.exists():raise SystemExit('Refusing to overwrite output directory')
a.out.mkdir(parents=True);image=a.out/'payload.img';shutil.copyfile(a.base/'payload.img',image)
subprocess.run(['mcopy','-o','-i',str(image),str(a.kernel),'::/EFI/UniXNU/Payloads/kernel.macho'],check=True)
with tempfile.TemporaryDirectory() as directory:
    cfg=Path(directory)/'unixnu.toml'
    subprocess.run(['mcopy','-i',str(image),'::/EFI/UniXNU/unixnu.toml',str(cfg)],check=True)
    text=cfg.read_text().replace('Ace 5 XNU + APFS Data handoff','Ace 5 XNU early-entry diagnostics')
    cfg.write_text(text)
    subprocess.run(['mcopy','-o','-i',str(image),str(cfg),'::/EFI/UniXNU/unixnu.toml'],check=True)
r.update(payload_kernel_sha256=audit['patched_sha256'],payload_sha256=sha(image),
         purpose='XNU entry/MMU/panic diagnostics with unchanged Data seed',entry_probe=audit,
         panic_screen=audit['panic_screen'],hardware_tested=False)
(a.out/'payload.json').write_text(json.dumps(r,indent=2)+'\n')
crc=0
with image.open('rb') as f:
    while chunk:=f.read(1<<20):crc=zlib.crc32(chunk,crc)
identity={'payload_bytes':image.stat().st_size,'payload_crc32':f'{crc:08x}',
          'payload_sha256':r['payload_sha256'],'kernel_sha256':r['payload_kernel_sha256'],
          'data_sha256':r['data_ramdisk_sha256'],'purpose':r['purpose']}
a.identity.write_text(json.dumps(identity,indent=2)+'\n');print(json.dumps(identity,indent=2))
