"""Inventory checksum-valid APFS volume superblocks in a bounded image prefix.

This is a metadata inventory, not object-map/checkpoint resolution or a mount.
Layout: Apple File System Reference (2020), apfs_superblock_t.
https://developer.apple.com/support/downloads/Apple-File-System-Reference.pdf
"""
import argparse
import json
from pathlib import Path
import struct
import uuid

def checksum(block):
    modulus=0xffffffff
    first=second=0
    for (word,) in struct.iter_unpack('<I',block[8:]):
        first=(first+word)%modulus
        second=(second+first)%modulus
    low=modulus-(first+second)%modulus
    high=modulus-(first+low)%modulus
    return struct.pack('<II',low,high)==block[:8]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('image',type=Path)
    p.add_argument('--container-offset',type=lambda value:int(value,0),default=0)
    p.add_argument('--scan-mib',type=int,default=64)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.container_offset<0 or not 1<=a.scan_mib<=512:p.error('Invalid scan bounds')
    with a.image.open('rb') as f:
        f.seek(a.container_offset);nx=f.read(4096)
        if len(nx)!=4096 or nx[32:36]!=b'NXSB' or not checksum(nx):
            raise SystemExit('Container header magic/checksum failed')
        size=struct.unpack_from('<I',nx,36)[0]
        blocks=struct.unpack_from('<Q',nx,40)[0]
        if size!=4096 or blocks*size>a.image.stat().st_size-a.container_offset:
            raise SystemExit('Unsupported block size or container bounds')
        scan=min(a.scan_mib*1024*1024,blocks*size)
        f.seek(a.container_offset);data=f.read(scan)
    volumes=[]
    for offset in range(0,len(data)-4095,4096):
        block=data[offset:offset+4096]
        if block[32:36]!=b'APSB' or struct.unpack_from('<I',block,24)[0]&0xffff!=13:
            continue
        if not checksum(block):continue
        volumes.append({'block':offset//4096,'oid':struct.unpack_from('<Q',block,8)[0],
            'xid':struct.unpack_from('<Q',block,16)[0],
            'uuid':str(uuid.UUID(bytes=block[240:256])).upper(),
            'name':block[704:960].split(b'\0',1)[0].decode('utf-8'),
            'role':struct.unpack_from('<H',block,964)[0]})
    report={'image':str(a.image),'container_offset':a.container_offset,
            'container_uuid':str(uuid.UUID(bytes=nx[72:88])).upper(),
            'scanned_bytes':scan,'checksum_valid_candidates':volumes,
            'current_checkpoint_resolved':False,'mounted':False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
