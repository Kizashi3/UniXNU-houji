#!/usr/bin/env python3
"""Offline real Native adapter/Memory/Cpu + NormalNC DMA and alias boundary peers.

The original 6050-case WB runner stays independent. This runner reuses its
fixtures and failure suite, adding NC attribute/alias/barrier observations.
"""
from pathlib import Path
import hashlib,json,os,shutil,subprocess
HERE=Path(__file__).resolve().parent
P=HERE.parents[1]
B=HERE/'build'; B.mkdir(exist_ok=True)
S=B/'snapshot'
if S.exists():shutil.rmtree(S)
for relative in ['native/gpu/xnu','native/gpu/vendor','native/gpu/uefi']:
 shutil.copytree(P/relative,S/relative)
(S/'tests').mkdir(exist_ok=True)
for name in ['check-houji-gpu-external-canary-probe.py','check-houji-gpu-handoff-probe.py','gpu-probe-fixture.h']:
 if (P/'tests'/name).exists():shutil.copy2(P/'tests'/name,S/'tests'/name)
# Include any fixture header the untouched producer needs.
for pattern in ['*.h','*.c']:
 for src in (P/'tests').glob(pattern):shutil.copy2(src,S/'tests'/src.name)
source=(S/'tests/check-houji-gpu-external-canary-probe.py').read_text()
ns={'__file__':str(S/'tests/check-houji-gpu-external-canary-probe.py')}
exec(compile(source.split("with tempfile.TemporaryDirectory(prefix='houji-external-canary-')")[0],str(S/'tests/check-houji-gpu-external-canary-probe.py'),'exec'),ns)
prefix,cpu,mmio,peer=(ns[k] for k in ['prefix','cpu','mmio','peer'])
A,X,V,U=(ns[k] for k in ['A','X','V','U'])
prefix='#include <cstdint>\nstatic void host_pmap_hook(uint32_t,unsigned);\nstatic int nc_boot_value=1;static bool nc_boot_present=true;\n'+prefix
prefix=prefix.replace('uint64_t gPhysBase=0x10000000,gPhysSize=0x100000000','uint64_t gPhysBase=UINT64_C(0x800000000),gPhysSize=UINT64_C(0x800000000)')
prefix=prefix.replace('return pa;}','return UINT64_C(0xffff000000000000)|pa;}')
prefix=prefix.replace('pmap_writes.push_back({pn,attr});','host_pmap_hook(pn,attr);pmap_writes.push_back({pn,attr});')
mmio=mmio.replace('*(int*)out=0;return false;','if(nc_boot_present)*(int*)out=nc_boot_value;return nc_boot_present;')
# Derive AT from the actual IOKit allocation and pmap boundary, never info PA.
a=peer.index('static bool houjiGpuExternalAt(');b=peer.index('static void external_cache_hook(',a)
peer=peer[:a]+r'''
static unsigned alias_fault,bad_par_at,nc_shareability=0,alias_at_calls;
static unsigned change_alias_commit,change_attr_commit,change_alias_acquire,change_attr_acquire,nc_data_dc,nc_pretransition_lines,nc_barrier_calls;
static bool alias_wb=true,nc_no_cpu_dma_write;
static bool houjiGpuExternalAt(uint64_t va,bool write,uint64_t*par){
 CHECK(par);++at_calls;const bool alias=(va>>48)==0xffff;if(alias)++alias_at_calls;
 auto&p=gHoujiGpuExternalCanary;
 for(auto*d:fixture.live){
  uint64_t begin=alias?(UINT64_C(0xffff000000000000)|d->physical_base):(uint64_t)(uintptr_t)d->raw;
  if(va<begin || va-begin>=d->bytes)continue;
  uint64_t pa=d->physical_base+va-begin;unsigned attr=(alias && alias_wb)?0xff:attributes[(ppnum_t)(pa>>14)]==VM_WIMG_WCOMB?0x44:attributes[(ppnum_t)(pa>>14)]==VM_WIMG_DEFAULT?0xff:0;
  if(alias && alias_fault==1)attr=0;if(alias && alias_fault==2)attr=0x55;
  if(alias && alias_fault==4 && write)attr=attr==0xff?0x44:0xff;
  const unsigned share=attr==0x44?nc_shareability:3u;
  *par=((uint64_t)attr<<56)|(pa&UINT64_C(0x0000fffffffff000))|0x800|((uint64_t)share<<7);
  if(alias && alias_fault==3)*par^=UINT64_C(1)<<12;
  if(at_calls==fail_at)*par=1;if(at_calls==bad_par_at)*par^=UINT64_C(1)<<56;
  if(fail_cpu_cache && p.result.phase==GEC_PHASE_CPU_FINISH)cpu_ctr=UINT64_C(11)<<16;
  return true;
 }CHECK(false);return false;
}
static void host_pmap_hook(uint32_t pn,unsigned attr){
 auto&p=gHoujiGpuExternalCanary;CHECK(attr==VM_WIMG_WCOMB && !p.held_mask && !p.published_mask && stores.empty());
 for(auto*d:fixture.live)if((d->physical_base>>14)==pn){
  CHECK(pn!=(p.info[GECN_TABLE].pa>>14));
  unsigned lines=0;for(auto&c:cache_lines)if(c.address>=(uintptr_t)d->raw && c.address-(uintptr_t)d->raw<d->bytes && c.operation==1)++lines;
  CHECK(lines==256 && !preemption_depth);nc_pretransition_lines+=lines;
  for(auto&bo:p.bo)CHECK(!bo.deviceReferences());return;
 }CHECK(false);
}
''' +peer[b:]
# Capture any attempt to use WB cache invalidation for NC data as a failure.
peer=peer.replace('CHECK(!(address&63));','CHECK(!(address&63));\n  if(i!=GECN_TABLE && p.bo[i].writeCombined()){++nc_data_dc;CHECK(false);}')
# Actual DMA peer: NC writes become visible at its descriptor mapping, while
# WB data continues to require cache invalidation in the original suite.
peer=peer.replace('// CPU mapping still holds stale seed until the actual adapter invalidates.\n CHECK(((uint32_t*)p.memory.owned.data)[2]==0);++expose_data_reads;', '''// Peer performs the DMA store against NC memory itself. No invalidate hook copies it.
 if(p.memory_profile==GEC_MEMORY_NORMAL_NC){
  if(!nc_no_cpu_dma_write)memcpy((unsigned char*)p.memory.owned.data+8,&value,4);
  CHECK(((uint32_t*)p.memory.owned.data)[2]==(nc_no_cpu_dma_write?0:value));
 }else CHECK(((uint32_t*)p.memory.owned.data)[2]==0);++expose_data_reads;''')
