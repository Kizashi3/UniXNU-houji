#!/usr/bin/env python3
"""Actual external-canary core/actual raw observer; peers never operate a device."""
from pathlib import Path
import hashlib,re,struct,subprocess,tempfile
p=Path(__file__).resolve().parents[1]
words=[int(x,16) for x in re.findall(r'0x([0-9a-f]+)u',(p/'native/gpu/uefi/GpuDmaCode.h').read_text())]
assert len(words)==44 and hashlib.sha256(struct.pack('<44I',*words)).hexdigest()=='b3a876b2a2a6aed251b824ba412fdf9e1d1f4c340a8093868e63c3bba721e076'
assert hashlib.sha256((p/'native/gpu/firmware/houji_gmu_dma_probe.S').read_bytes()).hexdigest()=='f806f67a357e58715d80ae9b561d99d67a18bebf701db4c8b3c43b045fcab774'
program=r'''
#define main handoff_fixture_main
#include "FIXTURE"
#undef main
#include "GmuExternalCanary.h"
_Alignas(16384) static unsigned char table_cpu[16384],data_cpu[16384],zero_cpu[16384];
struct test_state {
 struct mock bus;struct hph_record record;struct hph_cold current;struct hph_clock clock;
 struct gec_memory memory;struct gec_result result;
 uint32_t tcm[68],original[68],control[9],control_original[9],actlr,prr_lo,prr_hi,fsr,fsynr;
 uint64_t context[9],far;
 unsigned reads,writes,barriers,owners,freshes,commits,delays,memory_checks,publishes,finishes;
 unsigned raw_reads,raw_fail,raw_owners,raw_owner_fail;
 unsigned fail_read,fail_write,fail_barrier,fail_owner,fail_fresh,fail_commit,fail_delay,fail_memory,fail_publish,fail_finish;
 unsigned warning,timeout,partial_dma,reset_timeout,completion_after,release_writes,reset_writes,enable_writes,route_writes;
 unsigned bad_clock,bad_route,bad_root,bad_cxo,bad_fsr,bad_far,bad_fsynr,bad_hfi,bad_bank;
 unsigned bad_mailbox,bad_tail,fault,expected_fault,frame_damage,frame_flags;uint32_t frame_r12,frame_lr;
 unsigned stack_damage,data_damage,padding_damage,zero_damage;
 unsigned commit_table_damage,commit_program_damage,commit_backup_damage,commit_clock_loss,commit_control_damage;
 unsigned pending,stopped,stop_reads,stop_writes,release_noapply,reset_noapply,tlb_timeout;
 unsigned write_not_applied,restore_alias,readonly_guards;
};
static struct test_state t;
static struct mock good_bus;static struct hph_record good_record;
static int field_index(uint32_t a,unsigned *high){
 *high=0;for(unsigned i=0;i<9;i++){
  if(a==gec_field_address(i))return (int)i;
  if((i==5 || i==6) && a==gec_field_address(i)+4){*high=1;return (int)i;}
 }return -1;
}
static int xowner(void*c){struct test_state*x=c;assert(x==&t);
 if(++x->owners==x->fail_owner){x->stopped=1;x->stop_reads=x->reads;x->stop_writes=x->writes;return 1;}return 0;}
static int raw_owner(void*c){struct test_state*x=c;assert(x==&t);return ++x->raw_owners==x->raw_owner_fail;}
static uint64_t raw_read(void*c,uint32_t a,uint32_t*v){
 struct test_state*x=c;assert(x==&t && v && !x->pending);if(++x->raw_reads==x->raw_fail)return 1;
 int reg=reg_index(a),ci=clock_index(a);unsigned high=0;int fi=field_index(a,&high);
 if(reg>=0)*v=x->bus.regs[reg];
 else if(ci>=0)*v=x->bus.clock[ci];
 else if(a==0x3d7e600u)*v=x->bus.hfi;
 else if(a==0x3d99144u)*v=x->bad_cxo==x->freshes?0x80000001u:1;
 else if(a>=0x3da0800u && a<0x3da0860u)*v=x->bus.smr[(a-0x3da0800)/4];
 else if(a>=0x3da0c00u && a<0x3da0c60u)*v=x->bus.s2cr[(a-0x3da0c00)/4];
 else if(a>=0x3dc0000u && a<0x3dd6000u && !(a&4095))*v=x->bus.banks[(a-0x3dc0000)/4096];
 else if(fi>=0)*v=(uint32_t)(x->context[fi]>>(high?32:0));
 else if(a==HGP_CB(4))*v=x->actlr;
 else if(a==0x3da6008u)*v=x->prr_lo;
 else if(a==0x3da600cu)*v=x->prr_hi;
 else if(a==HGP_CB(0x58))*v=x->fsr;
 else if(a==HGP_CB(0x60))*v=(uint32_t)x->far;
 else if(a==HGP_CB(0x64))*v=(uint32_t)(x->far>>32);
 else if(a==HGP_CB(0x68))*v=x->fsynr;
 else {fprintf(stderr,"bad raw %x\n",a);assert(0);}return 0;
}
static void execute_peer(void){
 struct gec_result*r=&t.result;if(t.partial_dma){((uint32_t*)data_cpu)[2]=0xa750cafeu;return;}
 if(t.timeout || r->polls<t.completion_after)return;
 uint32_t*d=(uint32_t*)data_cpu;d[2]=t.data_damage?0xdeadbeefu:0xa750cafeu;
 t.tcm[44]=t.fault?0xa750deadu:0xa7500003u;t.tcm[45]=0x7504cafe;t.tcm[46]=0x86500071;t.tcm[47]=0xa750cafe;t.tcm[48]=0;
 t.tcm[49]=0;t.tcm[50]=t.fault?0x102:0;t.tcm[51]=0;
 if(t.bad_mailbox)t.tcm[44+t.bad_mailbox]^=1;if(t.bad_tail)t.tcm[44+t.bad_tail]=1;
 t.fsr=t.bad_fsr?4:2;t.far=t.bad_far?0x60003000u:0x60002000u;t.fsynr=t.bad_fsynr?16:0;
 if(t.stack_damage || t.fault)for(unsigned i=60;i<68;i++)t.tcm[i]=0xe0000000u+i;
 if(t.expected_fault){
  t.tcm[44]=0xa750dead;t.tcm[50]=0x8200;t.tcm[51]=0x60002000;
  const uint32_t frame[]={0x10004000,0xa7500001,0x60002000,0xa750cafe,t.frame_r12,t.frame_lr,0x6e,0x01000000u|t.frame_flags};
  for(unsigned i=0;i<8;i++)t.tcm[60+i]=frame[i];
  if(t.frame_damage){unsigned i=t.frame_damage-1;t.tcm[52+i]^=1;}
 }
 if(t.padding_damage)data_cpu[4096]^=1;if(t.zero_damage)zero_cpu[0]^=1;
}
static uint64_t xread32(void*c,uint32_t a,uint32_t*v){
 struct test_state*x=c;struct gec_result*r=&x->result;assert(x==&t && !x->stopped && !x->pending && r->load_count);
 const struct gec_load*l=&r->loads[r->load_count-1];assert(l->address==a && !l->wide && l->access.attempted && !l->access.returned);
 ++x->reads;int ti=gec_tcm_index(a),ci=gie_control_index(a);unsigned high=0;int fi=field_index(a,&high);
 if(ti>=0){if(r->phase==GEC_PHASE_POLL && a==0x3d71000u)execute_peer();*v=x->tcm[ti];}
 else if(ci>=0)*v=x->control[ci];else if(fi>=0){assert(!high);*v=(uint32_t)x->context[fi];}
 else if(a==0x3d7e000u)*v=r->phase==GEC_PHASE_RESET_POLL && x->reset_timeout?0:x->bus.regs[HGB_RESET];
 else if(a==HGP_CB(0x7f4))*v=x->tlb_timeout?1:0;
 else {assert(raw_read(c,a,v)==0);}
 return x->reads==x->fail_read?(x->warning?1:UINT64_C(0x8000000000000007)):0;
}
static uint64_t xread64(void*c,uint32_t a,uint64_t*v){
 struct test_state*x=c;struct gec_result*r=&x->result;assert(x==&t && !x->stopped && !x->pending && r->load_count);
 const struct gec_load*l=&r->loads[r->load_count-1];assert(l->address==a && l->wide && l->access.attempted && !l->access.returned);
 ++x->reads;unsigned hi=0;int fi=field_index(a,&hi);assert(!hi);if(fi==5 || fi==6)*v=x->context[fi];else {assert(a==HGP_CB(0x60));*v=x->far;}
 return x->reads==x->fail_read?(x->warning?1:UINT64_C(0x8000000000000007)):0;
}
static uint64_t xwrite(void*c,uint32_t a,uint64_t v,unsigned wide){
 struct test_state*x=c;struct gec_result*r=&x->result;assert(x==&t && !x->stopped && !x->pending && r->event_count && gec_store_allowed(&x->memory,r,a,v,wide));
 const struct gec_event*e=&r->events[r->event_count-1];assert(e->address==a && e->wide==wide && e->wanted==v && e->store.attempted && !e->store.returned);
 ++x->writes;x->pending=1;if(x->write_not_applied==x->writes)return 0;
 int ti=gec_tcm_index(a),ci=gie_control_index(a);unsigned hi=0;int fi=field_index(a,&hi);assert(!hi);
 if(ti>=0){assert(x->bus.regs[HGB_RESET]==1);x->tcm[ti]=(uint32_t)v;if(x->restore_alias && r->phase==GEC_PHASE_RESTORE_TCM && ti==67)x->tcm[0]^=1;}
 else if(ci>=0)x->control[ci]=ci==8 && r->phase==GEC_PHASE_CONTROL?(uint32_t)v&127:(uint32_t)v;
 else if(fi>=0){x->context[fi]=v;if(fi==0){x->bus.banks[2]=(uint32_t)v;if(r->phase==GEC_PHASE_ENABLE)x->enable_writes++;}}
 else if(a==0x3d7e000u){
  if(v==0){assert(r->possible_execution && !x->release_writes++);if(!x->release_noapply)x->bus.regs[HGB_RESET]=0;}
  else {assert(v==1 && r->phase==GEC_PHASE_RESET && r->guard_reset==2 && !x->reset_writes++);if(!x->reset_noapply)x->bus.regs[HGB_RESET]=1;}
 }else if(a==0x3da0800u){x->bus.smr[0]=(uint32_t)v;if(v)x->route_writes++;}
 else if(a==0x3da0c00u)x->bus.s2cr[0]=(uint32_t)v;
 else if(a==HGP_CB(4))x->actlr=(uint32_t)v;
 else if(a==0x3da6008u)x->prr_lo=(uint32_t)v;
 else if(a==0x3da600cu)x->prr_hi=(uint32_t)v;
 else if(a==HGP_CB(0x58)){assert(v==2 && r->isolated && r->negative);x->fsr&=~2u;}
 else assert(a==HGP_CB(0x618) || a==HGP_CB(0x7f0));
 return x->writes==x->fail_write?(x->warning?1:UINT64_C(0x8000000000000007)):0;
}
static uint64_t xwrite32(void*c,uint32_t a,uint32_t v){return xwrite(c,a,v,0);}
static uint64_t xwrite64(void*c,uint32_t a,uint64_t v){return xwrite(c,a,v,1);}
static uint64_t xbarrier(void*c){struct test_state*x=c;assert(x==&t && x->pending);x->pending=0;return ++x->barriers==x->fail_barrier?1:0;}
static uint64_t xdelay(void*c,unsigned us){struct test_state*x=c;assert(x==&t && us==10 && !x->stopped && !x->pending);return ++x->delays==x->fail_delay?1:0;}
static unsigned xfresh(void*c,unsigned reset,struct gec_snapshot*s,uint32_t*failed){
 struct test_state*x=c;assert(x==&t && !x->stopped && !x->pending);++x->freshes;
 if(x->freshes==x->fail_fresh){*failed=0x171004u;x->stopped=1;x->stop_reads=x->reads;x->stop_writes=x->writes;return HPH_READ;}
 if(x->freshes==x->bad_clock)x->bus.clock[HCW_GMU_CFG]^=0x100;
 if(x->freshes==x->bad_route)x->bus.smr[1]=0x80000006u;if(x->freshes==x->bad_hfi)x->bus.hfi=1;if(x->freshes==x->bad_bank)x->bus.banks[1]=1;
 if(x->freshes==x->bad_root)x->context[5]^=4096;
 const struct hph_ro_io ro={x,raw_read,raw_owner};return gec_observe_ro(&ro,reset,s,failed);
}
static uint64_t xcommit(void*c,unsigned stage,const struct gec_result*r){
 struct test_state*x=c;assert(x==&t && r==&x->result && !x->pending && !x->stopped && stage>=1 && stage<=3);
 assert(x->bus.regs[HGB_RESET]==1 && !x->bus.smr[0] && x->bus.s2cr[0]==0x20000 && (stage==1?!(x->bus.banks[2]&0x41u):!x->bus.banks[2]) && !r->safe_to_save && gec_backup_intact(&x->result));
 if(stage==1)assert(!x->writes && r->phase==GEC_PHASE_BACKUP_COMMIT);
 if(stage==2)assert(r->phase==GEC_PHASE_PREPARED_COMMIT && r->programmed_words==52 && r->control_programmed==9 && !r->possible_execution);
 if(stage==3)assert((!r->possible_execution || (r->positive && r->negative)) && r->phase==GEC_PHASE_FINAL_COMMIT && r->context_retired && r->isolated && r->restored_words==68 && r->final_verified_words==68);
 ++x->commits;if(x->commit_table_damage==stage)((uint64_t*)table_cpu)[0]^=1;
 if(x->commit_program_damage==stage)x->tcm[0]^=1;if(x->commit_control_damage==stage)x->control[0]^=1;
 if(x->commit_backup_damage==stage)x->result.backup[0].value^=1;if(x->commit_clock_loss==stage)x->bus.clock[HCW_GMU_CFG]^=0x100;
 return x->commits==x->fail_commit?(x->warning?1:UINT64_C(0x8000000000000007)):0;
}
static uint64_t xmemory(void*c,unsigned stage,const struct gec_memory*m){
 struct test_state*x=c;assert(x==&t && m==&x->memory && stage<=2 && !x->pending && !x->stopped);
 if(stage==2)assert(x->result.context_retired && x->result.isolated && x->bus.regs[HGB_RESET]==1 && !x->bus.smr[0] && !x->bus.banks[2]);
 return ++x->memory_checks==x->fail_memory?1:0;
}
static uint64_t xpublish(void*c,const struct gec_memory*m){struct test_state*x=c;assert(x==&t && m==&x->memory && !x->writes && !x->pending);return ++x->publishes==x->fail_publish?1:0;}
static uint64_t xfinish(void*c,const struct gec_memory*m,struct gec_cpu_result*r){
 struct test_state*x=c;assert(x==&t && m==&x->memory && x->result.context_retired && x->result.isolated && !x->pending && !x->stopped);
 assert(!x->bus.smr[0] && x->bus.s2cr[0]==0x20000 && !x->bus.banks[2] && !x->context[5] && !x->context[6] && x->actlr==3 && !x->prr_lo && !x->prr_hi);
 if(++x->finishes==x->fail_finish)return 1;
 r->invalidated=1;uint32_t*d=(uint32_t*)data_cpu;r->observed=d[2];
 for(unsigned i=0;i<1024;i++){if(d[i]!=(i==0?0x7504cafeu:i==1?0x86500071u:i==2?0xa750cafeu:0u))return 1;r->checked_words++;}
 for(size_t i=4096;i<m->data_owned_bytes;i++)if(data_cpu[i])return 1;
 for(size_t i=12288;i<m->table_owned_bytes;i++)if(table_cpu[i])return 1;
 for(size_t i=0;i<m->zero_owned_bytes;i++)if(zero_cpu[i])return 1;
 r->padding_checked=1;r->verified=1;d[2]=0;r->restored=1;return 0;
}
static const struct gec_io io={&t,xread32,xread64,xwrite32,xwrite64,xbarrier,xdelay,xfresh,xcommit,xowner,xmemory,xpublish,xfinish};
static void init(unsigned cpu,unsigned ones){
 memset(&t,0,sizeof(t));memset(table_cpu,0,sizeof(table_cpu));memset(data_cpu,0,sizeof(data_cpu));memset(zero_cpu,0,sizeof(zero_cpu));
 t.bus=good_bus;t.record=good_record;t.completion_after=1;t.actlr=3;
 for(unsigned i=0;i<68;i++)t.original[i]=t.tcm[i]=ones?UINT32_MAX:0x80000000u+i*0x12345u;
 for(unsigned i=0;i<9;i++)t.control_original[i]=t.control[i]=ones?UINT32_MAX:0x12340000u+i;
 struct gec_memory*m=&t.memory;m->cpu_page_bytes=cpu;m->table_owned_bytes=((12288+cpu-1)/cpu)*cpu;m->data_owned_bytes=m->zero_owned_bytes=cpu;
 m->owned.tables=table_cpu;m->owned.data=data_cpu;m->owned.table_physical=0x90000000;m->owned.data_physical=0x91000000;m->zero_cpu=zero_cpu;m->zero_physical=0x92000000;
 m->owned.config=(ArmSmmu4KConfig){32,36,m->owned.table_physical,1};m->owned.range=(ArmSmmu4KRange){0x60000000,m->owned.data_physical,4096,ArmSmmu4KRead|ArmSmmu4KWrite,1,3};
 assert(ArmSmmu4KBuild(&m->owned.config,&m->owned.range,1,(uint64_t*)table_cpu,3,&m->owned.built)==0);
 ((uint32_t*)data_cpu)[0]=0x7504cafe;((uint32_t*)data_cpu)[1]=0x86500071;
 const struct hph_ro_io ro={&t.bus,read32,owner};uint32_t a=0;assert(hph_observe_ro(&ro,&t.current,&t.clock,&a)==0);
}
static unsigned run_exec(void){return gec_run(&io,&t.record,&t.current,&t.clock,&t.memory,&t.result);}
static void high_pa(void){
 struct gec_memory*m=&t.memory;m->owned.table_physical=UINT64_C(0x8c5d00000);m->owned.data_physical=UINT64_C(0x8c6d00000);m->zero_physical=UINT64_C(0x8c7d00000);
 m->owned.config.table_physical=m->owned.table_physical;m->owned.range.physical=m->owned.data_physical;
 assert(ArmSmmu4KBuild(&m->owned.config,&m->owned.range,1,(uint64_t*)table_cpu,3,&m->owned.built)==0);
}
static void check(void){
 struct gec_result*r=&t.result;assert(t.writes==t.barriers && !t.pending && r->reads==t.reads && r->writes==t.writes && r->barriers==t.barriers);
 assert(t.release_writes<=1 && t.reset_writes<=1 && t.enable_writes<=1 && t.route_writes<=1 && r->polls<=1000 && r->reset_polls<=1000);
 if(t.stopped)assert(t.reads==t.stop_reads && t.writes==t.stop_writes);
 if(r->qualification_lost || r->barrier_uncertain)assert(!r->safe_to_save && !r->complete);
 if(r->code)assert(!r->complete && r->first.code==r->code && r->first.phase && r->first.operation);
 if(t.finishes)assert(r->isolated && r->context_retired && !r->enabled && !r->stream_attached && !r->route_prepared && r->reset_held);
 if(r->safe_to_save){assert(r->restore_committed && r->context_retired && r->isolated && r->restored_words==68 && r->final_verified_words==68 && !r->tcm_retained);assert(!memcmp(t.tcm,t.original,sizeof(t.tcm)));}
 if(r->complete)assert(!r->code && gec_complete_proof(r) && r->safe_to_save && r->positive && r->negative && r->irq_retained==3 && t.finishes==1);
 cases++;
}
int main(void){
 struct gpp_report power_good=power();good_bus=initial();assert(run(&good_bus,&power_good,&good_record)==0);
 for(unsigned cpu=4096;cpu<=16384;cpu*=4)for(unsigned ones=0;ones<2;ones++){
  init(cpu,ones);unsigned code=run_exec();if(code)fprintf(stderr,"normal code%u phase%u a%x exp%llx got%llx\n",code,t.result.phase,t.result.first.address,(unsigned long long)t.result.first.expected,(unsigned long long)t.result.first.observed);assert(!code);check();assert(t.result.complete);
  unsigned ops=t.reads+t.writes;struct gec_result saved=t.result;assert(run_exec()==GEC_REUSED && !memcmp(&saved,&t.result,sizeof(saved)) && ops==t.reads+t.writes);cases++;
 }
 /* r144 hardware: M/CFRE clear but other SCTLR and TTBR bits are stale.
  * Capture those originals only; publish our exact known image, never replay. */
 init(16384,0);t.bus.banks[2]=0x3ff5a71eu;t.current.sctlr[2]=t.bus.banks[2];t.context[0]=t.bus.banks[2];
 t.context[5]=UINT64_C(0xff77fee6effebfeb);t.context[6]=UINT64_C(0x7d7beaedfffdeeff);
 assert(run_exec()==0);check();assert(t.result.complete && t.writes==179 && t.commits==3);
 assert(t.result.context_backup[0].value==0x3ff5a71eu && t.result.context_backup[5].value==UINT64_C(0xff77fee6effebfeb) && t.result.context_backup[6].value==UINT64_C(0x7d7beaedfffdeeff));
 assert(!t.context[0] && !t.context[5] && !t.context[6]);
 /* Once prepared, even an otherwise-disabled nonzero SCTLR is refused. */
 {struct gec_snapshot wrong=t.result.last;wrong.cold.sctlr[2]=2;wrong.context[0]=2;
  assert(!gec_state_qualified(&t.record,&t.memory,&t.result,&wrong,1));cases++;
  wrong=t.result.last;wrong.context[0]^=2;assert(!gec_state_qualified(&t.record,&t.memory,&t.result,&wrong,1));cases++;}
 for(unsigned bit=1;bit<=0x40;bit<<=6){init(16384,0);t.bus.banks[2]=0x3ff5a71eu|bit;t.context[0]=t.bus.banks[2];
  assert(run_exec()!=0);check();assert(!t.writes && !t.commits);}
 init(16384,0);high_pa();assert(run_exec()==0);check();assert(t.result.complete && t.result.context_image[5]==(UINT64_C(0x750)<<48|UINT64_C(0x8c5d00000)));
 assert((t.result.context_image[5]&UINT64_C(0x0000fffffffff000))==UINT64_C(0x8c5d00000));
 /* The actual physical table walker must recover byte PA above 4GiB. */
 {uint64_t *tables=(uint64_t*)table_cpu;uint64_t l1=tables[(0x60000000u>>30)&511],l2=tables[512+((0x60000000u>>21)&511)],leaf=tables[1024];
  assert((l1&UINT64_C(0x0000fffffffff000))==UINT64_C(0x8c5d01000) && (l2&UINT64_C(0x0000fffffffff000))==UINT64_C(0x8c5d02000));
  assert((leaf&UINT64_C(0x0000fffffffff000))==UINT64_C(0x8c6d00000) && tables[1025]==0 && tables[1026]==0);}
 init(16384,0);assert(run_exec()==0);unsigned nr=t.reads,nw=t.writes,ng=t.freshes,no=t.owners,nm=t.memory_checks;
 printf("baseline reads%u writes%u fresh%u owner%u memory%u commits%u\n",nr,nw,ng,no,nm,t.commits);
 for(unsigned i=1;i<=nr;i++)for(unsigned warn=0;warn<2;warn++){init(16384,0);t.fail_read=i;t.warning=warn;assert(run_exec()!=0);check();}
 for(unsigned i=1;i<=nw;i++)for(unsigned warn=0;warn<2;warn++){init(16384,0);t.fail_write=i;t.warning=warn;assert(run_exec()!=0);check();}
 for(unsigned i=1;i<=nw;i++){init(16384,0);t.fail_barrier=i;assert(run_exec()!=0);check();assert(t.result.barrier_uncertain && !t.result.safe_to_save && t.writes==i);}
 for(unsigned i=1;i<=no;i++){init(16384,0);t.fail_owner=i;assert(run_exec()!=0);check();assert(t.result.qualification_lost && t.owners==i);}
 for(unsigned i=1;i<=ng;i++)for(unsigned kind=0;kind<7;kind++){
  init(16384,0);if(kind==0)t.fail_fresh=i;if(kind==1)t.bad_clock=i;if(kind==2)t.bad_route=i;if(kind==3)t.bad_root=i;if(kind==4)t.bad_cxo=i;if(kind==5)t.bad_hfi=i;if(kind==6)t.bad_bank=i;
  if(kind==3 && i<=3)continue;unsigned code=run_exec();if(!code)fprintf(stderr,"fresh miss i%u kind%u\n",i,kind);assert(code!=0);check();assert(t.result.qualification_lost || kind==3);
 }
 for(unsigned i=1;i<=3;i++)for(unsigned warn=0;warn<2;warn++){init(16384,0);t.fail_commit=i;t.warning=warn;assert(run_exec()!=0);check();}
 for(unsigned i=1;i<=nm;i++){init(16384,0);t.fail_memory=i;assert(run_exec()!=0);check();assert(t.result.qualification_lost);}
 init(16384,0);t.fail_publish=1;assert(run_exec()==GEC_PUBLISH);check();assert(!t.writes);
 init(16384,0);t.fail_finish=1;assert(run_exec()==GEC_CPU);check();assert(!t.result.safe_to_save);
 for(unsigned kind=0;kind<6;kind++){
  init(16384,0);if(kind==0)t.timeout=1;if(kind==1)t.reset_timeout=t.reset_noapply=1;if(kind==2)t.tlb_timeout=1;if(kind==3)t.release_noapply=1;if(kind==4)t.fault=1;if(kind==5)t.stack_damage=1;
  assert(run_exec()!=0);check();if(kind<3)assert(t.result.code==GEC_TIMEOUT || t.result.qualification_lost);if(kind==4)assert(t.result.first.code==GEC_FAULT);if(kind==5)assert(!t.finishes && t.commits==2 && !t.result.safe_to_save && !t.result.isolated);
 }
 /* A posted write may land while no DSB-ordered completion is observed.
  * Even reset1 and a matching canary never permit CPU access or HFS. */
 init(16384,0);t.partial_dma=1;assert(run_exec()==GEC_TIMEOUT);check();assert(!t.finishes && !t.result.safe_to_save && !t.result.isolated && t.commits==2);
 for(unsigned i=1;i<8;i++){init(16384,0);t.bad_mailbox=i;assert(run_exec()!=0);check();assert(!t.finishes && !t.result.safe_to_save && !t.result.isolated && t.commits==2);}
 init(16384,0);t.completion_after=5;assert(run_exec()==0);check();assert(t.result.polls==5 && t.delays==4);
 for(unsigned i=1;i<8;i++){init(16384,0);t.bad_mailbox=i;assert(run_exec()!=0);check();assert(t.result.first.address==0x3d71000u+4*i);}
 for(unsigned kind=0;kind<7;kind++){
  init(16384,0);if(kind==0)t.bad_fsr=1;if(kind==1)t.bad_far=1;if(kind==2)t.bad_fsynr=1;if(kind==3)t.data_damage=1;if(kind==4)t.padding_damage=1;if(kind==5)t.zero_damage=1;if(kind==6)t.restore_alias=1;
  assert(run_exec()!=0);check();assert(!t.result.complete);
 }
 for(unsigned kind=0;kind<5;kind++){
  init(16384,0);if(kind==0)t.commit_table_damage=2;if(kind==1)t.commit_program_damage=2;if(kind==2)t.commit_control_damage=2;if(kind==3)t.commit_backup_damage=1;if(kind==4)t.commit_clock_loss=2;
  assert(run_exec()!=0);check();assert(!t.release_writes);
 }
 for(unsigned kind=0;kind<12;kind++){
  init(16384,0);if(kind==0)t.memory.owned.range.bytes=16384;if(kind==1)t.memory.owned.range.iova+=4096;if(kind==2)t.memory.data_owned_bytes=4096;if(kind==3)t.memory.zero_physical=t.memory.owned.data_physical;
  if(kind==4)t.memory.owned.range.permissions|=ArmSmmu4KExecute;if(kind==5)t.memory.owned.range.writeback=0;if(kind==6)t.memory.owned.config.input_bits=36;
  if(kind==7)t.memory.owned.built.leaf_pages=4;if(kind==8)t.memory.cpu_page_bytes=8192;if(kind==9)t.memory.owned.table_physical+=4096;if(kind==10)t.memory.zero_cpu=data_cpu;if(kind==11)t.record.crc32^=1;
  assert(run_exec()!=0);check();assert(!t.writes && !t.release_writes);
 }
 init(16384,0);assert(run_exec()==0);const struct gec_result good=t.result;
 for(unsigned i=0;i<good.event_count;i++)for(unsigned k=0;k<3;k++){t.result=good;struct gec_event*e=&t.result.events[i];if(k==0)e->store.valid=0;if(k==1)e->barrier.valid=0;if(k==2){if(!e->mask)continue;e->verify.valid=0;}assert(!gec_complete_proof(&t.result));cases++;}
 for(unsigned i=0;i<good.load_count;i++){t.result=good;t.result.loads[i].access.valid=0;assert(!gec_complete_proof(&t.result));cases++;}
 for(unsigned i=0;i<68;i++){t.result=good;t.result.backup[i].value^=1;assert(!gec_complete_proof(&t.result));cases++;}
 for(unsigned i=0;i<16;i++){t.result=good;t.result.stack_after[i].returned=0;assert(!gec_complete_proof(&t.result));cases++;}
 for(unsigned i=0;i<4;i++){t.result=good;t.result.memory_access[i].returned=0;assert(!gec_complete_proof(&t.result));cases++;}
 for(unsigned i=0;i<3;i++){t.result=good;t.result.commit_access[i].valid=0;assert(!gec_complete_proof(&t.result));cases++;}
 t.result=good;t.result.publication.status=1;assert(!gec_complete_proof(&t.result));cases++;
 t.result=good;t.result.cpu_finish_access.attempted=0;assert(!gec_complete_proof(&t.result));cases++;
 t.result=good;t.result.event_count--;assert(!gec_complete_proof(&t.result));cases++;
 t.result=good;t.result.fsr=0x400;assert(!gec_complete_proof(&t.result));cases++;
 /* Exact negative-load exception frame: only its top eight stack words
  * differ. Raw R12/LR and five APSR flags are variable, never control inputs. */
 for(unsigned flags=0;flags<32;flags++){
  init(16384,0);t.expected_fault=1;t.frame_flags=flags<<27;t.frame_r12=0x12abc000u+flags;t.frame_lr=0xe0000000u+flags;
  assert(run_exec()==0);check();assert(t.result.complete && t.result.positive && t.result.negative && t.writes==179 && t.commits==3);
  assert(t.result.stack_after[12].value==t.frame_r12 && t.result.stack_after[13].value==t.frame_lr && t.result.stack_after[14].value==0x6e);
 }
 for(unsigned i=0;i<16;i++)if(i!=12 && i!=13){
  init(16384,0);t.expected_fault=1;t.frame_damage=i+1;assert(run_exec()!=0);check();
  assert(!t.result.isolated && !t.result.context_retired && !t.finishes && !t.result.safe_to_save && t.commits==2);
 }
 for(unsigned kind=0;kind<3;kind++){
  init(16384,0);t.expected_fault=1;if(kind==0)t.bad_fsr=1;if(kind==1)t.bad_far=1;if(kind==2)t.bad_fsynr=1;
  assert(run_exec()!=0);check();assert(!t.finishes && !t.result.safe_to_save && t.commits==2);
 }
 init(16384,0);t.expected_fault=1;assert(run_exec()==0);const struct gec_result fault_good=t.result;
 for(unsigned i=0;i<8;i++)for(unsigned bit=0;bit<32;bit++){t.result=fault_good;t.result.mailbox[i].value^=UINT64_C(1)<<bit;assert(!gec_complete_proof(&t.result));cases++;}
 for(unsigned i=0;i<16;i++)for(unsigned bit=0;bit<32;bit++){
  t.result=fault_good;t.result.stack_after[i].value^=UINT64_C(1)<<bit;t.result.stack_changed_mask=0;
  for(unsigned j=0;j<16;j++)if(t.result.stack_after[j].value!=t.result.backup[52+j].value)t.result.stack_changed_mask|=1u<<j;
  int permitted=i==12 || i==13 || (i==15 && bit>=27);assert(gec_complete_proof(&t.result)==permitted);cases++;
 }
 for(unsigned i=0;i<16;i++)for(unsigned field=0;field<3;field++){t.result=fault_good;if(field==0)t.result.stack_after[i].attempted=0;if(field==1)t.result.stack_after[i].returned=0;if(field==2)t.result.stack_after[i].valid=0;assert(!gec_complete_proof(&t.result));cases++;}
 for(unsigned i=12;i<=13;i++){t.result=fault_good;t.result.stack_after[i].value=UINT64_C(1)<<32;assert(!gec_complete_proof(&t.result));cases++;}
 t.result=fault_good;t.result.stack_changed_mask^=1;assert(!gec_complete_proof(&t.result));cases++;
 /* Unreported reset FAR/FSYNR is data, not a live fault or failed read. */
 {struct gec_snapshot cold;uint32_t failed=0;const struct hph_ro_io ro={&t,raw_read,raw_owner};
  init(16384,0);t.far=UINT64_MAX;t.fsynr=UINT32_MAX;
  assert(gec_observe_ro(&ro,1,&cold,&failed)==0 && cold.far==UINT64_MAX && cold.fsynr==UINT32_MAX);cases++;
  for(unsigned bad=0;bad<8;bad++){
   init(16384,0);t.far=UINT64_MAX;t.fsynr=UINT32_MAX;
   if(bad==0)t.fsr=2;
   if(bad==1)t.bus.banks[2]=t.context[0]=1;
   if(bad==2)t.bus.banks[3]=1;
   if(bad==3)t.bus.smr[0]=0x80000005;
   if(bad==4)t.bus.s2cr[0]=2;
   if(bad==5)t.actlr=0x32b;
   if(bad==6)t.prr_lo=0x4000;
   if(bad==7)t.bus.banks[2]=t.context[0]=0x40;
   unsigned refusal=gec_observe_ro(&ro,1,&cold,&failed);if(!refusal || !failed)fprintf(stderr,"cold FAR negative case %u returned %u at %x\n",bad,refusal,failed);assert(refusal && failed);cases++;
  }
 }
 /* Raw observer independently handles partial read failures/owner refusals. */
 init(16384,0);struct gec_snapshot snapshot;uint32_t failed=0;const struct hph_ro_io ro={&t,raw_read,raw_owner};assert(gec_observe_ro(&ro,1,&snapshot,&failed)==0);unsigned raw_total=t.raw_reads;
 for(unsigned i=1;i<=raw_total;i++){init(16384,0);t.raw_fail=i;assert(gec_observe_ro(&ro,1,&snapshot,&failed)!=0 && failed);cases++;}
 init(16384,0);t.raw_owner_fail=1;assert(gec_observe_ro(&ro,1,&snapshot,&failed)!=0);cases++;
 printf("PASS %u actual core/observer cases, CPU4K/16K, real Build/Audit/Context, bounded fixed SID5/bank2, no device\n",cases);return 0;
}
'''.replace('FIXTURE',str(p/'tests/check-gpu-power-only-handoff.c'))
with tempfile.TemporaryDirectory(prefix='houji-external-canary-') as d:
 src=Path(d)/'test.c';src.write_text(program);exe=Path(d)/'test'
 vendor=p/'native/gpu/vendor/ArmSmmu4K'
 sources=[vendor/(name+'.c') for name in ['ArmSmmu4K','ArmSmmu4KAudit','ArmSmmu4KContext','ArmSmmu4KProgram']]
 flags=['-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(p/'native/gpu/vendor/ArmSmmu4K'),'-I',str(p/'native/gpu/xnu'),'-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu')]
 subprocess.run(['clang',*flags,str(src),*map(str,sources),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
 objects=[]
 for source in sources:
  obj=Path(d)/(source.stem+'.o');subprocess.run(['clang',*flags,'-c',str(source),'-o',str(obj)],check=True);objects.append(obj)
 cpp=Path(d)/'header.cpp';cpp.write_text('#include "GmuExternalCanary.h"\nint main(){ auto a=&gec_run; auto b=&gec_observe_ro; return a==nullptr || b==nullptr; }\n')
 subprocess.run(['clang++','-std=c++14','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/vendor/ArmSmmu4K'),'-I',str(p/'native/gpu/xnu'),'-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu'),str(cpp),*map(str,objects),'-o',str(Path(d)/'cpp')],check=True)
 subprocess.run([str(Path(d)/'cpp')],check=True)
