#!/usr/bin/env python3
"""Actual CPU-only memory probe and frozen NativeAdreno Memory/Cpu bodies.

Only architectural register/cache/AT and IOKit/pmap peers are replaced. No GPU
or live XNU qualification is inferred from these ASAN/UBSAN host tests.
"""
from pathlib import Path
import ast
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
XNU = PROJECT / 'native/gpu/xnu'
CANDIDATE = XNU / 'Adreno740'
FIXTURES = CANDIDATE / 'tests'
tree = ast.parse((FIXTURES / 'check_page_geometry.py').read_text())
prefix = next(node.value.value for node in tree.body
              if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
              and any(isinstance(target, ast.Name) and target.id == 'prefix' for target in node.targets))
prefix = '#include <cstdint>\nstatic void mem_probe_cache_hook(uintptr_t,unsigned);\nstatic void mem_probe_attr_write(uint32_t,unsigned);\nstatic unsigned mem_probe_attr_read(uint32_t);\n' + prefix
prefix = prefix.replace('constexpr IOReturn kIOReturnNotFound=9;\n', '')
prefix = prefix.replace('constexpr unsigned kIOMapAnywhere=1,kIOMapInhibitCache=2;\n', '')
assert prefix.count('cache_lines.push_back({address,op});') == 1
prefix = prefix.replace('cache_lines.push_back({address,op});',
                        'cache_lines.push_back({address,op});mem_probe_cache_hook(address,op);')
assert prefix.count('attributes[pn]=attr;') == 1
prefix = prefix.replace('attributes[pn]=attr;', 'attributes[pn]=attr;mem_probe_attr_write(pn,attr);')
assert prefix.count('return attributes[pn];') == 1
prefix = prefix.replace('return attributes[pn];', 'return mem_probe_attr_read(pn);')
cpu = (CANDIDATE / 'NativeAdrenoCpu.cpp').read_text()
for field, reg in [('tcr', 'tcr_el1'), ('ttbr0', 'ttbr0_el1'), ('ttbr1', 'ttbr1_el1'), ('sctlr', 'sctlr_el1')]:
    old = f'__asm__ volatile("mrs %0, {reg}" : "=r"(out->{field}));'
    assert old in cpu
    cpu = cpu.replace(old, f'out->{field}=cpu_{field};')
old = '__asm__ volatile("mrs %0, ctr_el0":"=r"(ctr));'
assert cpu.count(old) == 2
cpu = cpu.replace(old, 'ctr=cpu_ctr;')
for operation, value in [('cvac', 0), ('civac', 1), ('ivac', 2)]:
    old = f'__asm__ volatile("dc {operation}, %0"::"r"(address):"memory");'
    assert cpu.count(old) == 2
    cpu = cpu.replace(old, f'cache_line(address,{value});')
cpu = cpu.replace('__asm__ volatile("dsb sy":::"memory");', '++barriers;')
assert '__asm__' not in cpu

