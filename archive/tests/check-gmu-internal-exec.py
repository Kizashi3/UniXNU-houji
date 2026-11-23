#!/usr/bin/env python3
"""Actual internal-only CM3 core + actual phase-aware RO observer; host peers only."""
from pathlib import Path
import subprocess,tempfile,hashlib,struct,re
p=Path(__file__).resolve().parents[1]
code=(p/'native/gpu/uefi/GpuGmuCode.h').read_text();words=[int(x,16) for x in re.findall(r'0x([0-9a-f]+)u',code)]
assert len(words)==34 and hashlib.sha256(struct.pack('<34I',*words)).hexdigest()=='6c1d70a8de298accbb03a8dd39cc5aaa289b741cb7a7ab3d176261d2cdb795e0'
# Bind all nine physical addresses and values to the real fixed vendor files,
# independently of the C helper used by the simulated MMIO peer.
research=Path('${HOUJI_ARTIFACTS}/native-research/sources')
reg=(research/'OnePlus453d-gen7_reg.h').read_bytes();vendor=(research/'OnePlus453d-adreno_gen7_gmu.c').read_bytes()
assert hashlib.sha256(reg).hexdigest()=='5da9d8b167c5edb1e2225878461a0b2cbaaae1d1680f2eff467c0b95a78f7a48'
assert hashlib.sha256(vendor).hexdigest()=='e2bc9fa61fb637bfae209a67f5383777677dc97f0b7763de06089a25a30cf098'
names=['GEN7_GPU_GMU_CX_GMU_CX_FAL_INTF','GEN7_GPU_GMU_CX_GMU_CX_FALNEXT_INTF','GEN7_GMU_CM3_BOOT_CONFIG','GEN7_GMU_CM3_CFG','GEN7_GMU_SYS_BUS_CONFIG','GEN7_GMU_ICACHE_CONFIG','GEN7_GMU_DCACHE_CONFIG','GEN7_GMU_GMU2HOST_INTR_MASK','GEN7_GMU_AO_HOST_INTERRUPT_MASK']
addresses=[0x3d00000+4*int(re.search(r'^#define\s+'+name+r'\s+(0x[0-9a-fA-F]+)',reg.decode(),re.M).group(1),16) for name in names]
values=[]
for name in names:
 token=re.search(r'gmu_core_regwrite\(device,\s*'+name+r',\s*(0x[0-9a-fA-F]+|[0-9]+|UINT_MAX)\s*\)',vendor.decode()).group(1)
 values.append(0xffffffff if token=='UINT_MAX' else int(token,0))
