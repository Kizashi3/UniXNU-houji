#!/usr/bin/env python3
"""Real candidate + core/observer; IOKit and CM3 are CPU-memory peers only.

No device or actual XNU source is changed. This qualifies adapter control-flow
and whitelists, not physical Device mappings, hardware execution or watchdogs.
"""
from pathlib import Path
import ast
import os
import subprocess
import tempfile
PROJECT=Path(__file__).resolve().parent.parent
XNU=PROJECT/'native/gpu/xnu'
POLICY=PROJECT/'native/gpu/uefi'
text=(XNU/'HoujiGpuInternalExecProbe.inc').read_text()
for forbidden in ('hgd_probe(', 'hgb_result', 'ArmSmmu4KProgram', 'pmap_', 'setRecoveryBoot(', 'native_adreno_publish(', 'smc #'):
    assert forbidden not in text, forbidden
assert text.count('*pointer=value;')==1 and text.count('houji_ufs_checkpoint(')==1
assert 'gie_observe_ro(&io,mode' in text and 'gie_recheck_running' in text
assert 'hph_observe_ro(' not in text
assert 'GIEN_FRESH_LIMIT=2*GIE_POLLS+32' in text
module=ast.parse((PROJECT/'tests/check-houji-gpu-handoff-probe.py').read_text())
literals={n.targets[0].id:n.value.value for n in module.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)}
producer=literals['producer']
prefix=literals['peer'].split('#define HOUJI_GPU_HANDOFF_PROBE_HOST_TEST 1')[0]
prefix=prefix.replace('uint64_t getVirtualAddress(){return va;}','uint64_t getVirtualAddress();')
prefix=prefix.replace('backing[4]','backing[6]').replace('mappings[4]','mappings[6]')
prefix=prefix.replace('0x3da0000};','0x3da0000,0x3d6c000,0x3d8c000};').replace('0x40000};','0x40000,0x10000,0x4000};')
prefix=prefix.replace('i<4;','i<6;').replace('CHECK(i<4)','CHECK(i<6)')
prefix=prefix.replace('CHECK(options==(kIOMapAnywhere|kIOMapReadOnly|kIOMapInhibitCache));','CHECK(options==(unsigned)(kIOMapAnywhere|kIOMapInhibitCache|((index==2 || index==4 || index==5)?0:kIOMapReadOnly)));')
prefix=prefix.replace('static unsigned inject_load=~0u,drop_owner_after=~0u;\n','').replace('static unsigned calls_before_failed_gate;\n','')
prefix=prefix.replace('houji_gpu_handoff_probe','houji_gpu_internal_exec_probe')
peer=prefix+r"""
static bool gRootEnabled=true,gLogEnabled=true,gReturnRecovery=true;
extern "C" void houji_ufs_checkpoint(const char*,unsigned);
static void IODelay(unsigned);
#define HOUJI_GPU_INTERNAL_EXEC_PROBE_HOST_TEST 1
#include "HoujiGpuInternalExecProbe.inc"
struct SimulatedTerminalPanic{};
struct Store{unsigned phase;uint32_t address,value;};
static std::vector<Store> stores;
static unsigned map_accesses,fail_map_access,corrupt_store,owner_lost_store,clock_lost_store;
static unsigned checkpoint_calls,fail_commit,mutate_commit,damage_backup_commit,damage_prepared_commit;
static unsigned final_save_calls,panic_calls,cxo_bad_guard,mail_delay,mail_behavior,reset_delay,delay_calls,reset_reads;
static unsigned readback_corrupt_at,program_read_count;
static std::array<unsigned char,HPH_RECORD_BYTES+1> wire;
static hph_record original;
uint64_t IOMemoryMap::getVirtualAddress(){
 if(index>=2 && ++map_accesses==fail_map_access)return 0;
 return va;
}
static void IOLog(const char*format,...){
 char b[2048];va_list ap;va_start(ap,format);int n=vsnprintf(b,sizeof(b),format,ap);va_end(ap);
 CHECK(n>=0 && (size_t)n<sizeof(b));logs.emplace_back(b);
}
static void finish_program(){
 word(0x3d71000)=mail_behavior==1?0xa750deadu:0xa7500002u;
 word(0x3d71004)=mail_behavior==2?0xdeadbeefu:0x750c0de0u;word(0x3d71008)=128;
 if(mail_behavior==1)word(gie_address(57))^=0x55;
}
static void houjiGpuInternalReadBarrier(){
 ++barriers;auto&p=gHoujiGpuInternalExec;auto&r=p.result;
 if(cxo_bad_guard && p.fresh_count==cxo_bad_guard && p.in_fresh && p.fresh[p.current_fresh].reads==1)word(0x3d99144)=0x80000001u;
 if(!p.in_fresh && r.phase==GIE_PHASE_PROGRAM){++program_read_count;if(program_read_count==readback_corrupt_at)word(p.last_address)^=1;}
 if(!p.in_fresh && r.phase==GIE_PHASE_RESET_POLL && p.last_address==0x3d7e000u){++reset_reads;if(reset_delay && reset_reads==reset_delay)word(0x3d7e000)=1;}
}
static void houjiGpuInternalWriteBarrier(){
 auto&p=gHoujiGpuInternalExec;auto&r=p.result;
 CHECK(p.pending_barrier && word(p.last_address)==p.last_value && r.backup_committed);
 const int t=houjiGpuInternalIndex(p.last_address),c=gie_control_index(p.last_address);
 CHECK(t>=0 || c>=0 || p.last_address==0x3d7e000u);
 if(t>=0)CHECK(r.phase==GIE_PHASE_PROGRAM || r.phase==GIE_PHASE_RESTORE_TCM);
 if(c>=0)CHECK(r.phase==GIE_PHASE_CONTROL || r.phase==GIE_PHASE_RESTORE_CONTROL);
 if(p.last_address==0x3d7e000u)CHECK(r.phase==GIE_PHASE_RELEASE || r.phase==GIE_PHASE_RESET);
 stores.push_back({r.phase,p.last_address,p.last_value});
 // AO hardware exposes only its low 7 implemented mask bits. GMU2HOST keeps
 // FFFFFFFF; this must remain legal in control and final verification domains.
 if(c==8)word(p.last_address)&=0x7f;
 if(stores.size()==corrupt_store)word(p.last_address)^=1;
 if(stores.size()==owner_lost_store)p.active=0;
 if(stores.size()==clock_lost_store)word(0x171004)=0;
 if(p.last_address==0x3d7e000 && p.last_value==0 && !mail_delay && mail_behavior!=3)finish_program();
 if(p.last_address==0x3d7e000 && p.last_value==1 && reset_delay)word(p.last_address)=0;
}
static void houjiGpuInternalFullBarrier(){++barriers;}
static void IODelay(unsigned us){
 CHECK(us==10 && gHoujiGpuInternalExec.result.possible_execution);++delay_calls;
 if(mail_delay && delay_calls==mail_delay && mail_behavior!=3)finish_program();
}
extern "C" void houji_ufs_checkpoint(const char*label,unsigned stop){
 auto&p=gHoujiGpuInternalExec;auto&r=p.result;
 CHECK(stop==0 && p.in_commit && !p.fresh_ready && !p.cxo_valid && !p.pending_barrier && gLogEnabled && gReturnRecovery);
 CHECK(word(0x3d7e000)==1 && !r.qualification_lost && !r.barrier_uncertain);
 ++checkpoint_calls;
 if(r.phase==GIE_PHASE_BACKUP_COMMIT)CHECK(strstr(label,"originals58+controls9") && stores.empty() && r.backup_words==58 && r.control_backup_words==9);
 else if(r.phase==GIE_PHASE_PREPARED_COMMIT)CHECK(strstr(label,"code42+controls9") && r.programmed_words==42 && r.control_programmed==9 && !p.release_seen);
 else CHECK(r.phase==GIE_PHASE_FINAL_COMMIT && strstr(label,"originals58+controls7 restored") && r.restored_words==58 && r.control_restored==7 && r.final_verified_words==58);
 if(checkpoint_calls==fail_commit)throw SimulatedTerminalPanic{};
 if(checkpoint_calls==mutate_commit)word(0x171004)=0;
 if(checkpoint_calls==damage_backup_commit)r.backup[0].value^=1;
 if(checkpoint_calls==damage_prepared_commit)word(gie_address(0))^=1;
}
static void reset(){
 gHoujiGpuInternalExec={};gHoujiGpuInternalExecOnce=0;
 chosen_present=property_present=property_type=boot_present=true;boot_value=1;
 gRootEnabled=gLogEnabled=gReturnRecovery=true;
 chosen_lookups=chosen_releases=property_lookups=descriptors=descriptor_releases=map_calls=barriers=boot_calls=0;
 fail_alloc=fail_map=bad_mapping=bad_kind=map_accesses=fail_map_access=corrupt_store=owner_lost_store=clock_lost_store=0;
 checkpoint_calls=fail_commit=mutate_commit=damage_backup_commit=damage_prepared_commit=final_save_calls=panic_calls=0;
 cxo_bad_guard=mail_delay=mail_behavior=reset_delay=delay_calls=reset_reads=readback_corrupt_at=program_read_count=0;
 logs.clear();mapping_order.clear();stores.clear();
 for(unsigned i=0;i<6;i++){backing[i].assign(mock_size[i]/4,0);mappings[i]={};}
 memcpy(wire.data()+1,&original,sizeof(original));property.bytes=wire.data()+1;property.length=HPH_RECORD_BYTES;
 for(unsigned i=0;i<HGB_REGS;i++)word(hgb_address(i))=fixture_register(hgb_address(i));
 for(unsigned i=0;i<HCW_REGS;i++)word(hcw_address(i))=fixture_register(hcw_address(i));
 for(unsigned i=0;i<24;i++){word(0x3da0800+4*i)=fixture_register(0x3da0800+4*i);word(0x3da0c00+4*i)=fixture_register(0x3da0c00+4*i);}
 for(unsigned i=0;i<22;i++)word(0x3dc0000+4096*i)=fixture_register(0x3dc0000+4096*i);
 word(0x3d7e600)=fixture_register(0x3d7e600);word(0x3d99144)=1;
 for(unsigned i=0;i<backing[4].size();i++)backing[4][i]=0x55a00000u+i;
 for(unsigned i=0;i<GIE_TOTAL_WORDS;i++)word(gie_address(i))=i%3?0x13570000u+37*i:UINT32_MAX;
 for(unsigned i=0;i<9;i++)word(gie_control_address(i))=i%3?0x87650000u+37*i:UINT32_MAX;
}
static bool rootContract(){bool safe=houjiGpuInternalExecProbeOnce();if(safe)++final_save_calls;else ++panic_calls;return safe;}
static void noIo(){CHECK(stores.empty() && !gHoujiGpuInternalExec.tcm_reads && !checkpoint_calls && !gHoujiGpuInternalExec.result.safe_to_save);}
static void once(bool expected){
 const unsigned reads=gHoujiGpuInternalExec.read_calls,maps=map_calls,commits=checkpoint_calls;const auto n=stores.size(),lines=logs.size();
 CHECK(houjiGpuInternalExecProbeOnce()==expected && stores.size()==n && logs.size()==lines && gHoujiGpuInternalExec.read_calls==reads && maps==map_calls && commits==checkpoint_calls);
}
static void restored(const std::vector<uint32_t>&saved,const std::array<uint32_t,9>&control){
 CHECK(backing[4]==saved);
 for(unsigned i=0;i<7;i++)CHECK(word(gie_control_address(i))==control[i]);
 CHECK(word(gie_control_address(7))==UINT32_MAX && word(gie_control_address(8))==0x7f && word(0x3d7e000)==1);
}
int main(){unsigned cases=0;fixture_record((unsigned char*)&original);CHECK(hph_record_valid(&original));
 auto&p=gHoujiGpuInternalExec;auto&r=p.result;
 for(int arg:{0,2,-1}){reset();boot_value=arg;CHECK(houjiGpuInternalExecProbeOnce());noIo();CHECK(!chosen_lookups && logs.empty());++cases;}
 reset();boot_present=false;CHECK(houjiGpuInternalExecProbeOnce());noIo();++cases;
 for(unsigned flags=0;flags<7;flags++){reset();gRootEnabled=flags&1;gLogEnabled=flags&2;gReturnRecovery=flags&4;CHECK(!rootContract());noIo();CHECK(!chosen_lookups && !final_save_calls && panic_calls==1);once(false);++cases;}
 for(unsigned kind=0;kind<7;kind++){reset();if(!kind)chosen_present=false;if(kind==1)property_present=false;if(kind==2)property_type=false;if(kind==3)property.bytes=nullptr;if(kind==4)property.length=0;if(kind==5)property.length=1375;if(kind==6)property.length=1377;CHECK(!rootContract());noIo();CHECK(!descriptors);++cases;}
 for(unsigned i=0;i<HPH_RECORD_BYTES;i++){reset();wire[1+i]^=1;CHECK(!rootContract());noIo();CHECK(!descriptors && !p.decoded);++cases;}
 reset();auto saved=backing[4];std::array<uint32_t,9> controls;for(unsigned i=0;i<9;i++)controls[i]=word(gie_control_address(i));
 CHECK(rootContract());
 CHECK(r.complete && r.safe_to_save && !r.code && !r.qualification_lost && !r.barrier_uncertain && !r.tcm_retained && r.possible_execution && r.reset_held);
 CHECK(r.backup_words==58 && r.control_backup_words==9 && r.programmed_words==42 && r.control_programmed==9 && r.restored_words==58 && r.control_restored==7 && r.final_verified_words==58 && r.irq_retained==3);
 CHECK(p.commit_attempted==3 && p.commit_returned==3 && r.backup_committed && r.prepared_committed && r.restore_committed && checkpoint_calls==3);
 CHECK(p.tcm_writes==100 && p.control_writes==16 && p.reset_writes==2 && p.write_barriers==118 && p.barriers==118 && stores.size()==118);
 CHECK(r.polls==1 && r.reset_polls==1 && !r.delays && !delay_calls && p.map_valid==63 && p.map_attempted==63 && descriptors==6 && descriptor_releases==6 && !p.first_io_code);
 CHECK(r.release_verify.valid && r.release_verify.value==0 && r.mailbox[0].value==0xa7500002u && r.mailbox[1].value==0x750c0de0u && r.mailbox[2].value==128);
 CHECK(r.prepared_control_verify[7].value==UINT32_MAX && r.prepared_control_verify[8].value==0x7f && r.control_final_verify[7].value==UINT32_MAX);
 restored(saved,controls);CHECK(final_save_calls==1 && !panic_calls && !p.active && p.read_barriers==p.read_calls);
 const auto success_stores=stores;const auto success_result=r;const unsigned accesses=map_accesses,freshes=p.fresh_count;
 size_t output_bytes=0;for(auto&line:logs)output_bytes+=line.size();CHECK(output_bytes<15000);once(true);++cases;
 for(unsigned i=0;i<42;i++)CHECK(stores[i].address==gie_address(i) && stores[i].value==gie_program_value(i));
 const unsigned order[]={1,0,2,3,4,5,6,7,8};for(unsigned i=0;i<9;i++)CHECK(stores[42+i].address==gie_control_address(order[i]) && stores[42+i].value==gie_control_value(order[i]));
 CHECK(stores[51].address==0x3d7e000 && stores[51].value==0 && stores[52].address==0x3d7e000 && stores[52].value==1);
 for(unsigned i=0;i<58;i++)CHECK(stores[53+i].address==gie_address(i) && stores[53+i].value==r.backup[i].value);
 for(unsigned i=0;i<7;i++)CHECK(stores[111+i].address==gie_control_address(6-i));
 // Returned corrupt writes are observed. Pre-execution errors are restored
 // through a fresh cold path; running/reset uncertainty never selects FS.
 for(unsigned i=1;i<=118;i++){
  reset();saved=backing[4];corrupt_store=i;bool safe=rootContract();CHECK(!r.complete && r.code && !p.pending_barrier);
  if(safe){CHECK(r.safe_to_save && !r.tcm_retained && r.restored_words==58 && r.final_verified_words==58 && final_save_calls==1 && !panic_calls && backing[4]==saved);}
  else CHECK(!r.safe_to_save && !final_save_calls && panic_calls==1);
  ++cases;
 }
 // Failure at every actual Device peer getVirtualAddress includes reads,
 // prepared re-read, release, running, cleanup and final verification.
 for(unsigned i=1;i<=accesses;i++){
  reset();saved=backing[4];fail_map_access=i;bool safe=rootContract();CHECK(!r.complete && (r.code || p.code) && p.first_io_code==GIEN_MAPPING && !p.pending_barrier);
  if(safe)CHECK(r.safe_to_save && r.restored_words==58 && r.final_verified_words==58 && final_save_calls==1 && backing[4]==saved);
  else CHECK(!r.safe_to_save && !final_save_calls && panic_calls==1);
  ++cases;
 }
 for(unsigned window=1;window<=6;window++)for(unsigned kind=0;kind<6;kind++){
  reset();if(!kind)fail_alloc=window;if(kind==1)fail_map=window;if(kind>=2){bad_mapping=window;bad_kind=kind-2;}
  CHECK(!rootContract());CHECK(!r.safe_to_save && !final_save_calls && panic_calls==1 && descriptor_releases==descriptors);
  if(window<5)CHECK(stores.empty());++cases;
 }
 for(unsigned stage=1;stage<=3;stage++){
  reset();mutate_commit=stage;CHECK(!rootContract());CHECK(r.qualification_lost && !r.safe_to_save && checkpoint_calls==stage && !final_save_calls && panic_calls==1);++cases;
  reset();fail_commit=stage;bool terminal=false;try{(void)rootContract();}catch(const SimulatedTerminalPanic&){terminal=true;}
  CHECK(terminal && !r.safe_to_save && checkpoint_calls==stage && p.in_commit && p.commit_returned==stage-1 && !final_save_calls && !panic_calls);++cases;
 }
 reset();damage_backup_commit=1;CHECK(!rootContract());CHECK(r.code==GIE_BACKUP && stores.empty() && !r.safe_to_save && checkpoint_calls==1);++cases;
 reset();damage_prepared_commit=2;CHECK(rootContract());CHECK(r.code==GIE_VERIFY && r.first.phase==GIE_PHASE_PREPARED_COMMIT && !p.release_seen && !r.complete && r.safe_to_save && backing[4]==saved);++cases;
 for(unsigned i=1;i<=freshes;i++){reset();cxo_bad_guard=i;CHECK(!rootContract());CHECK(r.qualification_lost && !r.safe_to_save && !r.complete && !final_save_calls);++cases;}
 for(unsigned i=1;i<=118;i++){
  reset();owner_lost_store=i;CHECK(!rootContract());CHECK(r.qualification_lost && !r.safe_to_save && stores.size()==i && p.barriers==i && !p.pending_barrier && !final_save_calls && panic_calls==1);++cases;
 }
 // Fresh read after an own store may see lost power; reset is never issued
 // blindly to compensate for a dead power/clock prerequisite.
 reset();clock_lost_store=52;CHECK(!rootContract());CHECK(r.qualification_lost && p.release_seen && !p.reset_seen && !r.safe_to_save && checkpoint_calls==2);++cases;
 for(unsigned behavior:{1u,2u}){reset();saved=backing[4];mail_behavior=behavior;CHECK(rootContract());CHECK(r.code && !r.complete && r.safe_to_save && r.restored_words==58 && backing[4]==saved && r.stack_changed_mask==(behavior==1?(1u<<15):0));++cases;}
 reset();saved=backing[4];mail_delay=3;CHECK(rootContract());CHECK(r.complete && r.polls==4 && delay_calls==3 && p.fresh_count==freshes+3 && backing[4]==saved);++cases;
 reset();saved=backing[4];mail_behavior=3;CHECK(rootContract());CHECK(r.code==GIE_TIMEOUT && r.polls==1000 && r.delays==999 && p.fresh_count>GIEN_FRESH_SLOTS && r.safe_to_save && !r.complete && backing[4]==saved);++cases;
 reset();saved=backing[4];reset_delay=3;CHECK(rootContract());CHECK(r.complete && r.reset_polls==4 && delay_calls==3 && backing[4]==saved);++cases;
 reset();reset_delay=1001;CHECK(!rootContract());CHECK(r.code==GIE_TIMEOUT && r.reset_polls==1000 && !r.safe_to_save && r.tcm_retained && checkpoint_calls==2);++cases;
 // Exact address/phase/value/attempted/once checks are enforced by the actual
 // adapter even for direct/misrouted requests, not only by the portable core.
 for(uint32_t address:{0u,0x3d6cffcu,0x3d6d088u,0x3d71020u,0x3d74f80u,0x3da0800u,0x3d993f0u,0x3d7e004u,0x3d7e000u,0x3d8ec18u}){
  reset();p.active=p.decoded=p.record_ready=p.fresh_ready=p.cxo_valid=1;p.cxo_raw=1;gHoujiGpuInternalExecOnce=1;
  CHECK(houjiGpuInternalWrite(&p,address,0)!=0 && stores.empty() && !descriptors);++cases;
 }
 // Independently valid original backups cannot authorize an incorrect value,
 // unscheduled phase, duplicate store, stack program, IRQ restore or fake
 // prepared-read proof. These failures occur before the first map/store.
 for(unsigned fault=0;fault<10;fault++){
  reset();r=success_result;r.phase=GIE_PHASE_PROGRAM;r.safe_to_save=r.complete=0;
  p.active=p.decoded=p.record_ready=p.fresh_ready=p.cxo_valid=1;p.cxo_raw=1;p.fresh_mode=1;p.fresh[0].cold.values[HGB_RESET]=1;
  gHoujiGpuInternalExecOnce=1;uint32_t address=gie_address(0),value=gie_program_value(0);
  r.program_store[0].attempted=1;r.program_store[0].returned=0;r.program_store[0].value=value;
  if(fault==0)value^=1;if(fault==1)r.program_store[0].value^=1;if(fault==2)r.program_store[0].attempted=0;
  if(fault==3)r.program_store[0].returned=1;if(fault==4)p.store_seen[0][0]=1;if(fault==5)r.phase=GIE_PHASE_POLL;
  if(fault==6)address=gie_address(42);
  if(fault==7){address=gie_control_address(7);value=r.control_backup[7].value;r.phase=GIE_PHASE_RESTORE_CONTROL;}
  if(fault==8){address=0x3d7e000;value=0;r.phase=GIE_PHASE_RELEASE;r.release_store.attempted=1;r.release_store.returned=0;r.release_store.value=0;r.prepared_tcm_verify[0].valid=0;}
  if(fault==9){address=0x3d7e000;value=1;r.phase=GIE_PHASE_RESET;r.reset_store.attempted=1;r.reset_store.returned=0;r.reset_store.value=1;r.guard_reset=1;p.release_seen=1;}
  CHECK(houjiGpuInternalWrite(&p,address,value)!=0 && stores.empty() && !descriptors);++cases;
 }
 reset();CHECK(houjiGpuInternalBarrier(&p)==0 && p.barriers==1 && !descriptors);CHECK(houjiGpuInternalBarrier(nullptr)!=0);CHECK(houjiGpuInternalDelay(&p,10)!=0);++cases;
 printf("PASS: %u actual internal-CM3 XNU adapter/core/Device-map/reset0-running/cleanup/118-store/58-restore/no-FS-on-unknown cases (ASAN/UBSAN); success logs=%zu bytes fresh=%u; CPU peers, not hardware qualification\n",cases,output_bytes,freshes);
}
"""
with tempfile.TemporaryDirectory(prefix='houji-internal-exec-') as temporary:
    d=Path(temporary);c=d/'producer.c';cpp=d/'probe.cpp';obj=d/'producer.o';binary=d/'probe'
    c.write_text(producer);cpp.write_text(peer);Path("/tmp/houji-internal-exec-host.cpp").write_text(peer)
    flags=['-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer']
    subprocess.run(['clang','-std=c11',*flags,'-I',str(POLICY),'-I',str(PROJECT/'tests'),'-c',str(c),'-o',str(obj)],check=True)
    subprocess.run(['clang++','-std=c++17',*flags,'-I',str(POLICY),'-I',str(XNU),str(cpp),str(obj),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'})
