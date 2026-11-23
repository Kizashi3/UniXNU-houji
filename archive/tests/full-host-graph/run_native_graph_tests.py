#!/usr/bin/env python3
"""Real full-graph C + Native Memory/Cpu; only IOKit/architecture peers.
No kernel build, firmware boot, phone, MMIO, SMC or GPU execution.
"""
from pathlib import Path
import ast, hashlib, json, os, shutil, subprocess
HERE=Path(__file__).resolve().parent
P=Path('${HOUJI_PORT_ROOT}')
C=P/'native/gpu/xnu/full-host-graph'
A=P/'native/gpu/xnu/Adreno740'
B=HERE/'build/native';B.mkdir(parents=True,exist_ok=True)
tree=ast.parse((A/'tests/check_page_geometry.py').read_text())
prefix=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='prefix')
prefix=prefix.replace('uint64_t gPhysBase=0x10000000,gPhysSize=0x100000000','uint64_t gPhysBase=UINT64_C(0x8c0000000),gPhysSize=UINT64_C(0x200000000)')
prefix=prefix.replace('return pa;}','return UINT64_C(0xffff000000000000)|pa;}')
prefix=prefix.replace('constexpr IOReturn kIOReturnNotFound=9;','').replace('constexpr unsigned kIOMapAnywhere=1,kIOMapInhibitCache=2;','')
cpu=(A/'NativeAdrenoCpu.cpp').read_text()
for field,reg in [('tcr','tcr_el1'),('ttbr0','ttbr0_el1'),('ttbr1','ttbr1_el1'),('sctlr','sctlr_el1')]:
 old=f'__asm__ volatile("mrs %0, {reg}" : "=r"(out->{field}));';assert old in cpu;cpu=cpu.replace(old,f'out->{field}=cpu_{field};')
old='__asm__ volatile("mrs %0, ctr_el0":"=r"(ctr));';assert cpu.count(old)==2;cpu=cpu.replace(old,'ctr=cpu_ctr;')
for op,value in [('cvac',0),('civac',1),('ivac',2)]:
 old=f'__asm__ volatile("dc {op}, %0"::"r"(address):"memory");';assert cpu.count(old)==2;cpu=cpu.replace(old,f'cache_line(address,{value});')
