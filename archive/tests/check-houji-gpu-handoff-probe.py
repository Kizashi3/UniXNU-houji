#!/usr/bin/env python3
"""Actual candidate/portable observer; only IOKit and physical loads are peers.

The CPU still executes the candidate's real volatile loads from host Device
mapping peers. These tests do not qualify XNU mapping attributes or hardware
fault recovery. No device, source tree or live kernel is accessed.
"""
from pathlib import Path
import os
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
XNU = PROJECT / 'native/gpu/xnu'
POLICY = PROJECT / 'native/gpu/uefi'
candidate = XNU / 'HoujiGpuHandoffProbe.inc'
text = candidate.read_text()
for forbidden in ('hph_run(', '->write', 'write32(', 'pmap_', 'ArmSmmu4KProgram',
                  'setRecoveryBoot(', 'houji_ufs_checkpoint(', 'IOServiceOpen(',
                  'native_adreno_publish(', 'SMC', 'smc #', 'memcpy('):
    assert forbidden not in text, forbidden
assert text.count('*reinterpret_cast<const volatile uint32_t *>') == 1
assert 'kIOMapAnywhere|kIOMapReadOnly|kIOMapInhibitCache' in text

# Use the real producer and its source-pinned fixture to obtain a valid ready
# record, instead of manually inventing success flags/CRC or stubbing decode.
producer = r'''
#define main hph_reference_test_main
#include "check-gpu-power-only-handoff.c"
#undef main
static struct mock fixture_running;
void fixture_record(unsigned char *wire) {
 struct hph_record r={0};struct gpp_report p=power();fixture_running=initial();
 assert(run(&fixture_running,&p,&r)==HPH_OK && hph_record_valid(&r));
 memcpy(wire,&r,sizeof(r));
}
uint32_t fixture_register(uint32_t a) {
 uint32_t v=0;assert(read32(&fixture_running,a,&v)==0);return v;
}
'''