peer=peer.replace('if(padding_damage)dram[1][4096]^=1;if(zero_damage)dram[2][0]^=1;', '''if(padding_damage){dram[1][4096]^=1;((unsigned char*)p.memory.owned.data)[4096]^=1;}
 if(zero_damage){dram[2][0]^=1;((unsigned char*)p.memory.zero_cpu)[0]^=1;}''')
peer=peer.replace('static void houjiGpuExternalNcPublishBarrier(){CHECK(false);}\nstatic void houjiGpuExternalNcAcquireBarrier(){CHECK(false);}',r'''
static void houjiGpuExternalNcPublishBarrier(){
 ++barriers;++nc_barrier_calls;auto&p=gHoujiGpuExternalCanary;auto&r=p.result;
 if(r.phase==GEC_PHASE_BACKUP_COMMIT){
  CHECK(!p.held_mask && !p.release_seen && p.memory_profile==GEC_MEMORY_NORMAL_NC);
  unsigned i=(p.nc_published&(1u<<GECN_DATA))?GECN_ZERO:GECN_DATA;
  CHECK(p.bo[i].writeCombined() && !p.bo[i].deviceReferences());
  dram[i].assign((unsigned char*)p.bo[i].mapping(),(unsigned char*)p.bo[i].mapping()+p.bo[i].ownedBytes());++publication_count;
 }else{
  CHECK(r.phase==GEC_PHASE_CPU_FINISH && p.cpu_access_allowed && houjiGpuExternalIsolated());
  CHECK(((uint32_t*)p.memory.owned.data)[2]==0);memcpy(dram[1].data(),p.memory.owned.data,16384);
 }
}
static void houjiGpuExternalNcAcquireBarrier(){
 ++barriers;++nc_barrier_calls;auto&p=gHoujiGpuExternalCanary;
 CHECK(p.result.phase==GEC_PHASE_CPU_FINISH && p.cpu_access_allowed && p.cpu_finish_called && houjiGpuExternalIsolated());
 if(change_alias_acquire)alias_wb=false;if(change_attr_acquire)attributes[(ppnum_t)(p.info[GECN_DATA].pa>>14)]=VM_WIMG_DEFAULT;
 // This is ordering only: deliberately no stale-WB-copy invalidation or memcpy.
}
''')
peer=peer.replace('discardHostAfterReset();memset((void*)&gHoujiGpuExternalCanary,0,sizeof(gHoujiGpuExternalCanary));','discardHostAfterReset();memset((void*)&gHoujiGpuExternalCanary,0,sizeof(gHoujiGpuExternalCanary));\n nc_boot_value=1;nc_boot_present=true;gPhysBase=UINT64_C(0x800000000);gPhysSize=UINT64_C(0x800000000);alias_fault=bad_par_at=alias_at_calls=change_alias_commit=change_attr_commit=change_alias_acquire=change_attr_acquire=nc_data_dc=nc_pretransition_lines=nc_barrier_calls=0;nc_shareability=0;alias_wb=true;nc_no_cpu_dma_write=false;')
peer=peer.replace('if(checkpoint_calls==fail_commit)throw SimulatedTerminalPanic{};', '''if(checkpoint_calls==change_alias_commit)alias_wb=!alias_wb;
 if(checkpoint_calls==change_attr_commit)attributes[(ppnum_t)(p.info[GECN_DATA].pa>>14)]=VM_WIMG_DEFAULT;
 if(checkpoint_calls==fail_commit)throw SimulatedTerminalPanic{};''')