cpu=cpu.replace('__asm__ volatile("dsb sy":::"memory");','++barriers;');assert '__asm__' not in cpu
source=prefix+cpu+(A/'NativeAdrenoMemory.cpp').read_text()+r'''
#include <memory>
#include <fstream>
#include <string>
#define HOUJI_FULL_HOST_NATIVE_HOST_TEST 1
#include "HoujiFullHostNativeMemory.h"
static unsigned full_at,full_fail_at,full_bad_alias,full_barriers;
static bool houjiFullHostAt(uint64_t va,bool write,uint64_t*out){
 ++full_at;const bool alias=(va>>48)==0xffff;
 for(auto*d:fixture.live){
  uint64_t start=alias?(UINT64_C(0xffff000000000000)|d->physical_base):(uintptr_t)d->raw;
  if(va<start || va-start>=d->bytes)continue;
  const uint64_t pa=d->physical_base+va-start;
  const unsigned shift=PAGE_SIZE==16384?14:12;
  unsigned attr=alias?0xff:attributes[(ppnum_t)(pa>>shift)]==VM_WIMG_WCOMB?0x44:0xff;
  if(alias && full_bad_alias)attr=write?0x44:0xff;
  *out=((uint64_t)attr<<56)|(pa&UINT64_C(0x0000fffffffff000))|0x800|(attr==0xff?0x180:0);
  if(full_at==full_fail_at)*out=1;
  return true;
 }return false;
}
static void houjiFullHostBarrier(){++full_barriers;}
static std::vector<uint8_t> read_file(const char*path){
 std::ifstream in(path,std::ios::binary);CHECK(in.good());return std::vector<uint8_t>(std::istreambuf_iterator<char>(in),{});
}
static void reset(){
 CHECK(fixture.live.empty() && fixture.metadata.empty());fixture=MemoryFixture{};
 fixture.cpu_page_bytes=PAGE_SIZE;fixture.next_physical=UINT64_C(0x8c1000000);
 page_size=map_page_bytes=PAGE_SIZE;cpu_tcr=PAGE_SIZE==16384?(UINT64_C(2)<<14|UINT64_C(1)<<30):(UINT64_C(2)<<30);
 cpu_ttbr0=0x30000000;cpu_ttbr1=0x30004000;cpu_sctlr=1;cpu_ctr=UINT64_C(4)<<16;
 attributes.clear();pmap_writes.clear();cache_lines.clear();attribute_write_fail=barriers=0;
 full_at=full_fail_at=full_bad_alias=full_barriers=0;
}
static void discard_after_host_reset(){
 // Host peer teardown only. Production retains descriptors and refs until reset.
 while(!fixture.live.empty())fixture.live.back()->release();
 while(!fixture.metadata.empty())fixtureMetadataFree(fixture.metadata.back());
}
static FhgConfig config(){FhgConfig c{};c.abi_version=FHG_ABI_VERSION;c.cpu_page_bytes=PAGE_SIZE;return c;}
static std::vector<uint8_t> gmu,sqe,aqe;
static unsigned cases;
static void attempt(unsigned fault){
 reset();auto memory=std::make_unique<HoujiFullHostNativeMemory>();auto storage=std::make_unique<FhgStorage>();*storage={};
 HoujiFullHostNativeMemory::Span foreign{};unsigned count=0;
 if(fault==8){foreign={UINT64_C(0xffff100000000000),fixture.next_physical,16384};count=1;}
 CHECK(memory->begin(count?&foreign:nullptr,count));CHECK(!memory->begin(nullptr,0));
 auto ops=memory->callbacks();auto cfg=config();CHECK(!fhg_init(storage.get(),sizeof(*storage),&cfg,sizeof(cfg),&ops,sizeof(ops)));
 if(fault==1)fixture.contiguous_limit=1024*1024;
 if(fault==2)full_fail_at=1;
 if(fault==3)full_bad_alias=1;
 if(fault==4)fixture.null_mapping=true;
 if(fault==5)fixture.mode=HighPhysical;
 if(fault==6)attribute_write_fail=1;
 if(fault==7)fixture.mode=ZeroPhysical;
 uint32_t code=999;CHECK(!fhg_prepare(storage.get(),sizeof(*storage),gmu.data(),gmu.size(),sqe.data(),sqe.size(),aqe.data(),aqe.size(),&code));
 FhgSummary summary{};CHECK(!fhg_summary(storage.get(),sizeof(*storage),&summary,sizeof(summary)));
 if(fault && fault<=8){CHECK(code && !summary.ready && !memory->prepared());memory->retainFailure();for(unsigned i=0;i<memory->count();i++)if(memory->bo(i).backed())CHECK(memory->bo(i).quarantined());}
 else {
  CHECK(!code && summary.ready && summary.allocated==FHG_ALL && summary.validated==FHG_ALL && summary.published==FHG_ALL && summary.retained==FHG_ALL && !summary.uncertain_outputs);
  CHECK(memory->count()==15 && memory->publishes()==15 && full_barriers==15);
  FhgGraph graph{};CHECK(!fhg_graph(storage.get(),sizeof(*storage),1,&graph,sizeof(graph)));
  CHECK(graph.range_count==12 && graph.table_pages==7 && graph.leaf_pages==1567 && graph.audit_complete && graph.root_physical>=UINT64_C(0x8c0000000));
  for(unsigned i=0;i<15;i++){
   const auto&e=memory->entry(i);CHECK(memory->bo(i).deviceReferences()==0 && !memory->bo(i).quarantined());
   CHECK(e.rows==e.request.owned_bytes/4096 && e.request.cpu_page_bytes==PAGE_SIZE);
   FhgRow row{};CHECK(!fhg_row(storage.get(),sizeof(*storage),i,&row,sizeof(row)) && row.backing.cpu==e.backing.cpu && row.backing.physical==e.backing.physical);
  }
  if(fault==9){const auto&e=memory->entry(14);CHECK(e.request.owned_bytes>e.request.logical_bytes);static_cast<uint8_t*>(e.backing.cpu)[e.request.logical_bytes]=1;}
  if(fault==10){const auto&e=memory->entry(12);attributes[(ppnum_t)(e.backing.physical>>(PAGE_SIZE==16384?14:12))]=VM_WIMG_DEFAULT;}
  if(fault==11)CHECK(!const_cast<NativeAdrenoMemory&>(memory->bo(12)).holdForDevice());
  if(fault==12)full_bad_alias=1;
  const unsigned before_writes=pmap_writes.size(),before_publications=memory->publishes();
  uint32_t verify=999;
  if(fault==13){CHECK(!const_cast<NativeAdrenoMemory&>(memory->bo(12)).holdForDevice());CHECK(!memory->sealPrepared(*storage) && memory->failure().code==16);}
  if(fault==14){static_cast<uint8_t*>(memory->entry(13).backing.cpu)[4096]^=1;CHECK(!memory->sealPrepared(*storage) && memory->failure().code==17);}
  if(fault<13)CHECK(!fhg_verify(storage.get(),sizeof(*storage),&verify));
  CHECK(pmap_writes.size()==before_writes && memory->publishes()==before_publications);
  if(fault>=9){CHECK(verify && !memory->sealPrepared(*storage) && !memory->prepared());memory->retainFailure();if(fault==11 || fault==13)CHECK(memory->bo(12).deviceReferences()==1);}
  else {
   CHECK(!verify && memory->sealPrepared(*storage) && memory->prepared());CHECK(!memory->sealPrepared(*storage));
   auto fresh=memory->callbacks();FhgBacking out{};CHECK(fresh.allocate(fresh.cookie,&memory->entry(0).request,&out));
  }
 }
 uint32_t again=987;CHECK(fhg_prepare(storage.get(),sizeof(*storage),gmu.data(),gmu.size(),sqe.data(),sqe.size(),aqe.data(),aqe.size(),&again)==FHG_ALREADY_PREPARED && again==987);
 memory.reset();storage.reset();discard_after_host_reset();++cases;
}
int main(int argc,char**argv){
 CHECK(argc==4);gmu=read_file(argv[1]);sqe=read_file(argv[2]);aqe=read_file(argv[3]);
 for(unsigned fault=0;fault<=14;fault++){if(PAGE_SIZE==4096 && fault==9)continue;attempt(fault);}
 printf("PASS: CPU%u real Native/full-graph %u integrated profiles; full15BO/12GPUrange/7table/1567leaf, full-owned PAR+alias AT, no MMIO/SMC/exec/refs/phone\n",PAGE_SIZE,cases);
}
'''
(B/'probe.cpp').write_text(source)
shutil.copy2(A/'tests/XnuMemoryFixture.h',B/'XnuMemoryFixture.h')
for name in ['IOKit/IOTypes.h','IOKit/IOBufferMemoryDescriptor.h','IOKit/IOLib.h','kern/task.h','kern/cpu_data.h','vm/vm_map.h','mach/vm_param.h','kern/clock.h','vm/memory_types.h']:
 f=B/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('#include "XnuMemoryFixture.h"\n')
