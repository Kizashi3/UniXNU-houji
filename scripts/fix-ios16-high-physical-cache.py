"""Apply/check the compiled equivalent of the Darwin 22 high-PA source patch.

For existing rebased ARM64/16-KiB builds only. Resolve the actual function symbol,
verify the function AND its two inlined copies, including their four-instruction
sequences and flush_dcache targets. Retain the input image. Future source builds
include patch 0081 directly, so the compiler fixes every inline expansion.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import bisect

OLD=0x53124400  # lsl w0,w0,#14: shifts in 32 bits, truncating physical addresses
NEW=0xd3727c00  # ubfiz x0,x0,#14,#32: zero-extend ppnum_t, then shift in 64 bits


def locate(data):
    if len(data)<32 or struct.unpack_from('<III',data)!=(0xfeedfacf,0x100000c,0):
        raise ValueError('Expected a plain ARM64 Mach-O')
    count,command_bytes=struct.unpack_from('<II',data,16)
    if count>128 or command_bytes>len(data)-32:
        raise ValueError('Invalid Mach-O command bounds')
    at=32;segments=[];symtab=None
    for _ in range(count):
        if at+8>32+command_bytes:raise ValueError('Truncated command')
        command,size=struct.unpack_from('<II',data,at)
        if size<8 or size%8 or size>32+command_bytes-at:raise ValueError('Invalid command size')
        if command==0x1d:raise ValueError('Refusing a code-signed Mach-O')
        if command==0x19:
            if size<72:raise ValueError('Short segment')
            _,va,vm,offset,length=struct.unpack_from('<16sQQQQ',data,at+8)
            if offset>len(data) or length>len(data)-offset:raise ValueError('Segment file bounds')
            protection=struct.unpack_from('<I',data,at+60)[0]
            segments.append((va,offset,length,protection))
        if command==2:
            if size!=24 or symtab:raise ValueError('Invalid/duplicate symbol table')
            symtab=struct.unpack_from('<IIII',data,at+8)
        at+=size
    if at!=32+command_bytes or not symtab:raise ValueError('Missing symbol table')
    offset,count,strings,bytes_=symtab
    if offset>len(data) or count>(len(data)-offset)//16 or strings>len(data) or bytes_>len(data)-strings:
        raise ValueError('Symbol table bounds')
    wanted={b'_pmap_sync_page_attributes_phys',b'_flush_dcache'};found={};symbols=[]
    for i in range(count):
        index,kind,section,description,value=struct.unpack_from('<IBBHQ',data,offset+16*i)
        if index>=bytes_:raise ValueError('Symbol string outside table')
        end=data.find(b'\0',strings+index,strings+bytes_)
        if end<0:raise ValueError('Unterminated symbol')
        name=bytes(data[strings+index:end])
        if kind&0xe==0xe:symbols.append((value,name))
        if name in wanted and kind&0xe==0xe:
            if name in found:raise ValueError('Ambiguous function symbol')
            found[name]=value
    if found.keys()!=wanted:raise ValueError('Required functions missing')
    address=found[b'_pmap_sync_page_attributes_phys'];positions=[]
    for va,offset,length,protection in segments:
        if va<=address and address-va+16<=length:positions.append(offset+address-va)
    if len(positions)!=1 or address%4:raise ValueError('Function mapping is ambiguous')
    offset=positions[0];words=struct.unpack_from('<4I',data,offset)
    if words[0] not in (OLD,NEW) or words[1:3]!=(0x52880001,0x52800022) or words[3]&0xfc000000!=0x14000000:
        raise ValueError('Unexpected cache-sync implementation; refusing a guessed patch')
    branch=words[3]&0x3ffffff
    if branch&0x2000000:branch-=0x4000000
    if address+12+branch*4!=found[b'_flush_dcache']:
        raise ValueError('Cache-sync tail call is not flush_dcache')
    symbols.sort();addresses=[v for v,n in symbols]
    expected={b'_pmap_sync_page_attributes_phys',b'_pmap_update_compressor_page_internal',
              b'_pmap_set_cache_attributes_internal'}
    sites=[]
    for va,start,length,protection in segments:
        if not protection&4:continue
        for offset in range(start,start+length-15,4):
            word=struct.unpack_from('<I',data,offset)[0]
            hoisted=word==0xaa1303e0 # reviewed compiler form: mov x0,x19
            if word&~0x3e0 not in (OLD,NEW) and not hoisted:continue
            w1,w2,call=struct.unpack_from('<3I',data,offset+4)
            if (w1,w2)!=(0x52880001,0x52800022) or call&0x7c000000!=0x14000000:continue
            address=va+offset-start;relative=call&0x3ffffff
            if relative&0x2000000:relative-=0x4000000
            if address+12+relative*4!=found[b'_flush_dcache']:continue
            index=bisect.bisect_right(addresses,address)-1
            name=symbols[index][1] if index>=0 else b''
            if name not in expected:raise ValueError('Unreviewed cache-sync inline site: '+repr(name))
            site={'symbol':name.decode(),'address':hex(address),'file_offset':hex(offset),
                  'instruction':hex(word),'fixed':word&~0x3e0==NEW}
            if hoisted:
                # Source builds reuse the PA already widened in the prologue.
                # x19 is the callee-saved PA in both reviewed pmap functions.
                # Require their exact widening operation before any branches;
                # merely seeing a 64-bit move is insufficient.
                if name==b'_pmap_sync_page_attributes_phys':raise ValueError('Unexpected hoisted standalone function')
                origin=start+symbols[index][0]-va+0x1c
                if not start<=origin<offset:raise ValueError('Invalid hoisted address origin')
                widened=struct.unpack_from('<I',data,origin)[0]
                if widened&~0x3e0!=(NEW|19):raise ValueError('Hoisted page address was not widened before shifting')
                site.update(fixed=True,form='hoisted-64-bit-address',origin_file_offset=hex(origin),origin_instruction=hex(widened))
            sites.append(site)
    if len(sites)!=3 or {s['symbol'].encode() for s in sites}!=expected:
        raise ValueError('Expected the cache-sync function and both reviewed inline expansions')
    return sites


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel',type=Path,required=True)
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--out',type=Path);mode.add_argument('--check',action='store_true')
    a=p.parse_args();data=a.kernel.read_bytes();sites=locate(data)
    report={'patch_version':2,'sites':sites,'fixed':all(s['fixed'] for s in sites)}
    if a.check:
        if not report['fixed']:raise ValueError('High physical-address truncation remains in a function or inline copy')
        print(json.dumps(report,indent=2));return
    if report['fixed']:raise ValueError('Input is already fully fixed')
    if a.out.exists() or a.out.with_suffix('.json').exists():raise ValueError('Output already exists')
    metadata=json.loads(a.kernel.with_suffix('.json').read_text())
    digest=hashlib.sha256(data).hexdigest()
    if metadata.get('output_sha256')!=digest or metadata.get('boot_args_bytes')!=736 or metadata.get('page_bytes')!=16384:
        raise ValueError('Input handoff report mismatch')
    changed=bytearray(data);allowed=set()
    for site in sites:
        if site['fixed']:continue
        offset=int(site['file_offset'],0);word=int(site['instruction'],0)
        if word&~0x3e0!=OLD:raise ValueError('Only reviewed truncating shifts may be patched')
        struct.pack_into('<I',changed,offset,NEW|(word&0x3e0));allowed.update(range(offset,offset+4))
    assert len(changed)==len(data)
    assert all(i in allowed for i,(a,b) in enumerate(zip(data,changed)) if a!=b)
    assert all(s['fixed'] for s in locate(changed))
    patch=Path(__file__).resolve().parents[1]/'ios16/0081-giulia-pmap-high-physical-cache-sync.patch'
    report.update(fixed=True,original_sites=sites,sites=locate(changed),
                  input_sha256=digest,source_patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
                  changed_instruction_bytes=len(allowed),hardware_tested=False)
    metadata.update(output_sha256=hashlib.sha256(changed).hexdigest(),hardware_verified=False,
                    high_physical_cache_fix=report)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_bytes(changed)
    a.out.with_suffix('.json').write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
