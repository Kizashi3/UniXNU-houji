#!/usr/bin/env python3
"""Actual held-reset XNU adapter + portable core, IOKit/CPU-barrier peers only.

No device or actual XNU source is accessed. MMIO peers are CPU RAM: they do
not establish physical Device attributes, fault recovery or hardware results.
"""
from pathlib import Path
import ast
import os
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
XNU = PROJECT / 'native/gpu/xnu'
POLICY = PROJECT / 'native/gpu/uefi'
source = (XNU / 'HoujiGpuHeldTcmProbe.inc').read_text()
for forbidden in ('hgd_probe(', 'hgb_bus_complete(', 'hgb_result', 'ArmSmmu4KProgram',
                  'pmap_', 'setRecoveryBoot(', 'native_adreno_publish(', 'IOServiceOpen(', 'smc #'):
    assert forbidden not in source, forbidden
assert source.count('*pointer=value;') == 1
assert source.count('houji_ufs_checkpoint(') == 1
assert 'HHT_PHASE_RESTORE' in source and 'HHT_PROGRAM_WORDS' in source

# Reuse only the existing IOKit peer definitions and genuine producer fixture;
# the candidate and both real portable policies are compiled without rewriting.
tree = ast.parse((PROJECT / 'tests/check-houji-gpu-handoff-probe.py').read_text())
literals = {n.targets[0].id: n.value.value for n in tree.body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)}
producer = literals['producer']
prefix = literals['peer'].split('#define HOUJI_GPU_HANDOFF_PROBE_HOST_TEST 1')[0]
prefix = prefix.replace('uint64_t getVirtualAddress(){return va;}', 'uint64_t getVirtualAddress();')
prefix = prefix.replace('backing[4]', 'backing[5]').replace('mappings[4]', 'mappings[5]')
prefix = prefix.replace('0x3da0000};', '0x3da0000,0x3d6c000};')
prefix = prefix.replace('0x40000};', '0x40000,0x10000};')
prefix = prefix.replace('i<4;', 'i<5;').replace('CHECK(i<4)', 'CHECK(i<5)')
prefix = prefix.replace('CHECK(options==(kIOMapAnywhere|kIOMapReadOnly|kIOMapInhibitCache));',
                        'CHECK(options==(unsigned)(kIOMapAnywhere|kIOMapInhibitCache|(index==4?0:kIOMapReadOnly)));')
prefix = prefix.replace('static unsigned inject_load=~0u,drop_owner_after=~0u;\n', '')
prefix = prefix.replace('static unsigned calls_before_failed_gate;\n', '')
prefix = prefix.replace('houji_gpu_handoff_probe', 'houji_gpu_held_tcm_probe')