# Keep the original failure suite intact except profile-specific observations.
peer=peer.replace('pmap_writes.empty()', 'pmap_writes.size()==2 && nc_pretransition_lines==512 && !nc_data_dc && p.nc_published==6 && p.nc_acquired==6 && p.nc_restored && p.nc_publish_barriers==3 && p.nc_acquire_barriers==2')
peer=peer.replace('p.cpu_invalidated && p.cpu_restored','!p.cpu_invalidated && !r.cpu.invalidated && r.nc_acquired==6 && r.nc_table_invalidated==1 && r.nc_restore_published==1 && p.cpu_restored')
peer=peer.replace('invalidate_count==3*256','invalidate_count==256').replace('CHECK(bytes<24000)','CHECK(bytes<42000)')
# NC adds AT qualification after acquire/restore, so a late AT refusal can
# happen after entering CPU finish. Only this exhaustive AT-failure loop has
# a broader entry allowance; unsafe/unknown execution matrices retain every
# original !cpu_finish_called assertion from the independent WB suite.
at_loop='for(unsigned n=1;n<=ats;n++){reset();fail_at=n;CHECK(!contract() && !r.safe_to_save && !fixture.released && !p.cpu_finish_called);++cases;}'
assert peer.count(at_loop)==1
peer=peer.replace(at_loop,at_loop.replace(' && !p.cpu_finish_called',''))
# This runner's inherited baseline is NC; the independent WB runner requires
# all four appended result fields to stay zero.
peer=peer.replace('CHECK(!r.memory_profile && !r.nc_acquired && !r.nc_restore_published && !r.nc_table_invalidated);', 'CHECK(r.memory_profile==1 && r.nc_acquired==6 && r.nc_restore_published==1 && r.nc_table_invalidated==1);',1)
# Additional NC-specific acceptance/failure profiles follow all inherited cases.
marker=' printf("PASS: %u actual external-canary'
extra=r'''
 for(int invalid:{-1,2,17}){reset();nc_boot_value=invalid;CHECK(!contract() && !chosen_lookups && !fixture.created && stores.empty());++cases;}
 reset();nc_boot_present=false;CHECK(contract() && p.memory_profile==GEC_MEMORY_WRITEBACK && pmap_writes.empty() && invalidate_count==768 && !nc_barrier_calls && !r.memory_profile && !r.nc_acquired && !r.nc_restore_published && !r.nc_table_invalidated);++cases;
 reset();nc_boot_value=0;CHECK(contract() && p.memory_profile==GEC_MEMORY_WRITEBACK && pmap_writes.empty() && invalidate_count==768 && !nc_barrier_calls && !r.memory_profile && !r.nc_acquired);++cases;
 for(unsigned sh:{0u,2u,3u}){reset();nc_shareability=sh;CHECK(contract() && p.memory_profile==GEC_MEMORY_NORMAL_NC && !nc_data_dc && nc_barrier_calls==5 && alias_at_calls && r.safe_to_save);++cases;}
 reset();nc_shareability=1;CHECK(!contract() && !r.safe_to_save && !p.release_seen);++cases;
 reset();alias_wb=false;CHECK(contract() && p.info[1].alias_nc==4 && !p.info[1].alias_wb && !nc_data_dc);++cases;
 for(unsigned fault=1;fault<=4;fault++){reset();alias_fault=fault;CHECK(!contract() && !r.safe_to_save && !p.release_seen && !p.held_mask);++cases;}
 for(unsigned stage:{1u,2u}){reset();change_alias_commit=stage;CHECK(!contract() && !p.release_seen && !r.safe_to_save && !p.cpu_finish_called);++cases;reset();change_attr_commit=stage;CHECK(!contract() && !p.release_seen && !r.safe_to_save);++cases;}
 for(unsigned kind:{1u,2u}){reset();if(kind==1)change_alias_acquire=1;else change_attr_acquire=1;CHECK(!contract() && p.cpu_finish_called && !r.cpu.checked_words && !r.cpu.verified && !r.safe_to_save);++cases;}
 for(unsigned kind=0;kind<5;kind++){reset();const uint64_t begin=fixture.next_physical;
  if(kind==0)gPhysBase=begin+1;if(kind==1)gPhysSize=begin-gPhysBase+16383;
  if(kind==2)gPhysBase=UINT64_MAX-15;if(kind==3)gPhysSize=0;if(kind==4)gPhysSize=UINT64_MAX;
  CHECK(!contract() && !p.release_seen && !r.safe_to_save && !p.held_mask);++cases;
 }
 for(unsigned n:{1u,16u,17u,64u,128u,256u,512u,656u}){reset();bad_par_at=n;CHECK(!contract() && !r.safe_to_save && !fixture.released);++cases;}
 for(unsigned attempt:{1u,2u}){reset();attribute_write_fail=attempt;CHECK(!contract() && !p.release_seen && !r.safe_to_save && !p.held_mask && p.bo[attempt].quarantined());++cases;}
 reset();nc_no_cpu_dma_write=true;CHECK(!contract() && p.cpu_finish_called && !r.cpu.verified && !r.safe_to_save && invalidate_count==256 && !nc_data_dc);++cases;
 // Explicit final profile: one NC leaf; no PRR zero IOVA/leaf. Table walks WB.
 reset();CHECK(contract() && p.memory.memory_profile==GEC_MEMORY_NORMAL_NC && p.memory.owned.range.writeback==0 && p.memory.owned.built.mair==0xff44 && !device_walk(0x60002000));
 CHECK(!p.bo[GECN_TABLE].writeCombined() && p.bo[GECN_DATA].writeCombined() && p.bo[GECN_ZERO].writeCombined() && p.nc_published==6 && p.nc_acquired==6 && !nc_data_dc && nc_pretransition_lines==512 && nc_barrier_calls==5 && p.wb_invalidated_mask==1 && !r.cpu.invalidated && !p.cpu_invalidated && r.memory_profile==1 && r.nc_acquired==6 && r.nc_restore_published==1 && r.nc_table_invalidated==1);
 CHECK(p.memory.zero_physical==p.info[GECN_ZERO].pa && p.memory.owned.built.leaf_pages==1 && p.held_mask==7 && !fixture.released);++cases;
'''
peer=peer.replace(marker,extra+marker,1)
peer=peer.replace('actual external-canary Native/Memory/Cpu/Build/Audit/core cases','NormalNC actual Native/Memory/Cpu/Build/Audit/core cases')
peer=peer.replace('separate CPU/DRAM peers, no hardware qualification','NC DMA visible without data invalidate, alias AT only; no hardware qualification')
(B/'XnuMemoryFixture.h').write_text((A/'tests/XnuMemoryFixture.h').read_text())
for name in ['IOKit/IOTypes.h','IOKit/IOBufferMemoryDescriptor.h','IOKit/IOLib.h','kern/task.h','kern/cpu_data.h','vm/vm_map.h','mach/vm_param.h','kern/clock.h','vm/memory_types.h']:
 out=B/name;out.parent.mkdir(parents=True,exist_ok=True);out.write_text('#include "XnuMemoryFixture.h"\n')
