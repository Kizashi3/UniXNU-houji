"""Decode pinned UDIF system images to new raw host files using LZFSE.

Only supports the chunk types present in the qualified images. Refuses
overlapping/out-of-range chunks and checks every decoded chunk length.
Requires the lzfse Python binding; never opens a device or mounts a volume.
"""
import argparse
import bz2
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import zlib
import lzfse

p=argparse.ArgumentParser()
p.add_argument('--source',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
p.add_argument('--sha256',required=True)
args=p.parse_args()
def require(value,message):
    if not value: raise SystemExit(message)
require(not args.output.exists(),'Refusing to overwrite output')
with args.source.open('rb') as f:
    require(hashlib.file_digest(f,'sha256').hexdigest()==args.sha256,'Input SHA256 mismatch')
    f.seek(-512,2); footer=f.read(512)
    require(footer[:4]==b'koly','Missing UDIF trailer')
    data_base,data_size=struct.unpack_from('>QQ',footer,24)
    xml_at,xml_size=struct.unpack_from('>QQ',footer,216)
    total=struct.unpack_from('>Q',footer,492)[0]*512
    require(0<xml_size<16*1024*1024 and xml_at+xml_size<=args.source.stat().st_size-512,'Invalid XML range')
    f.seek(xml_at); metadata=plistlib.loads(f.read(xml_size))
    plan=[]
    for item in metadata['resource-fork']['blkx']:
        table=item['Data']
        require(table[:4]==b'mish','Invalid UDIF block table')
        first,sectors,relative_data=struct.unpack_from('>QQQ',table,8)
        count=struct.unpack_from('>I',table,200)[0]
        require(204+count*40==len(table),'Invalid chunk table length')
        for i in range(count):
            kind,comment,start,length,offset,packed=struct.unpack_from('>IIQQQQ',table,204+i*40)
            if kind==0xffffffff: continue
            require(kind in (0,1,2,0x80000005,0x80000006,0x80000007),'Unsupported compression type')
            require(start+length<=sectors,'Chunk outside block table')
            at=(first+start)*512; size=length*512
            require(at+size<=total,'Chunk outside disk')
            require(relative_data+offset+packed<=data_size,'Compressed chunk outside data fork')
            if kind not in (0,2): require(0<size<=256*1024*1024,'Unreasonable decoded chunk size')
            plan.append((at,size,kind,data_base+relative_data+offset,packed))
    plan.sort()
    end=0
    for at,size,kind,offset,packed in plan:
        require(at==end,'Overlapping chunks or uncovered logical sectors')
        end=at+size
    require(end==total,'Logical disk is incomplete')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('xb') as output:
        output.truncate(total)
        for i,(at,size,kind,offset,packed) in enumerate(plan):
            if kind in (0,2):
                require(packed==0,'Unexpected data in zero/ignored chunk')
                continue
            f.seek(offset); encoded=f.read(packed)
            require(len(encoded)==packed,'Short source read')
            if kind==1: decoded=encoded
            elif kind==0x80000005: decoded=zlib.decompress(encoded)
            elif kind==0x80000006: decoded=bz2.decompress(encoded)
            else: decoded=lzfse.decompress(encoded)
            require(len(decoded)==size,f'Chunk {i} decoded length mismatch')
            output.seek(at); output.write(decoded)
            if i%256==0: print(f'Decoded {i}/{len(plan)} chunks',flush=True)
with args.output.open('rb') as f:
    digest=hashlib.file_digest(f,'sha256').hexdigest()
report={'source_sha256':args.sha256,'raw_sha256':digest,'raw_bytes':total,
        'chunks':len(plan),'all_chunks_length_checked':True,'mounted':False}
args.output.with_suffix(args.output.suffix+'.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
