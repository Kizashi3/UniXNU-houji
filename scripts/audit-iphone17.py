"""Inspect an official iPhone restore kernel; never relabel or patch its ABI."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import zipfile

p=argparse.ArgumentParser()
p.add_argument('--unixnu',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
args=p.parse_args()
root=Path(__file__).resolve().parents[1]
target=json.loads((root/'targets/iphone17.json').read_text())
sys.path.insert(0,str(args.unixnu/'scripts'))
from unixnu.ipsw import RangeFile,im4p_payload
sys.path.insert(0,str(args.unixnu/'kits/NativePrelink'))
from native_prelink import macho

args.out.mkdir(parents=True,exist_ok=True)
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
packed=args.out/'kernel.lzfse'
packed.write_bytes(im4p_payload(im4p))
raw=args.out/'kernel.raw'
subprocess.run(['/usr/bin/compression_tool','-decode','-a','lzfse','-i',str(packed),'-o',str(raw)],check=True)
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
    results.append({'cpu':hex(cpu),'cpu_subtype':hex(subtype),'base_subtype':subtype&0xffffff,
                    'size':size,'sha256':hashlib.sha256(blob).hexdigest(),
                    'native_prelink_accepts':accepted,'reason':reason})
report={'target':target,'member':member,'im4p_sha256':hashlib.sha256(im4p).hexdigest(),
        'slices':results,'hardware_tested':False}
(args.out/'architecture.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
