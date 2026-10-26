"""Expand a verified HFSX root and validate its Android sparse transport copy.

Produces host files only. Does not invoke fastboot, mount a volume or write
to any connected handset. Run under Linux/WSL with img2simg installed.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess

def need(ok,why):
    if not ok:raise ValueError(why)

def sparse_digest(path):
    sha=hashlib.sha256();written=0; zero=bytes(1024**2)
    with path.open('rb') as f:
        h=f.read(28)
        need(len(h)==28,'Short sparse header')
        magic,major,minor,fh,ch,block,blocks,chunks,checksum=struct.unpack('<IHHHHIIII',h)
        need(magic==0xed26ff3a and major==1 and minor==0 and fh==28 and ch==12 and block==4096,'Unexpected sparse format')
        for _ in range(chunks):
            h=f.read(12);need(len(h)==12,'Short chunk header')
            typ,reserved,n,total=struct.unpack('<HHII',h);length=n*block
            need(written+length<=blocks*block and total>=12 and reserved==0,'Chunk bounds')
            if typ==0xcac1:
                need(total==12+length,'Raw chunk size')
                left=length
                while left:
                    b=f.read(min(left,1024**2));need(bool(b),'Truncated raw chunk')
                    sha.update(b);left-=len(b)
            elif typ in (0xcac2,0xcac3):
                need(total==12+(4 if typ==0xcac2 else 0),'Fill/skip size')
                value=f.read(4) if typ==0xcac2 else bytes(4)
                need(len(value)==4,'Truncated fill')
                data=value*(1024**2//4) if any(value) else zero
                left=length
                while left:
                    take=min(left,len(data));sha.update(data[:take]);left-=take
            elif typ==0xcac4:
                need(n==0 and total==16 and len(f.read(4))==4,'CRC chunk size')
            else:raise ValueError('Unknown sparse chunk type')
            written+=length
        need(written==blocks*block and f.read(1)==b'','Sparse total/trailing data')
    return written,sha.hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--gzip',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();r=json.loads(a.report.read_text())
    need(r['bytes']==16*1024**3 and r['block_size']==4096 and not r['partition_table'],'Unexpected root format')
    a.out.mkdir(parents=True,exist_ok=True)
    raw=a.out/'giulia-ios16-userdata.img'; sparse=a.out/'giulia-ios16-userdata.sparse.img'
    need(not raw.exists() and not sparse.exists(),'Output already exists')
    sha=hashlib.sha256();done=0
    with gzip.open(a.gzip,'rb') as src,raw.with_suffix('.partial').open('wb') as dst:
        while b:=src.read(8*1024**2):
            done+=len(b);need(done<=r['bytes'],'Root exceeds expected size')
            sha.update(b);dst.write(b)
    need(done==r['bytes'] and sha.hexdigest()==r['sha256'],'Root SHA256 mismatch')
    raw.with_suffix('.partial').rename(raw)
    with raw.open('rb') as f:f.seek(1024);h=f.read(512)
    need(h[:4]==b'HX\x00\x05' and h[104:112].hex()==r['hfs_finder_id'],'HFSX identity mismatch')
    need(struct.unpack_from('>II',h,40)==(4096,4194304),'HFSX geometry mismatch')
    need(struct.unpack_from('>I',h,4)[0]&0x2000,'Missing HFS journal')
    print('Raw 16 GiB HFSX SHA256 and volume identity verified',flush=True)
    subprocess.run(['img2simg',str(raw),str(sparse),'4096'],check=True)
    size,digest=sparse_digest(sparse)
    need(size==r['bytes'] and digest==r['sha256'],'Sparse expansion differs from raw root')
    with sparse.open('rb') as f:transport_sha=hashlib.file_digest(f,'sha256').hexdigest()
    result=dict(r,raw_file=raw.name,sparse_file=sparse.name,sparse_sha256=transport_sha,
                sparse_bytes=sparse.stat().st_size,sparse_expansion_verified=True,
                target_partition='userdata',target_serial='3B159A00A5U00000',flashed=False)
    (a.out/'userdata.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__': main()
