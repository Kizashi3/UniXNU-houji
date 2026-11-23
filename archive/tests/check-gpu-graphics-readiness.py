#!/usr/bin/env python3
"""Actual capture/native glue with only retained-owner/read/console boundaries mocked."""
from pathlib import Path
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
source = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define STATIC static
#define CONST const
#define VOID void
static unsigned print_calls;
#define Print(...) ((void)++print_calls)
#include "GpuGraphicsReadiness.h"
static unsigned mHostRingPrepared,mHostRingCpFailed,mHostWriteFaults,mHostRingUnsafe;
static struct {unsigned stage;} mHostBusStop;
static struct {unsigned code;} mHostRing;
static struct {unsigned valid;uint32_t last;} mHostRingBusy;
static unsigned guards,reads,fail_guard,fail_read;
static uint32_t raw[3];
static int HostRingGuard(void*c){(void)c;guards++;return guards==fail_guard?17:0;}
static int GpuTryRead32(uint64_t a,uint32_t*v){assert(v && reads<3 && a==hgr_address(reads));reads++;*v=0xfeedface;if(reads==fail_read)return 23;*v=raw[reads-1];return 0;}
#include "GpuGraphicsReadinessNative.h"
static void reset(void){memset(mGraphicsReadiness,0,sizeof mGraphicsReadiness);mHostRingPrepared=mHostRingBusy.valid=1;mHostRingBusy.last=0x71000000;mHostRingCpFailed=mHostWriteFaults=mHostBusStop.stage=mHostRing.code=mHostRingUnsafe=0;guards=reads=fail_guard=fail_read=print_calls=0;raw[0]=1;raw[1]=0x12345678;raw[2]=0x89abcdef;}
int main(void){unsigned cases=0;
 for(unsigned s=0;s<HGR_STAGES;s++)for(unsigned trust=0;trust<3;trust++){
  reset();raw[0]=trust==2?0xffffffffu:trust;
  assert(!GraphicsReadinessCapture(s));struct hgr_result r=mGraphicsReadiness[s];
  assert(r.started && r.stage==s && !r.code && r.phase==4 && r.guards==4 && r.reads==3 && r.attempted==7 && r.valid==7 && !r.owner_code && !r.read_code && !memcmp(r.raw,raw,sizeof raw) && guards==4 && reads==3 && !print_calls);
  assert(GraphicsReadinessCapture(s)==HGR_REUSED && guards==4 && reads==3 && !memcmp(&r,&mGraphicsReadiness[s],sizeof r));cases++;
 }
 for(unsigned i=1;i<=4;i++){
  reset();fail_guard=i;assert(GraphicsReadinessCapture(0)==HGR_OWNER);
  const struct hgr_result*r=&mGraphicsReadiness[0];unsigned n=i-1;
  assert(guards==i && reads==n && r->guards==i && r->reads==n && r->owner_code==1 && r->valid==((1u<<n)-1) && r->attempted==r->valid && !print_calls);cases++;
 }
 for(unsigned i=1;i<=3;i++){
  reset();fail_read=i;assert(GraphicsReadinessCapture(0)==HGR_READ);const struct hgr_result*r=&mGraphicsReadiness[0];
  assert(reads==i && guards==i && r->read_code==23 && r->attempted==((1u<<i)-1) && r->valid==((1u<<(i-1))-1) && !r->raw[i-1] && !print_calls);cases++;
 }
 for(unsigned field=0;field<6;field++){
  reset();unsigned *state[]={&mHostRingPrepared,&mHostBusStop.stage,&mHostRing.code,&mHostRingCpFailed,&mHostWriteFaults,&mHostRingBusy.valid};*state[field]^=1;
  assert(GraphicsReadinessCapture(0)==HGR_OWNER && !reads && !mGraphicsReadiness[0].valid && !print_calls);assert(guards==(field==5));cases++;
 }
 reset();mHostRingBusy.last=0x71c00004;assert(GraphicsReadinessCapture(0)==HGR_OWNER && guards==1 && !reads);cases++;
 reset();mHostRingUnsafe=1;assert(!GraphicsReadinessCapture(2) && reads==3 && !print_calls);GraphicsReadinessReport();assert(!print_calls);mHostRingUnsafe=0;GraphicsReadinessReport();assert(print_calls==4);cases++;
 reset();assert(GraphicsReadinessCapture(HGR_STAGES)==HGR_ARGUMENT && !reads && !guards);cases++;
 reset();uint32_t v=0xfeedface;assert(GraphicsReadinessRead(NULL,0x3d3e000,&v) && v==0xfeedface && !reads);assert(GraphicsReadinessRead(NULL,hgr_address(0),NULL) && !reads);cases++;
 reset();struct hgr_result r={0};struct hgr_io io={0};assert(hgr_capture(&io,0,&r)==HGR_ARGUMENT && !reads && !guards);assert(hgr_capture(NULL,0,NULL)==HGR_ARGUMENT);cases++;
 assert(hgr_address(0)==0x3d3d000 && hgr_address(1)==0x3d3f000 && hgr_address(2)==0x3d3f004 && !hgr_address(3));cases++;
 printf("PASS: %u graphics-state capture cases; actual native glue, fixed read-only register set, per-read retained-owner checks, invalid output excluded, no mode inference or device writes\n",cases);
}
'''
with tempfile.TemporaryDirectory() as directory:
    f = Path(directory)
    (f / "test.c").write_text(source)
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-I", str(p / "native/gpu/uefi"),
                    str(f / "test.c"), "-o", str(f / "test")], check=True)
    subprocess.run([str(f / "test")], check=True)
