#!/usr/bin/env python3
"""Exercise the actual native allowlist and owner gates, without an SMC."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#define GG_HOST_TEST 1
#include <assert.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#define STATIC static
#define CONST const
#define VOID void
typedef uint64_t UINT64;
#include "vendor/Ace5Gmu/giulia_gpu_scm.h"
static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { \
 fprintf(stderr,"native line %d: %s\n",__LINE__,#x); assert(x); } } while(0)
static unsigned mHostRingUnsafe,mHostWriteCalls,mGpuSaveAllowed,mHostRingPrepared;
static struct { unsigned enabled,started; } mHostRing;
static struct ggs_state mSecureCx;
static unsigned prep_phase,prep_bad,prep_calls,raw_calls,prints,delay_calls;
static unsigned mode,available,flip_after_call,pending;
static unsigned per_query[5],trace_count;
static uint64_t clock_us,cookie,reply_status;
static struct { unsigned step;uint64_t address,value; } traces[128];
static int HostPreparationGuard(void *c) {
 (void)c;++prep_calls;return prep_bad || (prep_phase!=5 && prep_phase!=6);
}
static uint64_t BatchCounter(void) { return clock_us; }
static uint64_t BatchMicroseconds(uint64_t begin) { return clock_us-begin; }
static int SecureCxDelay(void *c,unsigned ms) {
 (void)c;CHECK(ms==30);CHECK(!prints);++delay_calls;clock_us+=(uint64_t)ms*1000;return 0;
}
static void Print(const wchar_t *format,...) { CHECK(format!=0);++prints; }
static void trace(unsigned step,uint64_t address,uint64_t value) {
 CHECK(trace_count<128);traces[trace_count++]=(typeof(traces[0])){step,address,value};
}
#define HOUJI_CALL_TRACE(S,A,V) trace(S,A,V)
static int ggs_aarch64_call(void *,struct ggs_regs *);
#include "uefi/GpuPasProbeNative.h"

static unsigned query(const struct ggs_regs *r) {
 const uint64_t targets[]={0x02000207,0x02000201,0x02000202,0x02000205};
 if(r->x[2]==13)return 4;
 for(unsigned i=0;i<4;i++)if(r->x[2]==targets[i])return i;
 CHECK(0);return 0;
}
static int ggs_aarch64_call(void *unused,struct ggs_regs *r) {
 (void)unused;unsigned q=query(r),n=per_query[q]++;
 CHECK(!prints && !mHostRingUnsafe && !mHostRing.enabled && !mHostWriteCalls);
 CHECK(mGpuSaveAllowed && !mHostRingPrepared && !mHostRing.started);
 CHECK(r->x[0]==(pending?1:(q<4?0x42000601u:0x42000207u)));
 CHECK(r->x[1]==1 && !r->x[3] && !r->x[4] && !r->x[5] && !r->x[7]);
 CHECK(r->x[6]==(pending?cookie:0));
 ++raw_calls;clock_us+=37;pending=0;
 if(mode==1 && n==0)r->x[0]=(uint64_t)(int64_t)-12;
 else if(mode==1 && n==1) {
  r->x[0]=1;pending=1;cookie=UINT64_C(0xa0a0000000000000)+raw_calls;r->x[6]=cookie;
 } else {
  r->x[0]=reply_status;r->x[1]=q<4?!!(available&(1u<<q)):1;
 }
 if(flip_after_call)mHostRingUnsafe=1;
 return 0;
}
static void reset(void) {
 mPasProbe=(struct hpp_result){0};memset(&mPasProbeNative,0,sizeof mPasProbeNative);
 mSecureCx=(struct ggs_state){.convention_verified=1,.available=1,.init_succeeded=1};
 mHostRingUnsafe=mHostWriteCalls=mHostRingPrepared=0;mGpuSaveAllowed=1;
 mHostRing.enabled=mHostRing.started=0;prep_phase=5;prep_bad=prep_calls=0;
 raw_calls=prints=delay_calls=mode=flip_after_call=pending=trace_count=0;
 clock_us=cookie=reply_status=0;available=15;memset(per_query,0,sizeof per_query);
}
static void active(unsigned phase,struct ggs_regs *r) {
 reset();mPasProbeNative.running=1;mPasProbe.started=1;mPasProbe.phase=phase;
 mPasProbe.available_mask=1;CHECK(hpp_frame(phase-1,r)==0);
}
static void normal_runs(void) {
 reset();CHECK(RunPasProbe()==HPP_OK);
 CHECK(raw_calls==5 && mPasProbeNative.calls==5 && mPasProbe.actual_calls==5);
 CHECK(!prints && !delay_calls && !mPasProbeNative.running && !mPasProbeNative.pending);
 CHECK(mPasProbe.valid_mask==31 && mPasProbe.available_mask==15 && mPasProbe.supported);
 CHECK(mPasProbeNative.elapsed==185 && mPasProbeNative.total_elapsed==185);
 CHECK(trace_count==10);
 for(unsigned i=0;i<5;i++) {
  CHECK(mPasProbeNative.query_elapsed[i]==37);
  CHECK(traces[2*i].step==0x7101+i && traces[2*i+1].step==0x7111+i);
  CHECK(traces[2*i].address==mPasProbe.query[i].request.x[0]);
  CHECK(traces[2*i].value==mPasProbe.query[i].request.x[2]);
  CHECK(traces[2*i+1].address==0 && traces[2*i+1].value==1);
 }
 CHECK(RunPasProbe()==HPP_ALREADY_STARTED && raw_calls==5);
 unsigned before=prep_calls;PasProbeReport();CHECK(prints==21 && prep_calls==before);
 reset();prep_phase=6;CHECK(RunPasProbe()==HPP_OK && raw_calls==5);
 reset();available=0;CHECK(RunPasProbe()==HPP_OK && raw_calls==4);
 CHECK(!mPasProbe.supported_valid && !mPasProbe.supported && mPasProbe.valid_mask==15);
 reset();mode=1;CHECK(RunPasProbe()==HPP_OK);
 CHECK(raw_calls==15 && delay_calls==5 && mPasProbeNative.elapsed==555);
 CHECK(mPasProbeNative.total_elapsed==150555 && trace_count==30);
 CHECK(mPasProbe.transport.busy_retries==5 && mPasProbe.transport.interrupt_resumes==5);
 reset();reply_status=UINT64_C(0x100000000);CHECK(RunPasProbe()==HPP_SCM);
 CHECK(raw_calls==1 && mPasProbeNative.last_output.x[0]==UINT64_C(0x100000000));
 CHECK(!mPasProbe.valid_mask && !mPasProbe.supported_valid && !prints);
}
static void owner_gates(void) {
 for(unsigned i=0;i<12;i++) {
  reset();
  if(i==0)mHostRingUnsafe=1;
  if(i==1)mHostRing.enabled=1;
  if(i==2)mHostWriteCalls=1;
  if(i==3)mGpuSaveAllowed=0;
  if(i==4)mHostRingPrepared=1;
  if(i==5)mHostRing.started=1;
  if(i==6)mSecureCx.convention_verified=0;
  if(i==7)mSecureCx.available=0;
  if(i==8)mSecureCx.init_succeeded=0;
  if(i==9)mSecureCx.quarantined=1;
  if(i==10)prep_bad=1;
  if(i==11)prep_phase=4;
  CHECK(RunPasProbe()==HPP_PREREQUISITE && !raw_calls && !prints);
 }
 struct ggs_regs r;
 active(1,&r);flip_after_call=1;
 CHECK(PasProbeCall(0,&r)!=0 && raw_calls==1 && mPasProbe.guard_failed);
 CHECK(mPasProbeNative.rejected==3 && mPasProbeNative.elapsed==37 && !prints);
 reset();flip_after_call=1;CHECK(RunPasProbe()==HPP_GUARD);
 CHECK(raw_calls==1 && mPasProbe.transport.quarantined && mPasProbe.query[0].response_present);
}
static void malformed_frames(void) {
 for(unsigned phase=1;phase<=5;phase++)for(unsigned field=0;field<8;field++)for(unsigned bit=0;bit<64;bit++) {
  struct ggs_regs r;active(phase,&r);r.x[field]^=UINT64_C(1)<<bit;
  CHECK(PasProbeCall(0,&r)!=0);
  CHECK(!raw_calls && !mPasProbeNative.calls && !trace_count && !mPasProbeNative.elapsed);
  CHECK(mPasProbeNative.rejected==2);
 }
 for(unsigned state=0;state<5;state++) {
  struct ggs_regs r;active(1,&r);
  if(state==0)mPasProbeNative.running=0;
  if(state==1)mPasProbe.started=0;
  if(state==2)mPasProbe.phase=0;
  if(state==3)mPasProbe.phase=6;
  if(state==4){mPasProbe.phase=5;mPasProbe.available_mask=0;CHECK(hpp_frame(4,&r)==0);}
  CHECK(PasProbeCall(0,&r)!=0 && !raw_calls && !trace_count);
 }
 struct ggs_regs r;active(1,&r);CHECK(PasProbeCall(0,0)!=0 && !raw_calls);
 const uint64_t forbidden[]={0x42000201,0x42000202,0x42000205,0x42000206,0xc2000207};
 for(unsigned i=0;i<5;i++) {
  active(1,&r);r.x[0]=forbidden[i];CHECK(PasProbeCall(0,&r)!=0 && !raw_calls);
 }
}
static void exact_resume(void) {
 struct ggs_regs r;
 active(1,&r);r.x[0]=1;CHECK(PasProbeCall(0,&r)!=0 && !raw_calls);
 for(unsigned field=1;field<8;field++)for(unsigned bit=0;bit<64;bit++) {
  active(1,&r);mPasProbeNative.pending=1;mPasProbeNative.pending_phase=1;
  mPasProbeNative.cookie=UINT64_C(0x1122334455667788);
  r.x[0]=1;r.x[6]=mPasProbeNative.cookie;r.x[field]^=UINT64_C(1)<<bit;
  CHECK(PasProbeCall(0,&r)!=0 && !raw_calls && !trace_count);
 }
 active(1,&r);mPasProbeNative.pending=1;mPasProbeNative.pending_phase=2;
 mPasProbeNative.cookie=7;r.x[0]=1;r.x[6]=7;
 CHECK(PasProbeCall(0,&r)!=0 && !raw_calls);
 active(1,&r);mPasProbeNative.pending=1;mPasProbeNative.pending_phase=1;
 mPasProbeNative.cookie=7; /* A new call must not discard an interrupted one. */
 CHECK(PasProbeCall(0,&r)!=0 && !raw_calls);
 active(1,&r);mPasProbeNative.pending=1;mPasProbeNative.pending_phase=1;
 mPasProbeNative.cookie=cookie=UINT64_C(0x1122334455667788);pending=1;
 r.x[0]=1;r.x[6]=cookie;
 CHECK(PasProbeCall(0,&r)==0 && raw_calls==1 && !mPasProbeNative.pending);
}
static void report_gates(void) {
 reset();CHECK(RunPasProbe()==0);unsigned before=prep_calls;
 mHostRingUnsafe=1;PasProbeReport();CHECK(!prints);
 mHostRingUnsafe=0;mGpuSaveAllowed=0;PasProbeReport();CHECK(!prints);
 mGpuSaveAllowed=1;mPasProbeNative.running=1;PasProbeReport();CHECK(!prints);
 mPasProbeNative.running=0;mHostRing.enabled=1;mHostRing.started=1;
 mHostRingPrepared=1;mHostWriteCalls=2;
 PasProbeReport();CHECK(prints==21 && prep_calls==before); /* safe post-stop CPU report */
}
int main(void) {
 normal_runs();owner_gates();malformed_frames();exact_resume();report_gates();
 printf("PASS: %u actual PAS native boundary/owner/frame/resume/report checks; ASAN/UBSAN; no SMC\n",checks);
 return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="houji-pas-native-") as temp:
    source = Path(temp) / "native.c"
    binary = Path(temp) / "native"
    source.write_text(SOURCE)
    subprocess.run([
        os.environ.get("CC", "clang"), "-std=gnu11", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g",
        "-I", str(ROOT / "native/gpu"), str(source), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True, env={
        **os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1",
    })
