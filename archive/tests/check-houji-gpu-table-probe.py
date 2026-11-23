#!/usr/bin/env python3
"""Actual inactive ArmSmmu4K Build/Audit + actual XNU Memory/Cpu/probe.

Only IOKit, CPU system registers/cache operations and CPU AT are host peers.
No SMMU hardware activation, GPU work or DMA qualification is inferred.
"""
from pathlib import Path
import ast
import hashlib
import json
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
XNU = PROJECT / 'native/gpu/xnu'
CANDIDATE = XNU / 'Adreno740'
FIXTURES = CANDIDATE / 'tests'
VENDOR = PROJECT / 'native/gpu/vendor/ArmSmmu4K'
manifest = json.loads((VENDOR / 'source-manifest.json').read_text())
assert manifest['commit'] == '8bb168ad058c28d5c04f179ba407875eacba7ef3'
for name, expected in manifest['files'].items():
    assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == expected, name
probe = (XNU / 'HoujiGpuTableProbe.inc').read_text()
for forbidden in ('ArmSmmu4KProgram(', 'ArmSmmu4KObserve', 'LiveUpdate', 'holdForDevice(',
                  'retireAfterQuiescence(', 'makeWriteCombined(', 'pmap_set_cache_attributes('):
    assert forbidden not in probe, forbidden

tree = ast.parse((FIXTURES / 'check_page_geometry.py').read_text())
prefix = next(node.value.value for node in tree.body
              if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
              and any(isinstance(t, ast.Name) and t.id == 'prefix' for t in node.targets))
prefix = '#include <cstdint>\nstatic void table_probe_cache_hook(uintptr_t,unsigned);\n' + prefix
prefix = prefix.replace('constexpr IOReturn kIOReturnNotFound=9;\n', '')
prefix = prefix.replace('constexpr unsigned kIOMapAnywhere=1,kIOMapInhibitCache=2;\n', '')
assert prefix.count('cache_lines.push_back({address,op});') == 1
prefix = prefix.replace('cache_lines.push_back({address,op});',
                        'cache_lines.push_back({address,op});table_probe_cache_hook(address,op);')
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
static bool PE_parse_boot_argn(const char *name,void *value,int bytes){CHECK(!strcmp(name,"houji_gpu_table_probe") && bytes==sizeof(int));*(int*)value=boot_arg;return true;}
#define HOUJI_GPU_TABLE_PROBE_HOST_TEST 1
#include "HoujiGpuTableProbe.inc"
enum Fault {None,Geometry,WalkDisabled,AllocFirst,AllocSecond,AllocRetained,HighPa,Alias,AtPa,AtCpu,ZeroFirst,ZeroSecond,
 Spare,DataChanged,LeafBit,ExtraLeaf,MissingLeaf,Cycle,ForeignTable,ReadRefused,CacheFailure,ReleaseFirst,ReleaseSecond};