header=(p/'native/gpu/xnu/GmuInternalExec.h').read_text()
actual_a=re.search(r'gie_control_address.*?a\[\]=\{([^}]+)',header,re.S).group(1)
actual_v=re.search(r'gie_control_value.*?v\[\]=\{([^}]+)',header,re.S).group(1)
assert [int(x.strip().removesuffix('u'),0) for x in actual_a.split(',')]==addresses
assert [int(x.strip().removesuffix('u'),0) for x in actual_v.split(',')]==values
program=r'''
#define main handoff_fixture_main
#include "FIXTURE"
#undef main
#include "GmuInternalExec.h"
struct exec_test {
 struct mock bus;struct hph_record record;struct hph_cold current;struct hph_clock current_clock;
 struct gie_result result;uint32_t tcm[58],original[58],controls[9],control_original[9];
 unsigned reads,writes,barriers,owners,freshes,commits,delays,pending,complete_after;
 unsigned reset_writes,release_writes,stopped,stopped_reads,stopped_writes;
 unsigned fail_read,fail_write,fail_barrier,fail_owner,fail_fresh,fail_commit,fail_delay,warning;
 unsigned bad_clock,bad_cold,bad_cxo,timeout,reset_timeout,fault,bad_mailbox,bad_tail;
 unsigned prepared_tcm_damage,prepared_control_damage,backup_damage,control_backup_damage;
 unsigned clock_loss_running_delay,clock_loss_reset_delay,release_not_applied,reset_not_applied;
 unsigned mismatch_read,stack_damage,restore_alias,mutate_record,clock_loss_on_resetwrite;
 unsigned control_order[9],control_calls,bad_status,running_marker;
};
static struct exec_test t;
static struct mock good_bus;static struct hph_record good_record;
static int index_tcm(uint32_t a){for(unsigned i=0;i<58;i++)if(gie_address(i)==a)return (int)i;return -1;}
static int xowner(void*c){
 struct exec_test*x=c;assert(x==&t);
 if(++x->owners==x->fail_owner){x->stopped=1;x->stopped_reads=x->reads;x->stopped_writes=x->writes;return 1;}return 0;
}
static uint64_t xread(void*c,uint32_t a,uint32_t*v){
 struct exec_test*x=c;struct gie_result*r=&x->result;assert(x==&t && v && !x->pending && !x->stopped);
 int ti=index_tcm(a),ci=gie_control_index(a);assert(ti>=0 || ci>=0 || a==0x3d99144u || a==0x3d7e000u);
 ++x->reads;
 if(a==0x3d99144u)*v=x->bad_cxo==x->freshes?0x80000001u:1;
 else if(a==0x3d7e000u){
  if(r->phase==GIE_PHASE_RESET_POLL && x->reset_timeout)*v=0;
  else *v=x->bus.regs[HGB_RESET];
 } else if(ci>=0)*v=x->controls[ci];
 else {
  if(r->phase==GIE_PHASE_POLL && ti==34){
   assert(x->release_writes==1 && x->bus.regs[HGB_RESET]==0 && r->possible_execution);
   if(x->running_marker && r->polls<x->complete_after)x->tcm[34]=0xa7500001u;
   if(!x->timeout && r->polls>=x->complete_after){
    x->tcm[34]=x->fault?0xa750deadu:0xa7500002u;x->tcm[35]=x->fault==1?0:0x750c0de0u;
    x->tcm[36]=x->fault==1?0:128;if(x->bad_mailbox==1)x->tcm[35]^=1;if(x->bad_mailbox==2)x->tcm[36]^=1;if(x->bad_tail)x->tcm[34+x->bad_tail]=1;if(x->bad_status)x->tcm[34]=0x12345678u;
    if(x->fault || x->stack_damage)for(unsigned j=50;j<58;j++)x->tcm[j]=0xe0000000u+j;
   }
  }
  *v=x->tcm[ti];
 }
 if(x->reads==x->mismatch_read)*v^=1;
 return x->reads==x->fail_read?(x->warning?1:UINT64_C(0x8000000000000007)):0;
}
static uint64_t xwrite(void*c,uint32_t a,uint32_t v){
 struct exec_test*x=c;struct gie_result*r=&x->result;
 assert(x==&t && !x->stopped && !x->pending && r->backup_committed && gie_backup_intact(r) && gie_store_allowed(r,a,v));
 int ti=index_tcm(a),ci=gie_control_index(a);++x->writes;x->pending=1;
 if(a==0x3d7e000u){
  if(!v){assert(r->phase==GIE_PHASE_RELEASE && r->possible_execution && r->prepared_committed && !x->release_writes++);if(!x->release_not_applied)x->bus.regs[HGB_RESET]=0;}
  else {assert(v==1 && r->phase==GIE_PHASE_RESET && r->guard_reset==2 && r->possible_execution && !x->reset_writes++);if(!x->reset_not_applied)x->bus.regs[HGB_RESET]=1;if(x->clock_loss_on_resetwrite)x->bus.clock[HCW_GMU_CFG]^=0x100;}
 }else if(ti>=0){
  assert(x->bus.regs[HGB_RESET]==1);
  if(r->phase==GIE_PHASE_PROGRAM)assert(ti<42 && v==gie_program_value((unsigned)ti));
  else assert(r->phase==GIE_PHASE_RESTORE_TCM && v==x->original[ti]);
  x->tcm[ti]=v;
  if(x->restore_alias && r->phase==GIE_PHASE_RESTORE_TCM && ti==57)x->tcm[0]^=1;
 }else{
  assert(ci>=0 && x->bus.regs[HGB_RESET]==1);
  if(r->phase==GIE_PHASE_CONTROL){assert(v==gie_control_value((unsigned)ci) && x->control_calls<9);x->control_order[x->control_calls++]=(unsigned)ci;}
  else assert(r->phase==GIE_PHASE_RESTORE_CONTROL && ci<7 && v==x->control_original[ci]);
  x->controls[ci]=ci==8 && r->phase==GIE_PHASE_CONTROL?v&0x7fu:v;
 }
 return x->writes==x->fail_write?(x->warning?1:UINT64_C(0x8000000000000007)):0;
}
static uint64_t xbarrier(void*c){struct exec_test*x=c;assert(x==&t && x->pending);x->pending=0;return ++x->barriers==x->fail_barrier?1:0;}
static uint64_t xdelay(void*c,unsigned us){
 struct exec_test*x=c;assert(x==&t && us==10 && !x->pending && !x->stopped);
 assert(x->result.phase==GIE_PHASE_POLL || x->result.phase==GIE_PHASE_RESET_POLL);++x->delays;
 if((x->clock_loss_running_delay && x->result.phase==GIE_PHASE_POLL) || (x->clock_loss_reset_delay && x->result.phase==GIE_PHASE_RESET_POLL))x->bus.clock[HCW_GMU_CFG]^=0x100;
 return x->delays==x->fail_delay?1:0;
}
static unsigned xfresh(void*c,unsigned reset,struct hph_cold*s,struct hph_clock*clock,uint32_t*failed){
 struct exec_test*x=c;assert(x==&t && !x->stopped && !x->pending);++x->freshes;
 if(reset==0)assert(x->result.phase==GIE_PHASE_POLL && x->result.possible_execution);
 if(reset==2)assert((x->result.phase==GIE_PHASE_RESET || x->result.phase==GIE_PHASE_RESET_POLL) && x->result.possible_execution);
 if(x->freshes==x->fail_fresh){x->stopped=1;x->stopped_reads=x->reads;x->stopped_writes=x->writes;*failed=0x3d99108u;return HPH_READ;}
 const struct hph_ro_io ro={&x->bus,read32,owner};unsigned code=gie_observe_ro(&ro,reset,s,clock,failed);
 if(x->freshes==x->bad_clock)clock->raw[1][HCW_GMU_CFG]^=0x100;
 if(x->freshes==x->bad_cold)s->smr[0]=0x80000000u;
 return code;
}
static uint64_t xcommit(void*c,unsigned stage,const struct gie_result*r){
 struct exec_test*x=c;assert(x==&t && r==&x->result && !x->stopped && !x->pending && r->cxo.valid && x->bus.regs[HGB_RESET]==1);
 ++x->commits;assert(stage>=1 && stage<=3 && !r->safe_to_save && gie_backup_intact(&x->result));
 if(stage==1){assert(r->phase==GIE_PHASE_BACKUP_COMMIT && !x->writes);}
 if(stage==2){assert(r->phase==GIE_PHASE_PREPARED_COMMIT && r->programmed_words==42 && r->control_programmed==9 && !r->possible_execution);}
 if(stage==3){assert(r->phase==GIE_PHASE_FINAL_COMMIT && r->restored_words==58 && r->control_restored==7 && r->final_verified_words==58 && !r->tcm_retained);assert(!memcmp(x->tcm,x->original,sizeof(x->tcm)));}
 if(stage==2 && x->prepared_tcm_damage)x->tcm[5]^=1;
 if(stage==2 && x->prepared_control_damage)x->controls[3]^=1;
 if(stage==1 && x->backup_damage)x->result.backup[2].value^=1;
 if(stage==1 && x->control_backup_damage)x->result.control_backup[2].value^=1;
 if(x->mutate_record==stage)x->record.crc32^=1;
 return x->commits==x->fail_commit?(x->warning?1:UINT64_C(0x8000000000000007)):0;
}
static const struct gie_io io={&t,xread,xwrite,xbarrier,xdelay,xfresh,xcommit,xowner};
static void init(unsigned allones){
 memset(&t,0,sizeof(t));t.bus=good_bus;t.record=good_record;t.complete_after=1;
 for(unsigned i=0;i<58;i++)t.tcm[i]=t.original[i]=allones?UINT32_MAX:(i%3?0xa1b20000u+i*0x01020305u:UINT32_MAX);
 for(unsigned i=0;i<9;i++)t.controls[i]=t.control_original[i]=allones?UINT32_MAX:0x76540000u+i;
 const struct hph_ro_io ro={&t.bus,read32,owner};uint32_t a=0;assert(gie_observe_ro(&ro,1,&t.current,&t.current_clock,&a)==0);
 assert(hph_recheck(&t.record,&t.current,&t.current_clock)==0);
}
static unsigned run_exec(void){return gie_run(&io,&t.record,&t.current,&t.current_clock,&t.result);}
static void check(void){
 const struct gie_result*r=&t.result;
 assert(t.writes==t.barriers && !t.pending && r->writes==t.writes && r->barriers==t.barriers && r->reads==t.reads);
 assert(t.release_writes<=1 && t.reset_writes<=1 && r->polls<=1000 && r->reset_polls<=1000);
 if(t.stopped)assert(t.reads==t.stopped_reads && t.writes==t.stopped_writes);
 if(r->qualification_lost)assert(!r->safe_to_save && !r->complete);
 if(r->safe_to_save){assert(r->reset_held && r->restore_committed && r->restored_words==58 && r->control_restored==7 && r->final_verified_words==58 && !r->qualification_lost && !r->tcm_retained);assert(!memcmp(t.tcm,t.original,sizeof(t.tcm)));for(unsigned i=0;i<7;i++)assert(t.controls[i]==t.control_original[i]);}
 if(r->code)assert(r->first.code==r->code && r->first.phase && r->first.operation && !r->complete);
 if(r->complete)assert(!r->code && r->safe_to_save && r->irq_retained==3 && r->mailbox[0].valid && r->mailbox[0].value==0xa7500002u && r->mailbox[1].value==0x750c0de0u && r->mailbox[2].value==128);
 cases++;
}
int main(void){
 struct gpp_report pwr=power();good_bus=initial();assert(run(&good_bus,&pwr,&good_record)==HPH_OK);
 for(unsigned all=0;all<2;all++){init(all);assert(run_exec()==0);check();assert(t.result.complete && t.release_writes==1 && t.reset_writes==1 && t.writes==118 && t.result.polls==1 && t.result.reset_polls==1 && t.commits==3 && t.result.guards==15 && t.result.reads==343);
  assert(t.control_calls==9 && t.control_order[0]==1 && t.control_order[1]==0);for(unsigned j=2;j<9;j++)assert(t.control_order[j]==j);
  struct gie_result old=t.result;unsigned calls=t.reads+t.writes;assert(run_exec()==GIE_REUSED && !memcmp(&old,&t.result,sizeof(old)) && calls==t.reads+t.writes);cases++;}
 init(0);assert(run_exec()==0);assert(gie_complete_proof(&t.result));
 {
  const struct gie_result good=t.result;
  const struct gie_access *groups[]={good.backup,good.control_backup,good.program_store,good.program_barrier,good.program_verify,
   good.prepared_tcm_verify,good.prepared_control_verify,good.control_store,good.control_barrier,good.control_verify,
   &good.release_store,&good.release_barrier,&good.release_verify,&good.reset_store,&good.reset_barrier,
   good.mailbox_poll,good.reset_poll,good.mailbox,good.stack_after,good.restore_store,good.restore_barrier,good.restore_verify,
   good.control_restore_store,good.control_restore_barrier,good.control_restore_verify,good.final_verify,good.control_final_verify};
  const unsigned sizes[]={58,9,42,42,42,42,9,9,9,9,1,1,1,1,1,1,1,8,16,58,58,58,7,7,7,58,9};
  for(unsigned g=0;g<sizeof(sizes)/sizeof(sizes[0]);g++)for(unsigned i=0;i<sizes[g];i++)for(unsigned flag=0;flag<4;flag++){
   struct gie_result bad=good;unsigned long off=(unsigned long)((const unsigned char*)&groups[g][i]-(const unsigned char*)&good);
   struct gie_access *a=(struct gie_access*)((unsigned char*)&bad+off);
   if(flag==0)a->attempted=0;if(flag==1)a->returned=0;if(flag==2)a->valid=0;if(flag==3)a->status=1;
   assert(!gie_complete_proof(&bad));cases++;
  }
 }
 for(unsigned missing=0;missing<11;missing++){
  init(0);struct gie_io bad=io;
  if(missing==0)bad.read=0;if(missing==1)bad.write=0;if(missing==2)bad.barrier=0;if(missing==3)bad.delay=0;
  if(missing==4)bad.fresh=0;if(missing==5)bad.commit=0;if(missing==6)bad.exclusive=0;
  assert(gie_run(missing==7?0:&bad,missing==8?0:&t.record,missing==9?0:&t.current,missing==10?0:&t.current_clock,&t.result)==GIE_ARGUMENT);
  assert(!t.reads && !t.writes && !t.freshes && !t.result.safe_to_save);check();
 }
 init(0);assert(gie_run(&io,&t.record,&t.current,&t.current_clock,0)==GIE_ARGUMENT && !t.reads && !t.writes);cases++;
 init(0);assert(run_exec()==0);unsigned reads=t.reads,writes=t.writes,owners=t.owners,freshes=t.freshes;
 for(unsigned i=1;i<=reads;i++)for(unsigned warn=0;warn<2;warn++){init(0);t.fail_read=i;t.warning=warn;assert(run_exec()!=0);check();}
 for(unsigned i=1;i<=writes;i++)for(unsigned warn=0;warn<2;warn++){init(0);t.fail_write=i;t.warning=warn;assert(run_exec()!=0);check();assert(t.result.first.code==GIE_WRITE);}
 for(unsigned i=1;i<=writes;i++){init(0);t.fail_barrier=i;assert(run_exec()!=0);check();assert(t.result.barrier_uncertain && !t.result.safe_to_save && t.writes==i);}
 for(unsigned i=1;i<=owners;i++){init(0);t.fail_owner=i;assert(run_exec()!=0);check();assert(t.result.qualification_lost && !t.result.safe_to_save && t.owners==i);}
 for(unsigned i=1;i<=freshes;i++)for(unsigned kind=0;kind<4;kind++){init(0);if(kind==0)t.fail_fresh=i;if(kind==1)t.bad_clock=i;if(kind==2)t.bad_cold=i;if(kind==3)t.bad_cxo=i;assert(run_exec()!=0);check();assert(t.result.qualification_lost && !t.result.safe_to_save);}
 for(unsigned i=1;i<=3;i++)for(unsigned warn=0;warn<2;warn++){init(0);t.fail_commit=i;t.warning=warn;assert(run_exec()!=0);check();if(i<3)assert(!t.release_writes);}
 init(0);t.complete_after=7;assert(run_exec()==0);check();assert(t.result.polls==7 && t.delays==6);
 init(0);t.timeout=1;assert(run_exec()==GIE_TIMEOUT);check();assert(t.result.polls==1000 && t.delays==999 && t.reset_writes==1 && t.result.safe_to_save);
 init(0);t.fault=1;assert(run_exec()==GIE_FAULT);check();assert(t.result.stack_changed_mask==0xff00 && t.result.safe_to_save);
 init(0);t.fault=2;assert(run_exec()==GIE_FAULT);check();assert(t.result.mailbox[1].valid && t.result.mailbox[1].value==0x750c0de0u && t.result.mailbox[2].value==128 && t.result.safe_to_save);
 init(0);t.stack_damage=1;assert(run_exec()==GIE_VERIFY);check();assert(t.result.stack_changed_mask==0xff00 && t.result.safe_to_save && !t.result.complete);
 init(0);t.bad_mailbox=1;assert(run_exec()==GIE_VERIFY);check();assert(t.result.safe_to_save && t.result.first.index==1 && t.result.first.address==0x3d71004u && t.result.first.expected==0x750c0de0u && t.result.first.observed!=t.result.first.expected);
 for(unsigned i=3;i<8;i++){init(0);t.bad_tail=i;assert(run_exec()==GIE_VERIFY);check();assert(t.result.safe_to_save);}
 init(0);t.bad_mailbox=2;assert(run_exec()==GIE_VERIFY);check();assert(t.result.safe_to_save && t.result.first.index==2 && t.result.first.address==0x3d71008u && t.result.first.expected==128 && t.result.first.observed!=128);
 init(0);t.bad_status=1;assert(run_exec()==GIE_VERIFY);check();assert(t.result.safe_to_save);
 init(0);t.running_marker=1;t.complete_after=3;assert(run_exec()==0);check();assert(t.result.polls==3 && t.result.mailbox_poll[0].value==0xa7500001u);
 for(unsigned kind=0;kind<4;kind++){init(0);if(kind==0)t.backup_damage=1;if(kind==1)t.control_backup_damage=1;if(kind==2)t.prepared_tcm_damage=1;if(kind==3)t.prepared_control_damage=1;assert(run_exec()!=0);check();assert(!t.release_writes);}
 init(0);t.release_not_applied=1;assert(run_exec()==GIE_VERIFY);check();assert(t.reset_writes==1 && t.result.safe_to_save);
 init(0);t.reset_not_applied=t.reset_timeout=1;assert(run_exec()==GIE_TIMEOUT);check();assert(t.result.reset_polls==1000 && !t.result.reset_held && !t.result.safe_to_save && !t.result.restored_words);
 init(0);t.complete_after=4;t.clock_loss_running_delay=1;assert(run_exec()!=0);check();assert(t.result.qualification_lost && !t.reset_writes && !t.result.safe_to_save);
 init(0);t.reset_not_applied=t.reset_timeout=t.clock_loss_reset_delay=1;assert(run_exec()!=0);check();assert(t.reset_writes==1 && t.result.reset_polls==1 && t.result.qualification_lost && !t.result.safe_to_save);
 for(unsigned kind=0;kind<2;kind++){init(0);if(!kind)t.complete_after=4;else t.reset_not_applied=t.reset_timeout=1;t.fail_delay=1;assert(run_exec()==GIE_DELAY);check();if(kind)assert(!t.result.safe_to_save);}
 init(0);t.clock_loss_on_resetwrite=1;assert(run_exec()!=0);check();assert(t.reset_writes==1 && !t.result.reset_polls && t.result.qualification_lost && !t.result.safe_to_save);
 init(0);t.restore_alias=1;assert(run_exec()==GIE_VERIFY);check();assert(!t.result.safe_to_save && !t.result.restore_committed);
 for(unsigned stage=1;stage<=3;stage++){init(0);t.mutate_record=stage;assert(run_exec()!=0);check();assert(t.result.qualification_lost && !t.result.safe_to_save);}
 for(unsigned bit=0;bit<HPH_RECORD_BYTES*8u;bit++){init(0);((uint8_t*)&t.record)[bit/8]^=(uint8_t)(1u<<(bit%8));assert(run_exec()==GIE_INPUT && !t.reads && !t.writes && !t.freshes);check();}
 // The phase-aware observer accepts true reset0 only for running/recovery,
 // leaves its raw value intact, and never weakens streams/CB/clock checking.
 for(unsigned reset=0;reset<=2;reset++)for(unsigned raw=0;raw<=2;raw++){
  init(0);t.bus.regs[HGB_RESET]=raw;struct hph_cold c;struct hph_clock k;uint32_t failed=0;const struct hph_ro_io ro={&t.bus,read32,owner};
  unsigned code=gie_observe_ro(&ro,reset,&c,&k,&failed);assert((code==0)==(raw<=1 && (reset==2 || reset==raw)));
  assert(c.values[HGB_RESET]==raw);if(!code)assert(gie_recheck_running(&t.record,&c,&k,reset)==0);cases++;
 }
 for(unsigned field=0;field<5;field++){init(0);t.bus.regs[HGB_RESET]=0;if(field==0)t.bus.smr[5]=0x80000000u;if(field==1)t.bus.s2cr[5]=0;if(field==2)t.bus.banks[2]=1;if(field==3)t.bus.hfi=1;if(field==4)t.bus.regs[HGB_GXPOWER]=0;struct hph_cold c;struct hph_clock k;uint32_t a;const struct hph_ro_io ro={&t.bus,read32,owner};assert(gie_observe_ro(&ro,0,&c,&k,&a)!=0);cases++;}
 printf("PASS: internal CM3 actual core %u cases; 58+9 originals, 34 fixed code+8 zero mailbox, 9 controls, true reset0 running survey, reset1/58+7 restore, IRQ2 retained; ASAN/UBSAN/-Werror\n",cases);
}
'''.replace('FIXTURE',str(p/'tests/check-gpu-power-only-handoff.c'))
with tempfile.TemporaryDirectory(prefix='houji-internal-exec-') as d:
 src=Path(d)/'test.c';exe=Path(d)/'test';src.write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(p/'native/gpu/xnu'),'-I',str(p/'native/gpu/uefi'),str(src),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
 cpp=Path(d)/'header.cpp';cpp.write_text('#include "GmuInternalExec.h"\nint main(){return gie_control_address(9)!=0;}\n')
 subprocess.run(['clang++','-std=c++14','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/xnu'),'-I',str(p/'native/gpu/uefi'),str(cpp),'-o',str(Path(d)/'cpp')],check=True)
 subprocess.run([str(Path(d)/'cpp')],check=True)
print('PASS: fixed vendor nine-register addresses/values/source SHA, unchanged 136B payload SHA and Clang C++14 header; no firmware, DDR, DMA, SMMU or clock stores')