peer = prefix + r'''
static bool gRootEnabled=true,gLogEnabled=true,gReturnRecovery=true;
extern "C" void houji_ufs_checkpoint(const char*,unsigned);
#define HOUJI_GPU_HELD_TCM_PROBE_HOST_TEST 1
#include "HoujiGpuHeldTcmProbe.inc"
struct SimulatedTerminalPanic {};
struct Store {unsigned phase,index;uint32_t address,value;};
static std::vector<Store> stores;
static unsigned map_accesses,fail_map_access,corrupt_store,owner_lost_store,checkpoint_calls;
static unsigned fail_commit,mutate_commit,damage_backup_commit,final_save_calls,panic_calls;
static unsigned cxo_bad_guard;
static std::array<unsigned char,HPH_RECORD_BYTES+1> wire;
static hph_record original;
uint64_t IOMemoryMap::getVirtualAddress(){
 if(index==4 && ++map_accesses==fail_map_access)return 0;
 return va;
}
static void IOLog(const char*format,...){
 char buffer[2048];va_list ap;va_start(ap,format);int n=vsnprintf(buffer,sizeof(buffer),format,ap);va_end(ap);
 CHECK(n>=0 && (size_t)n<sizeof(buffer));logs.emplace_back(buffer);
}
static void houjiGpuHeldReadBarrier(){
 ++barriers;auto&p=gHoujiGpuHeldTcm;
 if(cxo_bad_guard && p.fresh_count==cxo_bad_guard && p.in_fresh && p.fresh[p.current_fresh].reads==131)
  word(0x3d99144)=0x80000001u;
}
static void houjiGpuHeldWriteBarrier(){
 auto&p=gHoujiGpuHeldTcm;const int i=houjiGpuHeldIndex(p.last_address);
 CHECK(i>=0 && (unsigned)i<HHT_PROGRAM_WORDS && word(p.last_address)==p.last_value);
 CHECK(p.result.phase==HHT_PHASE_PROGRAM || p.result.phase==HHT_PHASE_RESTORE);
 CHECK(p.result.backup[i].valid && p.result.backup_committed && p.pending_barrier);
 stores.push_back({p.result.phase,(unsigned)i,p.last_address,p.last_value});
 if(stores.size()==corrupt_store)word(p.last_address)^=1;
 if(stores.size()==owner_lost_store)p.active=0;
}
static void houjiGpuHeldFullBarrier(){++barriers;}
extern "C" void houji_ufs_checkpoint(const char*label,unsigned stop){
 auto&p=gHoujiGpuHeldTcm;auto&r=p.result;
 CHECK(stop==0 && p.in_commit && !p.fresh_ready && !p.cxo_valid && !p.pending_barrier && gLogEnabled && gReturnRecovery);
 ++checkpoint_calls;
 if(checkpoint_calls==1){CHECK(strstr(label,"originals complete") && stores.empty() && r.backup_words==58);}
 else {CHECK(checkpoint_calls==2 && strstr(label,"42 originals restored") && r.restored_words==42 && r.final_verified_words==58);}
 if(checkpoint_calls==fail_commit)throw SimulatedTerminalPanic{};
 if(checkpoint_calls==mutate_commit)word(0x171004)=0;
 if(checkpoint_calls==damage_backup_commit)r.backup[0].value^=1;
}
static void reset(){
 gHoujiGpuHeldTcm={};gHoujiGpuHeldTcmOnce=0;
 chosen_present=property_present=property_type=boot_present=true;boot_value=1;
 gRootEnabled=gLogEnabled=gReturnRecovery=true;
 chosen_lookups=chosen_releases=property_lookups=descriptors=descriptor_releases=map_calls=barriers=boot_calls=0;
 fail_alloc=fail_map=bad_mapping=bad_kind=0;map_accesses=fail_map_access=corrupt_store=owner_lost_store=checkpoint_calls=0;
 fail_commit=mutate_commit=damage_backup_commit=final_save_calls=panic_calls=cxo_bad_guard=0;
 logs.clear();mapping_order.clear();stores.clear();
 for(unsigned i=0;i<5;i++){backing[i].assign(mock_size[i]/4,0);mappings[i]={};}
 memcpy(wire.data()+1,&original,sizeof(original));property.bytes=wire.data()+1;property.length=HPH_RECORD_BYTES;
 for(unsigned i=0;i<HGB_REGS;i++)word(hgb_address(i))=fixture_register(hgb_address(i));
 for(unsigned i=0;i<HCW_REGS;i++)word(hcw_address(i))=fixture_register(hcw_address(i));
 for(unsigned i=0;i<24;i++){word(0x3da0800+4*i)=fixture_register(0x3da0800+4*i);word(0x3da0c00+4*i)=fixture_register(0x3da0c00+4*i);}
 for(unsigned i=0;i<22;i++)word(0x3dc0000+4096*i)=fixture_register(0x3dc0000+4096*i);
 word(0x3d7e600)=fixture_register(0x3d7e600);word(0x3d99144)=1;
 for(unsigned i=0;i<backing[4].size();i++)backing[4][i]=0x55a00000u+i;
 for(unsigned i=0;i<HHT_TOTAL_WORDS;i++)word(hht_address(i))=i%3?0x13570000u+37*i:UINT32_MAX;
}
static bool rootContract(){
 bool safe=houjiGpuHeldTcmProbeOnce();if(safe)++final_save_calls;else ++panic_calls;return safe;
}
static void noTcm(){CHECK(stores.empty() && !gHoujiGpuHeldTcm.tcm_reads && !checkpoint_calls && !gHoujiGpuHeldTcm.result.safe_to_save);}
static void noRetry(bool expected){
 const auto count=stores.size(),lines=logs.size();const auto reads=gHoujiGpuHeldTcm.read_calls,maps=map_calls,commits=checkpoint_calls;
 CHECK(houjiGpuHeldTcmProbeOnce()==expected && stores.size()==count && logs.size()==lines && gHoujiGpuHeldTcm.read_calls==reads && map_calls==maps && checkpoint_calls==commits);
}
int main(){unsigned cases=0;fixture_record((unsigned char*)&original);CHECK(hph_record_valid(&original));
 for(int arg:{0,2,-1}){reset();boot_value=arg;CHECK(houjiGpuHeldTcmProbeOnce());noTcm();CHECK(!chosen_lookups && logs.empty());++cases;}
 reset();boot_present=false;CHECK(houjiGpuHeldTcmProbeOnce());noTcm();++cases;
 for(unsigned flags=0;flags<7;flags++){
  reset();gRootEnabled=flags&1;gLogEnabled=flags&2;gReturnRecovery=flags&4;
  CHECK(!rootContract());noTcm();CHECK(!chosen_lookups && panic_calls==1 && !final_save_calls);noRetry(false);++cases;
 }
 for(unsigned kind=0;kind<7;kind++){
  reset();if(!kind)chosen_present=false;if(kind==1)property_present=false;if(kind==2)property_type=false;
  if(kind==3)property.bytes=nullptr;if(kind==4)property.length=0;if(kind==5)property.length=1375;if(kind==6)property.length=1377;
  CHECK(!rootContract());noTcm();CHECK(!descriptors && panic_calls==1 && !final_save_calls);++cases;
 }
 for(unsigned i=0;i<HPH_RECORD_BYTES;i++){
  reset();wire[1+i]^=1;CHECK(!rootContract());noTcm();CHECK(!descriptors && !gHoujiGpuHeldTcm.decoded && panic_calls==1);++cases;
 }
 reset();auto saved=backing[4];CHECK(rootContract());auto&p=gHoujiGpuHeldTcm;auto&r=p.result;
 CHECK(r.complete && r.safe_to_save && !r.code && !r.qualification_lost && !r.tcm_retained && r.backup_words==58 && r.programmed_words==42 && r.stack_checked==16 && r.restored_words==42 && r.final_verified_words==58);
 CHECK(!p.active && p.core_called && !p.core_code && p.tcm_reads==216 && p.tcm_writes==84 && p.write_barriers==84 && p.barriers==84 && p.fresh_count==9 && checkpoint_calls==2);
 CHECK(p.commit_attempted==2 && p.commit_returned==2 && r.backup_committed && r.restore_committed && backing[4]==saved && !p.first_io_code && stores.size()==84);
 CHECK(p.map_valid==31 && p.map_attempted==31 && descriptors==5 && descriptor_releases==5 && map_calls==5 && mapping_order==std::vector<unsigned>({0,1,2,3,4}));
 CHECK(final_save_calls==1 && !panic_calls && p.read_barriers==p.read_calls && p.tcm_reads==216);
 for(unsigned i=0;i<42;i++){
  CHECK(stores[i].phase==HHT_PHASE_PROGRAM && stores[i].index==i && stores[i].value==hht_program_value(i));
  CHECK(stores[42+i].phase==HHT_PHASE_RESTORE && stores[42+i].index==i && stores[42+i].value==r.backup[i].value);
 }
 for(unsigned i=0;i<58;i++)CHECK(r.backup[i].attempted && r.backup[i].returned && r.backup[i].valid && r.final_verify[i].value==r.backup[i].value && r.final_verify[i].valid);
 size_t output_bytes=0;for(auto&line:logs)output_bytes+=line.size();CHECK(output_bytes<16000);noRetry(true);++cases;
 const unsigned accesses=map_accesses;
 // Returned corrupted stores are observed, then independently cold-guarded
 // and restored. Original failure stays visible although save is now safe.
 for(unsigned i=1;i<=42;i++){
  reset();saved=backing[4];corrupt_store=i;CHECK(rootContract());
  CHECK(!r.complete && r.safe_to_save && r.code==HHT_VERIFY && !r.qualification_lost && r.restored_words==42 && r.final_verified_words==58 && r.first.index==i-1 && r.first.phase==HHT_PHASE_PROGRAM && backing[4]==saved && checkpoint_calls==2);
  CHECK(stores.size()==i+42 && final_save_calls==1 && !panic_calls);++cases;
 }
 for(unsigned i=43;i<=84;i++){
  reset();corrupt_store=i;CHECK(!rootContract());CHECK(!r.safe_to_save && !r.complete && r.code==HHT_VERIFY && r.first.phase==HHT_PHASE_RESTORE && checkpoint_calls==1 && !final_save_calls && panic_calls==1);++cases;
 }
 // Each actual mapping access may fail once. A backup failure never reaches a
 // store; later uncertainty cannot accidentally select another filesystem save.
 for(unsigned i=1;i<=accesses;i++){
  reset();saved=backing[4];fail_map_access=i;bool safe=rootContract();
  CHECK(!r.complete && r.code && p.first_io_code==HHTN_MAPPING && !p.pending_barrier);
  if(safe){CHECK(r.safe_to_save && r.restored_words==42 && r.final_verified_words==58 && backing[4]==saved && checkpoint_calls==2 && final_save_calls==1 && !panic_calls);}
  else {CHECK(!r.safe_to_save && !final_save_calls && panic_calls==1 && checkpoint_calls<=1);}
  for(auto&s:stores)CHECK(s.index<42 && s.address==hht_address(s.index));++cases;
 }
 for(unsigned window=1;window<=5;window++)for(unsigned kind=0;kind<6;kind++){
  reset();if(!kind)fail_alloc=window;if(kind==1)fail_map=window;if(kind>=2){bad_mapping=window;bad_kind=kind-2;}
  CHECK(!rootContract());CHECK(!r.safe_to_save && stores.empty() && !checkpoint_calls && !final_save_calls && panic_calls==1 && descriptor_releases==descriptors);++cases;
 }
 for(unsigned stage=1;stage<=2;stage++){
  reset();mutate_commit=stage;CHECK(!rootContract());CHECK(r.qualification_lost && !r.safe_to_save && checkpoint_calls==stage && !final_save_calls && panic_calls==1);
  CHECK(stores.size()==(stage==1?0u:84u));++cases;
  reset();fail_commit=stage;bool terminal=false;try{(void)rootContract();}catch(const SimulatedTerminalPanic&){terminal=true;}
  CHECK(terminal && !r.safe_to_save && checkpoint_calls==stage && p.in_commit && p.commit_returned==stage-1 && !final_save_calls && !panic_calls);++cases;
 }
 reset();damage_backup_commit=1;CHECK(!rootContract());CHECK(r.code==HHT_BACKUP && stores.empty() && !r.safe_to_save && checkpoint_calls==1);++cases;
 for(unsigned guard=1;guard<=9;guard++){
  reset();cxo_bad_guard=guard;CHECK(!rootContract());CHECK(r.qualification_lost && !r.safe_to_save && !r.complete && !final_save_calls && panic_calls==1);++cases;
 }
 for(unsigned i=1;i<=84;i++){
  reset();owner_lost_store=i;CHECK(!rootContract());CHECK(r.qualification_lost && !r.safe_to_save && stores.size()==i && p.barriers==i && !p.pending_barrier && !final_save_calls && panic_calls==1);++cases;
 }
 // Same whitelist and value checks apply to direct/misrouted calls too; no
 // GPIO, reset, IRQ, SMMU, RCG/PLL, adjacent TCM word or stack can be stored.
 for(uint32_t address:{0u,0x3d6cffcu,0x3d6d088u,0x3d71020u,0x3d74f40u,0x3d74f80u,0x3d7e000u,0x3d7e64cu,0x3da0800u,0x3d993f0u}){
  reset();p.active=p.decoded=p.record_ready=p.fresh_ready=p.cxo_valid=1;p.cxo_raw=1;gHoujiGpuHeldTcmOnce=1;
  CHECK(houjiGpuHeldWrite(&p,address,0)!=0 && stores.empty() && !descriptors);++cases;
 }
 reset();CHECK(houjiGpuHeldBarrier(&p)==0 && p.barriers==1 && !descriptors && stores.empty());CHECK(houjiGpuHeldBarrier(nullptr)!=0);++cases;
 printf("PASS: %u actual held-TCM XNU adapter/core/RO-guard/Device-map/84-store/rollback/no-FS-on-unknown cases (ASAN/UBSAN); successful logs=%zu bytes, no hardware qualification\n",cases,output_bytes);
}
'''

with tempfile.TemporaryDirectory(prefix='houji-held-tcm-') as temporary:
    directory = Path(temporary)
    c, cpp = directory / 'producer.c', directory / 'probe.cpp'
    obj, binary = directory / 'producer.o', directory / 'probe'
    c.write_text(producer)
    cpp.write_text(peer)
    flags = ['-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    subprocess.run(['clang', '-std=c11', *flags, '-I', str(POLICY), '-I', str(PROJECT / 'tests'), '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['clang++', '-std=c++17', *flags, '-I', str(POLICY), '-I', str(XNU), str(cpp), str(obj), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
