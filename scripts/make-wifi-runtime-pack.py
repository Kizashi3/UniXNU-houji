"""Create a deterministic read-only pack and a small source digest pin."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from ios16_wifi_firmware import load_bundle

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--bundle',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--header',type=Path,required=True)
a=p.parse_args()
r=load_bundle(a.bundle)
if a.out.exists():raise ValueError('Refusing to replace an existing pack')
entries=sorted(r['files'],key=lambda e:e['path'])
start=(64+112*len(entries)+0x3fff)&~0x3fff
data=bytearray(start)
for i,e in enumerate(entries):
    name=e['path'].encode('ascii')
    if len(name)>63:raise ValueError('Asset name too long')
    while len(data)%64:data.append(0)
    offset=len(data);payload=(a.bundle/e['path']).read_bytes();data.extend(payload)
    at=64+i*112;data[at:at+len(name)]=name
    struct.pack_into('<II',data,at+64,offset,len(payload))
    data[at+72:at+104]=bytes.fromhex(e['sha256'])
    struct.pack_into('<I',data,at+104,int(payload.startswith(b'\x7fELF')))
struct.pack_into('<8s9I',data,0,b'GWFWPK1\0',1,len(entries),len(data),64,112,start,23851,0x4e43,0x110717cb)
digest=hashlib.sha256(data).digest()
a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_bytes(data)
a.header.parent.mkdir(parents=True,exist_ok=True)
a.header.write_text('/* Original PKG110 16.0.3.500 CN firmware pack; generated, contains no firmware bytes. */\n'
    '#ifndef GIULIA_WIFI_FIRMWARE_PIN_H\n#define GIULIA_WIFI_FIRMWARE_PIN_H\n'
    'static const unsigned char gw_firmware_pack_sha256[32]={'+','.join(f'0x{x:02x}' for x in digest)+'};\n'
    f'#define GW_FIRMWARE_PACK_BYTES {len(data)}u\n#endif\n')
report={'sha256':digest.hex(),'bytes':len(data),'assets':len(entries),'manifest_sha256':hashlib.sha256((a.bundle/'manifest.json').read_bytes()).hexdigest(),'firmware_uploaded':False}
a.out.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
