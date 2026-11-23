#!/usr/bin/env python3
"""Compile the actual fixed PAS query policy, with real bounded SCM transport.

The fixture checks full ABI frames, response semantics, guard ordering and
returned-status limits. It never invokes an SMC or models firmware loading.
"""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#define GG_HOST_TEST 1
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "uefi/GpuPasProbe.h"

static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { \
 fprintf(stderr,"check line %d: %s\n",__LINE__,#x); assert(x); } } while(0)
enum { NORMAL, STATUS, TRANSPORT, BUSY, INTERRUPT, MIXED };
struct fixture {
 unsigned mask,mode,fail_query,calls,guards,deny_guard,delays,fail_delay;
 unsigned per_query[5],pending;
 uint64_t supported,noncanonical,status,cookie;
};
static int guard(void *cookie) {
 struct fixture *f=cookie;++f->guards;
 return f->guards==f->deny_guard?0:1;
}
static unsigned identify(const struct ggs_regs *r) {
 /* Independent target list from qcom_scm.h svc2 cmd7/1/2/5, PASID13. */
 const uint64_t target[]={0x02000207,0x02000201,0x02000202,0x02000205};
 if(r->x[2]==13)return 4;
 for(unsigned i=0;i<4;i++)if(r->x[2]==target[i])return i;
 CHECK(0);return 0;
}
static int call(void *cookie,struct ggs_regs *r) {
 struct fixture *f=cookie;
 unsigned q=identify(r),n=f->per_query[q]++;
 uint64_t original=q<4?UINT64_C(0x42000601):UINT64_C(0x42000207);
 CHECK(r->x[0]==(f->pending?1:original));
 CHECK(r->x[1]==1);
 CHECK(r->x[3]==0 && r->x[4]==0 && r->x[5]==0 && r->x[7]==0);
 CHECK(r->x[6]==(f->pending?f->cookie:0));
 CHECK((original>>31)==0); /* STD, not FAST */
 CHECK(((original>>30)&1)==1 && ((original>>24)&0x3f)==2); /* SMC64 SiP */
 CHECK((original&0xffff)==(q<4?0x0601:0x0207));
 ++f->calls;f->pending=0;
 if(q==f->fail_query && f->mode==TRANSPORT)return 7;
 uint64_t status=0;
 if(q==f->fail_query) {
  if(f->mode==STATUS)status=f->status;
  if(f->mode==BUSY)status=f->status;
  if(f->mode==INTERRUPT)status=1;
 }
 if(f->mode==MIXED)status=n==0?(uint64_t)(int64_t)-12:n==1?1:0;
 r->x[0]=status;
 if(status==1) {
  f->pending=1;f->cookie=UINT64_C(0xa5a5000000000000)+f->calls;
  r->x[6]=f->cookie;
 } else {
  r->x[1]=q==4?f->supported:((f->mask&(1u<<q))?(f->noncanonical?f->noncanonical:1):0);
  /* Returned data must not leak into fresh input frames. */
  r->x[3]=UINT64_C(0xf1f2f3f4);r->x[7]=UINT64_C(0x11223344);
 }
 return 0;
}
static int delay(void *cookie,unsigned ms) {
 struct fixture *f=cookie;CHECK(ms==30);++f->delays;
 return f->delays==f->fail_delay?9:0;
}
static struct ggs_state qualified(void) {
 const struct ggs_state q={.convention_verified=1,.available=1,.init_succeeded=1};
 return q;
}
static struct fixture normal(void) {
 const struct fixture f={.mask=15,.supported=1,.fail_query=99};return f;
}
static unsigned run(struct fixture *f,struct hpp_result *r) {
 struct ggs_state q=qualified();
 const struct hpp_io io={f,guard,call,delay};
 return hpp_run(&io,&q,r);
}
static void success_matrix(void) {
 const uint64_t booleans[]={0,1,2,UINT64_MAX};
 for(unsigned mask=0;mask<16;mask++)for(unsigned b=0;b<4;b++) {
  struct fixture f=normal();struct hpp_result r={0};
  f.mask=mask;f.supported=booleans[b];
  CHECK(run(&f,&r)==HPP_OK);
  unsigned count=4+!!(mask&1);
  CHECK(r.started==1 && r.phase==6 && r.code==0 && r.completed==count);
  CHECK(f.calls==count && r.actual_calls==count && r.transport.calls==count);
  CHECK(r.attempted_mask==((mask&1)?31u:15u));
  CHECK(r.valid_mask==r.attempted_mask && r.available_mask==mask);
  CHECK(r.supported_valid==!!(mask&1));
  CHECK(r.supported==((mask&1)?!!booleans[b]:0));
  CHECK(!r.guard_failed && !r.transport.quarantined && f.delays==0);
  for(unsigned i=0;i<4;i++) {
   CHECK(r.query[i].attempted && r.query[i].valid && r.query[i].actual_calls==1);
   CHECK(r.query[i].response_present && r.query[i].response_transport==0);
   CHECK(r.query[i].response.x[1]==!!(mask&(1u<<i)));
   CHECK(r.query[i].response.x[0]==0 && r.query[i].transport_code==GGS_OK);
  }
  if(mask&1)CHECK(r.query[4].response.x[1]==booleans[b]);
  else CHECK(!r.query[4].attempted && !r.query[4].response_present);
  unsigned before=f.calls;
  CHECK(run(&f,&r)==HPP_ALREADY_STARTED && f.calls==before);
 }
 /* The target Linux query API uses !!result[0], not result==1. */
 struct fixture f=normal();struct hpp_result r={0};f.noncanonical=UINT64_MAX;
 CHECK(run(&f,&r)==HPP_OK && r.available_mask==15);
 for(unsigned i=0;i<4;i++)CHECK(r.query[i].response.x[1]==UINT64_MAX);
}
static void arguments(void) {
 struct fixture f=normal();struct ggs_state q=qualified();
 struct hpp_io io={&f,guard,call,delay};struct hpp_result r={0};
 CHECK(hpp_run(&io,&q,0)==HPP_ARGUMENT);
 CHECK(hpp_run(0,&q,&r)==HPP_ARGUMENT);
 CHECK(hpp_run(&io,0,&r)==HPP_ARGUMENT);
 struct hpp_io bad=io;bad.call=0;CHECK(hpp_run(&bad,&q,&r)==HPP_ARGUMENT);
 bad=io;bad.guard=0;CHECK(hpp_run(&bad,&q,&r)==HPP_ARGUMENT);
 bad=io;bad.delay_ms=0;CHECK(hpp_run(&bad,&q,&r)==HPP_ARGUMENT);
 CHECK(f.calls==0 && f.guards==0);
 for(unsigned field=0;field<4;field++)for(unsigned value=0;value<3;value++) {
  q=qualified();r=(struct hpp_result){0};
  if(field==0)q.convention_verified=value;
  if(field==1)q.available=value;
  if(field==2)q.init_succeeded=value;
  if(field==3)q.quarantined=value+1;
  if(field<3 && value==1)continue;
  CHECK(hpp_run(&io,&q,&r)==HPP_CONVENTION && !r.started && !f.calls);
 }
 struct ggs_regs out={{1,2,3,4,5,6,7,8}},before=out;
 CHECK(hpp_frame(5,&out)==HPP_ARGUMENT && !memcmp(&out,&before,sizeof out));
 CHECK(hpp_frame(0,0)==HPP_ARGUMENT);
}
static void smc_errors(void) {
 const uint64_t errors[]={UINT64_MAX,(uint64_t)(int64_t)-3,4,
  UINT64_C(0x100000000),UINT64_C(0xffff000000000000)};
 for(unsigned query=0;query<5;query++)for(unsigned e=0;e<5;e++) {
  struct fixture f=normal();struct hpp_result r={0};
  f.mode=STATUS;f.fail_query=query;f.status=errors[e];
  CHECK(run(&f,&r)==HPP_SCM && r.code==HPP_SCM);
  CHECK(f.calls==query+1 && r.actual_calls==f.calls && r.completed==query);
  CHECK(r.valid_mask==((1u<<query)-1) && !r.query[query].valid);
  CHECK(r.query[query].response_present && r.query[query].response.x[0]==errors[e]);
  CHECK(r.query[query].transport_code==GGS_SECURE_ERROR && !r.supported_valid);
 }
 for(unsigned query=0;query<5;query++) {
  struct fixture f=normal();struct hpp_result r={0};f.mode=TRANSPORT;f.fail_query=query;
  CHECK(run(&f,&r)==HPP_SCM && r.transport.quarantined);
  CHECK(f.calls==query+1 && r.query[query].response_transport==7);
  CHECK(r.query[query].transport_code==GGS_TRANSPORT && !r.query[query].valid);
 }
 for(unsigned status=2;status<=3;status++) {
  struct fixture f=normal();struct hpp_result r={0};
  f.mode=STATUS;f.fail_query=0;f.status=status;
  CHECK(run(&f,&r)==HPP_SCM && r.transport.quarantined);
  CHECK(f.calls==1 && !f.delays && r.query[0].transport_code==GGS_WAITQ);
 }
}
static void bounded_transport(void) {
 struct fixture f=normal();struct hpp_result r={0};f.mode=MIXED;
 CHECK(run(&f,&r)==HPP_OK && r.completed==5);
 CHECK(f.calls==15 && f.delays==5 && r.transport.interrupt_resumes==5);
 CHECK(r.transport.busy_retries==5 && r.actual_calls==15);
 for(unsigned q=0;q<5;q++)CHECK(r.query[q].actual_calls==3 && r.query[q].valid);
 const uint64_t busy[]={ (uint64_t)(int64_t)-12,UINT64_C(0xfffffff4)};
 for(unsigned b=0;b<2;b++) {
  f=normal();r=(struct hpp_result){0};f.mode=BUSY;f.fail_query=2;f.status=busy[b];
  CHECK(run(&f,&r)==HPP_SCM && r.transport.quarantined);
  CHECK(f.calls==2+GGS_BUSY_RETRIES+1 && f.delays==GGS_BUSY_RETRIES);
  CHECK(r.query[2].transport_code==GGS_RETRY_LIMIT && r.completed==2);
 }
 f=normal();r=(struct hpp_result){0};f.mode=INTERRUPT;f.fail_query=1;
 CHECK(run(&f,&r)==HPP_SCM && r.transport.quarantined);
 CHECK(f.calls==1+GGS_INTERRUPT_RESUMES+1 && f.delays==0);
 CHECK(r.query[1].transport_code==GGS_RETRY_LIMIT && r.completed==1);
 f=normal();r=(struct hpp_result){0};f.mode=MIXED;f.fail_delay=1;
 CHECK(run(&f,&r)==HPP_SCM && r.transport.quarantined);
 CHECK(f.calls==1 && f.delays==1 && r.completed==0);
}
static void guard_ordering(void) {
 for(unsigned deny=1;deny<=11;deny++) {
  struct fixture f=normal();struct hpp_result r={0};f.deny_guard=deny;
  CHECK(run(&f,&r)==(deny==1?HPP_PREREQUISITE:HPP_GUARD));
  CHECK(f.guards==deny);
  CHECK(f.calls==(deny-1)/2);
  if(deny==1)CHECK(!r.started && f.calls==0);
  else CHECK(r.guard_failed && r.transport.quarantined && r.completed<5);
 }
 /* Includes guard changes during BUSY delays and INTERRUPTED resumes. */
 for(unsigned deny=1;deny<=41;deny++) {
  struct fixture f=normal();struct hpp_result r={0};f.mode=MIXED;f.deny_guard=deny;
  CHECK(run(&f,&r)==(deny==1?HPP_PREREQUISITE:HPP_GUARD));
  CHECK(f.guards==deny && f.calls<=15 && f.delays<=5);
  if(deny>1)CHECK(r.guard_failed && r.transport.quarantined);
 }
}
int main(void) {
 success_matrix();arguments();smc_errors();bounded_transport();guard_ordering();
 printf("PASS: %u PAS query ABI/semantics/guard/retry checks; actual policy + existing SCM transport; no SMC or loader\n",checks);
 return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="houji-pas-probe-") as temp:
    source = Path(temp) / "probe.c"
    binary = Path(temp) / "probe"
    source.write_text(SOURCE)
    subprocess.run([
        os.environ.get("CC", "clang"), "-std=c11", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g",
        "-I", str(ROOT / "native/gpu"), str(source), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True, env={
        **os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1",
    })
