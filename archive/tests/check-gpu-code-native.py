#!/usr/bin/env python3
"""Actual four-base native binding whitelist; no GPU execution."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1];s=(p/'native/gpu/uefi/GpuCodeBindNative.h').read_text()
def fn(name):
 a=s.index('STATIC int '+name+'(');b=s.index('{',a)+1;d=1
 while d:d+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b].replace('__asm__ volatile("dsb sy":::"memory");','')
body=fn('CodeBindRead')+'\n'+fn('CodeBindWrite')
program=r'''
#include <assert.h>
#include <stdio.h>
#include "GpuCodeBind.h"
#define STATIC static
#define VOID void
#define BOOLEAN int
#define TRUE 1
#define FALSE 0
static unsigned safe=1,reads,writes;
static int CodeBindGuard(void*c){(void)c;return !safe;}
static uint32_t MmioRead32(uint32_t a){(void)a;reads++;return 0;}
static void MmioWrite32(uint32_t a,uint32_t v){(void)a;(void)v;writes++;}
'''+body+r'''
int main(){unsigned cases=0;uint32_t v;
 for(unsigned i=0;i<4;i++){assert(!CodeBindWrite(0,hcb_address(i),hcb_value(i)) && !CodeBindRead(0,hcb_address(i),&v));cases++;
  for(unsigned bit=0;bit<32;bit++){unsigned old=writes;assert(CodeBindWrite(0,hcb_address(i),hcb_value(i)^(1u<<bit)) && writes==old);cases++;}}
 for(uint32_t a=0x3d00000;a<0x3d40000;a+=4){unsigned expected=0;for(unsigned i=0;i<4;i++)expected|=a==hcb_address(i) && hcb_value(i)==0;unsigned old=writes;assert((!CodeBindWrite(0,a,0))==expected && writes==old+expected);cases++;}
 assert(CodeBindWrite(0,0x3d02020,1) && CodeBindWrite(0,0x3d0f400,0));cases++;
 safe=0;for(unsigned i=0;i<4;i++){unsigned old=writes,read=reads;assert(CodeBindWrite(0,hcb_address(i),hcb_value(i)) && CodeBindRead(0,hcb_address(i),&v) && writes==old && reads==read);cases++;}
 printf("PASS: %u actual CP-code binding native cases; only exact four SQE/AQE GPU-address writes, per-operation guard, CP enable/trust/other GPU writes rejected\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu'),'-I',str(p/'native/gpu/uefi'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
