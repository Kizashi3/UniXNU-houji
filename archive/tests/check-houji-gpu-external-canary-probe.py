#!/usr/bin/env python3
"""Actual XNU external-canary adapter + Memory/Cpu/Build/Audit/core.

Only IOKit, MRS/DC/DSB/AT and device MMIO are host peers. Separate CPU/DRAM
copies force real adapter cache publication/invalidation sequencing. No device
or actual XNU tree is read or mutated by this runner.
"""
from pathlib import Path
import ast,os,subprocess,tempfile
P=Path(__file__).resolve().parents[1];X=P/'native/gpu/xnu';A=X/'Adreno740';V=P/'native/gpu/vendor/ArmSmmu4K';U=P/'native/gpu/uefi'
text=(X/'HoujiGpuExternalCanaryProbe.inc').read_text()
for forbidden in ('hga_probe(', 'hgp_disabled_context(', 'hgb_result', 'pmap_', 'setRecoveryBoot(', 'native_adreno_publish(', '.release(', '.retireAfterQuiescence('):assert forbidden not in text,forbidden
assert 'gec_observe_ro(&io,mode' in text and 'gec_state_qualified' in text and text.count('houji_ufs_checkpoint(')==3
hold=text.split('static void houjiGpuExternalFailureHold(void) {',1)[1].split('static bool houjiGpuExternalCanaryProbeOnce(void)',1)[0]
for forbidden in ('houji_ufs_checkpoint(', 'houjiGpuExternalPointer(', 'houjiGpuExternalFresh(', 'gec_observe_ro(', 'MemoryIdentity(', 'MaintainOwnedPages(', '.quarantine(', '.release('):assert forbidden not in hold,forbidden
assert hold.count('IOLog(')==4 and hold.count('IOSleep(8000)')==1

def literals(path):
 t=ast.parse(path.read_text());return {n.targets[0].id:n.value.value for n in t.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)}
f=literals(A/'tests/check_page_geometry.py');prefix=f['prefix']
prefix=prefix.replace('constexpr unsigned kIOMapAnywhere=1,kIOMapInhibitCache=2;\n','').replace('constexpr IOReturn kIOReturnNotFound=9;\n','')
prefix='#include <cstdint>\nstatic void external_cache_hook(uintptr_t,unsigned);\n'+prefix
prefix=prefix.replace('cache_lines.push_back({address,op});','cache_lines.push_back({address,op});external_cache_hook(address,op);')
h=literals(P/'tests/check-houji-gpu-handoff-probe.py');producer=h['producer'];mmio=h['peer'].split('#define HOUJI_GPU_HANDOFF_PROBE_HOST_TEST 1')[0]
mmio=mmio.replace('#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL %s:%u: %s\\n",__FILE__,__LINE__,#x);__builtin_abort();}}while(0)','')
mmio=mmio.replace('map_calls,barriers,boot_calls','map_calls,boot_calls').replace('uint64_t getVirtualAddress(){return va;}','uint64_t getVirtualAddress();')
mmio=mmio.replace('backing[4]','backing[6]').replace('mappings[4]','mappings[6]').replace('0x3da0000};','0x3da0000,0x3d6c000,0x3d8c000};').replace('0x40000};','0x40000,0x10000,0x4000};').replace('i<4;','i<6;').replace('CHECK(i<4)','CHECK(i<6)')
mmio=mmio.replace('CHECK(options==(kIOMapAnywhere|kIOMapReadOnly|kIOMapInhibitCache));','CHECK(options==(unsigned)(kIOMapAnywhere|kIOMapInhibitCache|((index==2 || index==3 || index==4 || index==5)?0:kIOMapReadOnly)));')
mmio=mmio.replace('static unsigned inject_load=~0u,drop_owner_after=~0u;\n','').replace('static unsigned calls_before_failed_gate;\n','').replace('houji_gpu_handoff_probe','houji_gpu_external_canary_probe')
mmio=mmio.replace('static bool PE_parse_boot_argn(const char*name,void*out,int bytes){','static bool PE_parse_boot_argn(const char*name,void*out,int bytes){if(!strcmp(name,\"houji_gpu_external_nc_probe\")){CHECK(bytes==(int)sizeof(int));*(int*)out=0;return false;}')
cpu=(A/'NativeAdrenoCpu.cpp').read_text()
for field,reg in [('tcr','tcr_el1'),('ttbr0','ttbr0_el1'),('ttbr1','ttbr1_el1'),('sctlr','sctlr_el1')]:
 old=f'__asm__ volatile("mrs %0, {reg}" : "=r"(out->{field}));';assert old in cpu;cpu=cpu.replace(old,f'out->{field}=cpu_{field};')