flags=['-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer']
commands=[]
def run(cmd):
 commands.append(cmd);r=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'});print(r.stdout,end='');return r
objects=[]
for name in ['ArmSmmu4K','ArmSmmu4KAudit','ArmSmmu4KContext','ArmSmmu4KProgram']:
 obj=B/(name+'.o');r=run(['clang','-std=c11',*flags,'-I',str(V),'-c',str(V/(name+'.c')),'-o',str(obj)]);assert not r.returncode;objects.append(str(obj))
c=B/'producer.c';c.write_text(ns['producer']);obj=B/'producer.o';r=run(['clang','-std=c11',*flags,'-I',str(U),'-I',str(S/'tests'),'-c',str(c),'-o',str(obj)]);assert not r.returncode;objects.append(str(obj))
cpp=B/'probe.cpp';cpp.write_text(prefix+cpu+(A/'NativeAdrenoMemory.cpp').read_text()+mmio+peer)
exe=B/'probe';r=run(['clang++','-std=c++17',*flags,'-DPAGE_SIZE=16384','-I',str(B),'-I',str(A/'tests'),'-I',str(A),'-I',str(X),'-I',str(V),'-I',str(U),str(cpp),*objects,'-o',str(exe)])
(B/'compile-output.txt').write_text(r.stdout)
if r.returncode:raise SystemExit(r.returncode)
r=run([str(exe)]);(B/'test-output.txt').write_text(r.stdout)
manifest={'scope':'offline host peer; real Native Memory/Cpu/adapter/core compiled; no device or actual XNU execution','exit_code':r.returncode,'commands':commands,'sha256':{str(p.relative_to(S)):hashlib.sha256(p.read_bytes()).hexdigest() for p in S.rglob('*') if p.is_file()},'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'boundary_replacements':['MRS','DC','DSB','AT','IOKit/pmap','MMIO device peer'],'nc_visibility':'NC peer DMA stores update descriptor NC mapping directly; NC acquire never copies DRAM from a WB invalidation hook; data DC after conversion aborts'}
(B/'verification.json').write_text(json.dumps(manifest,indent=2)+'\n')
raise SystemExit(r.returncode)
