#!/usr/bin/env python3
"""Actual SQE STR wrapper/handler with only its instruction execution mocked."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1]
source=(p/'native/gpu/uefi/GpuHostWriteFaultNative.h').read_text()
leaf='''STATIC VOID __attribute__((naked)) HostWriteStub(UINT64 Address,uint32_t Value) {
 __asm__ volatile("str w1, [x0]\\n\\tret");
}'''
assert source.count(leaf)==1
source=source.replace(leaf,'STATIC CONST UINT32 HostWriteStub[]={0xb9000001u,0xd65f03c0u};')
source=source.replace('HostWriteStub(0x3d02020,Value);','MockStore(0x3d02020,Value);')
source=source.replace('__asm__ volatile("dsb sy":::"memory");','')
prefix=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define STATIC static
#define CONST const
#define VOID void
#define UINT64 uint64_t
#define UINT32 uint32_t
#define UINTN uintptr_t
#define BOOLEAN unsigned
#define EFIAPI
#define TRUE 1
#define FALSE 0
#define Print(...) ((void)0)
typedef unsigned EFI_EXCEPTION_TYPE;
typedef struct {uint64_t ELR,X0,X1,ESR,FAR,LR;}EFI_SYSTEM_CONTEXT_AARCH64;
enum {EXCEPT_AARCH64_SYNCHRONOUS_EXCEPTIONS=1};
static unsigned inject,stores;
static void MockStore(uint64_t,uint32_t);
struct trace_record {unsigned step;uint64_t address,value;};
static struct trace_record traces[64];
static unsigned trace_count;
static void __attribute__((unused)) RecordTrace(unsigned step,uint64_t address,uint64_t value){assert(trace_count<64);traces[trace_count++]=(struct trace_record){step,address,value};}
#ifdef TEST_CALL_TRACE
#define HOUJI_CALL_TRACE(step,address,value) RecordTrace(step,address,value)
#endif
'''
suffix=r'''
static uint64_t syndrome(void){return (UINT64_C(0x25)<<26)|(1u<<25)|0x50;}
static void MockStore(uint64_t address,uint32_t value){stores++;if(inject){EFI_SYSTEM_CONTEXT_AARCH64 c={(uintptr_t)HostWriteStub,address,value,syndrome(),address,0x1234};assert(HoujiGpuHandleHostWriteFault(1,&c));assert(c.ELR==(uintptr_t)HostWriteStub+4 && c.X0==address && c.X1==value && c.LR==0x1234);}}
static void reset(void){memset((void*)&mHostWriteRequest,0,sizeof mHostWriteRequest);memset(&mHostWriteFirst,0,sizeof mHostWriteFirst);mHostWriteCalls=mHostWriteFaults=mHostHaltAttempted=mHostHaltFailed=stores=inject=trace_count=0;}
int main(void){unsigned cases=0;
 for(unsigned value=1;value<=3;value+=2){struct hhw_request r={(uintptr_t)HostWriteStub,1,0,value};uint64_t pc=r.pc,a=0x3d02020,e=syndrome();assert(hhw_match(&r,pc,a,value,e,a,0xb9000001));cases++;
  for(unsigned bit=0;bit<64;bit++){
   assert(!hhw_match(&r,pc^(UINT64_C(1)<<bit),a,value,e,a,0xb9000001));
   assert(!hhw_match(&r,pc,a^(UINT64_C(1)<<bit),value,e,a,0xb9000001));
   assert(!hhw_match(&r,pc,a,value^(UINT64_C(1)<<bit),e,a,0xb9000001));
   assert(!hhw_match(&r,pc,a,value,e,a^(UINT64_C(1)<<bit),0xb9000001));cases+=4;
  }
  for(unsigned bit=0;bit<32;bit++){assert(!hhw_match(&r,pc,a,value,e,a,0xb9000001u^(1u<<bit)));cases++;}
  for(unsigned bit=0;bit<32;bit++){int ignored=bit>=11 && bit<25;assert(hhw_match(&r,pc,a,value,e^(UINT64_C(1)<<bit),a,0xb9000001)==ignored);cases++;}
 }
 reset();assert(!HostRingStore32(1) && stores==1 && !mHostWriteRequest.armed && !mHostWriteFaults);cases++;
 reset();inject=1;assert(HostRingStore32(1) && mHostWriteFaults==1 && mHostWriteFirst.valid && mHostWriteFirst.value==1 && mHostWriteFirst.esr==syndrome());assert(HostRingStore32(1) && stores==1);inject=0;assert(!HostRingStore32(3) && stores==2);HostWriteReport();cases++;
 reset();inject=1;assert(HostRingStore32(1));assert(HostRingStore32(3) && mHostWriteFaults==2 && mHostWriteFirst.value==1);assert(HostRingStore32(3) && stores==2);cases++;
 reset();assert(!HostRingStore32(3) && mHostHaltAttempted && !mHostHaltFailed && stores==1);inject=1;assert(HostRingStore32(1) && stores==2 && mHostWriteFaults==1 && !mHostHaltFailed);inject=0;assert(!HostRingStore32(3) && stores==3 && !mHostHaltFailed);assert(HostRingStore32(1) && stores==3);cases++;
 reset();inject=1;assert(HostRingStore32(3) && mHostHaltFailed && stores==1);inject=0;assert(HostRingStore32(3) && stores==1);cases++;
 reset();assert(HostRingStore32(0) && HostRingStore32(2) && !stores);cases++;
 reset();mHostWriteRequest=(struct hhw_request){(uintptr_t)HostWriteStub,1,0,1};EFI_SYSTEM_CONTEXT_AARCH64 c={(uintptr_t)HostWriteStub,0x3d02020,1,syndrome(),0x3d02020,0};assert(!HoujiGpuHandleHostWriteFault(2,&c) && !mHostWriteFaults);cases++;
#ifdef TEST_CALL_TRACE
 reset();assert(!HostRingStore32(1));const unsigned success[]={0x5000,0x5002,0x5003,0x5004,0x5005,0x5006,0x5007,0x5008,0x500a};assert(trace_count==sizeof success/sizeof success[0]);for(unsigned i=0;i<trace_count;i++){assert(traces[i].step==success[i] && traces[i].address==0x3d02020 && traces[i].value==1);cases++;}
 reset();inject=1;assert(HostRingStore32(3));const unsigned failed[]={0x5000,0x5002,0x5003,0x5004,0x50f0,0x50f1,0x5005,0x5006,0x5007,0x5008,0x5009};assert(trace_count==sizeof failed/sizeof failed[0]);for(unsigned i=0;i<trace_count;i++){assert(traces[i].step==failed[i]);cases++;}assert(traces[4].address==(uintptr_t)HostWriteStub && traces[4].value==syndrome());assert(traces[5].address==0x3d02020 && traces[5].value==3);cases+=2;
 trace_count=0;assert(HostRingStore32(3) && trace_count==2 && traces[0].step==0x5000 && traces[1].step==0x5001 && stores==1);cases++;
#endif
 printf("PASS: %u exact SQE store matcher/wrapper/handler cases; wrong PC/address/value/opcode/ESR refused, failed effects UNKNOWN, no start retry, successful halt does not consume the later fault-recovery halt\n",cases);
}
'''
with tempfile.TemporaryDirectory() as d:
 f=Path(d);(f/'test.c').write_text(prefix+source+suffix)
 for flags in [[],['-DTEST_CALL_TRACE']]:
  subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',*flags,'-I',str(p/'native/gpu/uefi'),str(f/'test.c'),'-o',str(f/'test')],check=True)
  subprocess.run([str(f/'test')],check=True)