peer = r'''
#include <cstdarg>
#include <string>
static std::vector<std::string> logs;
static void IOLog(const char *format,...){char buffer[2048];va_list ap;va_start(ap,format);int n=vsnprintf(buffer,sizeof(buffer),format,ap);va_end(ap);CHECK(n>=0 && (size_t)n<sizeof(buffer));logs.emplace_back(buffer);}
static int boot_arg=1;
static bool PE_parse_boot_argn(const char *name,void *value,int bytes){CHECK(!strcmp(name,"houji_gpu_mem_probe") && bytes==sizeof(int));*(int*)value=boot_arg;return true;}
#define HOUJI_GPU_MEMORY_PROBE_HOST_TEST 1
#include "HoujiGpuMemoryProbe.inc"
enum Fault {None,Geometry,WalkDisabled,AllocFirst,AllocSecond,InitialAttr,ZeroFirst,ZeroSecond,Alias,AtPa,AtCpu,WcWrite,NeighborAttr,Reassert,NeighborPattern,ReleaseFirst,ReleaseRestore,ReleaseSecond,FinalNeighborAttr};
static Fault fault=None;static unsigned at_calls,at_fail;
static bool houjiGpuMemoryAt(uint64_t va,bool write,uint64_t *par){
 CHECK(par);++at_calls;auto&p=gHoujiGpuMemoryProbe;
 for(unsigned i=0;i<HGMP_BOS;++i){auto&bo=p.bo[i];uint64_t base=(uint64_t)(uintptr_t)bo.mapping();
  if(!base || va<base || va-base>=bo.ownedBytes())continue;
  uint64_t pa=bo.ownedSpans()[0].physical+va-base;
  *par=UINT64_C(0x4400000000000000)|(pa&UINT64_C(0x0000fffffffff000));
  if(at_fail==at_calls)*par=1;
  if(fault==AtPa && at_calls==1)*par^=4096;
  if(fault==AtCpu && at_calls==1)return false;
  if(at_calls==8){if(fault==AllocSecond)fixture.allocation_fail=true;if(fault==Alias)fixture.next_physical=bo.ownedSpans()[0].physical;if(fault==ZeroFirst)((unsigned char*)bo.mapping())[0]=1;}
  if(at_calls==16 && fault==ZeroSecond)((unsigned char*)bo.mapping())[0]=1;
  if(at_calls==24 && fault==Reassert)attributes[(ppnum_t)(p.info[0].owned_pa>>14)]=7;
  (void)write;return true;
 }
 CHECK(false);return false;
}
static void mem_probe_cache_hook(uintptr_t,unsigned op){
 auto&p=gHoujiGpuMemoryProbe;
 if(fault==NeighborPattern && p.phase==6 && op==1)((unsigned char*)p.bo[1].mapping())[0]=0;
}
static void mem_probe_attr_write(uint32_t,unsigned attr){
 if(fault==NeighborAttr && gHoujiGpuMemoryProbe.phase==5 && attr==VM_WIMG_WCOMB)
  attributes[(ppnum_t)(gHoujiGpuMemoryProbe.info[1].owned_pa>>14)]=VM_WIMG_WCOMB;
}
static unsigned mem_probe_attr_read(uint32_t pn){
 if(gHoujiGpuMemoryProbe.phase==8){if(fault==ReleaseSecond)fixture.complete_fail=true;if(fault==FinalNeighborAttr)return 7;}
 return attributes[pn];
}
static void discardHostOnly(){
 while(!fixture.live.empty())fixture.live.back()->release();
 while(!fixture.metadata.empty())fixtureMetadataFree(fixture.metadata.back());
}
static void reset(Fault f=None,unsigned fail_at=0){
 CHECK(!preemption_depth && fixture.live.empty() && fixture.metadata.empty());
 fixture=MemoryFixture{};fixture.cpu_page_bytes=PAGE_SIZE;attributes.clear();pmap_writes.clear();cache_lines.clear();logs.clear();
 void*state=&gHoujiGpuMemoryProbe;memset(state,0,sizeof(gHoujiGpuMemoryProbe));gHoujiGpuMemoryProbeOnce=0;
 page_size=map_page_bytes=PAGE_SIZE;cpu_tcr=PAGE_SIZE==16384?(UINT64_C(2)<<14|UINT64_C(1)<<30):(UINT64_C(2)<<30);cpu_ttbr0=0x30000000;cpu_ttbr1=0x30004000;cpu_sctlr=1;cpu_ctr=UINT64_C(4)<<16;
 boot_arg=1;fault=f;at_calls=0;at_fail=fail_at;attribute_write_fail=barriers=0;
 if(f==Geometry)page_size=4096;if(f==WalkDisabled)cpu_tcr|=UINT64_C(1)<<23;
 if(f==AllocFirst)fixture.allocation_fail=true;if(f==InitialAttr)attributes[(ppnum_t)(fixture.next_physical>>14)]=7;
 if(f==WcWrite)attribute_write_fail=1;if(f==ReleaseRestore)attribute_write_fail=2;if(f==ReleaseFirst)fixture.complete_fail=true;
}
static void stopped(unsigned expected_code,unsigned retained){
 auto&p=gHoujiGpuMemoryProbe;CHECK(p.code==expected_code && !p.completed && p.retained==retained);
 unsigned backed=0;for(auto&bo:p.bo)if(bo.backed()){CHECK(bo.quarantined());++backed;}
 CHECK(backed==retained && fixture.live.size()==retained && !preemption_depth);
 CHECK(!logs.empty() && logs.back().find("GPU-mapped=0 GPU-execution=0 DMA=0")!=std::string::npos);
 const auto allocations=fixture.created,ats=at_calls,releases=fixture.released;const auto writes=pmap_writes.size();
 houjiGpuMemoryProbeOnce();CHECK(fixture.created==allocations && at_calls==ats && pmap_writes.size()==writes && fixture.released==releases);
 discardHostOnly();
}
int main(){unsigned cases=0;
 for(int argument:{0,2}){reset();boot_arg=argument;houjiGpuMemoryProbeOnce();CHECK(!fixture.created && !at_calls && pmap_writes.empty() && logs.empty());++cases;}
 if(PAGE_SIZE==4096){reset();houjiGpuMemoryProbeOnce();stopped(HGMP_GEOMETRY,0);++cases;printf("PASS: CPU4K probe explicitly refuses 16K-only experiment (%u cases)\n",cases);return 0;}
 reset();houjiGpuMemoryProbeOnce();auto&p=gHoujiGpuMemoryProbe;
 CHECK(p.completed && !p.code && p.phase==9 && !p.retained && at_calls==24 && fixture.created==2 && fixture.completed==2 && fixture.released==2 && fixture.live.empty() && fixture.metadata.empty());
 CHECK(p.info[0].logical_bytes==4096 && p.info[0].owned_bytes==16384 && p.info[0].owned_pa!=p.info[1].owned_pa && p.info[0].released && p.info[1].released && p.neighbor_valid);
 CHECK(p.info[0].attr_sampled==3 && p.info[1].attr_sampled==7 && pmap_writes.size()==2 && pmap_writes[0].first==pmap_writes[1].first);
 CHECK(pmap_writes[0].second==VM_WIMG_WCOMB && pmap_writes[1].second==VM_WIMG_USE_DEFAULT && p.wc_rows==4);
 const auto count=logs.size();houjiGpuMemoryProbeOnce();CHECK(logs.size()==count && fixture.created==2 && at_calls==24);++cases;
 for(Fault f:{Geometry,WalkDisabled}){reset(f);houjiGpuMemoryProbeOnce();CHECK(!fixture.created && !at_calls && pmap_writes.empty());stopped(HGMP_GEOMETRY,0);++cases;}
 for(Fault f:{AllocFirst,AllocSecond}){reset(f);houjiGpuMemoryProbeOnce();CHECK(!p.wc_attempted && pmap_writes.empty());stopped(HGMP_ALLOC,f==AllocFirst?0:1);++cases;}
 reset(InitialAttr);houjiGpuMemoryProbeOnce();CHECK(!at_calls && pmap_writes.empty());stopped(HGMP_ATTRIBUTE,1);++cases;
 for(Fault f:{ZeroFirst,ZeroSecond}){reset(f);houjiGpuMemoryProbeOnce();CHECK(!p.wc_attempted && pmap_writes.empty());stopped(HGMP_ZERO,f==ZeroFirst?1:2);++cases;}
 reset(Alias);houjiGpuMemoryProbeOnce();CHECK(!p.wc_attempted && pmap_writes.empty() && !fixture.completed);stopped(HGMP_ALIAS,2);++cases;
 for(Fault f:{AtPa,AtCpu}){reset(f);houjiGpuMemoryProbeOnce();CHECK(!p.wc_attempted && pmap_writes.empty());stopped(HGMP_TRANSLATION,1);++cases;}
 for(unsigned n=1;n<=24;++n){reset(None,n);houjiGpuMemoryProbeOnce();CHECK(!p.info[0].release_attempted && !p.info[1].release_attempted);stopped(HGMP_TRANSLATION,n<=8?1:2);++cases;}
 reset(WcWrite);houjiGpuMemoryProbeOnce();CHECK(p.wc_attempted && !p.reassert_attempted && !fixture.completed && pmap_writes.size()==1);stopped(HGMP_CACHE,2);++cases;
 reset(NeighborAttr);houjiGpuMemoryProbeOnce();CHECK(p.wc_attempted && !p.reassert_attempted && !fixture.completed);stopped(HGMP_ATTRIBUTE,2);++cases;
 reset(Reassert);houjiGpuMemoryProbeOnce();CHECK(p.reassert_status==kIOReturnUnsupported && !p.info[0].release_attempted && !fixture.completed);stopped(HGMP_CACHE,2);++cases;
 reset(NeighborPattern);houjiGpuMemoryProbeOnce();CHECK(!p.neighbor_valid && !p.info[0].release_attempted && !fixture.completed);stopped(HGMP_PATTERN,2);++cases;
 for(Fault f:{ReleaseFirst,ReleaseRestore}){reset(f);houjiGpuMemoryProbeOnce();CHECK(p.info[0].release_attempted && !p.info[0].released && !p.info[1].release_attempted);stopped(HGMP_RELEASE,2);++cases;}
 reset(ReleaseSecond);houjiGpuMemoryProbeOnce();CHECK(p.info[0].released && p.info[1].release_attempted && !p.info[1].released);stopped(HGMP_RELEASE,1);++cases;
 reset(FinalNeighborAttr);houjiGpuMemoryProbeOnce();CHECK(p.info[0].released && !p.info[1].release_attempted);stopped(HGMP_PATTERN,1);++cases;
 printf("PASS: CPU16K actual Memory/Cpu/probe %u success/fail-stop/retention/AT and isolation cases (ASAN/UBSAN); CPU-only, no DMA qualification\n",cases);
}
'''

with tempfile.TemporaryDirectory(prefix='houji-xnu-memory-probe-') as directory:
    tmp = Path(directory)
    for name in ['IOKit/IOTypes.h', 'IOKit/IOBufferMemoryDescriptor.h', 'IOKit/IOLib.h', 'kern/task.h',
                 'kern/cpu_data.h', 'vm/vm_map.h', 'mach/vm_param.h', 'kern/clock.h', 'vm/memory_types.h']:
        path = tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#include "XnuMemoryFixture.h"\n')
    cpp = tmp / 'probe.cpp'
    cpp.write_text(prefix + cpu + (CANDIDATE / 'NativeAdrenoMemory.cpp').read_text() + peer)
    for page in (4096, 16384):
        exe = tmp / ('test-' + str(page))
        subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-DPAGE_SIZE=' + str(page), '-I' + str(tmp),
                        '-I' + str(FIXTURES), '-I' + str(CANDIDATE), '-I' + str(XNU), str(cpp), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
