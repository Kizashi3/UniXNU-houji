#!/usr/bin/env python3
"""Actual fixed capture; direct-read offsets checked against the pinned primary source."""
from pathlib import Path
import argparse
import re
import subprocess
import tempfile
p=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--gen7-reg',type=Path)
args=parser.parse_args()
if args.gen7_reg:
    source=args.gen7_reg.read_text()
    header=(p/'native/gpu/uefi/GpuCpStall.h').read_text()
    words=[int(x,16) for x in re.findall('0x([0-9a-f]+)',re.search(r'static const uint32_t a\[\]=\{(.*?)\};',header,re.S).group(1))]
    names=['RBBM_STATUS','RBBM_STATUS3','CP_INTERRUPT_STATUS','CP_HW_FAULT','CP_PROTECT_STATUS','CP_STATUS_1','CP_IB1_BASE','CP_IB1_BASE_HI','CP_IB1_REM_SIZE','CP_IB2_BASE','CP_IB2_BASE_HI','CP_IB2_REM_SIZE','CP_BV_HW_FAULT','CP_BV_PROTECT_STATUS']
    for name,physical in zip(names,words):
        reg=int(re.search(r'#define GEN7_'+name+r'\s+0x([0-9a-f]+)\b',source).group(1),16)
        assert physical==0x3d00000+4*reg,(name,hex(physical),hex(reg))
    print('All 14 offsets match pinned OnePlus primary header.')
program=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "GpuCpStall.h"
static unsigned guards,reads,fail_owner,fail_read;
static uint32_t raw[HCS_REGS];
static int owned(void*c){assert(!c);guards++;return guards==fail_owner?17:0;}
static int read32(void*c,uint32_t a,uint32_t*v){assert(!c && v && reads<HCS_REGS && a==hcs_address(reads));reads++;*v=0xdeadbeef;if(reads==fail_read)return 23;*v=raw[reads-1];return 0;}
static const struct hcs_io io={NULL,owned,read32};
static void reset(void){guards=reads=fail_owner=fail_read=0;for(unsigned i=0;i<HCS_REGS;i++)raw[i]=i+0xa000;raw[HCS_STATUS]=0x800005;}
int main(void){unsigned cases=0;
 reset();struct hcs_result r={0};assert(!hcs_capture(&io,7,&r));assert(r.started && r.stage==7 && !r.code && r.guards==15 && r.reads==14 && r.attempted==0x3fff && r.valid==0x3fff && !memcmp(raw,r.raw,sizeof raw));struct hcs_result saved=r;assert(hcs_capture(&io,8,&r)==HCS_REUSED && !memcmp(&saved,&r,sizeof r) && reads==14);cases++;
 for(unsigned n=1;n<=15;n++){reset();r=(struct hcs_result){0};fail_owner=n;assert(hcs_capture(&io,0,&r)==HCS_OWNER && r.owner_code==17 && guards==n && reads==n-1 && r.reads==reads && r.valid==((1u<<(n-1))-1) && r.attempted==r.valid);cases++;}
 for(unsigned n=1;n<=14;n++){reset();r=(struct hcs_result){0};fail_read=n;assert(hcs_capture(&io,0,&r)==HCS_READ && r.read_code==23 && guards==n && reads==n && r.valid==((1u<<(n-1))-1) && r.attempted==((1u<<n)-1) && r.raw[n-1]==0);cases++;}
 reset();r=(struct hcs_result){0};assert(hcs_capture(NULL,0,&r)==HCS_ARGUMENT && !reads && !guards);assert(hcs_capture(&io,0,NULL)==HCS_ARGUMENT);assert(!hcs_address(HCS_REGS) && !strcmp(hcs_name(HCS_REGS),"invalid"));cases+=3;
 printf("CP stall capture: %u actual C cases PASS (ASAN/UBSAN); no idle relaxation.\n",cases);return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='houji-cp-stall-') as td:
    c=Path(td)/'test.c';c.write_text(program);exe=Path(td)/'test'
    subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(p/'native/gpu/uefi'),str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
