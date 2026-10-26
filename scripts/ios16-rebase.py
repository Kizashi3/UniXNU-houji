"""Resolve plain ARM64 chained rebases before DarwinBoot copies segments.

Decoder follows the pinned reference tools/mkpayload.py; chain walks are bounded
to their segment/page and reject imports, arm64e and repeated pointer slots.
"""
import argparse
import hashlib
import json
import runpy
import struct
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ios16_modem import kernel_declaration

def require(ok,why):
    if not ok: raise ValueError(why)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--kernel',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    require(not a.out.exists(),'Output already exists')
    buf=bytearray(a.kernel.read_bytes()); original=hashlib.sha256(buf).hexdigest()
    require(len(buf)>=32,'Truncated Mach-O')
    magic,cpu,sub,_,ncmd,cmdbytes,_,_=struct.unpack_from('<8I',buf)
    require((magic,cpu,sub)==(0xfeedfacf,0x100000c,0),'Expected plain ARM64 kernel')
    require(cmdbytes<=len(buf)-32 and ncmd<=cmdbytes//8,'Bad command bounds')
    at=32
    for _ in range(ncmd):
        require(at+8<=32+cmdbytes,'Truncated command')
        cmd,size=struct.unpack_from('<II',buf,at)
        require(size>=8 and size%8==0 and at+size<=32+cmdbytes,'Bad command size')
        if cmd==0x19: require(size>=72,'Short segment')
        if cmd==0x80000034: require(size==16,'Short fixup command')
        at+=size
    require(at==32+cmdbytes,'Command length mismatch')
    sys.path.insert(0,str(a.reference/'tools'))
    lib=runpy.run_path(str(a.reference/'tools/mkpayload.py'))
    m=lib['parse_macho'](buf)
    require(m['entry'] is not None and m['segs'],'Missing entry/segments')
    require(m['segs'][0]['name']=='__TEXT' and m['segs'][0]['fileoff']==0,'Unexpected image base')
    for s in m['segs']:
        require(s['fileoff']<=len(buf) and s['filesize']<=len(buf)-s['fileoff'],'Segment file bounds')
        # __CTF is file-only debug metadata (vmsize=0); DarwinBoot omits it.
        require(not s['vmsize'] or s['filesize']<=s['vmsize'],'Loaded segment bounds')
    count=0; seen=set()
    if m['fixups']:
        off,size=m['fixups']; limit=off+size
        require(size>=28 and limit<=len(buf),'Fixup bounds')
        version,starts,_,_,imports,_,_=struct.unpack_from('<7I',buf,off)
        require(version==0 and imports==0 and 28<=starts<=size-4,'Unsupported fixup header')
        ns,=struct.unpack_from('<I',buf,off+starts)
        require(ns<=len(m['segs']) and starts+4+4*ns<=size,'Starts array bounds')
        for i in range(ns):
            relative,=struct.unpack_from('<I',buf,off+starts+4+4*i)
            if not relative: continue
            base=off+starts+relative
            require(base>=off and base+22<=limit,'Segment chain header bounds')
            sz,page,fmt,_,_,np=struct.unpack_from('<IHHQIH',buf,base)
            require(fmt in (2,6,8) and page==0x4000,'Unsupported pointer/page format')
            require(sz>=22+2*np and base+sz<=limit,'Page array bounds')
            seg=m['segs'][i]
            for j in range(np):
                start,=struct.unpack_from('<H',buf,base+22+2*j)
                if start==0xffff: continue
                require(start<page and not start&0x8000,'Unsupported multi-start')
                lo=seg['fileoff']+j*page
                hi=min(lo+page,seg['fileoff']+seg['filesize'])
                loc=lo+start
                while True:
                    require(loc>=lo and loc+8<=hi and loc not in seen,'Chain escaped/revisited page')
                    seen.add(loc)
                    value,=struct.unpack_from('<Q',buf,loc)
                    target,nxt,stride=lib['decode'](value,fmt,m['segs'][0]['vmaddr'])
                    struct.pack_into('<Q',buf,loc,target); count+=1
                    if not nxt: break
                    loc+=nxt*stride
    modem_declaration=kernel_declaration(buf)
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_bytes(buf)
    report={'input_sha256':original,'output_sha256':hashlib.sha256(buf).hexdigest(),
            'rebases':count,'virtual_base':hex(m['segs'][0]['vmaddr']&~0x1ffffff),
            'entry':hex(m['entry']),'boot_args_bytes':736,'page_bytes':16384,
            'hardware_verified':False}
    report.update(modem_declaration)
    a.out.with_suffix('.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