static Fault fault=None;
static unsigned at_calls,at_fail,mutation_bit,mutation_row,mutated,table_clean_lines;
static uint64_t saved_table[2048];
static bool table_probe_complete_hook(){return fault==ReleaseFirst || (fault==ReleaseSecond && fixture.completed==2);}
static bool houjiGpuTableAt(uint64_t va,bool write,uint64_t *par){
 CHECK(par);++at_calls;auto&p=gHoujiGpuTableProbe;
 for(unsigned i=0;i<HGTP_BOS;++i){auto&bo=p.bo[i];uint64_t base=(uint64_t)(uintptr_t)bo.mapping();
  if(!base || va<base || va-base>=bo.ownedBytes())continue;
  uint64_t pa=bo.ownedSpans()[0].physical+va-base;
  *par=UINT64_C(0x4400000000000000)|(pa&UINT64_C(0x0000fffffffff000));
  if(at_fail==at_calls)*par=1;
  if(fault==AtPa && at_calls==1)*par^=4096;
  if(fault==AtCpu && at_calls==1)return false;
  if(at_calls==8){if(fault==AllocSecond)fixture.allocation_fail=true;if(fault==Alias)fixture.next_physical=bo.ownedSpans()[0].physical;if(fault==ZeroFirst)((unsigned char*)bo.mapping())[0]=1;}
  if(at_calls==16){if(fault==ZeroSecond)((unsigned char*)bo.mapping())[0]=1;if(fault==CacheFailure)cpu_ctr=UINT64_C(11)<<16;}
  (void)write;return true;
 }
 CHECK(false);return false;
}
static void table_probe_cache_hook(uintptr_t address,unsigned op){
 auto&p=gHoujiGpuTableProbe;if(p.phase!=5)return;
 CHECK(op==0 && address>=p.info[HGTP_TABLE].va && address<p.info[HGTP_TABLE].va+HGTP_BYTES);++table_clean_lines;
 if(mutated++)return;
 auto*t=static_cast<uint64_t*>(p.bo[HGTP_TABLE].mapping());memcpy(saved_table,t,HGTP_BYTES);
 const size_t leaf=2*512+((kHoujiGpuTableIova>>12)&511);
 if(fault==Spare)t[3*512+mutation_row]=1;
 if(fault==DataChanged)((unsigned char*)p.bo[HGTP_DATA].mapping())[mutation_row]=1;
 if(fault==LeafBit)t[leaf+mutation_row]^=UINT64_C(1)<<mutation_bit;
 if(fault==ExtraLeaf)t[mutation_row?leaf+HGTP_ROWS:leaf-1]=t[leaf];
 if(fault==MissingLeaf)t[leaf+mutation_row]=0;
 if(fault==Cycle)t[(kHoujiGpuTableIova>>30)&511]=p.info[HGTP_TABLE].pa|3;
 if(fault==ForeignTable)t[(kHoujiGpuTableIova>>30)&511]=p.info[HGTP_DATA].pa|3;
 if(fault==ReadRefused)p.bo[HGTP_TABLE].quarantine();
}
static void discardHostOnly(){
 // Test peer teardown after a simulated reset, never runtime authorization.
 while(!fixture.live.empty())fixture.live.back()->release();
 while(!fixture.metadata.empty())fixtureMetadataFree(fixture.metadata.back());
}
static void reset(Fault f=None,unsigned fail_at=0,unsigned row=0,unsigned bit=0){
 CHECK(!preemption_depth && fixture.live.empty() && fixture.metadata.empty());
 fixture=MemoryFixture{};fixture.cpu_page_bytes=PAGE_SIZE;attributes.clear();pmap_writes.clear();cache_lines.clear();logs.clear();
 void*state=&gHoujiGpuTableProbe;memset(state,0,sizeof(gHoujiGpuTableProbe));gHoujiGpuTableProbeOnce=0;
 page_size=map_page_bytes=PAGE_SIZE;cpu_tcr=PAGE_SIZE==16384?(UINT64_C(2)<<14|UINT64_C(1)<<30):(UINT64_C(2)<<30);
 cpu_ttbr0=0x30000000;cpu_ttbr1=0x30004000;cpu_sctlr=1;cpu_ctr=UINT64_C(4)<<16;
 boot_arg=1;fault=f;at_calls=mutated=table_clean_lines=0;at_fail=fail_at;mutation_row=row;mutation_bit=bit;attribute_write_fail=barriers=0;memset(saved_table,0,sizeof(saved_table));
 if(f==Geometry)page_size=4096;if(f==WalkDisabled)cpu_tcr|=UINT64_C(1)<<23;
 if(f==AllocFirst)fixture.allocation_fail=true;if(f==HighPa)fixture.next_physical=UINT64_C(1)<<36;
 if(f==AllocRetained){fixture.null_mapping=true;fixture.complete_fail=true;}
}
static void stopped(unsigned expected_code,unsigned retained){
 auto&p=gHoujiGpuTableProbe;CHECK(p.code==expected_code && !p.completed && p.retained==retained);
 unsigned backed=0;for(auto&bo:p.bo){CHECK(!bo.deviceReferences());if(bo.backed()){CHECK(bo.quarantined());++backed;}}
 CHECK(backed==retained && fixture.live.size()==retained && !preemption_depth && pmap_writes.empty());
 CHECK(!logs.empty() && logs.back().find("GPU-mapped=0 GPU-execution=0 DMA=0")!=std::string::npos);
 const auto allocations=fixture.created,ats=at_calls,releases=fixture.released;const auto lines=cache_lines.size(),reads=p.physical_reads;
 houjiGpuTableProbeOnce();CHECK(fixture.created==allocations && at_calls==ats && cache_lines.size()==lines && p.physical_reads==reads && fixture.released==releases);
 discardHostOnly();
}
int main(){unsigned cases=0;
 for(int argument:{0,2}){reset();boot_arg=argument;houjiGpuTableProbeOnce();CHECK(!fixture.created && !at_calls && pmap_writes.empty() && logs.empty());++cases;}
 if(PAGE_SIZE==4096){reset();houjiGpuTableProbeOnce();stopped(HGTP_GEOMETRY,0);++cases;printf("PASS: CPU4K explicitly refuses CPU16K table experiment (%u cases)\n",cases);return 0;}
 reset();houjiGpuTableProbeOnce();auto&p=gHoujiGpuTableProbe;
 CHECK(p.completed && !p.code && p.phase==9 && !p.retained && at_calls==16 && fixture.created==2 && fixture.completed==2 && fixture.released==2 && fixture.live.empty() && fixture.metadata.empty());
 CHECK(p.info[0].logical_bytes==16384 && p.info[0].owned_bytes==16384 && p.info[1].logical_bytes==16384 && p.info[1].owned_bytes==16384 && p.info[0].pa!=p.info[1].pa);
 CHECK(p.built.table_pages==3 && p.built.leaf_pages==4 && p.built.start_level==1 && p.built.root_physical==p.info[1].pa && p.built.mair==0xff44);
 CHECK(p.audit.complete && p.audit.table_pages==3 && p.audit.leaf_pages==4 && p.audit.descriptor_reads==1536 && p.physical_reads==1554 && !p.physical_refusals);
 CHECK(p.spare_zero && p.neighbors_invalid && p.leaves_valid==4 && p.cleaned && table_clean_lines==256 && pmap_writes.empty());
 CHECK(fixture.allocation_bytes==std::vector<size_t>({16384,16384}) && fixture.segment_calls==10 && cache_lines.size()==3*256);
 for(unsigned row=0;row<4;++row)CHECK(p.byte_pa[row]==p.info[0].pa+row*4096+0x5a);
 const auto count=logs.size();houjiGpuTableProbeOnce();CHECK(logs.size()==count && fixture.created==2 && at_calls==16);++cases;
 for(Fault f:{Geometry,WalkDisabled}){reset(f);houjiGpuTableProbeOnce();CHECK(!fixture.created && !at_calls);stopped(HGTP_GEOMETRY,0);++cases;}
 for(Fault f:{AllocFirst,AllocSecond,HighPa}){reset(f);houjiGpuTableProbeOnce();CHECK(!p.cleaned);stopped(HGTP_ALLOC,f==AllocSecond?1:0);++cases;}
 reset(AllocRetained);houjiGpuTableProbeOnce();CHECK(!p.info[0].allocated && !p.cleaned && fixture.completed==1 && !fixture.released);stopped(HGTP_ALLOC,1);++cases;
 reset(Alias);houjiGpuTableProbeOnce();CHECK(!p.built.root_physical && !p.cleaned);stopped(HGTP_ALIAS,2);++cases;
 for(Fault f:{ZeroFirst,ZeroSecond}){reset(f);houjiGpuTableProbeOnce();stopped(HGTP_ZERO,f==ZeroFirst?1:2);++cases;}
 for(Fault f:{AtPa,AtCpu}){reset(f);houjiGpuTableProbeOnce();stopped(HGTP_TRANSLATION,1);++cases;}
 for(unsigned n=1;n<=16;++n){reset(None,n);houjiGpuTableProbeOnce();CHECK(!p.cleaned);stopped(HGTP_TRANSLATION,n<=8?1:2);++cases;}
 reset(CacheFailure);houjiGpuTableProbeOnce();CHECK(p.built.table_pages==3 && !p.cleaned && !p.physical_reads);stopped(HGTP_CACHE,2);++cases;
 for(unsigned row=0;row<4;++row)for(unsigned bit=0;bit<64;++bit){reset(LeafBit,0,row,bit);houjiGpuTableProbeOnce();CHECK(!p.audit.complete && p.cleaned);stopped(HGTP_AUDIT,2);++cases;}
 for(unsigned row=0;row<4;++row){reset(MissingLeaf,0,row);houjiGpuTableProbeOnce();stopped(HGTP_AUDIT,2);++cases;}
 for(unsigned side=0;side<2;++side){reset(ExtraLeaf,0,side);houjiGpuTableProbeOnce();stopped(HGTP_AUDIT,2);++cases;}
 for(Fault f:{Cycle,ForeignTable,ReadRefused}){reset(f);houjiGpuTableProbeOnce();CHECK(!p.audit.complete);stopped(HGTP_AUDIT,2);++cases;}
 for(unsigned slot:{0u,511u}){reset(Spare,0,slot);houjiGpuTableProbeOnce();CHECK(p.audit.complete && p.leaves_valid==4 && p.neighbors_invalid);stopped(HGTP_SPARE,2);++cases;}
 for(unsigned offset:{0u,4095u,4096u,16383u}){reset(DataChanged,0,offset);houjiGpuTableProbeOnce();CHECK(p.audit.complete && p.neighbors_invalid);stopped(HGTP_SPARE,2);++cases;}
 for(Fault f:{ReleaseFirst,ReleaseSecond}){reset(f);houjiGpuTableProbeOnce();CHECK(p.audit.complete && p.spare_zero);stopped(HGTP_RELEASE,f==ReleaseFirst?2:1);++cases;}
 // Exercise the independent physical boundary and walker on real, retained
 // built tables. No mirrored expected table is supplied to either reader.
 // A fresh allocation for boundary tests; no production quarantine is undone.
 reset();boot_arg=0;
 auto &bo=p.bo[HGTP_TABLE];CHECK(!bo.allocate(16384,36,true,16384,false));p.info[1].allocated=1;CHECK(houjiGpuTableProbeOwn(1));
 p.info[0].pa=0x20000000;p.config={36,36,p.info[1].pa,4};p.range={kHoujiGpuTableIova,p.info[0].pa,16384,ArmSmmu4KRead|ArmSmmu4KWrite,1,3};
 CHECK(!ArmSmmu4KBuild(&p.config,&p.range,1,(uint64_t*)bo.mapping(),4,&p.built));
 uint64_t value=UINT64_C(0xbadc0ffe),leaf=0,pa=0;
 for(uint64_t address:{p.info[0].pa,p.info[1].pa-8,p.info[1].pa+16384,p.info[1].pa+1,UINT64_MAX}){CHECK(houjiGpuTableRead(&p,address,&value) && value==UINT64_C(0xbadc0ffe));++cases;}
 CHECK(houjiGpuTableRead(nullptr,p.info[1].pa,&value) && houjiGpuTableRead(&p,p.info[1].pa,nullptr));cases+=2;
 for(uint64_t address:{kHoujiGpuTableIova-1,kHoujiGpuTableIova+16384,UINT64_C(0),UINT64_C(0xfffffffff)}){CHECK(houjiGpuTableLookup(address,&leaf,&pa)==0);++cases;}
 CHECK(houjiGpuTableLookup(UINT64_C(1)<<36,&leaf,&pa)==-1 && houjiGpuTableLookup(kHoujiGpuTableIova,nullptr,&pa)==-1);cases+=2;
 for(unsigned row=0;row<4;++row){CHECK(houjiGpuTableLookup(kHoujiGpuTableIova+row*4096+0xfff,&leaf,&pa)==1 && pa==p.info[0].pa+row*4096+0xfff);++cases;}
 CHECK(!bo.release() && fixture.live.empty() && fixture.metadata.empty() && pmap_writes.empty());
 printf("PASS: CPU16K actual Build/Audit/Memory/Cpu/table-probe %u success, corruption, exclusive ownership, PA-byte, bounds and fail-retain cases (ASAN/UBSAN); GPU/DMA=0\n",cases);
}
'''

with tempfile.TemporaryDirectory(prefix='houji-xnu-table-probe-') as directory:
    tmp = Path(directory)
    fixture = (FIXTURES / 'XnuMemoryFixture.h').read_text()
    fixture = fixture.replace('#include <cstddef>', 'static bool table_probe_complete_hook();\n#include <cstddef>')
    old = 'return fixture.complete_fail?kIOReturnIOError:kIOReturnSuccess;'
    assert fixture.count(old) == 2
    fixture = fixture.replace(old, 'return fixture.complete_fail || table_probe_complete_hook()?kIOReturnIOError:kIOReturnSuccess;')
    (tmp / 'XnuMemoryFixture.h').write_text(fixture)
    for name in ['IOKit/IOTypes.h', 'IOKit/IOBufferMemoryDescriptor.h', 'IOKit/IOLib.h', 'kern/task.h',
                 'kern/cpu_data.h', 'vm/vm_map.h', 'mach/vm_param.h', 'kern/clock.h', 'vm/memory_types.h']:
        path = tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#include "XnuMemoryFixture.h"\n')
    objects = []
    for name in ['ArmSmmu4K', 'ArmSmmu4KAudit', 'ArmSmmu4KProgram', 'ArmSmmu4KContext']:
        obj = tmp / (name + '.o')
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-I' + str(VENDOR), '-c', str(VENDOR / (name + '.c')), '-o', str(obj)], check=True)
        objects.append(str(obj))
    cpp = tmp / 'probe.cpp'
    cpp.write_text(prefix + cpu + (CANDIDATE / 'NativeAdrenoMemory.cpp').read_text() + peer)
    for page in (4096, 16384):
        exe = tmp / ('test-' + str(page))
        subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-DPAGE_SIZE=' + str(page), '-I' + str(tmp), '-I' + str(FIXTURES),
                        '-I' + str(CANDIDATE), '-I' + str(XNU), '-I' + str(VENDOR), str(cpp), *objects, '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
