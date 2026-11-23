#!/usr/bin/env python3
"""Actual precise one-STR exception handler, quarantine and wrapper semantics."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1];s=(p/'native/gpu/uefi/GpuDoorbellFaultNative.h').read_text()
def fn(name):
 at=s.index(name+'(');a=s.rfind('\n',0,at)+1;b=s.index('{',at)+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b].replace('__asm__ volatile("dsb sy":::"memory");','')
common=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "GpuDoorbellFaultPolicy.h"
#define STATIC static
#define VOID void
#define CONST const
#define BOOLEAN int
#define EFIAPI
#define TRUE 1
#define FALSE 0
#define UINTN uintptr_t
#define UINT32 uint32_t
#define UINT64 uint64_t
typedef unsigned EFI_EXCEPTION_TYPE;
enum {EXCEPT_AARCH64_SYNCHRONOUS_EXCEPTIONS=0};
typedef struct {uint64_t ELR,X0,X1,ESR,FAR,LR,untouched;} EFI_SYSTEM_CONTEXT_AARCH64;
static volatile struct hdf_request mGpuDoorbellRequest;
static struct hdf_fault mGpuDoorbellFirstFault;
static unsigned mGpuDoorbellCalls,mGpuDoorbellFaults,mGpuDoorbellStage,mGpuDoorbellQuarantined,cases;
'''
handler=common+r'''
static uint32_t GpuDoorbellWriteStub[]={0xb9000001,0xd65f03c0};
'''+fn('HoujiGpuHandleDoorbellFault')+'\n'+fn('GpuDoorbellBegin')+r'''
static void reset(void){mGpuDoorbellRequest=(struct hdf_request){0};mGpuDoorbellFirstFault=(struct hdf_fault){0};mGpuDoorbellCalls=mGpuDoorbellFaults=mGpuDoorbellStage=mGpuDoorbellQuarantined=0;}
static EFI_SYSTEM_CONTEXT_AARCH64 context(void){return (EFI_SYSTEM_CONTEXT_AARCH64){(uintptr_t)GpuDoorbellWriteStub,0x3d7e650,1,0x96000050,0x3d7e650,0x12345678,0xabcdef};}
int main(void){reset();EFI_SYSTEM_CONTEXT_AARCH64 c=context(),expected=c;assert(!GpuDoorbellBegin(c.X0,1,c.ELR));expected.ELR+=4;assert(HoujiGpuHandleDoorbellFault(0,&c) && !memcmp(&c,&expected,sizeof c) && mGpuDoorbellRequest.failed && mGpuDoorbellQuarantined && mGpuDoorbellFirstFault.valid);cases++;
 mGpuDoorbellRequest.armed=0;assert(GpuDoorbellBegin(0x3d7e650,1,(uintptr_t)GpuDoorbellWriteStub) && mGpuDoorbellCalls==1);cases++;
 struct hdf_fault first=mGpuDoorbellFirstFault;c=context();mGpuDoorbellRequest.armed=1;mGpuDoorbellRequest.failed=0;assert(HoujiGpuHandleDoorbellFault(0,&c) && !memcmp(&first,&mGpuDoorbellFirstFault,sizeof first));cases++;
 for(unsigned field=0;field<4;field++)for(unsigned bit=0;bit<64;bit++){reset();c=context();assert(!GpuDoorbellBegin(c.X0,1,c.ELR));if(field==0)c.ELR^=UINT64_C(1)<<bit;if(field==1)c.X0^=UINT64_C(1)<<bit;if(field==2)c.X1^=UINT64_C(1)<<bit;if(field==3)c.FAR^=UINT64_C(1)<<bit;expected=c;assert(!HoujiGpuHandleDoorbellFault(0,&c) && !memcmp(&c,&expected,sizeof c) && !mGpuDoorbellQuarantined);cases++;}
 for(unsigned bit=0;bit<32;bit++)if(bit<=10 || bit>=25){reset();c=context();assert(!GpuDoorbellBegin(c.X0,1,c.ELR));c.ESR^=UINT64_C(1)<<bit;expected=c;assert(!HoujiGpuHandleDoorbellFault(0,&c) && !memcmp(&c,&expected,sizeof c));cases++;}
 for(unsigned i=0;i<6;i++){reset();c=context();assert(!GpuDoorbellBegin(c.X0,1,c.ELR));if(i==0)mGpuDoorbellRequest.armed=0;if(i==1)mGpuDoorbellRequest.failed=1;if(i==2)GpuDoorbellWriteStub[0]^=1;if(i==3)GpuDoorbellWriteStub[1]^=1;expected=c;assert(!HoujiGpuHandleDoorbellFault(i==4?1:0,i==5?0:&c) && !memcmp(&c,&expected,sizeof c));if(i==2)GpuDoorbellWriteStub[0]^=1;if(i==3)GpuDoorbellWriteStub[1]^=1;cases++;}
 for(uint64_t a=0x3d00000;a<0x3e00000;a+=4){reset();assert((!GpuDoorbellBegin(a,1,(uintptr_t)GpuDoorbellWriteStub))==(a==0x3d7e650));cases++;}
 for(unsigned bit=0;bit<32;bit++){reset();assert(GpuDoorbellBegin(0x3d7e650,1u^(1u<<bit),(uintptr_t)GpuDoorbellWriteStub) && !mGpuDoorbellCalls);cases++;}
 reset();assert(GpuDoorbellBegin(0x3d7e650,1,0));cases++;
 printf("PASS: %u actual STR matcher/begin cases; exact one-address/value/opcode/PC/X0/X1/FAR write abort only, ELR-only change, first fault retained, future notifications quarantined\n",cases);
}
'''
wrapper=common+r'''
static unsigned fail_begin,fail_stub,stub_calls;
static void GpuDoorbellWriteStub(uint64_t a,uint32_t v){assert(a==0x3d7e650 && v==1);stub_calls++;if(fail_stub){mGpuDoorbellRequest.failed=1;mGpuDoorbellQuarantined=1;}}
static int GpuDoorbellBegin(uint64_t a,uint32_t v,uintptr_t pc){assert(a==0x3d7e650 && v==1 && pc==(uintptr_t)GpuDoorbellWriteStub);if(fail_begin || mGpuDoorbellQuarantined)return 1;mGpuDoorbellRequest.armed=1;mGpuDoorbellRequest.failed=0;mGpuDoorbellStage=1;return 0;}
'''+fn('GpuDoorbellWrite')+r'''
int main(void){assert(!GpuDoorbellWrite(0x3d7e650,1) && stub_calls==1 && mGpuDoorbellStage==3 && !mGpuDoorbellRequest.armed);cases++;
 fail_stub=1;assert(GpuDoorbellWrite(0x3d7e650,1)==2 && stub_calls==2 && mGpuDoorbellStage==4 && mGpuDoorbellQuarantined && !mGpuDoorbellRequest.armed);cases++;
 assert(GpuDoorbellWrite(0x3d7e650,1)==1 && stub_calls==2 && mGpuDoorbellStage==4);cases++;
 fail_begin=1;assert(GpuDoorbellWrite(0x3d7e650,1)==1 && stub_calls==2);cases++;
 (void)mGpuDoorbellFirstFault;(void)mGpuDoorbellCalls;(void)mGpuDoorbellFaults;
 printf("PASS: %u actual STR wrapper cases; normal success after DSB, fault means uncertain failure and no automatic retry\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder)
 for name,program in [('handler',handler),('wrapper',wrapper)]:
  (f/(name+'.c')).write_text(program)
  subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),str(f/(name+'.c')),'-o',str(f/name)],check=True)
  subprocess.run([str(f/name)],check=True)
