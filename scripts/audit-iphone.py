"""Inspect an official iPhone restore kernel; never relabel or patch its ABI."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import shutil
import re
import sys
import zipfile

p=argparse.ArgumentParser()
p.add_argument('--unixnu',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--target',type=Path,required=True)
p.add_argument('--cache',type=Path,required=True)
args=p.parse_args()
root=Path(__file__).resolve().parents[1]
target=json.loads(args.target.read_text())
sys.path.insert(0,str(args.unixnu/'scripts'))
from unixnu.ipsw import RangeFile,im4p_payload
sys.path.insert(0,str(args.unixnu/'kits/NativePrelink'))
from native_prelink import macho

args.out.mkdir(parents=True,exist_ok=True)
args.cache.mkdir(parents=True,exist_ok=True)
cached=args.cache/'kernel.im4p'
pin=target.get('kernel_im4p_sha256')
im4p=cached.read_bytes() if cached.is_file() else b''
cache_hit=bool(pin and hashlib.sha256(im4p).hexdigest()==pin)
if cache_hit:
    member=target['kernel_member']
    print('Using SHA256-verified iPhone kernel cache; no CDN request')
else:
  stream=RangeFile(target['url'])
  with zipfile.ZipFile(stream) as archive:
    manifest=plistlib.loads(archive.read('BuildManifest.plist'))
    assert manifest['ProductVersion']==target['version']
    assert manifest['ProductBuildVersion']==target['build']
    assert target['product'] in manifest['SupportedProductTypes']
    ident=next(i for i in manifest['BuildIdentities'] if i['Info']['DeviceClass']==target['device_class']
               and i['Info']['RestoreBehavior']=='Erase')
    assert int(ident['ApChipID'],16)==int(target['chip_id'],16)
    assert int(ident['ApBoardID'],16)==int(target['board_id'],16)
    member=ident['Manifest']['KernelCache']['Info']['Path']
    im4p=archive.read(member)
  if pin and hashlib.sha256(im4p).hexdigest()!=pin:
    raise SystemExit('iPhone kernelcache SHA256 mismatch')
  cached.write_bytes(im4p)
packed=args.out/'kernel.lzfse'
packed.write_bytes(im4p_payload(im4p))
raw=args.out/'kernel.raw'
if shutil.which('compression_tool'):
    subprocess.run(['compression_tool','-decode','-a','lzfse','-i',str(packed),'-o',str(raw)],check=True)
else:
    import lzfse
    raw.write_bytes(lzfse.decompress(packed.read_bytes()))
data=raw.read_bytes()
slices=[]
if data[:4]==b'\xca\xfe\xba\xbe':
    count=struct.unpack_from('>I',data,4)[0]
    for i in range(count):
        cpu,subtype,offset,size,alignment=struct.unpack_from('>5I',data,8+20*i)
        slices.append((offset,size,cpu,subtype))
else:
    magic,cpu,subtype=struct.unpack_from('<3I',data)
    if magic!=0xfeedfacf:
        raise SystemExit('Unsupported kernel container')
    slices.append((0,len(data),cpu,subtype))
results=[]
for offset,size,cpu,subtype in slices:
    blob=data[offset:offset+size]
    if len(blob)!=size:
        raise SystemExit('Truncated kernel slice')
    try:
        macho(blob)
        accepted=True
        reason='accepted'
    except ValueError as e:
        accepted=False
        reason=str(e)
    version=re.search(rb'Darwin Kernel Version [^\x00\r\n]{1,300}',blob)
    results.append({'cpu':hex(cpu),'cpu_subtype':hex(subtype),'base_subtype':subtype&0xffffff,
                    'darwin_version':version.group().decode('ascii','replace') if version else None,
                    'size':size,'sha256':hashlib.sha256(blob).hexdigest(),
                    'native_prelink_accepts':accepted,'reason':reason})
report={'target':target,'member':member,'im4p_sha256':hashlib.sha256(im4p).hexdigest(),
        'slices':results,'cache_hit':cache_hit,'hardware_tested':False,'ready_to_boot':False}
(args.out/'architecture.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