peer = r'''
#include <cassert>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <array>
#include <algorithm>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"FAIL %s:%u: %s\n",__FILE__,__LINE__,#x);__builtin_abort();}}while(0)
#include "GpuPowerOnlyHandoff.h"
extern "C" void fixture_record(unsigned char *);
extern "C" uint32_t fixture_register(uint32_t);
enum {OSNoRetain=0,kIOMapAnywhere=1,kIOMapReadOnly=2,kIOMapInhibitCache=4};
struct OSObject {virtual ~OSObject()=default;};
struct OSData:OSObject {
 const void *bytes=nullptr;unsigned length=0;
 const void *getBytesNoCopy(){return bytes;}unsigned getLength(){return length;}
};
struct IOMemoryMap {
 uint64_t va=0,length=0;unsigned index=0;
 uint64_t getVirtualAddress(){return va;}uint64_t getLength(){return length;}
};
template<class T>struct OSSharedPtr {
 T *pointer=nullptr;OSSharedPtr()=default;OSSharedPtr(T*p,int):pointer(p){}
 explicit operator bool()const{return pointer!=nullptr;}T*operator->()const{return pointer;}
};
static OSData property;static OSObject wrong_type;
static bool chosen_present=true,property_present=true,property_type=true;
static unsigned chosen_lookups,chosen_releases,property_lookups,descriptors,descriptor_releases;
static unsigned map_calls,barriers,boot_calls,fail_alloc,fail_map,bad_mapping,bad_kind;
static int boot_value=1;static bool boot_present=true;
static std::vector<std::string> logs;
static std::vector<uint32_t> backing[4];static IOMemoryMap mappings[4];
static std::vector<unsigned> mapping_order;
static unsigned inject_load=~0u,drop_owner_after=~0u;
static unsigned calls_before_failed_gate;
static const uint64_t mock_base[]={0x170000,0x3d90000,0x3d7c000,0x3da0000};
static const uint64_t mock_size[]={0x4000,0x10000,0x4000,0x40000};
static uint32_t& word(uint32_t address){
 for(unsigned i=0;i<4;i++)if(address>=mock_base[i] && address-mock_base[i]<mock_size[i])return backing[i][(address-mock_base[i])/4];
 CHECK(false);return backing[0][0];
}
struct IODeviceMemory {
 unsigned index;
 static IODeviceMemory *withRange(uint64_t base,uint64_t bytes){
  unsigned i=0;for(;i<4;i++)if(base==mock_base[i] && bytes==mock_size[i])break;
  CHECK(i<4);mapping_order.push_back(i);if(fail_alloc==i+1)return nullptr;
  ++descriptors;return new IODeviceMemory{i};
 }
 IOMemoryMap *map(unsigned options){
  CHECK(options==(kIOMapAnywhere|kIOMapReadOnly|kIOMapInhibitCache));++map_calls;
  if(fail_map==index+1)return nullptr;auto&m=mappings[index];
  m.index=index;m.va=(uint64_t)(uintptr_t)backing[index].data();m.length=mock_size[index];
  if(bad_mapping==index+1){if(!bad_kind)m.va=0;if(bad_kind==1)m.va++;if(bad_kind==2)m.length--;if(bad_kind==3)m.va=UINT64_MAX-3;}
  return &m;
 }
 void release(){++descriptor_releases;delete this;}
};
static const char *gIODTPlane="IODeviceTree";
struct IORegistryEntry {
 static IORegistryEntry *fromPath(const char *path,const char *plane){
  CHECK(!strcmp(path,"/chosen") && plane==gIODTPlane);++chosen_lookups;
  static IORegistryEntry chosen;return chosen_present?&chosen:nullptr;
 }
 OSObject *getProperty(const char *key){CHECK(!strcmp(key,"houji,gpu-power-handoff"));++property_lookups;return !property_present?nullptr:property_type?&property:&wrong_type;}
 void release(){++chosen_releases;}
};
#define OSDynamicCast(type,value) dynamic_cast<type*>(value)
static bool PE_parse_boot_argn(const char*name,void*out,int bytes){
 CHECK(!strcmp(name,"houji_gpu_handoff_probe") && bytes==sizeof(int));++boot_calls;
 if(boot_present)*(int*)out=boot_value;return boot_present;
}
static void IOLog(const char*,...);
#define HOUJI_GPU_HANDOFF_PROBE_HOST_TEST 1
#include "HoujiGpuHandoffProbe.inc"
static void houjiGpuHandoffReadBarrier(){
 ++barriers;if(barriers==drop_owner_after)gHoujiGpuHandoffProbe.active=0;
}
static void IOLog(const char*format,...){
 char buffer[2048];va_list ap;va_start(ap,format);int n=vsnprintf(buffer,sizeof(buffer),format,ap);va_end(ap);
 CHECK(n>=0 && (size_t)n<sizeof(buffer));logs.emplace_back(buffer);
 if(!strncmp(format,"HOUJI GPU HANDOFF LOAD:",23)){
  auto&p=gHoujiGpuHandoffProbe;CHECK(p.calls && p.calls<=HGHP_READS);auto&r=p.reads[p.calls-1];
  CHECK(r.attempted && !r.returned && !r.valid);
  if(p.calls-1==inject_load)word(r.address)=UINT32_MAX;
 }
}
static std::array<unsigned char,HPH_RECORD_BYTES+1> wire;
static hph_record original;
static void reset(){
 gHoujiGpuHandoffProbe={};gHoujiGpuHandoffProbeOnce=0;
 chosen_present=property_present=property_type=boot_present=true;boot_value=1;
 chosen_lookups=chosen_releases=property_lookups=descriptors=descriptor_releases=map_calls=barriers=boot_calls=0;
 fail_alloc=fail_map=bad_mapping=bad_kind=0;inject_load=drop_owner_after=~0u;
 logs.clear();mapping_order.clear();calls_before_failed_gate=0;
 for(unsigned i=0;i<4;i++){backing[i].assign(mock_size[i]/4,0);mappings[i]={};}
 memcpy(wire.data()+1,&original,sizeof(original));property.bytes=wire.data()+1;property.length=HPH_RECORD_BYTES;
 for(unsigned i=0;i<HGB_REGS;i++)word(hgb_address(i))=fixture_register(hgb_address(i));
 for(unsigned i=0;i<HCW_REGS;i++)word(hcw_address(i))=fixture_register(hcw_address(i));
 for(unsigned i=0;i<24;i++){word(0x3da0800+4*i)=fixture_register(0x3da0800+4*i);word(0x3da0c00+4*i)=fixture_register(0x3da0c00+4*i);}
 for(unsigned i=0;i<22;i++)word(0x3dc0000+4096*i)=fixture_register(0x3dc0000+4096*i);
 word(0x3d7e600)=fixture_register(0x3d7e600);
}
static void inactive(){auto&p=gHoujiGpuHandoffProbe;
 CHECK(!p.complete && !p.calls && !p.map_attempted && !descriptors && !map_calls && !barriers);
}
static void onceUnchanged(){
 const auto p=gHoujiGpuHandoffProbe;const auto maps=map_calls,reads=barriers;const auto lines=logs.size();
 houjiGpuHandoffProbeOnce();CHECK(gHoujiGpuHandoffProbe.calls==p.calls && map_calls==maps && logs.size()==lines && barriers==reads);
}
static void direct(){reset();auto&p=gHoujiGpuHandoffProbe;p.record=original;p.decoded=p.record_ready=p.active=1;gHoujiGpuHandoffProbeOnce=1;}
int main(){unsigned cases=0;fixture_record((unsigned char*)&original);
 CHECK(sizeof(original)==1376 && hph_record_valid(&original) && original.complete);
 for(int arg:{0,2,-1}){reset();boot_value=arg;houjiGpuHandoffProbeOnce();inactive();CHECK(!chosen_lookups && logs.empty());++cases;}
 reset();boot_present=false;houjiGpuHandoffProbeOnce();inactive();CHECK(!chosen_lookups);++cases;
 reset();chosen_present=false;houjiGpuHandoffProbeOnce();inactive();CHECK(gHoujiGpuHandoffProbe.code==HGHP_CHOSEN && !chosen_releases);onceUnchanged();++cases;
 for(unsigned kind=0;kind<6;kind++){
  reset();if(!kind)property_present=false;if(kind==1)property_type=false;
  if(kind==2)property.bytes=nullptr;if(kind==3)property.length=0;if(kind==4)property.length=1375;if(kind==5)property.length=1377;
  houjiGpuHandoffProbeOnce();inactive();CHECK(gHoujiGpuHandoffProbe.code==HGHP_PROPERTY && chosen_releases==1);++cases;
 }
 for(unsigned byte=0;byte<HPH_RECORD_BYTES;byte++){
  reset();wire[1+byte]^=1;houjiGpuHandoffProbeOnce();inactive();CHECK(gHoujiGpuHandoffProbe.code==HGHP_RECORD && !gHoujiGpuHandoffProbe.decoded && !gHoujiGpuHandoffProbe.record.magic && chosen_releases==1);++cases;
 }
 reset();{hph_record r=original;r.complete=0;r.code=HPH_COLD;hph_seal(&r);CHECK(hph_record_valid(&r));memcpy(wire.data()+1,&r,sizeof(r));}
 houjiGpuHandoffProbeOnce();inactive();CHECK(gHoujiGpuHandoffProbe.decoded && !gHoujiGpuHandoffProbe.record_ready);++cases;
 reset();auto before=std::array<std::vector<uint32_t>,4>{backing[0],backing[1],backing[2],backing[3]};houjiGpuHandoffProbeOnce();auto&p=gHoujiGpuHandoffProbe;
 CHECK(p.complete && !p.code && p.phase==5 && !p.active && p.decoded && p.record_ready && !p.observe_code && !p.recheck_code);
 CHECK(p.cold.valid==0xffff && p.clock.stable && !p.clock.configured_valid && p.clock.configured_status_hi[0]==0x80000000u && p.clock.configured_status_lo[0]==0x13);
 CHECK(p.gate_valid==255 && p.map_valid==15 && p.map_attempted==15 && descriptors==4 && descriptor_releases==4 && map_calls==4 && chosen_releases==1);
 CHECK(mapping_order==std::vector<unsigned>({0,1,2,3}) && p.calls==barriers && p.valid_reads==barriers && p.calls<HGHP_READS);
 for(unsigned i=0;i<8;i++)CHECK(p.reads[i].address==hgb_address(i));
 for(unsigned i=0;i<4;i++)CHECK(backing[i]==before[i] && p.maps[i]);
 for(unsigned i=0;i<p.calls;i++)CHECK(p.reads[i].attempted && p.reads[i].returned && p.reads[i].valid && !p.reads[i].status && hph_read_allowed(p.reads[i].address));
 CHECK(logs.back().find("GPU-writes=0 GPU-execution=0 DMA=0")!=std::string::npos);const unsigned successful_reads=p.calls;onceUnchanged();++cases;
 for(unsigned i=0;i<successful_reads;i++){
  reset();inject_load=i;houjiGpuHandoffProbeOnce();CHECK(p.code==HGHP_OBSERVE && !p.complete && p.calls==i+1 && barriers==i+1 && p.valid_reads==i && p.first_io_code==HGHP_IO_ALL_ONES && p.first_io_address==p.reads[i].address);
  CHECK(p.reads[i].attempted && p.reads[i].returned && !p.reads[i].valid && p.reads[i].value==UINT32_MAX && p.reads[i].status==HGHP_IO_ALL_ONES);onceUnchanged();++cases;
 }
 const uint32_t corrupt[]={2,2,1,1,0x80000000u,0x80000000u,1,1};
 for(unsigned i=0;i<8;i++){
  reset();word(hgb_address(i))^=corrupt[i];houjiGpuHandoffProbeOnce();CHECK(p.code==HGHP_OBSERVE && p.observe_code==HPH_COLD && p.calls==i+1 && barriers==i+1 && !(p.gate_valid&(1u<<i)) && !p.complete);
  CHECK(p.reads[i].valid && !p.first_io_code);if(i<3)CHECK(mapping_order==std::vector<unsigned>({0}));if(i<6)CHECK(!(p.map_attempted&12));if(i<7)CHECK(!(p.map_attempted&8));++cases;
 }
 for(unsigned window=1;window<=4;window++)for(unsigned kind=0;kind<6;kind++){
  reset();if(!kind)fail_alloc=window;if(kind==1)fail_map=window;if(kind>=2){bad_mapping=window;bad_kind=kind-2;}
  houjiGpuHandoffProbeOnce();CHECK(p.code==HGHP_OBSERVE && !p.complete && p.first_io_code==(!kind?HGHP_IO_ALLOC:kind==1?HGHP_IO_MAP:HGHP_IO_MAPPING));
  CHECK(p.calls && !p.reads[p.calls-1].returned && !p.reads[p.calls-1].valid && p.reads[p.calls-1].status==p.first_io_code && p.valid_reads==barriers && p.calls==barriers+1);
  CHECK(mapping_order.size()==window && descriptor_releases==descriptors);onceUnchanged();++cases;
 }
 for(unsigned i=1;i<=successful_reads;i++){
  reset();drop_owner_after=i;houjiGpuHandoffProbeOnce();CHECK(p.code==HGHP_OBSERVE && !p.complete && barriers==i && p.calls==i && !p.active);++cases;
 }
 for(unsigned i=0;i<24;i++){
  reset();word(0x3da0800+4*i)=0x80000001u;houjiGpuHandoffProbeOnce();CHECK(!p.complete && p.observe_code==HPH_COLD && p.cold.smr[i]==0x80000001u);++cases;
  reset();word(0x3da0c00+4*i)=0;houjiGpuHandoffProbeOnce();CHECK(!p.complete && p.observe_code==HPH_COLD && !p.cold.s2cr[i]);++cases;
 }
 for(unsigned i=0;i<22;i++){reset();word(0x3dc0000+4096*i)=1;houjiGpuHandoffProbeOnce();CHECK(!p.complete && p.observe_code==HPH_COLD && p.cold.sctlr[i]==1);++cases;}
 reset();word(hcw_address(HCW_AHB_DIV))^=1;houjiGpuHandoffProbeOnce();CHECK(!p.complete && !p.observe_code && p.code==HGHP_RECHECK && p.recheck_code==HPH_CHANGED);++cases;
 reset();word(hcw_address(HCW_PLL1_STATUS))^=1;houjiGpuHandoffProbeOnce();CHECK(p.complete && !p.code);++cases;
 // Actual callback cannot be used for wider apertures, foreign cookies,
 // dependent loads without upstream gates, a second owner, or after finish.
 for(uint32_t a:{0u,0x171000u,0x3d02020u,0x3da0010u,0x3da0801u,0x3dd6000u}){
  direct();uint32_t v=0x1234;CHECK(houjiGpuHandoffRead(&p,a,&v)==HGHP_IO_ARGUMENT && v==0x1234);inactive();++cases;
 }
 direct();uint32_t v=0;CHECK(houjiGpuHandoffRead(&p,0x3da0020,&v)==HGHP_IO_ORDER);inactive();++cases;
 direct();CHECK(houjiGpuHandoffRead(nullptr,0x171004,&v)==HGHP_IO_OWNER);inactive();++cases;
 direct();p.active=0;CHECK(houjiGpuHandoffRead(&p,0x171004,&v)==HGHP_IO_OWNER);inactive();++cases;
 direct();CHECK(houjiGpuHandoffRead(&p,0x171004,nullptr)==HGHP_IO_ARGUMENT);inactive();++cases;
 direct();p.calls=HGHP_READS;CHECK(houjiGpuHandoffRead(&p,0x171004,&v)==HGHP_IO_CAPACITY && !descriptors && !barriers);++cases;
 reset();houjiGpuHandoffProbeOnce();unsigned read_count=p.calls;CHECK(houjiGpuHandoffRead(&p,0x171004,&v)==HGHP_IO_OWNER && p.calls==read_count);++cases;
 printf("PASS: %u actual XNU handoff probe/decode/RO-map/order/partial-failure/retention cases (ASAN/UBSAN); %u real candidate loads per successful observation; no hardware qualification\n",cases,successful_reads);
}
'''

with tempfile.TemporaryDirectory(prefix='houji-gpu-handoff-') as temporary:
    directory = Path(temporary)
    c = directory / 'producer.c'
    cpp = directory / 'probe.cpp'
    obj = directory / 'producer.o'
    binary = directory / 'probe'
    c.write_text(producer)
    cpp.write_text(peer)
    flags = ['-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    subprocess.run(['clang', '-std=c11', *flags, '-I', str(POLICY), '-I', str(PROJECT / 'tests'), '-c', str(c), '-o', str(obj)], check=True)
    subprocess.run(['clang++', '-std=c++17', *flags, '-I', str(POLICY), '-I', str(XNU), str(cpp), str(obj), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
