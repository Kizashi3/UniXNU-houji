#!/usr/bin/env python3
"""Exercise the actual exception matcher/begin and wrapper validity semantics."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1];s=(p/'native/gpu/uefi/GpuReadFaultNative.h').read_text()
# The C harness mocks the barrier instruction only. Keep proof that each
# completion marker remains after its real barrier in the native source.
assert s.count('__asm__ volatile("dsb sy":::"memory");')==3
assert s.count('__asm__ volatile("dsb sy":::"memory");\n HOUJI_READ_TRACE(0x4015,Address,')==2
assert '__asm__ volatile("dsb sy":::"memory");\n HOUJI_READ_TRACE(0x4003,Address,Width);' in s
def fn(name):
 at=s.index(name+'(');a=s.rfind('\n',0,at)+1;b=s.index('{',at)+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b].replace('__asm__ volatile("dsb sy":::"memory");','')
common=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "GpuReadFaultPolicy.h"
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
typedef struct {uint64_t ELR,X0,ESR,FAR,LR,untouched;} EFI_SYSTEM_CONTEXT_AARCH64;
static volatile struct hrf_request mGpuReadRequest;
static struct hrf_fault mGpuReadFirstFault;
static unsigned mGpuReadCalls,mGpuReadFaults,cases;
struct trace_record {unsigned step;uint64_t address,value;};
static struct trace_record traces[64];
static unsigned trace_count;
static void RecordTrace(unsigned step,uint64_t address,uint64_t value){traces[trace_count++%64]=(struct trace_record){step,address,value};}
#define HOUJI_READ_TRACE(step,address,value) RecordTrace(step,address,value)
'''
handler=common+r'''
static uint32_t GpuRead32Stub[]={0xb9400000,0xd65f03c0},GpuRead64Stub[]={0xf9400000,0xd65f03c0};
'''+fn('HoujiGpuHandleReadFault')+'\n'+fn('GpuReadBegin')+r'''
static EFI_SYSTEM_CONTEXT_AARCH64 context(unsigned width){return (EFI_SYSTEM_CONTEXT_AARCH64){width==32?(uintptr_t)GpuRead32Stub:(uintptr_t)GpuRead64Stub, width==32?0x3d00840:0x3dc2020,0x96000010,width==32?0x3d00840:0x3dc2020,0x12345678,0xabcdef};}
int main(void){for(unsigned width=32;width<=64;width+=32){
 trace_count=0;
 EFI_SYSTEM_CONTEXT_AARCH64 c=context(width);mGpuReadRequest=(struct hrf_request){0};mGpuReadFirstFault=(struct hrf_fault){0};assert(!GpuReadBegin(c.X0,width,c.ELR));
 EFI_SYSTEM_CONTEXT_AARCH64 expected=c;expected.X0=0;expected.ELR+=4;assert(HoujiGpuHandleReadFault(0,&c) && !memcmp(&c,&expected,sizeof c) && mGpuReadRequest.failed && mGpuReadFirstFault.valid && mGpuReadFirstFault.width==width);cases++;
 const unsigned begin_fault[]={0x4000,0x4002,0x4003,0x40f0,0x40f1};assert(trace_count==sizeof begin_fault/sizeof begin_fault[0]);for(unsigned i=0;i<trace_count;i++){assert(traces[i].step==begin_fault[i]);cases++;}assert(traces[0].value==width && traces[2].value==width && traces[3].address==expected.ELR-4 && traces[3].value==expected.ESR && traces[4].value==width);cases++;
 struct hrf_fault first=mGpuReadFirstFault;mGpuReadRequest.armed=0;c=context(width);assert(!GpuReadBegin(c.X0,width,c.ELR));assert(HoujiGpuHandleReadFault(0,&c) && !memcmp(&first,&mGpuReadFirstFault,sizeof first));cases++;
 for(unsigned i=0;i<3;i++)for(unsigned bit=0;bit<64;bit++){
  c=context(width);mGpuReadRequest.armed=0;assert(!GpuReadBegin(c.X0,width,c.ELR));
  if(i==0)c.ELR^=UINT64_C(1)<<bit;if(i==1)c.X0^=UINT64_C(1)<<bit;if(i==2)c.FAR^=UINT64_C(1)<<bit;expected=c;
  assert(!HoujiGpuHandleReadFault(0,&c) && !memcmp(&c,&expected,sizeof c) && !mGpuReadRequest.failed);cases++;
 }
 for(unsigned bit=0;bit<=31;bit++)if(bit<=10 || bit>=25){
  c=context(width);mGpuReadRequest.armed=0;assert(!GpuReadBegin(c.X0,width,c.ELR));c.ESR^=UINT64_C(1)<<bit;expected=c;assert(!HoujiGpuHandleReadFault(0,&c) && !memcmp(&c,&expected,sizeof c));cases++;
 }
 c=context(width);mGpuReadRequest.armed=0;assert(!GpuReadBegin(c.X0,width,c.ELR));assert(!HoujiGpuHandleReadFault(1,&c));mGpuReadRequest.armed=0;assert(!HoujiGpuHandleReadFault(0,&c));cases+=2;
 }
 mGpuReadRequest.armed=0;assert(GpuReadBegin(0x3d00840,32,0));cases++;
 GpuRead32Stub[1]^=1;assert(GpuReadBegin(0x3d00840,32,(uintptr_t)GpuRead32Stub));GpuRead32Stub[1]^=1;cases++;
 GpuRead32Stub[0]^=1;assert(GpuReadBegin(0x3d00840,32,(uintptr_t)GpuRead32Stub));GpuRead32Stub[0]^=1;cases++;
 for(uint64_t a=0x3d00000;a<0x3e00000;a+=4){assert(hrf_address(a,32));assert(!hrf_address(a+1,32));cases+=2;}
 assert(!hrf_address(0x1d84000,32) && !hrf_address(0x15000000,32) && !hrf_address(0x17100128,64) && !hrf_address(0x3dc2000,64));cases+=4;
 printf("PASS: %u actual precise read-fault/begin cases; only owned one-load PC/read ESR/FAR, no SError/write/OEM resume, retain first fault\n",cases);
}
'''
wrapper=common+r'''
static unsigned fail_begin,stub_fault,stub_calls;
static uint32_t GpuRead32Stub(uint64_t a){(void)a;stub_calls++;mGpuReadRequest.failed=stub_fault;return 0xdeadbeef;}
static uint64_t GpuRead64Stub(uint64_t a){(void)a;stub_calls++;mGpuReadRequest.failed=stub_fault;return UINT64_C(0x1122334455667788);}
static int GpuReadBegin(uint64_t a,unsigned width,uintptr_t pc){(void)a;(void)width;(void)pc;if(fail_begin)return 1;mGpuReadRequest.armed=1;return 0;}
'''+fn('GpuTryRead32')+'\n'+fn('GpuTryRead64')+r'''
int main(void){uint32_t a=123;uint64_t b=456;
 assert(!GpuTryRead32(0x3d00840,&a) && a==0xdeadbeef && !mGpuReadRequest.armed);cases++;
 const unsigned success[]={0x4010,0x4012,0x4013,0x4014,0x4015,0x4016,0x4018};assert(trace_count==sizeof success/sizeof success[0]);for(unsigned i=0;i<trace_count;i++){assert(traces[i].step==success[i] && traces[i].address==0x3d00840 && traces[i].value==((i==2 || i==6)?UINT64_C(0xdeadbeef):32));cases++;}
 trace_count=0;
 assert(!GpuTryRead64(0x3dc2020,&b) && b==UINT64_C(0x1122334455667788) && !mGpuReadRequest.armed);cases++;
 assert(trace_count==sizeof success/sizeof success[0]);for(unsigned i=0;i<trace_count;i++){assert(traces[i].step==success[i] && traces[i].address==0x3dc2020 && traces[i].value==((i==2 || i==6)?UINT64_C(0x1122334455667788):64));cases++;}
 stub_fault=1;a=123;b=456;trace_count=0;assert(GpuTryRead32(0x3d00840,&a)==2 && a==123 && !mGpuReadRequest.armed);const unsigned failed[]={0x4010,0x4012,0x4013,0x4014,0x4015,0x4016,0x4017};assert(trace_count==sizeof failed/sizeof failed[0]);for(unsigned i=0;i<trace_count;i++){assert(traces[i].step==failed[i]);cases++;}trace_count=0;assert(GpuTryRead64(0x3dc2020,&b)==2 && b==456 && !mGpuReadRequest.armed);assert(trace_count==sizeof failed/sizeof failed[0]);for(unsigned i=0;i<trace_count;i++){assert(traces[i].step==failed[i]);cases++;}cases+=2;
 unsigned before=stub_calls;fail_begin=1;assert(GpuTryRead32(0x3d00840,&a)==1 && GpuTryRead64(0x3dc2020,&b)==1 && stub_calls==before);cases++;
 assert(GpuTryRead32(0x3d00840,0)==1 && GpuTryRead64(0x3dc2020,0)==1 && stub_calls==before);cases++;
 (void)mGpuReadFirstFault;(void)mGpuReadCalls;(void)mGpuReadFaults;
 printf("PASS: %u actual wrapper cases; successful value only, abort placeholder never escapes as a valid register value\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder)
 for name,program in [('handler',handler),('wrapper',wrapper)]:
  (f/(name+'.c')).write_text(program)
  subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),str(f/(name+'.c')),'-o',str(f/name)],check=True)
  subprocess.run([str(f/name)],check=True)
