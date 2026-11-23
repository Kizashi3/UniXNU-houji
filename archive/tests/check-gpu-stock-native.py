#!/usr/bin/env python3
"""Test the actual native stock register writer; no ARM code or device I/O."""
from pathlib import Path
import re,subprocess,tempfile
p=Path(__file__).resolve().parents[1];source=(p/'native/gpu/uefi/GpuPower.c').read_text()
def function(name):
 m=re.search(r'STATIC int '+name+r'\([^;]+?\) \{',source);assert m,name
 a=source.index('{',m.start());depth=1;b=a+1
 while depth:depth+=(source[b]=='{')-(source[b]=='}');b+=1
 return source[m.start():b]
body='\n'.join(function(x) for x in ['StockWrite32','StockWrite64']).replace('__asm__ volatile("dsb sy":::"memory");','');assert '__asm__' not in body
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include "GpuStockGmu.h"
#include "vendor/Ace5Gmu/giulia_gpu_scm.h"
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define STATIC static
#define VOID void
#define CONST const
#define BOOLEAN int
#define TRUE 1
#define UINT32 uint32_t
#define UINT64 uint64_t
#define UINT8 uint8_t
#define UINTN uintptr_t
static unsigned mStockCalled,mFirmwareHeld,writes;
static struct ggs_state mSecureCx;
static struct hfm_result mFirmwareMemory;
static void*mFirmwareImage;
static uint64_t mDmaZeroPhysical=0x8ffff000;
static void MmioWrite32(uint32_t a,uint32_t v){(void)a;(void)v;writes++;}
static unsigned doorbell_error,doorbell_calls;
static int GpuDoorbellWrite(uint64_t a,uint32_t v){assert(a==0x3d7e650 && v==1);doorbell_calls++;if(doorbell_error)return 2;MmioWrite32((uint32_t)a,v);return 0;}
static void MmioWrite64(uint32_t a,uint64_t v){(void)a;(void)v;writes++;}
'''+body+r'''
int main(int argc,char**argv) {
 assert(argc==2);FILE*f=fopen(argv[1],"rb");assert(f);mFirmwareImage=malloc(HFM_FW_BYTES);assert(fread(mFirmwareImage,1,HFM_FW_BYTES,f)==HFM_FW_BYTES);fclose(f);
 void*tables=calloc(3,4096);mFirmwareMemory.config=(ArmSmmu4KConfig){32,36,0x89999000,1};
 ArmSmmu4KRange range={0x60000000,0x88888000,4096,3,1,3};assert(!ArmSmmu4KBuild(&mFirmwareMemory.config,&range,1,tables,3,&mFirmwareMemory.built));
 unsigned cases=0;mStockCalled=mFirmwareHeld=mSecureCx.init_succeeded=1;
 assert(!StockWrite32(0,0x3d7e650,1) && doorbell_calls==1);cases++;
 doorbell_error=1;unsigned before=writes;assert(StockWrite32(0,0x3d7e650,1)==2 && writes==before && doorbell_calls==2);doorbell_error=0;cases++;
 for(unsigned i=0;i<sizeof(hgf_rsc)/sizeof(hgf_rsc[0]);i++){assert(!StockWrite32(0,hgf_rsc[i].address,hgf_rsc[i].value));cases++;}
 for(unsigned i=0;i<sizeof(hgf_boot)/sizeof(hgf_boot[0]);i++){assert(!StockWrite32(0,hgf_boot[i].address,hgf_boot[i].value));cases++;}
 for(unsigned gate=0;gate<3;gate++) {
  mStockCalled=mFirmwareHeld=mSecureCx.init_succeeded=1;
  if(gate==0)mStockCalled=0;if(gate==1)mFirmwareHeld=0;if(gate==2)mSecureCx.init_succeeded=0;
  unsigned old=writes;assert(StockWrite32(0,0x3d7e000,0) && writes==old);cases++;
 }
 mStockCalled=mFirmwareHeld=mSecureCx.init_succeeded=1;
 const uint32_t invalid[][2]={{HGP_CB(0),0x1067},{HGP_CB(0),0x67},{HGP_CB(0x58),2},{0x3da0048,0xffffffff},
 {0x3da0804,0x80000000},{0x3da0c04,0},{0x3dc0000,0x1027},{0x3dc1000,0x1027},
 {HGP_CB(0x24),0x07500000},{0x3d7e64c,0},{0x3d8ec18,0},{0x3da6008,0x12340000},
 {0x3d7e650,2},{0x3d7e618,2},{0x3d7e000,2},{0xb284500,0}};
 for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++){unsigned old=writes;assert(StockWrite32(0,invalid[i][0],invalid[i][1]) && old==writes);cases++;}
 for(uint32_t a=0x3d00000;a<0x3d40000;a+=4) {
  unsigned old=writes;int code=StockWrite32(0,a,0);assert((!code)==(a==0x3d0f114));assert(writes==old+(a==0x3d0f114));cases++;
 }
 struct gg_fw_block blocks[64];size_t count;assert(!gg_fw_plan(mFirmwareImage,HFM_FW_BYTES,blocks,64,&count));
 for(unsigned i=0;i<count;i++) {
  struct gg_fw_block*b=&blocks[i];if(!b->size || (b->region!=GG_ITCM && b->region!=GG_DTCM))continue;
  uint32_t a=b->region==GG_ITCM?0x3d6d000+b->address:0x3d71000+b->address-0x10004000;
  for(unsigned n=0;n<b->size;n+=4) {
   uint32_t value=gg_le32((uint8_t*)mFirmwareImage+b->payload_offset+n);unsigned old=writes;
   assert(!StockWrite32(0,a+n,value) && writes==old+1);old=writes;
   assert(StockWrite32(0,a+n,value^1) && old==writes);cases+=2;
  }
 }
 uint64_t ttbr=(UINT64_C(0x750)<<48)|mFirmwareMemory.built.root_physical;
 for(uint32_t a=HGP_CB(0);a<HGP_CB(0x100);a+=4) {
  unsigned old=writes;int code=StockWrite64(0,a,ttbr);assert((!code)==(a==HGP_CB(0x20)));assert(writes==old+(a==HGP_CB(0x20)));cases++;
 }
 assert(StockWrite64(0,HGP_CB(0x20),ttbr^4096));assert(!StockWrite64(0,HGP_CB(0x28),UINT64_C(0x750)<<48));cases+=2;
 free(tables);free(mFirmwareImage);printf("PASS: %u actual native stock writer cases; no CP/GPU-bank writes, only pinned firmware TCM words, fixed startup constants, exact owned TTBR64, IRQ/fault-clear and foreign routes rejected\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 d=Path(folder);(d/'test.c').write_text(program)
 sources=[str(x) for x in (p/'native/gpu/vendor/ArmSmmu4K').glob('*.c')]
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu'),'-I',str(p/'native/gpu/uefi'),str(d/'test.c'),*sources,'-o',str(d/'test')],check=True)
 subprocess.run([str(d/'test'),'${HOUJI_ARTIFACTS}/native-research/houji-gpu-firmware-20261025/gmu_gen70900.bin'],check=True)
