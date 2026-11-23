#!/usr/bin/env python3
"""Actual fixed candidate, bounded callback failures, and optional pinned Mesa comparison.

Use --mesa-source and --mesa-build-freedreno to compile the actual selected Mesa
emitters/packers and compare every generated command word to this candidate.
All callbacks below are host models. No phone or rendering hardware is accessed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import struct
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mesa-source', type=Path)
parser.add_argument('--mesa-build-freedreno', type=Path)
args = parser.parse_args()
if bool(args.mesa_source) != bool(args.mesa_build_freedreno):
    parser.error('both Mesa paths are required for source qualification')

header = (p/'native/gpu/uefi/GpuKnownImage2d.h').read_text()
arrays = {}
for name in ['br', 'bv', 'prefix', 'body', 'ib']:
    content = re.search(r'static const uint32_t hgki_'+name+r'\[\] = \{(.*?)\};', header, re.S).group(1)
    arrays[name] = [int(v, 16) for v in re.findall(r'0x([0-9a-f]+)u', content)]
plan = json.loads((p/'native/gpu/known-image-2d-source-plan.json').read_text())
for name, words in arrays.items():
    expected = plan['cold_context_candidate']['streams'][name]
    assert len(words) == expected['dwords']
    assert hashlib.sha256(struct.pack('<'+'I'*len(words), *words)).hexdigest() == expected['sha256_le']

if args.mesa_source:
    actual = json.loads(subprocess.check_output([
        'python3', str(p/'scripts/qualify-gpu-known-image-2d.py'),
        '--mesa-source', str(args.mesa_source),
        '--mesa-build-freedreno', str(args.mesa_build_freedreno)], text=True))
    actual['prefix'] = actual.pop('main')
    assert actual == arrays, 'source-emitted command stream differs from fixed candidate'
    print('Pinned Mesa actual emitters/packers: all 573 DWORDs match (ASAN/UBSAN).')

# Decode complete packet streams independently of the C builder. The 2D path
# must not contain CPU-style CP_MEM_WRITE destinations or an arbitrary IB.
def packets(words):
    offset = 0
    while offset < len(words):
        header = words[offset]
        kind = header >> 28
        assert kind in [4, 7], (offset, hex(header))
        count = header & (0x7f if kind == 4 else 0x3fff)
        assert offset + count + 1 <= len(words)
        yield kind, ((header >> 8) & 0x7ffff) if kind == 4 else ((header >> 16) & 0x7f), words[offset+1:offset+1+count]
        offset += count + 1
    assert offset == len(words)

for name in ['br', 'bv', 'prefix', 'body']:
    for kind, op, data in packets(arrays[name]):
        if kind == 7:
            assert op not in [0x3d, 0x3f], (name, op)  # No MEM_WRITE or nested IB.
            if op == 0x55:  # CP_SET_AMBLE: only owned BR/BV BOs or source-zero disabled types.
                assert data[1] == 0
                assert data[0] in [0, 0x62082000, 0x62083000]
                assert data[0] != 0 or data[2] & 0xfffff == 0
body = list(packets(arrays['body']))
assert [x for x in body if x[0] == 7] == [(7, 0x2c, [3]), (7, 0x46, [0x21]), (7, 0x46, [0x31]), (7, 0x26, [])]
assert arrays['ib'] == [0x70bf8003, 0x62084000, 0, 247]
assert arrays['body'].count(0x62085000) == 1

source = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "GpuKnownImage2d.h"
static uint8_t cpu[HGKI_BYTES],device[HGKI_BYTES];
static unsigned guards,reserves,publishes,submits,idles,reads,fail_guard,fail_reserve,fail_publish,fail_submit,fail_idle,fail_read,corrupt;
static uint32_t cursor;
static struct hgki_qualification q;
static struct hgki_result r;
static int guard(void*c){assert(!c);return ++guards==fail_guard?29:0;}
static int reserve(void*c,uint32_t base,uint32_t bytes,uint32_t next){assert(!c && base==HGKI_BASE && bytes==HGKI_BYTES && next==HGKI_CLASS_CURSOR && cursor==next);reserves++;cursor+=bytes;return fail_reserve?31:0;}
static int publish(void*c,uint32_t base,const uint8_t*data,unsigned bytes){assert(!c && base==HGKI_BASE+publishes*HGKI_PAGE && bytes==HGKI_PAGE && data==cpu+publishes*HGKI_PAGE);for(unsigned i=0;i<bytes;i++)assert(data[i]==hgki_initial_byte(publishes*HGKI_PAGE+i));memcpy(device+publishes*HGKI_PAGE,data,bytes);publishes++;return publishes==fail_publish?33:0;}
static int submit(void*c,const uint32_t*packet,unsigned words){assert(!c && words==4 && publishes==7 && !memcmp(packet,hgki_ib,16));submits++;if(fail_submit)return 35;
 /* This callback models the device operation; build/publish never writes red. */
 if(corrupt!=1)for(unsigned i=0;i<HGKI_OUTPUT_BYTES;i++)device[5*HGKI_PAGE+i]=((i&3)==0 || (i&3)==3)?255:0;
 if(corrupt>=2)device[(corrupt-2)*HGKI_PAGE]^=1;return 0;}
static int idle(void*c){assert(!c && submits==1);idles++;return fail_idle?37:0;}
static int readback(void*c,uint32_t base,uint8_t*data,unsigned bytes){assert(!c && base==HGKI_BASE && data==cpu && bytes==HGKI_BYTES && idles==1);reads++;memcpy(data,device,bytes);return fail_read?39:0;}
static const struct hgki_io io={NULL,guard,reserve,publish,submit,idle,readback};
static void reset(void){memset(cpu,0xcc,sizeof cpu);memset(device,0xdd,sizeof device);memset(&r,0,sizeof r);q=(struct hgki_qualification){0x43051401,HGKI_CLASS_CURSOR,1,1,1,1,1};cursor=HGKI_CLASS_CURSOR;guards=reserves=publishes=submits=idles=reads=fail_guard=fail_reserve=fail_publish=fail_submit=fail_idle=fail_read=corrupt=0;}
int main(void){unsigned cases=0;
 reset();assert(!hgki_run(&io,&q,cpu,sizeof cpu,&r));assert(r.started && !r.code && r.phase==8 && r.guards==13 && r.reserve_attempted && r.retained && r.published_pages==7 && r.submit_attempted && r.submit_returned && r.completed && r.readback_valid && r.verified && r.output_crc==0xe843b26a && r.first_bad==UINT32_MAX);assert(guards==13 && reserves==1 && publishes==7 && submits==1 && idles==1 && reads==1 && cursor==HGKI_CLASS_CURSOR+HGKI_BYTES);struct hgki_result saved=r;assert(hgki_run(&io,&q,cpu,sizeof cpu,&r)==HGKI_REUSED && !memcmp(&r,&saved,sizeof r));cases++;
 for(unsigned field=0;field<5;field++)for(unsigned value=0;value<=2;value+=2){reset();unsigned *f[]={&q.normal_owned,&q.cp_init_idle,&q.authenticated_zap,&q.mode_exit_idle,&q.kmd_preemption_disabled};*f[field]=value;assert(hgki_run(&io,&q,cpu,sizeof cpu,&r)==HGKI_QUALIFICATION && !guards && !reserves && !r.retained);for(unsigned i=0;i<HGKI_BYTES;i++)assert(cpu[i]==0xcc);cases++;}
 for(unsigned f=0;f<2;f++){reset();if(f)q.class_cursor+=HGKI_PAGE;else q.chip_id^=1;assert(hgki_run(&io,&q,cpu,sizeof cpu,&r)==HGKI_QUALIFICATION && !guards && !reserves);cases++;}
 for(unsigned i=1;i<=13;i++){reset();fail_guard=i;assert(hgki_run(&io,&q,cpu,sizeof cpu,&r)==HGKI_OWNER && guards==i && r.callback_code==29 && !r.verified);assert(r.retained==(i>2));assert(!submits || i>=11);assert(!reads || i==13);cases++;}
 reset();fail_reserve=1;assert(hgki_run(&io,&q,cpu,sizeof cpu,&r)==HGKI_RESERVE && r.callback_code==31 && r.retained && reserves==1 && !publishes && !submits);cases++;
 for(unsigned i=1;i<=7;i++){reset();fail_publish=i;assert(hgki_run(&io,&q,cpu,sizeof cpu,&r)==HGKI_PUBLISH && r.callback_code==33 && r.retained && publishes==i && r.published_pages==i-1 && !submits);cases++;}
 reset();fail_submit=1;assert(hgki_run(&io,&q,cpu,sizeof cpu,&r)==HGKI_SUBMIT && r.callback_code==35 && r.retained && r.submit_attempted && !r.submit_returned && !r.completed && !idles && !reads);cases++;
 reset();fail_idle=1;assert(hgki_run(&io,&q,cpu,sizeof cpu,&r)==HGKI_COMPLETION && r.callback_code==37 && r.retained && r.submit_returned && !r.completed && !reads);cases++;
 reset();fail_read=1;assert(hgki_run(&io,&q,cpu,sizeof cpu,&r)==HGKI_READBACK && r.callback_code==39 && r.retained && r.completed && !r.readback_valid && !r.verified);cases++;
 for(unsigned i=1;i<=8;i++){reset();corrupt=i;unsigned result=hgki_run(&io,&q,cpu,sizeof cpu,&r);assert(result==((i==1 || i==7)?HGKI_COLOR:HGKI_CHANGED));assert(r.retained && r.completed && r.readback_valid && !r.verified && r.first_bad!=UINT32_MAX);cases++;}
 reset();assert(!hgki_build(cpu,sizeof cpu));for(unsigned i=0;i<HGKI_OUTPUT_BYTES;i++)assert(cpu[5*HGKI_PAGE+i]==0x6d);assert(hgki_verify(cpu,sizeof cpu,&r)==HGKI_COLOR);cases++;
 for(unsigned i=0;i<6;i++){reset();struct hgki_io bad=io;switch(i){case 0:bad.guard=NULL;break;case 1:bad.reserve_fixed=NULL;break;case 2:bad.publish_clean_poc=NULL;break;case 3:bad.submit_fixed_ib=NULL;break;case 4:bad.bounded_idle=NULL;break;case 5:bad.readback_invalidate_poc=NULL;break;}assert(hgki_run(&bad,&q,cpu,sizeof cpu,&r)==HGKI_ARGUMENT && !guards && !reserves);cases++;}
 reset();assert(hgki_run(NULL,&q,cpu,sizeof cpu,&r)==HGKI_ARGUMENT);reset();assert(hgki_run(&io,NULL,cpu,sizeof cpu,&r)==HGKI_QUALIFICATION);reset();assert(hgki_run(&io,&q,NULL,sizeof cpu,&r)==HGKI_ARGUMENT);reset();assert(hgki_run(&io,&q,cpu,sizeof cpu-1,&r)==HGKI_ARGUMENT);assert(hgki_run(&io,&q,cpu,sizeof cpu,NULL)==HGKI_ARGUMENT);assert(hgki_build((void*)(UINTPTR_MAX-4096),HGKI_BYTES)==HGKI_ARGUMENT);cases+=6;
 assert(HGKI_BASE+HGKI_BYTES<=HGKI_CLASS_END && HGKI_COMMAND_WORDS*4<HGKI_PAGE && HGKI_BR_WORDS*4<HGKI_PAGE && HGKI_BV_WORDS*4<HGKI_PAGE);puts("fixed known-image 2D candidate: actual C paths PASS");printf("%u cases, ASAN/UBSAN; runtime adapter intentionally not integrated.\n",cases);return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='houji-known-image-2d-') as td:
    c = Path(td)/'test.c'
    exe = Path(td)/'test'
    c.write_text(source)
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-I', str(p/'native/gpu/uefi'), str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
