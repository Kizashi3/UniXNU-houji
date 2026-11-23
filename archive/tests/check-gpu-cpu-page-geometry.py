#!/usr/bin/env python3
"""Compile the actual CPU geometry/probe; mock only XNU CPU/IOKit boundaries."""
from pathlib import Path
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
program = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <climits>
#include <initializer_list>
#include "GpuCpuPageGeometry.h"
using IOReturn=unsigned;using IOByteCount=uint64_t;using IOOptionBits=unsigned;
constexpr unsigned kIOReturnSuccess=0,kIODirectionInOut=3,kIOMemoryPhysicallyContiguous=0x10,kIOMemoryMapperNone=0x20;
static unsigned boot_value,parse_calls,preempt_depth,disables,enables,cpu_calls,register_calls,log_calls;
static unsigned alloc_calls,prepare_calls,bytes_calls,length_calls,segment_calls,complete_calls,release_calls;
static unsigned fail_alloc,prepare_code,complete_code,cpu_migrate;
static uint64_t compiled_page,page_size,map_page,descriptor_length,virtual_offset,physical[4],segment_length[4];
static void *kernel_task=(void*)0x100,*kernel_map=(void*)0x200;
alignas(16384) static uint8_t owned[16384];
static hcpg_sample hardware;
#define PAGE_SIZE compiled_page
static void PE_parse_boot_argn(const char *name,int *value,unsigned size){assert(!std::strcmp(name,"houji_gpu_cpu_probe") && size==sizeof(int));parse_calls++;*value=(int)boot_value;}
static void disable_preemption(){assert(!preempt_depth);preempt_depth++;disables++;}
static void enable_preemption(){assert(preempt_depth==1);preempt_depth--;enables++;}
static int cpu_number(){assert(preempt_depth==1);return (int)(2+((cpu_calls++ && cpu_migrate)?1:0));}
static int vm_map_page_size(void *map){assert(preempt_depth==1 && map==kernel_map);return (int)map_page;}
static void IOLog(const char *format,...){assert(format && !preempt_depth);log_calls++;}
class IOBufferMemoryDescriptor {
public:
 static IOBufferMemoryDescriptor *inTaskWithOptions(void *task,unsigned options,unsigned bytes,unsigned align){assert(!preempt_depth && task==kernel_task && options==(kIODirectionInOut|kIOMemoryPhysicallyContiguous|kIOMemoryMapperNone) && bytes==16384 && align==16384);alloc_calls++;static IOBufferMemoryDescriptor descriptor;return fail_alloc?nullptr:&descriptor;}
 unsigned prepare(unsigned direction){assert(!preempt_depth && direction==kIODirectionInOut && alloc_calls==1 && !prepare_calls);prepare_calls++;return prepare_code;}
 void *getBytesNoCopy(){assert(!preempt_depth && prepare_calls==1 && !prepare_code);bytes_calls++;return virtual_offset==UINT64_MAX?nullptr:(void*)((uintptr_t)owned+virtual_offset);}
 uint64_t getLength(){assert(!preempt_depth && prepare_calls==1 && !prepare_code);length_calls++;return descriptor_length;}
 uint64_t getPhysicalSegment(uint64_t offset,uint64_t *length,unsigned options){assert(!preempt_depth && options==kIOMemoryMapperNone && segment_calls<4 && offset==4096*segment_calls && length && !*length && !complete_calls);unsigned i=segment_calls++;*length=segment_length[i];return physical[i];}
 unsigned complete(unsigned direction){assert(!preempt_depth && direction==kIODirectionInOut && !prepare_code && prepare_calls==1 && segment_calls==4 && !complete_calls);complete_calls++;return complete_code;}
 void release(){assert(!preempt_depth && complete_calls==1 && !complete_code && !release_calls);release_calls++;}
};
#define HOUJI_CPU_PAGE_PROBE_HOST_TEST 1
#include "HoujiCpuPageProbe.inc"
static void houjiGpuCpuPageReadRegisters(hcpg_sample *s){assert(preempt_depth==1 && s);register_calls++;s->tcr=hardware.tcr;s->ttbr0=hardware.ttbr0;s->ttbr1=hardware.ttbr1;s->sctlr=hardware.sctlr;}
static hcpg_sample good(uint64_t bytes){hcpg_sample s={};s.cpu_before=s.cpu_after=2;s.compiled_bytes=s.runtime_bytes=s.map_bytes=bytes;s.tcr=25|(UINT64_C(25)<<16)|(UINT64_C(2)<<32)|(bytes==16384?(UINT64_C(2)<<14)|(UINT64_C(1)<<30):(UINT64_C(2)<<30));s.ttbr0=0x751000081000000;s.ttbr1=0x752000088000000;s.sctlr=0x30d00801;return s;}
static void reset(uint64_t bytes){boot_value=1;parse_calls=preempt_depth=disables=enables=cpu_calls=register_calls=log_calls=0;alloc_calls=prepare_calls=bytes_calls=length_calls=segment_calls=complete_calls=release_calls=0;fail_alloc=prepare_code=complete_code=cpu_migrate=0;compiled_page=page_size=map_page=bytes;descriptor_length=16384;virtual_offset=0;kernel_map=(void*)0x200;hardware=good(bytes);gHoujiCpuPageProbeOnce=0;gHoujiCpuPageProbe={};for(unsigned i=0;i<4;i++){physical[i]=UINT64_C(0x8c0000000)+4096*i;segment_length[i]=16384-4096*i;}std::memset(owned,0xa5,sizeof owned);}
static void untouched(){for(unsigned i=0;i<sizeof owned;i++)assert(owned[i]==0xa5);assert(!preempt_depth && disables==enables);}
static void retained(unsigned code,unsigned rows){const auto &p=gHoujiCpuPageProbe;assert(p.code==code && p.retained && p.descriptor && !p.released && !release_calls && !p.completed && p.rows_attempted==rows);untouched();}
int main(){unsigned cases=0;
 for(uint64_t bytes:{UINT64_C(4096),UINT64_C(16384)}){auto s=good(bytes);hcpg_geometry r={};assert(!hcpg_geometry_check(&s,&r) && r.cpu_shift==(bytes==16384?14u:12u));cases++;
  for(unsigned i=0;i<4;i++){hcpg_row row={};uint64_t base=0x8c0000000;assert(!hcpg_segment_check(bytes,base,4096*i,base+4096*i,16384-4096*i,&row) && row.valid && row.gpu36_fit && row.cpu_ppn==((base+4096*i)>>(bytes==16384?14:12)) && row.gpu4k_ppn==(base+4096*i)>>12 && row.cpu_subpage==(bytes==16384?i:0));cases++;}
  for(unsigned field=0;field<9;field++){auto bad=s;switch(field){case 0:bad.cpu_after++;break;case 1:bad.compiled_bytes=8192;break;case 2:bad.runtime_bytes=bytes==4096?16384:4096;break;case 3:bad.map_bytes=0;break;case 4:bad.tcr^=UINT64_C(1)<<14;break;case 5:bad.tcr^=UINT64_C(1)<<30;break;case 6:bad.sctlr&=~UINT64_C(1);break;case 7:bad.ttbr1=UINT64_C(0xffff)<<48;break;default:bad.tcr|=UINT64_C(1)<<23;break;}assert(hcpg_geometry_check(&bad,&r));cases++;}
  for(unsigned tg0=0;tg0<4;tg0++)for(unsigned tg1=0;tg1<4;tg1++){auto mixed=s;mixed.tcr=(mixed.tcr&~((UINT64_C(3)<<14)|(UINT64_C(3)<<30)))|((uint64_t)tg0<<14)|((uint64_t)tg1<<30);assert((hcpg_geometry_check(&mixed,&r)==0)==(tg0==(bytes==16384?2u:0u) && tg1==(bytes==16384?1u:2u)));cases++;}
  reset(bytes);houjiGpuCpuPageProbeOnce();const auto &p=gHoujiCpuPageProbe;assert(!p.code && p.phase==6 && p.sample.cpu_before==2 && p.sample.cpu_after==2 && p.sample.compiled_bytes==bytes && p.sample.runtime_bytes==bytes && p.sample.map_bytes==bytes && p.geometry.cpu_shift==(bytes==16384?14u:12u) && p.rows_attempted==4 && p.rows_valid==4 && p.prepare_attempted && !p.prepared && p.complete_attempted && p.completed && p.released && !p.retained && !p.descriptor);assert(alloc_calls==1 && prepare_calls==1 && segment_calls==4 && complete_calls==1 && release_calls==1 && register_calls==1 && disables==1 && enables==1 && cpu_calls==2 && log_calls==7);untouched();unsigned old_logs=log_calls;houjiGpuCpuPageProbeOnce();assert(alloc_calls==1 && register_calls==1 && log_calls==old_logs);cases++;
 }
 for(unsigned value:{0u,2u,UINT_MAX}){reset(16384);boot_value=value;houjiGpuCpuPageProbeOnce();assert(!gHoujiCpuPageProbeOnce && !disables && !alloc_calls && !log_calls && !register_calls);boot_value=1;houjiGpuCpuPageProbeOnce();assert(release_calls==1);cases++;}
 for(unsigned field=0;field<7;field++){reset(16384);if(!field)compiled_page=8192;else if(field==1)page_size=4096;else if(field==2)map_page=4096;else if(field==3)kernel_map=nullptr;else if(field==4)hardware.sctlr=0;else if(field==5)hardware.ttbr1=0;else cpu_migrate=1;houjiGpuCpuPageProbeOnce();assert(gHoujiCpuPageProbe.code==HCP_PROBE_GEOMETRY && gHoujiCpuPageProbe.geometry.issues && !alloc_calls && disables==1 && enables==1 && log_calls==3);untouched();cases++;}
 reset(16384);fail_alloc=1;houjiGpuCpuPageProbeOnce();assert(gHoujiCpuPageProbe.code==HCP_PROBE_ALLOC && !gHoujiCpuPageProbe.retained && !prepare_calls && !segment_calls && !complete_calls && !release_calls);untouched();cases++;
 reset(16384);prepare_code=0xe00002bc;houjiGpuCpuPageProbeOnce();retained(HCP_PROBE_PREPARE,0);assert(gHoujiCpuPageProbe.prepare_attempted && !gHoujiCpuPageProbe.prepared && !bytes_calls && !segment_calls && !complete_calls);cases++;
 for(unsigned field=0;field<5;field++){reset(16384);if(!field)virtual_offset=UINT64_MAX;else if(field==1)virtual_offset=4096;else if(field==2)virtual_offset=1;else if(field==3)descriptor_length=4096;else descriptor_length=32768;houjiGpuCpuPageProbeOnce();retained(HCP_PROBE_OWNERSHIP,0);assert(gHoujiCpuPageProbe.prepared && !segment_calls && !complete_calls);cases++;}
 for(unsigned row=0;row<4;row++)for(unsigned field=0;field<4;field++){reset(16384);if(!field)physical[row]=0;else if(field==1)physical[row]++;else if(field==2)segment_length[row]=4095;else physical[row]+=row?16384:4096;houjiGpuCpuPageProbeOnce();retained(HCP_PROBE_SEGMENT,row+1);assert(gHoujiCpuPageProbe.prepared && segment_calls==row+1 && !complete_calls && gHoujiCpuPageProbe.rows_valid==row);cases++;}
 reset(16384);complete_code=0xe00002bc;houjiGpuCpuPageProbeOnce();retained(HCP_PROBE_COMPLETE,4);assert(gHoujiCpuPageProbe.prepared && gHoujiCpuPageProbe.complete_attempted && complete_calls==1);unsigned calls=segment_calls;houjiGpuCpuPageProbeOnce();assert(segment_calls==calls && complete_calls==1 && !release_calls);cases++;
 hcpg_row row={};for(unsigned field=0;field<5;field++){uint64_t cpu=4096,first=0x10000,offset=0,pa=first,length=4096;if(!field)cpu=8192;else if(field==1)offset=16384;else if(field==2)offset=1;else if(field==3)first=UINT64_MAX-4095;else pa=UINT64_MAX-4095;assert(hcpg_segment_check(cpu,first,offset,pa,length,&row));cases++;}
 assert(!hcpg_segment_check(16384,UINT64_C(1)<<36,0,UINT64_C(1)<<36,16384,&row) && row.valid && !row.gpu36_fit);cases++;
 hcpg_geometry g={};auto sample=good(4096);assert(hcpg_geometry_check(nullptr,&g) && hcpg_geometry_check(&sample,nullptr) && hcpg_segment_check(4096,4096,0,4096,4096,nullptr));cases++;
 std::printf("CPU page geometry + actual XNU probe: %u cases PASS (ASAN/UBSAN); no GPU or cache/pmap mutations.\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='houji-cpu-page-geometry-') as td:
    source=Path(td)/'probe.cc';source.write_text(program);exe=Path(td)/'probe'
    subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined','-fno-omit-frame-pointer',
                    '-I',str(p/'native/gpu/xnu'),str(source),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
