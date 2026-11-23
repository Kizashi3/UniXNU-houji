#!/usr/bin/env python3
"""Verify exact signed assets and the actual fixed loader state machine.

No SMC, device, signing, loader integration, or GPU packet is executed. The
callbacks record the real policy's ABI/order and simulate partial failures.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts/make-gpu-zap-assets.py"
spec = importlib.util.spec_from_file_location("houji_zap_assets", GENERATOR)
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)
source_manifest = json.loads((ROOT / "native/gpu/zap-assets-source.json").read_text())
stock = Path(source_manifest["source"])
blob = stock.read_bytes()
metadata, segment, headers = assets.decode(blob)
assert len(metadata) == 4044 and len(segment) == 1072 and len(headers) == 3
assert hashlib.sha256(blob).hexdigest() == assets.SOURCE_SHA
assert metadata == blob[:148] + blob[8192:12088]
assert segment == blob[4096:5168]
assert struct.unpack_from("<I", metadata, 28)[0] == 52
generator_checks = 5

with tempfile.TemporaryDirectory(prefix="houji-zap-assets-") as temp:
    directory = Path(temp)
    header, manifest = directory / "assets.h", directory / "assets.json"
    command = ["python3", str(GENERATOR), "--source", str(stock),
               "--output-header", str(header), "--output-manifest", str(manifest)]
    subprocess.run(command, check=True, capture_output=True)
    assert header.read_bytes() == (ROOT / "native/gpu/uefi/GpuZapAssets.h").read_bytes()
    expected = json.loads(manifest.read_text())
    assert expected == source_manifest
    generator_checks += 2
    original = header.read_bytes(), manifest.read_bytes()
    for offset in (0, 4, 28, 52, 84, 116, 4096, 5167, 8192, 12087):
        corrupt = bytearray(blob)
        corrupt[offset] ^= 1
        bad = directory / "bad.mbn"
        bad.write_bytes(corrupt)
        result = subprocess.run(["python3", str(GENERATOR), "--source", str(bad),
                                 "--output-header", str(header), "--output-manifest", str(manifest)],
                                capture_output=True)
        assert result.returncode != 0
        assert (header.read_bytes(), manifest.read_bytes()) == original
        generator_checks += 2
    for size in (0, 52, 148, 5168, 12087, 12089):
        bad = directory / "bad.mbn"
        bad.write_bytes((blob + b"x")[:size])
        result = subprocess.run(["python3", str(GENERATOR), "--source", str(bad),
                                 "--output-header", str(header), "--output-manifest", str(manifest)],
                                capture_output=True)
        assert result.returncode != 0
        assert (header.read_bytes(), manifest.read_bytes()) == original
        generator_checks += 2

SOURCE = r'''
#define GG_HOST_TEST 1
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "uefi/GpuZapLoad.h"
static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { \
 fprintf(stderr,"zap line %d: %s\n",__LINE__,#x); assert(x); } } while(0)
_Alignas(4096) static uint8_t metadata[4096];
static uint8_t destination[0x2000];
enum { NORMAL, A0_ERROR, A1_ERROR, TRANSPORT, MIXED, BUSY, INTERRUPT };
struct fixture {
 struct hzl_result *result;
 unsigned mode,fail_query,publish_fail,publish_corrupt,copy_fail,partial_copy;
 unsigned guards,deny_guard,publishes,copies,raw_calls,delays,fail_delay,pending,closed,auth_seen;
 unsigned per_query[3],events[128],event_count;
 uint64_t status,cookie;
};
static struct ggs_state qualified;
static struct hpp_result capability;
static struct hzl_config config;
static int cap_guard(void *p) {(void)p;return 1;}
static int cap_call(void *p,struct ggs_regs *r) {
 (void)p;CHECK(r->x[0]==0x42000601u || r->x[0]==0x42000207u);
 CHECK(r->x[1]==1 && !r->x[3] && !r->x[4] && !r->x[5] && !r->x[6] && !r->x[7]);
 r->x[0]=0;r->x[1]=1;return 0;
}
static int cap_delay(void *p,unsigned ms) {(void)p;(void)ms;CHECK(0);return 1;}
static void reset(struct fixture *f,struct hzl_result *r) {
 memset(f,0,sizeof *f);memset(r,0,sizeof *r);f->result=r;f->fail_query=99;
 memset(metadata,0xa5,sizeof metadata);memset(destination,0x5a,sizeof destination);
 qualified=(struct ggs_state){.convention_verified=1,.available=1,.init_succeeded=1};
 capability=(struct hpp_result){0};
 const struct hpp_io capio={0,cap_guard,cap_call,cap_delay};
 CHECK(hpp_run(&capio,&qualified,&capability)==HPP_OK);
 config=(struct hzl_config){metadata,UINT64_C(0xc0000000),4096,HZL_RESERVATION_BASE,0x2000};
}
static int guard(void *cookie,unsigned phase) {
 struct fixture *f=cookie;++f->guards;
 CHECK(phase>=1 && phase<=7 && phase==f->result->phase);
 if(phase>=HZL_PHASE_AUTH)CHECK(f->closed && f->copies==1);
 return f->guards==f->deny_guard?0:1;
}
static void event(struct fixture *f,unsigned e) {
 CHECK(f->event_count<128);f->events[f->event_count++]=e;
}
static int publish(void *cookie,void *cpu,uint64_t physical,unsigned bytes) {
 struct fixture *f=cookie;
 CHECK(f->result->phase==HZL_PHASE_PUBLISH && f->result->metadata_copied);
 CHECK(!f->result->init_attempted && !f->result->retained && !f->auth_seen);
 CHECK(cpu==metadata && physical==UINT64_C(0xc0000000) && bytes==4044);
 CHECK(!memcmp(cpu,mHoujiZapMetadata,4044));
 for(unsigned i=4044;i<4096;i++)CHECK(metadata[i]==0xa5);
 ++f->publishes;event(f,90);
 if(f->publish_corrupt)metadata[4043]^=1;
 return f->publish_fail?7:0;
}
static int copy(void *cookie,uint64_t physical,const uint8_t *data,unsigned bytes) {
 struct fixture *f=cookie;struct hzl_result *r=f->result;
 CHECK(r->phase==HZL_PHASE_COPY && r->init_succeeded && r->mem_setup_succeeded);
 CHECK(r->retained && r->segment_copy_attempted && !r->auth_attempted);
 CHECK(!f->auth_seen && !f->closed && !f->copies);
 CHECK(physical==UINT64_C(0x9b09a000) && data==mHoujiZapSegment && bytes==1072);
 ++f->copies;event(f,91);
 memcpy(destination,data,f->partial_copy?17:bytes);
 f->closed=1; /* irreversible logical CPU-access close, no page-table claim */
 return f->copy_fail?9:0;
}
static int call(void *cookie,struct ggs_regs *r) {
 struct fixture *f=cookie;struct hzl_result *result=f->result;
 unsigned q=result->phase==HZL_PHASE_INIT?0:result->phase==HZL_PHASE_MEM_SETUP?1:2;
 CHECK(result->phase==(q==0?4:q==1?5:7));
 const uint64_t request[3][8]={
  {0x42000201,0x82,13,UINT64_C(0xc0000000),0,0,0,0},
  {0x42000202,3,13,UINT64_C(0x9b09a000),0x1000,0,0,0},
  {0x42000205,1,13,0,0,0,0,0}};
 CHECK(r->x[0]==(f->pending?1:request[q][0]));
 for(unsigned i=1;i<8;i++)CHECK(r->x[i]==(i==6?(f->pending?f->cookie:0):request[q][i]));
 CHECK(result->retained && result->init_attempted && result->metadata_published);
 if(q==0)CHECK(!f->copies && !result->mem_setup_succeeded);
 if(q==1)CHECK(result->init_succeeded && !f->copies);
 if(q==2)CHECK(result->mem_setup_succeeded && f->closed && result->segment_published);
 event(f,result->phase);++f->raw_calls;
 unsigned n=f->per_query[q]++;f->pending=0;
 if(q==2)f->auth_seen=1;
 if(q==f->fail_query && f->mode==TRANSPORT)return 11;
 uint64_t status=0,a1=0;
 if(q==f->fail_query) {
  if(f->mode==A0_ERROR || f->mode==BUSY)status=f->status;
  if(f->mode==A1_ERROR)a1=f->status;
  if(f->mode==INTERRUPT)status=1;
 }
 if(f->mode==MIXED)status=n==0?(uint64_t)(int64_t)-12:n==1?1:0;
 r->x[0]=status;r->x[1]=a1;
 if(status==1) {
  f->cookie=UINT64_C(0x1234000000000000)+f->raw_calls;f->pending=1;r->x[6]=f->cookie;
 }
 return 0;
}
static int delay(void *cookie,unsigned ms) {
 struct fixture *f=cookie;CHECK(ms==30);++f->delays;
 return f->delays==f->fail_delay?13:0;
}
static unsigned run(struct fixture *f,struct hzl_result *r) {
 const struct hzl_io io={f,guard,publish,copy,call,delay};
 return hzl_run(&io,&config,&qualified,&capability,r);
}
static void success(void) {
 struct fixture f;struct hzl_result r;reset(&f,&r);
 CHECK(run(&f,&r)==HZL_OK && r.phase==8 && r.authenticated && r.retained);
 CHECK(r.metadata_copied && r.metadata_published && r.init_succeeded && r.mem_setup_succeeded);
 CHECK(r.segment_published && r.init_attempted && r.mem_setup_attempted && r.auth_attempted);
 CHECK(f.publishes==1 && f.copies==1 && f.raw_calls==3 && r.actual_calls==3);
 CHECK(f.guards==14 && !f.delays && !r.transport.quarantined);
 const unsigned order[]={90,4,5,91,7};
 CHECK(f.event_count==5 && !memcmp(f.events,order,sizeof order));
 CHECK(!memcmp(metadata,mHoujiZapMetadata,4044));
 CHECK(!memcmp(destination,mHoujiZapSegment,1072));
 for(unsigned i=1072;i<sizeof destination;i++)CHECK(destination[i]==0x5a);
 for(unsigned i=4044;i<4096;i++)CHECK(metadata[i]==0xa5);
 for(unsigned i=0;i<3;i++)CHECK(r.call[i].valid && r.call[i].response_present && r.call[i].actual_calls==1);
 CHECK(run(&f,&r)==HZL_ALREADY_STARTED && f.raw_calls==3 && f.copies==1);
 reset(&f,&r);f.mode=MIXED;
 CHECK(run(&f,&r)==0 && r.authenticated && r.retained);
 CHECK(f.raw_calls==9 && f.delays==3 && r.transport.busy_retries==3 && r.transport.interrupt_resumes==3);
 for(unsigned i=0;i<3;i++)CHECK(r.call[i].actual_calls==3 && r.call[i].valid);
}
static void configurations(void) {
 struct fixture f;struct hzl_result r;
 for(unsigned i=0;i<11;i++) {
  reset(&f,&r);
  if(i==0)config.metadata_cpu=0;
  if(i==1)config.metadata_cpu=metadata+1;
  if(i==2)config.metadata_physical=0;
  if(i==3)config.metadata_physical++;
  if(i==4)config.metadata_capacity=4044;
  if(i==5)config.metadata_capacity=8192;
  if(i==6)config.reservation_base++;
  if(i==7)config.reservation_bytes=0x1000;
  if(i==8)config.metadata_physical=HZL_RESERVATION_BASE;
  if(i==9)config.metadata_physical=HZL_RESERVATION_BASE+4096;
  if(i==10)config.metadata_cpu=(void *)((uintptr_t)mHoujiZapMetadata&~(uintptr_t)4095);
  CHECK(run(&f,&r)==HZL_ARGUMENT && !r.started && !f.raw_calls && !f.publishes);
  CHECK(metadata[0]==0xa5 && destination[0]==0x5a);
 }
 reset(&f,&r);const struct hzl_io io={&f,guard,publish,copy,call,delay};
 CHECK(hzl_run(&io,&config,&qualified,&capability,0)==HZL_ARGUMENT);
 CHECK(hzl_run(0,&config,&qualified,&capability,&r)==HZL_ARGUMENT);
 CHECK(hzl_run(&io,0,&qualified,&capability,&r)==HZL_ARGUMENT);
 struct hzl_io bad=io;bad.guard=0;CHECK(hzl_run(&bad,&config,&qualified,&capability,&r)==HZL_ARGUMENT);
 bad=io;bad.publish_metadata=0;CHECK(hzl_run(&bad,&config,&qualified,&capability,&r)==HZL_ARGUMENT);
 bad=io;bad.copy_segment=0;CHECK(hzl_run(&bad,&config,&qualified,&capability,&r)==HZL_ARGUMENT);
 bad=io;bad.call=0;CHECK(hzl_run(&bad,&config,&qualified,&capability,&r)==HZL_ARGUMENT);
 bad=io;bad.delay_ms=0;CHECK(hzl_run(&bad,&config,&qualified,&capability,&r)==HZL_ARGUMENT);
 CHECK(!f.raw_calls && !f.publishes);
}
static void capabilities(void) {
 struct fixture f;struct hzl_result r;
 for(unsigned i=0;i<16;i++) {
  reset(&f,&r);
  if(i==0)qualified.convention_verified=0;
  if(i==1)qualified.available=0;
  if(i==2)qualified.init_succeeded=0;
  if(i==3)qualified.quarantined=1;
  if(i==4)capability.started=0;
  if(i==5)capability.phase=5;
  if(i==6)capability.code=1;
  if(i==7)capability.completed=4;
  if(i==8)capability.attempted_mask=15;
  if(i==9)capability.valid_mask=15;
  if(i==10)capability.available_mask=14;
  if(i==11)capability.supported_valid=0;
  if(i==12)capability.supported=0;
  if(i==13)capability.actual_calls=0;
  if(i==14)capability.guard_failed=1;
  if(i==15)capability.transport.quarantined=1;
  CHECK(run(&f,&r)==HZL_QUALIFICATION && !r.started && !f.raw_calls && !f.publishes);
 }
 for(unsigned q=0;q<5;q++)for(unsigned i=0;i<16;i++) {
  reset(&f,&r);struct hpp_observation *o=&capability.query[q];
  if(i==0)o->attempted=0;
  if(i==1)o->valid=0;
  if(i==2)o->actual_calls=0;
  if(i==3)o->transport_code=1;
  if(i==4)o->response_present=0;
  if(i==5)o->response_transport=1;
  if(i==6)o->response.x[0]=UINT64_C(0x100000000);
  if(i==7)o->response.x[1]=0;
  if(i>=8)o->request.x[i-8]^=1;
  CHECK(run(&f,&r)==HZL_QUALIFICATION && !f.raw_calls && !f.publishes);
 }
 reset(&f,&r);for(unsigned q=0;q<5;q++)capability.query[q].response.x[1]=2;
 CHECK(run(&f,&r)==0); /* query boolean != mutation status */
}
static void local_failures(void) {
 struct fixture f;struct hzl_result r;
 reset(&f,&r);f.publish_fail=1;
 CHECK(run(&f,&r)==HZL_PUBLISH && !r.retained && !r.init_attempted && !f.raw_calls && !f.copies);
 reset(&f,&r);f.publish_corrupt=1;
 CHECK(run(&f,&r)==HZL_METADATA && !r.metadata_published && !r.retained && !f.raw_calls);
 reset(&f,&r);f.copy_fail=f.partial_copy=1;
 CHECK(run(&f,&r)==HZL_COPY && r.retained && r.init_succeeded && r.mem_setup_succeeded);
 CHECK(r.segment_copy_attempted && !r.segment_published && !r.auth_attempted && !r.authenticated);
 CHECK(f.raw_calls==2 && f.copies==1 && f.closed && r.copy_code==9);
 CHECK(!memcmp(destination,mHoujiZapSegment,17) && destination[17]==0x5a);
 CHECK(run(&f,&r)==HZL_ALREADY_STARTED && f.copies==1 && f.raw_calls==2);
}
static void secure_failures(void) {
 const uint64_t errors[]={UINT64_MAX,(uint64_t)(int64_t)-3,4,UINT64_C(0x100000000)};
 struct fixture f;struct hzl_result r;
 for(unsigned q=0;q<3;q++)for(unsigned type=0;type<2;type++)for(unsigned e=0;e<4;e++) {
  reset(&f,&r);f.fail_query=q;f.mode=type?A1_ERROR:A0_ERROR;f.status=errors[e];
  CHECK(run(&f,&r)==(type?HZL_SECURE_RESULT:HZL_SCM));
  CHECK(r.retained && !r.authenticated && f.raw_calls==q+1);
  CHECK(f.copies==(q==2) && !r.call[q].valid && r.call[q].response_present);
  CHECK(r.call[q].response.x[type?1:0]==errors[e]);
  CHECK(run(&f,&r)==HZL_ALREADY_STARTED && f.raw_calls==q+1);
 }
 for(unsigned q=0;q<3;q++) {
  reset(&f,&r);f.mode=A1_ERROR;f.fail_query=q;f.status=1;
  CHECK(run(&f,&r)==HZL_SECURE_RESULT && r.retained && !r.authenticated);
  CHECK(f.raw_calls==q+1 && !r.call[q].valid && r.call[q].response.x[1]==1);
  reset(&f,&r);f.mode=TRANSPORT;f.fail_query=q;
  CHECK(run(&f,&r)==HZL_SCM && r.retained && r.transport.quarantined);
  CHECK(r.call[q].response_transport==11 && f.raw_calls==q+1 && !r.authenticated);
 }
 for(unsigned status=2;status<=3;status++) {
  reset(&f,&r);f.mode=A0_ERROR;f.fail_query=0;f.status=status;
  CHECK(run(&f,&r)==HZL_SCM && r.transport.quarantined && r.retained);
  CHECK(f.raw_calls==1 && !f.delays && !f.copies);
 }
 const uint64_t busy[]={(uint64_t)(int64_t)-12,UINT64_C(0xfffffff4)};
 for(unsigned i=0;i<2;i++) {
  reset(&f,&r);f.mode=BUSY;f.fail_query=1;f.status=busy[i];
  CHECK(run(&f,&r)==HZL_SCM && r.retained && r.transport.quarantined);
  CHECK(f.raw_calls==GGS_BUSY_RETRIES+2 && f.delays==GGS_BUSY_RETRIES && !f.copies);
 }
 reset(&f,&r);f.mode=INTERRUPT;f.fail_query=2;
 CHECK(run(&f,&r)==HZL_SCM && r.retained && r.transport.quarantined);
 CHECK(f.raw_calls==GGS_INTERRUPT_RESUMES+3 && f.copies==1 && f.closed);
 reset(&f,&r);f.mode=MIXED;f.fail_delay=1;
 CHECK(run(&f,&r)==HZL_SCM && r.retained && r.transport.quarantined);
 CHECK(f.raw_calls==1 && f.delays==1 && !f.copies && !r.authenticated);
}
static void guard_failures(void) {
 struct fixture f;struct hzl_result r;
 for(unsigned deny=1;deny<=14;deny++) {
  reset(&f,&r);f.deny_guard=deny;
  CHECK(run(&f,&r)==HZL_GUARD && r.guard_failed && !r.authenticated);
  CHECK(f.guards==deny && r.retained==(deny>=7));
  CHECK(f.raw_calls<=3 && f.copies<=1);
  CHECK(run(&f,&r)==HZL_ALREADY_STARTED);
 }
 // 14 baseline guards + 3 * (two extra SMC pairs + one delay pair).
 for(unsigned deny=1;deny<=32;deny++) {
  reset(&f,&r);f.mode=MIXED;f.deny_guard=deny;
  CHECK(run(&f,&r)==HZL_GUARD && r.guard_failed);
  CHECK(f.guards==deny && f.copies<=1 && !r.authenticated);
  if(r.init_attempted)CHECK(r.retained);
 }
}
int main(void) {
 CHECK(hzl_crc32(mHoujiZapMetadata,4044)==0xc73aee66u);
 CHECK(hzl_crc32(mHoujiZapSegment,1072)==0xef6cc69bu);
 success();configurations();capabilities();local_failures();secure_failures();guard_failures();
 printf("PASS: %u actual fixed ZAP policy/capability/ABI/order/retention checks; no SMC, GPU or loader integration\n",checks);
 return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="houji-zap-policy-") as temp:
    source = Path(temp) / "policy.c"
    binary = Path(temp) / "policy"
    source.write_text(SOURCE)
    subprocess.run([
        os.environ.get("CC", "clang"), "-std=c11", "-Wall", "-Wextra", "-Werror",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g",
        "-I", str(ROOT / "native/gpu"), str(source), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True, env={
        **os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1",
    })
print(f"PASS: {generator_checks} exact stock asset/generator checks; mismatches preserve outputs")
