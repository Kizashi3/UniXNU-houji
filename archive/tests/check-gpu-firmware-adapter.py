#!/usr/bin/env python3
"""Actual allocation bookkeeping at the firmware/GFX arena capacity boundary."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1];s=(p/'native/gpu/uefi/GpuFirmwarePrepare.h').read_text()
a=s.index('STATIC int FirmwareAllocate(');b=s.index('{',a)+1;depth=1
while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
body=s[a:b]
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define STATIC static
#define VOID void
#define UINT64 uint64_t
#define UINTN uintptr_t
#define EFI_PHYSICAL_ADDRESS uint64_t
#define EFI_STATUS uint64_t
#define EFI_ERROR(x) ((x)!=0)
enum {AllocateMaxAddress=1,EfiBootServicesData=4,HSC_LARGE_PAGES=1024,HFM_MAX=11};
static struct {uint64_t Pa,Bytes,Original;unsigned Changed;} mFirmwareAttributes[HFM_MAX+3];
static unsigned mFirmwareAttributeCount,calls,fail_call;
static uint64_t allocate(unsigned type,unsigned kind,unsigned pages,uint64_t *address) {
 assert(type==AllocateMaxAddress && kind==EfiBootServicesData && pages && pages<=1024 && *address==0xfffffffffULL);
 if(++calls==fail_call)return 1;*address=0x80000000+0x800000*calls;return 0;
}
struct BS {uint64_t(*AllocatePages)(unsigned,unsigned,unsigned,uint64_t*);};static struct BS bs={allocate},*gBS=&bs;
'''+body+r'''
int main(){unsigned cases=0;uint64_t pa=0;void*cpu=0;
 for(unsigned i=0;i<14;i++) {assert(!FirmwareAllocate(0,i==12?256:i==13?64:1,&pa,&cpu));assert(mFirmwareAttributeCount==i+1 && mFirmwareAttributes[i].Pa==pa && mFirmwareAttributes[i].Bytes==(i==12?0x100000u:i==13?0x40000u:4096u) && (uintptr_t)cpu==pa);cases++;}
 assert(FirmwareAllocate(0,1,&pa,&cpu) && calls==14 && mFirmwareAttributeCount==14);cases++;
 for(unsigned failure=1;failure<=14;failure++) {mFirmwareAttributeCount=calls=0;fail_call=failure;for(unsigned i=1;i<=failure;i++){int code=FirmwareAllocate(0,256,&pa,&cpu);assert(!!code==(i==failure));assert(mFirmwareAttributeCount==i-(i==failure));cases++;}}
 mFirmwareAttributeCount=calls=fail_call=0;assert(FirmwareAllocate(0,0,&pa,&cpu) && FirmwareAllocate(0,1025,&pa,&cpu) && !calls && !mFirmwareAttributeCount);cases++;
 assert(!FirmwareAllocate(0,1024,&pa,&cpu));cases++;
 printf("PASS: %u actual allocator ledger cases;12 original firmware allocations plus independent GPU-only/code arenas, full boundary refuses without allocation, every allocation failure preserves bookkeeping\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
