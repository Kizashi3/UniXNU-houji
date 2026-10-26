"""Verify a converted system disk against UDIF size, GPT CRCs and APFS magic.

Reads regular host files only. Does not mount, repair or write the disk image.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import uuid
import zlib

p=argparse.ArgumentParser()
p.add_argument('--dmg',type=Path,required=True)
p.add_argument('--raw',type=Path,required=True)
p.add_argument('--report',type=Path,required=True)
args=p.parse_args()
def require(value,message):
    if not value: raise SystemExit(message)
with args.dmg.open('rb') as f:
    f.seek(-512,2)
    footer=f.read(512)
require(footer[:4]==b'koly','Missing UDIF trailer')
expected=struct.unpack_from('>Q',footer,492)[0]*512
require(args.raw.stat().st_size==expected,'Converted image size differs from UDIF')
with args.raw.open('rb') as f:
    def gpt(lba):
        f.seek(lba*512)
        sector=f.read(512)
        require(sector[:8]==b'EFI PART','Missing GPT header')
        size,crc=struct.unpack_from('<II',sector,12)
        require(92<=size<=512,'Invalid GPT header length')
        header=bytearray(sector[:size]); header[16:20]=bytes(4)
        require(zlib.crc32(header)==crc,'GPT header CRC mismatch')
        this,other=struct.unpack_from('<QQ',sector,24)
        entries_lba=struct.unpack_from('<Q',sector,72)[0]
        count,entry_size,table_crc=struct.unpack_from('<III',sector,80)
        require(this==lba and other*512<expected,'Invalid GPT location')
        require(0<count<=4096 and entry_size>=128 and entry_size%8==0,'Invalid GPT table geometry')
        require(entries_lba*512+count*entry_size<=expected,'GPT table outside disk')
        f.seek(entries_lba*512)
        table=f.read(count*entry_size)
        require(zlib.crc32(table)==table_crc,'GPT entry CRC mismatch')
        return other,table,entry_size,sector[56:72]
    backup,table,entry_size,disk_uuid=gpt(1)
    back_primary,back_table,back_size,back_uuid=gpt(backup)
    require(back_primary==1 and table==back_table and entry_size==back_size and disk_uuid==back_uuid,
            'Primary and backup GPT disagree')
    partitions=[]
    for at in range(0,len(table),entry_size):
        entry=table[at:at+entry_size]
        if entry[:16]==bytes(16): continue
        kind=str(uuid.UUID(bytes_le=entry[:16])).upper()
        first,last=struct.unpack_from('<QQ',entry,32)
        require(first<=last and (last+1)*512<=expected,'Partition outside image')
        item={'type':kind,'first_lba':first,'last_lba':last,
              'name':entry[56:128].decode('utf-16le').rstrip('\0')}
        if kind=='7C3457EF-0000-11AA-AA11-00306543ECAC':
            f.seek(first*512)
            nx=f.read(4096)
            require(nx[32:36]==b'NXSB','Missing APFS container superblock')
            item['apfs_block_size']=struct.unpack_from('<I',nx,36)[0]
            item['apfs_container_uuid']=str(uuid.UUID(bytes=nx[72:88])).upper()
        partitions.append(item)
    require(any('apfs_block_size' in item for item in partitions),'No APFS partition')
with args.raw.open('rb') as f:
    digest=hashlib.file_digest(f,'sha256').hexdigest()
report={'bytes':expected,'sha256':digest,'gpt_crc_valid':True,'partitions':partitions,
        'mounted':False,'hardware_tested':False}
args.report.parent.mkdir(parents=True,exist_ok=True)
args.report.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
