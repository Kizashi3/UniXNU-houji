#!/usr/bin/env python3
"""Actual GX read gate and the two exact OOB writes, no device access."""
from pathlib import Path
import re,subprocess,tempfile
p=Path(__file__).resolve().parents[1];source=(p/'native/gpu/uefi/GpuGxStartNative.h').read_text()
def function(name):
 a=source.index('STATIC int '+name+'(');b=source.index('{',a)+1;d=1
 while d:d+=(source[b]=='{')-(source[b]=='}');b+=1
 return source[a:b].replace('__asm__ volatile("dsb sy":::"memory");','')
body=function('GxRead')+'\n'+function('GxWrite')
assert '__asm__' not in body
program=r'''
#include <assert.h>
#include <stdio.h>
#include "GpuGxStart.h"
#define STATIC static
#define VOID void
#define BOOLEAN int
#define UINT32 uint32_t
static unsigned mGxMapped=1,healthy=1,reads,writes,gx_reads,clock_state,fence_state,busy_state,fault_state;
static struct hgx_result mGxStart;
static unsigned mHostProfileReady,host_context_bad;
static int HostContextQualified(void){return host_context_bad;}
static int StockBootstrapHealthy(void*c){(void)c;return healthy;}
static uint32_t MmioRead32(uint32_t a){reads++;if(a==0x3dc0058)return 0x400|(fault_state==1?2:0);if(a==0x3dc3058)return 0x400|(fault_state==2?2:0);if(a==0x3d7e340)return clock_state;if(a==0x3d8ec40)return fence_state;if(a==0x3d8ec30)return busy_state;if(a==0x3d00840 || a==0x3d0084c || a==0x3d02020)gx_reads++;return 0xbeef;}
static void MmioWrite32(uint32_t a,uint32_t v){(void)a;(void)v;writes++;}
'''+body+r'''
int main(){unsigned cases=0;uint32_t value;
 mGxStart.gx_ready=mGxStart.acked=mGxStart.clear_confirmed=1;
 const uint32_t gx[]={0x3d00840,0x3d0084c,0x3d02020};
 for(unsigned i=0;i<3;i++){assert(!GxRead(0,gx[i],&value) && value==0xbeef);cases++;}
 for(unsigned gate=0;gate<10;gate++)for(unsigned i=0;i<3;i++) {
  mGxMapped=healthy=mGxStart.gx_ready=mGxStart.acked=mGxStart.clear_confirmed=1;clock_state=fence_state=busy_state=fault_state=0;
  if(gate==0)mGxMapped=0;if(gate==1)healthy=0;if(gate==2)mGxStart.gx_ready=0;if(gate==3)mGxStart.acked=0;if(gate==4)mGxStart.clear_confirmed=0;if(gate==5)clock_state=3;if(gate==6)fence_state=1;if(gate==7)busy_state=1u<<23;if(gate==8)fault_state=1;if(gate==9)fault_state=2;
  unsigned old=gx_reads;assert(GxRead(0,gx[i],&value) && gx_reads==old);cases++;
 }
 mGxMapped=healthy=1;clock_state=fence_state=busy_state=fault_state=0;
 mHostProfileReady=1;fault_state=2; // Absent secure bank is not part of host profile.
 for(unsigned i=0;i<3;i++){assert(!GxRead(0,gx[i],&value));cases++;}
 host_context_bad=1;for(unsigned i=0;i<3;i++){unsigned old=gx_reads;assert(GxRead(0,gx[i],&value) && gx_reads==old);cases++;}
 host_context_bad=0;fault_state=1;for(unsigned i=0;i<3;i++){unsigned old=gx_reads;assert(GxRead(0,gx[i],&value) && gx_reads==old);cases++;}
 mHostProfileReady=fault_state=0;
 for(uint32_t a=0x3d00000;a<0x3d40000;a+=4)if(a!=gx[0] && a!=gx[1] && a!=gx[2]){unsigned old=reads;assert(GxRead(0,a,&value) && reads==old);cases++;}
 mGxStart.requested=1;mGxStart.acked=0;mGxStart.clear_attempted=0;assert(!GxWrite(0,0x3d7e650,HGX_SET));cases++;
 assert(GxWrite(0,0x3d7e644,HGX_ACK));cases++;
 for(unsigned bit=0;bit<32;bit++){unsigned old=writes;assert(GxWrite(0,0x3d7e650,HGX_SET^(1u<<bit)) && writes==old);cases++;}
 mGxStart.acked=mGxStart.clear_attempted=1;assert(!GxWrite(0,0x3d7e644,HGX_ACK) && GxWrite(0,0x3d7e650,HGX_SET));cases++;
 for(unsigned bit=0;bit<32;bit++){unsigned old=writes;assert(GxWrite(0,0x3d7e644,HGX_ACK^(1u<<bit)) && writes==old);cases++;}
 for(uint32_t a=0x3d00000;a<0x3de0000;a+=4){unsigned old=writes;assert(GxWrite(0,a,0) && writes==old);cases++;}
 for(unsigned gate=0;gate<2;gate++){mGxMapped=healthy=1;if(gate==0)mGxMapped=0;else healthy=0;unsigned old=writes;assert(GxWrite(0,0x3d7e644,HGX_ACK) && writes==old);cases++;}
 printf("PASS: %u actual GX native cases; no gated read without per-read power/clock/AHB/OOB proof; exact set-bit30/ACK-W1C31 only; all CP/GPU writes, foreign masks and bad states rejected\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu'),'-I',str(p/'native/gpu/uefi'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
