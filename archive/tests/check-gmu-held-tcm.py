#!/usr/bin/env python3
"""Actual portable held-reset TCM core, actual hph/hcw fresh survey; no device."""
from pathlib import Path
import hashlib,json,re,struct,subprocess,tempfile
p=Path(__file__).resolve().parents[1]
refs={
 'native/gpu/uefi/GpuGmuCode.h':'3250956997b9d1356fe2713e3dc48e2bda61876e8fd207fbb3d4753848ebffc5',
 'native/gpu/firmware/houji_gmu_tcm_probe.S':'4a3cfdcce7677cb68061748e438a072ecf969718f35f47220216c48cdf42ec43',
}
for name,wanted in refs.items():assert hashlib.sha256((p/name).read_bytes()).hexdigest()==wanted
words=[int(x,16) for x in re.findall(r'0x([0-9a-f]+)u',(p/'native/gpu/uefi/GpuGmuCode.h').read_text())]
assert len(words)==34 and hashlib.sha256(struct.pack('<34I',*words)).hexdigest()=='6c1d70a8de298accbb03a8dd39cc5aaa289b741cb7a7ab3d176261d2cdb795e0'
header=(p/'native/gpu/xnu/GmuHeldTcm.h').read_text()
assert 'hph_recheck(record,current,current_clock)' in header
assert 'hph_recheck(record,&r->last_cold,&r->last_clock)' in header
assert 'hgd_probe(' not in header and 'hgd_control_address(' not in header
program=r'''
#define main portable_handoff_tests
#include "PORTABLE_TEST"
#undef main
#include "GmuHeldTcm.h"
struct tcm_test {
 struct mock hardware;
 uint32_t tcm[HHT_TOTAL_WORDS],original[HHT_TOTAL_WORDS];
 struct hht_result result;
 struct hph_record record;
 struct hph_cold current;
 struct hph_clock current_clock;
 unsigned read_calls,tcm_reads,cxo_reads,write_calls,barrier_calls,fresh_calls,commit_calls,owner_calls;
 unsigned fail_read,fail_write,fail_barrier,fail_fresh,fail_commit,fail_owner,bad_cxo,bad_cold,bad_clock;
 unsigned commit_power_loss,commit_backup_change,stack_damage,restore_alias,write_warning,read_warning,commit_warning;
 unsigned pending,stopped,stopped_reads,stopped_writes,stop_owner_count,mismatch_read;
};
static struct hph_record record_good;
static struct mock hardware_good;
static struct tcm_test test;
static int index_for(uint32_t address) {
 for(unsigned i=0;i<HHT_TOTAL_WORDS;i++)if(hht_address(i)==address)return (int)i;
 return -1;
}
static int tcm_owner(void *cookie) {
 struct tcm_test *t=cookie;assert(t==&test);
 if(++t->owner_calls==t->fail_owner) {
  t->stopped=1;t->stopped_reads=t->read_calls;t->stopped_writes=t->write_calls;t->stop_owner_count=t->owner_calls;return 1;
 }
 return 0; // A transient failure must nevertheless remain sticky in the core.
}
static GPP_U64 tcm_read(void *cookie,uint32_t address,uint32_t *value) {
 struct tcm_test *t=cookie;assert(t==&test && value && !t->stopped && !t->pending);
 int index=index_for(address);assert(address==0x3d99144u || index>=0);
 ++t->read_calls;
 if(address==0x3d99144u) {
  ++t->cxo_reads;*value=t->bad_cxo==t->cxo_reads?0x80000001u:1u;
 } else {
  ++t->tcm_reads;*value=t->tcm[index];
 }
 if(t->mismatch_read==t->read_calls)*value^=1;
 if(t->fail_read==t->read_calls)return t->read_warning?1:UINT64_C(0x8000000000000007);
 return 0;
}
static GPP_U64 tcm_write(void *cookie,uint32_t address,uint32_t value) {
 struct tcm_test *t=cookie;struct hht_result *r=&t->result;int index=index_for(address);
 assert(t==&test && !t->stopped && !t->pending && index>=0 && (unsigned)index<HHT_PROGRAM_WORDS);
 assert(r->backup_words==58 && r->backup_committed && r->backup[index].valid);
 if(r->phase==HHT_PHASE_PROGRAM) {
  assert(value==hht_program_value((unsigned)index) && r->program_store[index].attempted && !r->program_store[index].returned);
 } else {
  assert(r->phase==HHT_PHASE_RESTORE && value==t->original[index]);
  assert(r->restore_store[index].attempted && !r->restore_store[index].returned);
 }
 ++t->write_calls;t->pending=1;t->tcm[index]=value;
 if(t->stack_damage && r->phase==HHT_PHASE_PROGRAM && index==41)t->tcm[42]^=0x100;
 if(t->restore_alias && r->phase==HHT_PHASE_RESTORE && index==41)t->tcm[0]^=1;
 return t->write_calls==t->fail_write?(t->write_warning?1:UINT64_C(0x8000000000000007)):0;
}
static GPP_U64 tcm_barrier(void *cookie) {
 struct tcm_test *t=cookie;assert(t==&test && t->pending);
 ++t->barrier_calls;t->pending=0;return t->barrier_calls==t->fail_barrier?1:0;
}
static unsigned tcm_fresh(void *cookie,struct hph_cold *cold,struct hph_clock *clock,uint32_t *address) {
 struct tcm_test *t=cookie;assert(t==&test && !t->stopped && !t->pending);++t->fresh_calls;
 if(t->fresh_calls==t->fail_fresh) {
  t->stopped=1;t->stopped_reads=t->read_calls;t->stopped_writes=t->write_calls;*address=0x3d7e000;return HPH_READ;
 }
 const struct hph_ro_io io={&t->hardware,read32,owner};
 unsigned code=hph_observe_ro(&io,cold,clock,address);
 if(t->bad_cold==t->fresh_calls)cold->values[HGB_RESET]=0;
 if(t->bad_clock==t->fresh_calls)clock->raw[1][HCW_GMU_CFG]^=0x100;
 return code;
}
static GPP_U64 tcm_commit(void *cookie,unsigned stage,const struct hht_result *r) {
 struct tcm_test *t=cookie;assert(t==&test && !t->stopped && !t->pending && r==&t->result);
 ++t->commit_calls;
 assert(r->backup_words==58 && r->cxo.valid && r->cxo.value==1 && !r->safe_to_save);
 if(stage==1) {
  assert(r->phase==HHT_PHASE_BACKUP_COMMIT && !t->write_calls && !r->backup_committed);
  for(unsigned i=0;i<58;i++)assert(r->backup[i].valid && r->backup[i].value==t->original[i]);
 } else {
  assert(stage==2 && r->phase==HHT_PHASE_FINAL_COMMIT && r->restored_words==42 && r->final_verified_words==58 && !r->tcm_retained);
  assert(!memcmp(t->tcm,t->original,sizeof(t->tcm)));
 }
 if(t->commit_power_loss==stage)t->hardware.regs[HGB_RESET]=0;
 if(t->commit_backup_change && stage==1)t->result.backup[0].value^=1;
 return t->commit_calls==t->fail_commit?(t->commit_warning?1:UINT64_C(0x8000000000000007)):0;
}
static const struct hht_io io={&test,tcm_read,tcm_write,tcm_barrier,tcm_fresh,tcm_commit,tcm_owner};
static void fresh_test(unsigned all_ones) {
 memset(&test,0,sizeof(test));test.hardware=hardware_good;test.record=record_good;
 for(unsigned i=0;i<58;i++)test.original[i]=test.tcm[i]=all_ones?UINT32_MAX:(i%3?0x80000000u^(i*0x01030507u):UINT32_MAX);
 const struct hph_ro_io ro={&test.hardware,read32,owner};uint32_t address=0;
 assert(hph_observe_ro(&ro,&test.current,&test.current_clock,&address)==0);
 assert(hph_recheck(&test.record,&test.current,&test.current_clock)==0);
}
static unsigned execute(void) {return hgd_handoff_tcm_held_reset(&io,&test.record,&test.current,&test.current_clock,&test.result);}
static void invariant(void) {
 const struct hht_result *r=&test.result;
 assert(test.barrier_calls==test.write_calls && !test.pending && r->retained);
 assert(r->writes==test.write_calls && r->barriers==test.barrier_calls && r->reads==test.read_calls);
 assert(r->backup_words<=58 && r->programmed_words<=42 && r->restored_words<=42 && r->final_verified_words<=58);
 for(unsigned i=42;i<58;i++)assert(!r->program_store[0].attempted || test.stack_damage || test.tcm[i]==test.original[i]);
 if(r->qualification_lost)assert(!r->safe_to_save && !r->complete);
 if(test.stopped)assert(test.read_calls==test.stopped_reads && test.write_calls==test.stopped_writes);
 if(r->safe_to_save) {
  assert(r->restore_committed && r->restored_words==42 && r->final_verified_words==58 && !r->tcm_retained && !r->qualification_lost);
  assert(!memcmp(test.tcm,test.original,sizeof(test.tcm)));
 }
 if(r->code)assert(r->first.code==r->code && r->first.phase && r->first.operation && !r->complete);
 if(r->complete)assert(!r->code && r->safe_to_save && r->programmed_words==42 && r->stack_checked==16);
 cases++;
}
int main(void) {
 struct gpp_report pwr=power();hardware_good=initial();
 assert(run(&hardware_good,&pwr,&record_good)==HPH_OK);
 for(unsigned all=0;all<2;all++) {
  fresh_test(all);assert(execute()==HHT_OK);invariant();
  assert(test.result.complete && test.result.safe_to_save && test.write_calls==84 && test.read_calls==224);
  assert(test.result.guards==8 && test.result.commits==2 && test.result.backup_words==58 && test.result.restored_words==42);
  struct hht_result original=test.result;unsigned reads=test.read_calls,writes=test.write_calls;
  assert(execute()==HHT_REUSED && !memcmp(&original,&test.result,sizeof(original)) && reads==test.read_calls && writes==test.write_calls);cases++;
 }
 fresh_test(0);assert(execute()==0);unsigned total_reads=test.read_calls,total_writes=test.write_calls,total_owners=test.owner_calls;
 for(unsigned i=1;i<=total_reads;i++)for(unsigned warning=0;warning<2;warning++) {
  fresh_test(0);test.fail_read=i;test.read_warning=warning;
  assert(execute()!=0);invariant();assert(test.result.first.status==(warning?1:UINT64_C(0x8000000000000007)));
 }
 // Every actual program echo may return valid but incorrect data: retain
 // its first mismatch, restore exact originals, never mark test complete.
 for(unsigned i=62;i<=103;i++) {
  fresh_test(0);test.mismatch_read=i;assert(execute()==HHT_VERIFY);invariant();
  assert(test.result.first.phase==HHT_PHASE_PROGRAM && test.result.safe_to_save && !test.result.complete);
 }
 for(unsigned i=1;i<=total_writes;i++)for(unsigned warning=0;warning<2;warning++) {
  fresh_test(0);test.fail_write=i;test.write_warning=warning;
  assert(execute()!=0);invariant();assert(test.result.first.code==HHT_WRITE);
 }
 for(unsigned i=1;i<=total_writes;i++) {
  fresh_test(0);test.fail_barrier=i;assert(execute()!=0);invariant();
  assert(test.result.barrier_uncertain && !test.result.safe_to_save && test.write_calls==i);
 }
 for(unsigned i=1;i<=total_owners;i++) {
  fresh_test(0);test.fail_owner=i;assert(execute()!=0);invariant();
  assert(test.result.qualification_lost && test.owner_calls==i && !test.result.safe_to_save);
 }
 for(unsigned i=1;i<=8;i++)for(unsigned kind=0;kind<4;kind++) {
  fresh_test(0);if(kind==0)test.fail_fresh=i;if(kind==1)test.bad_cold=i;
  if(kind==2)test.bad_clock=i;if(kind==3)test.bad_cxo=i;
  assert(execute()!=0);invariant();assert(test.result.qualification_lost && !test.result.safe_to_save);
 }
 for(unsigned stage=1;stage<=2;stage++)for(unsigned kind=0;kind<3;kind++) {
  fresh_test(0);if(kind<2){test.fail_commit=stage;test.commit_warning=kind;}
  else test.commit_power_loss=stage;
  assert(execute()!=0);invariant();assert(!test.result.safe_to_save);
  if(stage==1)assert(!test.write_calls);else assert(test.result.restored_words==42);
 }
 fresh_test(0);test.commit_backup_change=1;assert(execute()==HHT_BACKUP);invariant();assert(!test.write_calls);
 fresh_test(0);test.stack_damage=1;assert(execute()==HHT_VERIFY);invariant();
 assert(test.result.first.index==42 && test.result.restored_words==42 && !test.result.safe_to_save);
 fresh_test(0);test.restore_alias=1;assert(execute()==HHT_VERIFY);invariant();
 assert(test.result.final_verified_words==0 && test.result.first.index==0 && !test.result.safe_to_save);
 // A failed program transport may have applied its store; a newly proven cold
 // state permits exact restoration, but never upgrades the original failure.
 fresh_test(0);test.fail_write=19;assert(execute()==HHT_WRITE);invariant();
 assert(test.result.first.phase==HHT_PHASE_PROGRAM && test.result.first.index==18 && test.result.safe_to_save && !test.result.complete);
 for(unsigned bit=0;bit<HPH_RECORD_BYTES*8u;bit++) {
  fresh_test(0);((uint8_t *)&test.record)[bit/8u]^=(uint8_t)(1u<<(bit%8u));
  assert(execute()==HHT_INPUT && !test.read_calls && !test.write_calls && !test.fresh_calls);invariant();
 }
 for(unsigned kind=0;kind<3;kind++) {
  fresh_test(0);if(kind==0)test.current.values[HGB_RESET]=0;
  if(kind==1)test.current.smr[0]=0x80000000u;
  if(kind==2)test.current_clock.raw[1][HCW_GMU_CFG]^=0x100;
  assert(execute()==HHT_INPUT && !test.read_calls && !test.write_calls && !test.fresh_calls);invariant();
 }
 for(unsigned missing=0;missing<7;missing++) {
  fresh_test(0);struct hht_io bad=io;
  if(missing==0)bad.read=0;if(missing==1)bad.write=0;if(missing==2)bad.barrier=0;
  if(missing==3)bad.fresh=0;if(missing==4)bad.commit=0;if(missing==5)bad.exclusive=0;
  assert(hgd_handoff_tcm_held_reset(missing==6?0:&bad,&test.record,&test.current,&test.current_clock,&test.result)==HHT_ARGUMENT);
  assert(!test.read_calls && !test.write_calls && !test.fresh_calls && !test.result.safe_to_save);invariant();
 }
 fresh_test(0);assert(hgd_handoff_tcm_held_reset(&io,&test.record,&test.current,&test.current_clock,0)==HHT_ARGUMENT);
 assert(!test.read_calls && !test.write_calls && !test.fresh_calls);cases++;
 assert(hht_address(0)==0x3d6d000u && hht_address(33)==0x3d6d084u && hht_address(34)==0x3d71000u &&
  hht_address(41)==0x3d7101cu && hht_address(42)==0x3d74f40u && hht_address(57)==0x3d74f7cu && !hht_address(58));
 for(uint32_t a=0x3d6c000;a<0x3d7c000;a++)assert(hht_tcm_allowed(a)==(index_for(a)>=0));
 assert(!hht_tcm_allowed(0x3d7e000) && !hht_tcm_allowed(0x3da0000) && !hht_tcm_allowed(0x3d99144));cases++;
 printf("PASS: held-reset TCM actual core %u cases; 58 backup / 42 fixed program / 42 restore / 58 final audit; no stack stores, execution, reset, SMMU or external RAM writes\n",cases);
}
'''.replace('PORTABLE_TEST',str(p/'tests/check-gpu-power-only-handoff.c'))
with tempfile.TemporaryDirectory(prefix='houji-held-tcm-') as d:
 src=Path(d)/'test.c';exe=Path(d)/'test';src.write_text(program)
 cmd=['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(p/'native/gpu/xnu'),'-I',str(p/'native/gpu/uefi'),str(src),'-o',str(exe)]
 subprocess.run(cmd,check=True);subprocess.run([str(exe)],check=True)
 # Header is usable from a strict actual XNU-style C++14 translation unit too.
 cpp=Path(d)/'header.cpp';cpp.write_text('#include "GmuHeldTcm.h"\nint main(){return hht_address(58)!=0;}\n')
 subprocess.run(['clang++','-std=c++14','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/xnu'),'-I',str(p/'native/gpu/uefi'),str(cpp),'-o',str(Path(d)/'cpp')],check=True)
 subprocess.run([str(Path(d)/'cpp')],check=True)
print('PASS: fixed code/source SHA binding and Clang C++14 header ASAN/UBSAN/-Werror (existing HCW initializer extension unchanged)')