V=P/'native/gpu/vendor';U=P/'native/gpu/uefi'
flags=['-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=address,undefined','-fno-omit-frame-pointer']
inc=['-I',str(C),'-I',str(C),'-I',str(B),'-I',str(P/'native/gpu/xnu'),'-I',str(A),'-I',str(P/'native/gpu'),'-I',str(U)]
commands=[];outputs=[]
def run(cmd):
 commands.append(cmd);r=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'});print(r.stdout,end='');outputs.append(r.stdout)
 if r.returncode:raise SystemExit(r.returncode)
objects=[]
for src in [C/'houji_native_full_host_graph.c',V/'AdrenoFirmware/AdrenoFirmware.c',*[V/'ArmSmmu4K'/f'{n}.c' for n in ['ArmSmmu4K','ArmSmmu4KAudit','ArmSmmu4KContext','ArmSmmu4KProgram']]]:
 obj=B/(src.stem+'.o');run(['clang','-std=c11',*flags,*inc,'-c',str(src),'-o',str(obj)]);objects.append(str(obj))
fw=Path('${HOUJI_ARTIFACTS}/native-research/houji-gpu-firmware-20261025')
for page in [4096,16384]:
 exe=B/f'probe-{page}';run(['clang++','-std=c++17',*flags,*inc,f'-DPAGE_SIZE={page}',str(B/'probe.cpp'),str(A/'NativeAdrenoSha256.cpp'),*objects,'-o',str(exe)])
 run([str(exe),str(fw/'gmu_gen70900.bin'),str(fw/'gen70900_sqe.fw'),str(fw/'gen70900_aqe.fw')])
proof={'hardware_tested':False,'scope':'real Native Memory/Cpu/full graph; IOKit and architecture peers only, no device','commands':commands,'sources':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [C/'HoujiFullHostNativeMemory.h',C/'houji_native_full_host_graph.h',C/'houji_native_full_host_graph.c',A/'NativeAdrenoMemory.cpp',A/'NativeAdrenoCpu.cpp']}}
(B/'verification.json').write_text(json.dumps(proof,indent=2)+'\n');(B/'output.txt').write_text(''.join(outputs))
