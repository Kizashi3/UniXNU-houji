#!/usr/bin/env python3
"""Exercise actual native DMA register adapters, replacing only ARM barriers."""
from pathlib import Path
import re
import subprocess
import tempfile
p=Path(__file__).resolve().parents[1]
source=(p/'native/gpu/uefi/GpuPower.c').read_text()
def function(name):
 m=re.search(r'STATIC (?:int|GPP_U64) '+name+r'\([^;{}]*\)\s*\{',source);assert m,name
 at=source.index('{',m.start());depth=1;end=at+1
 while depth:
  depth+=(source[end]=='{')-(source[end]=='}');end+=1
 return source[m.start():end]
names=['DmaRead64','DmaWrite32','DmaGmuRead','DmaGmuWrite']
body='\n'.join(function(x) for x in names).replace('__asm__ volatile("dsb sy":::"memory");','')
assert '__asm__' not in body
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "GpuDmaProbe.h"
#define STATIC static
#define VOID void
#define BOOLEAN int
#define UINT32 uint32_t
#define UINTN uintptr_t
#define EFI_ACCESS_DENIED 1
static unsigned mDmaCalled,mDmaZeroRetained,reads,writes;
static uint64_t mDmaZeroPhysical=UINT64_C(0x812340000);
static uint32_t last_address,last_value;
static uint64_t MmioRead64(uint32_t a){reads++;last_address=a;return UINT64_C(0x123456789abcdef0);}
static int GpuTryRead64(uint64_t a,uint64_t*v){*v=MmioRead64((uint32_t)a);return 0;}
static uint32_t MmioRead32(uint32_t a){reads++;last_address=a;return 0x12345678;}
static void MmioWrite32(uint32_t a,uint32_t v){writes++;last_address=a;last_value=v;}
static int ContextRead64(void*c,uint32_t a,uint64_t*v){(void)c;if(a!=HGP_CB(0x20) && a!=HGP_CB(0x28))return 1;*v=MmioRead64(a);return 0;}
static GPP_U64 GmuRead(void*c,GPP_U32 a,GPP_U32*v){(void)c;if(!hgd_control_address_valid(a) && a!=0x3d7e000)return 1;*v=MmioRead32(a);return 0;}
static GPP_U64 GmuWrite(void*c,GPP_U32 a,GPP_U32 v){(void)c;if(!hgd_control_address_valid(a) && !(a==0x3d7e000 && v<=1))return 1;MmioWrite32(a,v);return 0;}
'''+body+r'''
int main(void){
 unsigned cases=0;
 const uint32_t legal[][2]={{HGP_CB(0),0},{HGP_CB(0),0x1027},{HGP_CB(0x4),3},{HGP_CB(0x4),0x32b},
 {0x3da6008,0},{0x3da6008,0x12340000},{0x3da600c,0},{0x3da600c,8},
 {0x3da0800,0},{0x3da0800,0x80000005},{0x3da0c00,HGP_CONTEXT_BANK},{0x3da0c00,0x20000},
 {HGP_CB(0x58),2},{HGP_CB(0x618),0},{HGP_CB(0x7f0),0xffffffff}};
 for(unsigned enabled=0;enabled<=1;enabled++)for(unsigned retained=0;retained<=1;retained++){
  mDmaCalled=enabled;mDmaZeroRetained=retained;
  for(unsigned i=0;i<sizeof(legal)/sizeof(legal[0]);i++){
   unsigned old=writes;int code=DmaWrite32(0,legal[i][0],legal[i][1]);
   assert((!code)==(enabled && retained));assert(writes==old+(enabled && retained));cases++;
  }
 }
 mDmaCalled=mDmaZeroRetained=1;
 // No other context, stream, global control, fault clear or TTBR half-write.
 const uint32_t values[]={0,1,2,3,0x27,0x67,0x1027,0x1067,0x32b,0x20000,0x80000005,0xffffffff};
 for(uint32_t a=0x3da0000;a<0x3de0000;a+=4)for(unsigned j=0;j<sizeof(values)/sizeof(values[0]);j++){
  unsigned expected=0;
  for(unsigned i=0;i<sizeof(legal)/sizeof(legal[0]);i++)if(a==legal[i][0] && values[j]==legal[i][1])expected=1;
  unsigned old=writes;int code=DmaWrite32(0,a,values[j]);assert((!code)==expected && writes==old+expected);cases++;
 }
 for(uint32_t a=HGP_CB(0);a<HGP_CB(0x100);a+=4){
  unsigned expected=a==HGP_CB(0x20) || a==HGP_CB(0x28) || a==HGP_CB(0x60);
  unsigned old=reads;uint64_t value=0;assert((!DmaRead64(0,a,&value))==expected);
  assert(reads==old+expected);if(expected)assert(value==UINT64_C(0x123456789abcdef0));cases++;
 }
 for(uint32_t a=0x3d6d000;a<0x3d6d200;a+=4){
  unsigned expected=a<0x3d6d000+sizeof(hga_code),old=writes;uint32_t value=0;
  assert((!DmaGmuWrite(0,a,0x123))==expected && writes==old+expected);
  old=reads;assert((!DmaGmuRead(0,a,&value))==expected && reads==old+expected);cases++;
 }
 printf("PASS: %u native-adapter cases; actual whitelist rejects other banks/streams/global controls, IRQ-enabled SCTLR and partial TTBR writes; real wide FAR callback\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 d=Path(folder);(d/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
  '-I',str(p/'native/gpu'),'-I',str(p/'native/gpu/uefi'),str(d/'test.c'),'-o',str(d/'test')],check=True)
 subprocess.run([str(d/'test')],check=True)