cpu=cpu.replace('__asm__ volatile("mrs %0, ctr_el0":"=r"(ctr));','ctr=cpu_ctr;')
for name,op in [('cvac',0),('civac',1),('ivac',2)]:cpu=cpu.replace(f'__asm__ volatile("dc {name}, %0"::"r"(address):"memory");',f'cache_line(address,{op});')
cpu=cpu.replace('__asm__ volatile("dsb sy":::"memory");','++barriers;');assert '__asm__' not in cpu
peer=r"""
static bool gRootEnabled=true,gLogEnabled=true,gReturnRecovery=true;
extern "C" void houji_ufs_checkpoint(const char*,unsigned);
static void IODelay(unsigned);
static void IOSleep(unsigned);
#define HOUJI_GPU_EXTERNAL_CANARY_PROBE_HOST_TEST 1
#include "HoujiGpuExternalCanaryProbe.inc"
struct Store{unsigned phase,wide;uint32_t address;uint64_t value;};
static std::vector<Store> stores;
static std::array<std::vector<unsigned char>,3> dram;
static unsigned map_accesses,fail_map_access,corrupt_store,owner_lost_store,clock_lost_store,at_calls,fail_at;
static unsigned checkpoint_calls,fail_commit,mutate_commit,damage_backup_commit,damage_prepared_commit,damage_prepared_sctlr;
static unsigned final_save_calls,panic_calls,mail_delay,mail_behavior,delay_calls,publication_count,invalidate_count,wrong_data,padding_damage,zero_damage,negative_wrong,apply_partial_dma;
static unsigned expose_data_reads,fail_cpu_cache,table_extra,table_bit,fail_cache_once,early_checkpoint_calls,early_post_clock_loss,early_owner_loss,no_submission_checkpoints,no_submission_failures,ns_post_clock_loss,ns_post_table_damage,ns_post_owner_loss;
static unsigned failure_holds,failure_hold_ms;
static unsigned fault_mail_bit,fault_stack_bit,fault_saved_seed;
static std::array<unsigned char,HPH_RECORD_BYTES+1> wire;static hph_record original;
struct SimulatedTerminalPanic{};
uint64_t IOMemoryMap::getVirtualAddress(){if(index>=2 && ++map_accesses==fail_map_access)return 0;return va;}
static void IOLog(const char*f,...){char b[2048];va_list ap;va_start(ap,f);int n=vsnprintf(b,sizeof(b),f,ap);va_end(ap);CHECK(n>=0 && (size_t)n<sizeof(b));logs.emplace_back(b);}
static bool houjiGpuExternalAt(uint64_t va,bool write,uint64_t*par){
 CHECK(par);++at_calls;auto&p=gHoujiGpuExternalCanary;
 for(unsigned i=0;i<3;i++){const auto&b=p.info[i];if(!b.allocated || va<b.va || va-b.va>=b.owned)continue;
  uint64_t pa=b.pa+va-b.va;*par=UINT64_C(0xff00000000000b00)|(pa&UINT64_C(0x0000fffffffff000));
  if(at_calls==fail_at)*par=1;(void)write;return true;
 }CHECK(false);return false;
}
static void external_cache_hook(uintptr_t address,unsigned op){
 auto&p=gHoujiGpuExternalCanary;auto&r=p.result;
 if(fail_cpu_cache && r.phase==GEC_PHASE_CPU_FINISH && !fail_cache_once++){cpu_ctr=UINT64_C(11)<<16;return;}
 for(unsigned i=0;i<3;i++){
  const auto&b=p.info[i];if(!b.allocated || address<b.va || address-b.va>=b.owned)continue;
  CHECK(!(address&63));
  if(r.phase==GEC_PHASE_BACKUP_COMMIT){CHECK(!p.release_seen && r.publication.attempted && !r.publication.returned);if(address==b.va+b.owned-64){dram[i].assign((unsigned char*)b.va,(unsigned char*)b.va+b.owned);++publication_count;}}
  if(r.phase==GEC_PHASE_CPU_FINISH && op==2){CHECK(houjiGpuExternalIsolated() && p.cpu_access_allowed && p.cpu_finish_called && dram[i].size()==16384);if(address==b.va)memcpy((void*)b.va,dram[i].data(),dram[i].size());++invalidate_count;}
 }
}
static uint64_t device_walk(uint64_t iova){
 auto&p=gHoujiGpuExternalCanary;uint64_t pa=p.memory.owned.table_physical;
 CHECK(dram[0].size()==16384);
 for(unsigned level=1;level<=3;level++){
  CHECK(pa>=p.info[0].pa && pa-p.info[0].pa<12288);uint64_t d=0;
  memcpy(&d,dram[0].data()+pa-p.info[0].pa+8*((iova>>(39-9*level))&511),8);
  if(!d)return 0;CHECK((d&3)==3);if(level==3)return (d&UINT64_C(0x0000fffffffff000))|(iova&4095);pa=d&UINT64_C(0x0000fffffffff000);
 }CHECK(false);return 0;
}
static void finish_program(){
 auto&p=gHoujiGpuExternalCanary;auto&r=p.result;CHECK(p.release_seen && p.held_mask==7 && publication_count==3);
 CHECK(device_walk(0x60000000)==p.info[1].pa && device_walk(0x60000fff)==p.info[1].pa+4095 && !device_walk(0x60002000));
 CHECK(word(0x3da0800)==0x80000005 && word(0x3da0c00)==2 && (word(HGP_CB(0))&1));
 if(mail_behavior==3)return;
 uint32_t value=wrong_data?0xdeadbeef:0xa750cafe;memcpy(dram[1].data()+8,&value,4);
 // CPU mapping still holds stale seed until the actual adapter invalidates.
 CHECK(((uint32_t*)p.memory.owned.data)[2]==0);++expose_data_reads;
 if(padding_damage)dram[1][4096]^=1;if(zero_damage)dram[2][0]^=1;
 if(apply_partial_dma){word(0x3d71000)=0xa7500001;return;}
 const uint32_t mail[]={0xa7500003,0x7504cafe,0x86500071,0xa750cafe,0,0,0,0};
 for(unsigned i=0;i<8;i++)word(0x3d71000+4*i)=mail[i];
 if(mail_behavior==1)word(0x3d71000)=0xa750dead;if(mail_behavior==2)word(0x3d71004)^=1;
 if(mail_behavior==5)word(0x3d74f60)^=1;
 // Exact same fixed176B payload's precise negative BusFault path. The
 // CPU/DRAM peer still forces real native publication and invalidate.
 if(mail_behavior==4){
  word(0x3d71000)=0xa750dead;word(0x3d71018)=0x8200;word(0x3d7101c)=0x60002000;
  const uint32_t frame[]={0x10004000,0xa7500001,0x60002000,0xa750cafe,
    0xcef01234u^fault_saved_seed,0xdeadbeefu^fault_saved_seed,0x6e,0x01000000};
  for(unsigned i=0;i<8;i++)word(0x3d74f60+4*i)=frame[i];
  if(fault_mail_bit){unsigned bit=fault_mail_bit-1;word(0x3d71000+4*(bit/32))^=1u<<(bit%32);}
  if(fault_stack_bit){unsigned bit=fault_stack_bit-1;word(0x3d74f40+4*(bit/32))^=1u<<(bit%32);}
 }

 word(HGP_CB(0x58))=negative_wrong?4:2;word(HGP_CB(0x60))=negative_wrong?0x60003000:0x60002000;word(HGP_CB(0x64))=0;word(HGP_CB(0x68))=0;
 (void)r;
}
static void houjiGpuExternalReadBarrier(){++barriers;auto&p=gHoujiGpuExternalCanary;if(early_owner_loss && p.early_in_fresh && p.early_current==0)p.active=0;}
static void houjiGpuExternalWriteBarrier(){
 auto&p=gHoujiGpuExternalCanary;auto&r=p.result;CHECK(p.pending_barrier && p.held_mask==7 && r.backup_committed);
 uint64_t actual=word(p.last_address);if(p.last_wide)actual|=(uint64_t)word(p.last_address+4)<<32;CHECK(actual==p.last_value);
 stores.push_back({r.phase,p.last_wide,p.last_address,p.last_value});
 const int c=gie_control_index(p.last_address);if(c==8 && r.phase==GEC_PHASE_CONTROL)word(p.last_address)&=127;
 if(p.last_address==HGP_CB(0x58)){CHECK(p.last_value==2 && r.phase==GEC_PHASE_CLEAR_FAULT && houjiGpuExternalIsolated()==false);word(p.last_address)=0;}
 if(stores.size()==corrupt_store)word(p.last_address)^=1;
 if(stores.size()==owner_lost_store)p.active=0;if(stores.size()==clock_lost_store)word(0x171004)=0;
 if(p.last_address==0x3d7e000 && !p.last_value && !mail_delay)finish_program();
}
static void houjiGpuExternalFullBarrier(){++barriers;}
static void houjiGpuExternalNcPublishBarrier(){CHECK(false);}
static void houjiGpuExternalNcAcquireBarrier(){CHECK(false);}
static void IODelay(unsigned us){CHECK(us==10);++delay_calls;if(mail_delay && delay_calls==mail_delay)finish_program();}
static void IOSleep(unsigned ms){
 const auto&p=gHoujiGpuExternalCanary;const auto&r=p.result;
 CHECK(ms==8000 && r.started && !r.safe_to_save && !p.active && p.phase==4 && logs.size()>=4);
 for(auto&b:p.bo)if(b.backed())CHECK(b.quarantined());
 for(unsigned i=0;i<4;i++){char prefix[32];snprintf(prefix,sizeof(prefix),"HOUJI GMU STOP%u ",i+1);CHECK(logs[logs.size()-4+i].rfind(prefix,0)==0);}
 ++failure_holds;failure_hold_ms+=ms;
}
extern "C" void houji_ufs_checkpoint(const char*label,unsigned stop){
 auto&p=gHoujiGpuExternalCanary;auto&r=p.result;CHECK(stop==0 && p.in_commit && !p.fresh_ready && !p.pending_barrier && word(0x3d7e000)==1);
 if(strstr(label,"NO SUBMISSION")){
  const unsigned kind=strstr(label,"failure")?1u:0u;const auto&d=p.no_submission[2*kind];
  CHECK(p.core_called && !r.possible_execution && !p.release_seen && !p.reset_seen && !p.reset_writes && !r.qualification_lost && !r.barrier_uncertain && !p.early_owner_lost);
  CHECK(p.held_mask==7 && p.published_mask==7 && p.commit_returned==2 && d.attempted && d.returned && !d.raw_code && !d.code && d.gates==255 && d.memory_valid && d.table_crc==p.table_crc);
  CHECK(gec_state_qualified(&p.record,&p.memory,&r,&d.snapshot,1));
  for(auto&b:p.bo)CHECK(b.deviceReferences()==1 && !b.quarantined());
  for(auto&e:stores)CHECK(e.address!=0x3d7e000);
  if(!kind){CHECK(r.phase==GEC_PHASE_ROUTE && r.enabled && r.route_prepared && r.stream_attached && r.prepared_committed && stores.size()==80 && !r.code);++no_submission_checkpoints;}
  else {CHECK(!r.safe_to_save && !r.complete);++no_submission_failures;}
  if(ns_post_clock_loss)word(0x171004)=0;if(ns_post_table_damage)((uint64_t*)p.memory.owned.tables)[0]^=1;if(ns_post_owner_loss)p.active=0;return;
 }
 CHECK(!word(0x3da0800) && word(0x3da0c00)==0x20000);
 if(p.early_attempted && !p.core_called){
  CHECK(!(word(HGP_CB(0))&1));CHECK(strstr(label,"early") && !stores.size() && !r.started && !r.safe_to_save && !p.held_mask && !p.published_mask && !p.release_seen && !p.reset_seen && !p.commit_attempted && !p.early_owner_lost);
  CHECK(p.early_cold[0].attempted && p.early_cold[0].returned && !p.early_cold[0].code && !p.early_cold[0].recheck && p.early_cold[0].gates==255);
  for(auto&bo:p.bo)CHECK(!bo.deviceReferences());++early_checkpoint_calls;if(early_post_clock_loss)word(0x171004)=0;return;
 }
 CHECK(checkpoint_calls?word(HGP_CB(0))==0:(word(HGP_CB(0))&0x41u)==0);
 ++checkpoint_calls;if(checkpoint_calls==1)CHECK(strstr(label,"no MMIO store") && stores.empty());
 if(checkpoint_calls==2)CHECK(strstr(label,"no master released") && !p.release_seen && r.programmed_words==52);
 if(checkpoint_calls==3)CHECK(strstr(label,"CPU canary verified") && p.cpu_restored && r.positive && r.negative && r.context_retired);
 if(checkpoint_calls==fail_commit)throw SimulatedTerminalPanic{};
 if(checkpoint_calls==mutate_commit)word(0x171004)=0;if(checkpoint_calls==damage_backup_commit)r.backup[0].value^=1;
 if(checkpoint_calls==damage_prepared_commit)word(gec_address(0))^=1;
 if(checkpoint_calls==damage_prepared_sctlr)word(HGP_CB(0))=2;
 if(checkpoint_calls==1 && table_extra){auto*t=(uint64_t*)p.memory.owned.tables;t[2*512+2]=t[2*512];}
 if(checkpoint_calls==1 && table_bit)((uint64_t*)p.memory.owned.tables)[0]^=1;
}
static void discardHostAfterReset(){while(!fixture.live.empty())fixture.live.back()->release();while(!fixture.metadata.empty())fixtureMetadataFree(fixture.metadata.back());}
static void reset(){
 discardHostAfterReset();memset((void*)&gHoujiGpuExternalCanary,0,sizeof(gHoujiGpuExternalCanary));gHoujiGpuExternalCanaryOnce=0;
 fixture=MemoryFixture{};fixture.cpu_page_bytes=16384;fixture.next_physical=UINT64_C(0x8c5d10000);
 page_size=map_page_bytes=PAGE_SIZE;cpu_tcr=(UINT64_C(2)<<14)|(UINT64_C(1)<<30);cpu_ttbr0=0x30000000;cpu_ttbr1=0x30004000;cpu_sctlr=1;cpu_ctr=UINT64_C(4)<<16;
 attributes.clear();pmap_writes.clear();cache_lines.clear();attribute_write_fail=barriers=now=0;
 chosen_present=property_present=property_type=boot_present=true;boot_value=1;gRootEnabled=gLogEnabled=gReturnRecovery=true;
 chosen_lookups=chosen_releases=property_lookups=descriptors=descriptor_releases=map_calls=boot_calls=0;
 fail_alloc=fail_map=bad_mapping=bad_kind=map_accesses=fail_map_access=corrupt_store=owner_lost_store=clock_lost_store=at_calls=fail_at=0;
 checkpoint_calls=fail_commit=mutate_commit=damage_backup_commit=damage_prepared_commit=damage_prepared_sctlr=final_save_calls=panic_calls=0;
 mail_delay=mail_behavior=delay_calls=publication_count=invalidate_count=wrong_data=padding_damage=zero_damage=negative_wrong=apply_partial_dma=0;
 expose_data_reads=fail_cpu_cache=table_extra=table_bit=fail_cache_once=early_checkpoint_calls=early_post_clock_loss=early_owner_loss=0;no_submission_checkpoints=no_submission_failures=ns_post_clock_loss=ns_post_table_damage=ns_post_owner_loss=0;failure_holds=failure_hold_ms=fault_mail_bit=fault_stack_bit=fault_saved_seed=0;logs.clear();mapping_order.clear();stores.clear();for(auto&d:dram)d.clear();
 for(unsigned i=0;i<6;i++){backing[i].assign(mock_size[i]/4,0);mappings[i]={};}
 memcpy(wire.data()+1,&original,sizeof(original));property.bytes=wire.data()+1;property.length=HPH_RECORD_BYTES;
 for(unsigned i=0;i<HGB_REGS;i++)word(hgb_address(i))=fixture_register(hgb_address(i));
 for(unsigned i=0;i<HCW_REGS;i++)word(hcw_address(i))=fixture_register(hcw_address(i));
 for(unsigned i=0;i<24;i++){word(0x3da0800+4*i)=fixture_register(0x3da0800+4*i);word(0x3da0c00+4*i)=fixture_register(0x3da0c00+4*i);}
 for(unsigned i=0;i<22;i++)word(0x3dc0000+4096*i)=fixture_register(0x3dc0000+4096*i);
 word(0x3d7e600)=fixture_register(0x3d7e600);word(0x3d99144)=1;
 for(unsigned i=0;i<68;i++)word(gec_address(i))=i%3?0x13570000u+37*i:UINT32_MAX;
 for(unsigned i=0;i<9;i++)word(gie_control_address(i))=i%3?0x87650000u+37*i:UINT32_MAX;
 for(unsigned i=0;i<9;i++){word(gec_field_address(i))=0;if(i==5 || i==6)word(gec_field_address(i)+4)=0;}
 word(HGP_CB(4))=3;word(0x3da6008)=word(0x3da600c)=word(HGP_CB(0x58))=word(HGP_CB(0x60))=word(HGP_CB(0x64))=word(HGP_CB(0x68))=word(HGP_CB(0x7f4))=0;
}
static bool contract(){bool safe=houjiGpuExternalCanaryProbeOnce();if(safe)++final_save_calls;else ++panic_calls;CHECK(failure_holds==(!safe && gHoujiGpuExternalCanary.result.started?1u:0u) && failure_hold_ms==8000*failure_holds);return safe;}
static void once(bool safe){const auto n=stores.size(),lines=logs.size();const unsigned reads=gHoujiGpuExternalCanary.read_calls,created=fixture.created,holds=failure_holds;CHECK(houjiGpuExternalCanaryProbeOnce()==safe && stores.size()==n && logs.size()==lines && gHoujiGpuExternalCanary.read_calls==reads && fixture.created==created && failure_holds==holds);}
int main(){unsigned cases=0;fixture_record((unsigned char*)&original);CHECK(hph_record_valid(&original));auto&p=gHoujiGpuExternalCanary;auto&r=p.result;
 for(int arg:{0,2,-1}){reset();boot_value=arg;CHECK(houjiGpuExternalCanaryProbeOnce());CHECK(!chosen_lookups && !fixture.created && stores.empty());++cases;}
 for(unsigned flags=0;flags<7;flags++){reset();gRootEnabled=flags&1;gLogEnabled=flags&2;gReturnRecovery=flags&4;CHECK(!contract() && !fixture.created && stores.empty());once(false);++cases;}
 for(unsigned i=0;i<HPH_RECORD_BYTES;i++){reset();wire[1+i]^=1;CHECK(!contract() && !descriptors && !fixture.created && stores.empty());++cases;}
 reset();auto original_tcm=backing[4];CHECK(contract());
 CHECK(!r.memory_profile && !r.nc_acquired && !r.nc_restore_published && !r.nc_table_invalidated);
 CHECK(r.complete && r.safe_to_save && !r.code && !r.qualification_lost && !r.barrier_uncertain && r.positive && r.negative && r.context_retired && r.isolated && !r.tcm_retained);
 CHECK(r.backup_words==68 && r.programmed_words==52 && r.restored_words==68 && r.control_restored==7 && r.final_verified_words==68 && r.irq_retained==3);
 CHECK(r.event_count==179 && stores.size()==179 && p.write_barriers==179 && p.barriers==179 && p.event_claims==179);
 CHECK(p.held_mask==7 && p.published_mask==7 && fixture.created==3 && !fixture.completed && !fixture.released && p.memory_checks==4 && p.cpu_finish_called && p.cpu_invalidated && p.cpu_restored);
 CHECK(p.info[0].logical==16384 && p.info[1].logical==4096 && p.info[2].logical==4096 && fixture.allocation_bytes==std::vector<size_t>({16384,16384,16384}) && pmap_writes.empty());
 CHECK(p.info[0].pa>UINT32_MAX && p.info[1].pa>UINT32_MAX && p.info[2].pa>UINT32_MAX && p.info[0].pa!=p.info[1].pa && p.info[1].pa!=p.info[2].pa);
 CHECK(p.memory.owned.built.table_pages==3 && p.memory.owned.built.leaf_pages==1 && p.table_audit.complete && p.table_audit.descriptor_reads==1536 && !device_walk(0x60002000));
 CHECK(((uint32_t*)p.memory.owned.data)[2]==0 && r.cpu.observed==0xa750cafe && r.cpu.checked_words==1024 && r.cpu.padding_checked && publication_count==3 && invalidate_count==3*256 && expose_data_reads==1 && backing[4]==original_tcm);
 CHECK(word(HGP_CB(0))==0 && word(HGP_CB(0x20))==0 && word(HGP_CB(0x24))==0 && word(0x3da0800)==0 && word(0x3da0c00)==0x20000 && word(HGP_CB(4))==3 && !word(HGP_CB(0x58)) && !word(0x3da6008) && !word(0x3da600c));
 CHECK(checkpoint_calls==3 && no_submission_checkpoints==1 && !no_submission_failures && p.no_submission_post[0] && final_save_calls==1 && !panic_calls && !p.active && p.map_valid==63 && !p.first_io_code);
 std::vector<uint64_t> expected_masks;for(unsigned i=0;i<r.event_count;i++)expected_masks.push_back(r.events[i].mask);const unsigned accesses=map_accesses,ats=at_calls,freshes=p.fresh_count;size_t bytes=0;for(auto&l:logs)bytes+=l.size();CHECK(bytes<24000);once(true);++cases;
 // r147 exact physical failure: deterministic fault signature and a real
 // 8-register exception frame within the already-owned 64B TCM stack.
 reset();mail_behavior=4;auto fault_original_tcm=backing[4];CHECK(contract());
 CHECK(r.complete && gec_complete_proof(&r) && r.positive && r.negative && r.safe_to_save && !r.code && !failure_holds);
 CHECK(r.mailbox[0].value==0xa750dead && r.mailbox[6].value==0x8200 && r.mailbox[7].value==0x60002000 && r.stack_changed_mask==0xff00);
 CHECK(stores.size()==179 && checkpoint_calls==3 && p.cpu_finish_called && invalidate_count==3*256 && p.cpu_invalidated && p.cpu_restored && backing[4]==fault_original_tcm);once(true);++cases;
 reset();mail_behavior=5;CHECK(!contract() && !r.safe_to_save && !p.cpu_finish_called && !invalidate_count && !r.isolated && checkpoint_calls==2);++cases;
 // Every changed mailbox bit must exclude CPU access and final save.
 for(unsigned bit=0;bit<256;bit++){reset();mail_behavior=4;fault_mail_bit=bit+1;
  CHECK(!contract() && !r.complete && !r.safe_to_save && !p.cpu_finish_called && !invalidate_count && !r.isolated && checkpoint_calls==2 && panic_calls==1);++cases;}
 // Only the source-dead R12/LR data and NZCVQ flags may vary. All guards,
 // source-derived registers/PC, thread/T/IT/alignment state remain exact.
 for(unsigned bit=0;bit<512;bit++){reset();mail_behavior=4;fault_stack_bit=bit+1;
  const unsigned word_index=bit/32,word_bit=bit%32;
  const bool opaque_data=word_index==12 || word_index==13;
  const bool nzcvq=word_index==15 && word_bit>=27;
  const bool safe=contract();CHECK(safe==(opaque_data || nzcvq));
  if(safe)CHECK(r.complete && gec_complete_proof(&r) && p.cpu_finish_called && checkpoint_calls==3 && !failure_holds);
  else CHECK(!r.safe_to_save && !p.cpu_finish_called && !invalidate_count && !r.isolated && checkpoint_calls==2);++cases;}
 for(unsigned seed:{1u,0x12345678u,0xffffffffu}){reset();mail_behavior=4;fault_saved_seed=seed;CHECK(contract() && r.complete && gec_complete_proof(&r));++cases;}
 reset();mail_behavior=4;negative_wrong=1;CHECK(!contract() && !p.cpu_finish_called && !r.safe_to_save && checkpoint_calls==2);++cases;
 // Replay the exact r144 disabled bank originals. Only M/CFRE gate the
 // initial stage; known SCTLR0/TTBR image replaces them before any execution.
 reset();word(HGP_CB(0))=0x3ff5a71e;word(HGP_CB(0x20))=0xeffebfeb;word(HGP_CB(0x24))=0xff77fee6;
 word(HGP_CB(0x28))=0xfffdeeff;word(HGP_CB(0x2c))=0x7d7beaed;CHECK(contract());
 CHECK(r.complete && r.safe_to_save && stores.size()==179 && checkpoint_calls==3 && no_submission_checkpoints==1 && !early_checkpoint_calls && p.fresh_count==24);
 CHECK(r.context_backup[0].value==0x3ff5a71e && r.context_backup[5].value==UINT64_C(0xff77fee6effebfeb) && r.context_backup[6].value==UINT64_C(0x7d7beaedfffdeeff));
 CHECK(!word(HGP_CB(0)) && !word(HGP_CB(0x20)) && !word(HGP_CB(0x24)) && !word(HGP_CB(0x28)) && !word(HGP_CB(0x2c)));++cases;
 for(uint32_t bit:{1u,0x40u}){reset();word(HGP_CB(0))=0x3ff5a71e|bit;CHECK(!contract() && !p.core_called && stores.empty() && !checkpoint_calls && !r.safe_to_save);++cases;}
 reset();damage_prepared_sctlr=2;CHECK(!contract() && r.qualification_lost && !p.release_seen && !p.cpu_finish_called && checkpoint_calls==2 && !r.safe_to_save);++cases;
 for(unsigned n=1;n<=179;n++){reset();corrupt_store=n;bool safe=contract();if(expected_masks[n-1]&1)CHECK(!r.complete && (r.code || p.code));else if(r.complete)CHECK(safe && !(expected_masks[n-1]&1));if(safe)CHECK(r.safe_to_save && p.cpu_restored && r.positive && r.negative);else CHECK(!r.safe_to_save && !final_save_calls && panic_calls==1);CHECK(!p.pending_barrier && !fixture.released);++cases;}
 for(unsigned n=1;n<=179;n++){reset();owner_lost_store=n;CHECK(!contract() && r.qualification_lost && !r.safe_to_save && stores.size()==n && p.barriers==n && !p.pending_barrier && !fixture.released && !final_save_calls);++cases;}
 for(unsigned n=1;n<=accesses;n++){reset();fail_map_access=n;bool safe=contract();CHECK(!r.complete && (r.code || p.code) && p.first_io_code==GECN_MAPPING && !fixture.released);if(!safe)CHECK(!r.safe_to_save && !final_save_calls);++cases;}
 for(unsigned n=1;n<=ats;n++){reset();fail_at=n;CHECK(!contract() && !r.safe_to_save && !fixture.released && !p.cpu_finish_called);++cases;}
 for(unsigned stage=1;stage<=3;stage++){reset();mutate_commit=stage;CHECK(!contract() && r.qualification_lost && checkpoint_calls==stage && !final_save_calls);++cases;reset();fail_commit=stage;bool panic=false;try{(void)contract();}catch(const SimulatedTerminalPanic&){panic=true;}CHECK(panic && !r.safe_to_save && p.in_commit && p.commit_returned==stage-1);++cases;}
 for(unsigned kind=0;kind<9;kind++){reset();if(kind==0)mail_behavior=1;if(kind==1)mail_behavior=2;if(kind==2)mail_behavior=3;if(kind==3)apply_partial_dma=1;if(kind==4)negative_wrong=1;if(kind==5)wrong_data=1;if(kind==6)padding_damage=1;if(kind==7)zero_damage=1;if(kind==8)fail_cpu_cache=1;CHECK(!contract() && !r.safe_to_save && !final_save_calls && !fixture.released && checkpoint_calls==2);if(kind<5)CHECK(!p.cpu_finish_called && !invalidate_count && !r.isolated);++cases;}
 for(unsigned stage:{1u,2u}){reset();damage_backup_commit=stage;CHECK(!contract() && !r.safe_to_save && !p.cpu_finish_called && !final_save_calls);++cases;}
 reset();damage_prepared_commit=2;CHECK(!contract() && !r.safe_to_save && !p.release_seen && !p.cpu_finish_called);++cases;
 for(unsigned kind:{0u,1u}){reset();if(!kind)table_extra=1;else table_bit=1;CHECK(!contract() && !r.safe_to_save && !p.release_seen);++cases;}
 reset();mail_delay=3;CHECK(contract() && r.complete && r.polls==4 && p.fresh_count==freshes+3 && delay_calls==3);++cases;
 for(unsigned w=1;w<=6;w++)for(unsigned kind=0;kind<6;kind++){reset();if(kind==0)fail_alloc=w;if(kind==1)fail_map=w;if(kind>=2){bad_mapping=w;bad_kind=kind-2;}CHECK(!contract() && !r.safe_to_save && !final_save_calls && !fixture.released);++cases;}
 // r143 early-stop reproductions: retain the real full/partial extra
 // snapshot, save only independent cold proof, and NEVER enter the core.
 for(unsigned kind=0;kind<6;kind++){
  reset();if(kind==0)word(HGP_CB(4))=0;if(kind==1)word(HGP_CB(4))=UINT32_MAX;
  if(kind==2)word(0x3da6008)=UINT32_MAX;if(kind==3)word(HGP_CB(0x58))=UINT32_MAX;
  if(kind==4)word(HGP_CB(0x60))=UINT32_MAX;if(kind==5)word(0x3da6008)=0x1234;
  CHECK(!contract() && p.code==GECN_ORDER && !p.core_called && !r.started && !r.safe_to_save && !fixture.created && stores.empty());
  CHECK(p.early_attempted && p.early_reason==1 && p.early_saved && p.early_returned && early_checkpoint_calls==1 && !checkpoint_calls);
  CHECK(p.early_cold[0].returned && p.early_cold[1].returned && !p.early_cold[0].code && !p.early_cold[1].code && !p.early_cold[0].recheck && !p.early_cold[1].recheck);
  CHECK(p.fresh_count==1 && !p.fresh_ready && !p.cxo_valid && !p.commit_attempted && !p.commit_returned && !p.held_mask);
  if(kind==0)CHECK(p.fresh[0].raw_code==0 && p.fresh[0].code==HPH_COLD && p.fresh[0].snapshot.actlr==0 && p.fresh[0].snapshot.valid==0x1fff);
  if(kind>=1 && kind<=4)CHECK(p.fresh[0].raw_code && p.fresh[0].snapshot.valid!=0x1fff);
  once(false);const unsigned e=early_checkpoint_calls;houjiGpuExternalEarlyFailureSave(1);CHECK(early_checkpoint_calls==e);++cases;
 }
 for(unsigned kind=0;kind<5;kind++){
  reset();if(kind==0)word(0x171004)=0;if(kind==1)word(0x3da0804)=0x80000006;
  if(kind==2)word(0x3dc1000)=1;if(kind==3)word(0x3d7e000)=0;if(kind==4)word(0x3da0048)=1;
  CHECK(!contract() && !early_checkpoint_calls && !checkpoint_calls && !p.early_saved && !p.core_called && !fixture.created && stores.empty() && !r.safe_to_save);++cases;
 }
 reset();word(HGP_CB(4))=0;early_post_clock_loss=1;CHECK(!contract() && early_checkpoint_calls==1 && p.early_saved && p.early_cold[1].returned && p.early_cold[1].code && !p.fresh_ready && !r.safe_to_save && !p.core_called);++cases;
 reset();word(HGP_CB(4))=0;early_owner_loss=1;CHECK(!contract() && !early_checkpoint_calls && p.early_owner_lost && !p.early_saved && !r.safe_to_save);++cases;
 reset();fixture.allocation_fail=true;CHECK(!contract() && !fixture.created && !r.started && p.early_reason==2 && p.early_saved && early_checkpoint_calls==1 && !checkpoint_calls && !p.fresh_ready);++cases;
 // The new active-context save is independent from the three GEC commits.
 // A changed clock/owner/table after it never permits the release store.
 for(unsigned kind=0;kind<3;kind++){reset();if(kind==0)ns_post_clock_loss=1;if(kind==1)ns_post_table_damage=1;if(kind==2)ns_post_owner_loss=1;
  CHECK(!contract() && no_submission_checkpoints==1 && !no_submission_failures && !p.no_submission_post[0] && !p.release_seen && !p.reset_writes && !r.safe_to_save && checkpoint_calls==2 && stores.size()==80);++cases;}
 // An intact known disabled prefix with only CPU backup corruption can save
 // the terminal failure; the original core failure is never cleared/resumed.
 reset();damage_backup_commit=2;CHECK(!contract() && r.code==GEC_BACKUP && r.phase==GEC_PHASE_ENABLE && !p.release_seen && stores.size()==77 && !no_submission_checkpoints && no_submission_failures==1 && p.no_submission_post[1] && !r.safe_to_save && !r.complete);++cases;
 // Any release event (including attempted-only), unknown barrier/ownership or
 // partial software prefix permanently excludes this diagnostic FS route.
 reset();CHECK(contract());const auto no_extra=no_submission_checkpoints+no_submission_failures;
 CHECK(houjiGpuExternalNoSubmissionSave(1,nullptr,nullptr) && no_submission_checkpoints+no_submission_failures==no_extra);++cases;
 reset();fixture.null_mapping=true;fixture.complete_fail=true;CHECK(!contract() && fixture.live.size()==1 && !fixture.released && p.bo[0].quarantined());++cases;
 reset();fixture.next_physical=UINT64_C(1)<<36;CHECK(!contract() && !p.release_seen);++cases;
 // Direct misrouted callbacks cannot bypass native event/load/owner checks.
 for(uint32_t a:{0u,0x3da0804u,0x3dc0000u,0x3d6d0b0u,0x3d71020u,0x3d74f80u,0x3d993f0u}){reset();p.active=p.decoded=p.record_ready=p.fresh_ready=1;gHoujiGpuExternalCanaryOnce=1;uint32_t v=0;CHECK(houjiGpuExternalWrite32(&p,a,0) && houjiGpuExternalRead32(&p,a,&v) && stores.empty());++cases;}
 reset();CHECK(contract() && !failure_holds);{const auto count=logs.size();houjiGpuExternalFailureHold();CHECK(!failure_holds && logs.size()==count);}++cases;
 reset();{const auto count=logs.size();houjiGpuExternalFailureHold();CHECK(!failure_holds && logs.size()==count);}++cases;
 reset();CHECK(!houjiGpuExternalBarrier(&p) && p.barriers==1 && houjiGpuExternalBarrier(nullptr));CHECK(houjiGpuExternalDelay(&p,10));++cases;
 printf("PASS: %u actual external-canary Native/Memory/Cpu/Build/Audit/core cases (ASAN/UBSAN); success179stores/%ucorefresh+2diagnosticRO/%uAT, %zu log bytes; separate CPU/DRAM peers, no hardware qualification\n",cases,freshes,ats,bytes);discardHostAfterReset();
}
"""
with tempfile.TemporaryDirectory(prefix='houji-external-canary-') as temporary:
 d=Path(temporary);(d/'XnuMemoryFixture.h').write_text((A/'tests/XnuMemoryFixture.h').read_text())
 for name in ['IOKit/IOTypes.h','IOKit/IOBufferMemoryDescriptor.h','IOKit/IOLib.h','kern/task.h','kern/cpu_data.h','vm/vm_map.h','mach/vm_param.h','kern/clock.h','vm/memory_types.h']:
  out=d/name;out.parent.mkdir(parents=True,exist_ok=True);out.write_text('#include "XnuMemoryFixture.h"\n')
 flags=['-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer']
 objects=[]
 for name in ['ArmSmmu4K','ArmSmmu4KAudit','ArmSmmu4KContext','ArmSmmu4KProgram']:
  obj=d/(name+'.o');subprocess.run(['clang','-std=c11',*flags,'-I',str(V),'-c',str(V/(name+'.c')),'-o',str(obj)],check=True);objects.append(str(obj))
 c=d/'producer.c';c.write_text(producer);obj=d/'producer.o';subprocess.run(['clang','-std=c11',*flags,'-I',str(U),'-I',str(P/'tests'),'-c',str(c),'-o',str(obj)],check=True);objects.append(str(obj))
 cpp=d/'probe.cpp';cpp.write_text(prefix+cpu+(A/'NativeAdrenoMemory.cpp').read_text()+mmio+peer);Path('/tmp/houji-external-canary-host.cpp').write_text(cpp.read_text())
 exe=d/'probe';subprocess.run(['clang++','-std=c++17',*flags,'-DPAGE_SIZE=16384','-I',str(d),'-I',str(A/'tests'),'-I',str(A),'-I',str(X),'-I',str(V),'-I',str(U),str(cpp),*objects,'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
