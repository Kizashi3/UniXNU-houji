#!/usr/bin/env python3
"""Check retained CPU diagnostics, including concurrent writers and small buffers.

This does not model the GPU, scheduler, cache coherence or display performance.
"""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
GPU = ROOT / 'kernel/overlay/iokit/Kernel/houji-ufs-root'
provider = (GPU / 'HoujiGpuNativeProvider.inc').read_text()
publish = (GPU / 'Adreno740/NativeAdrenoPublish.cpp').read_text()
vm = (GPU / 'Adreno740/NativeAdrenoVm.cpp').read_text()
phase_start = vm.index('struct PhaseClock {')
phase_clock = vm[phase_start:vm.index('\n};', phase_start) + 3]

def function(source, name):
    start = source.index('extern "C" unsigned ' + name + '(char *out,unsigned capacity){')
    return source[start:source.index('\n}', start) + 2]

unit = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>
#include <atomic>
#include "Adreno740/NativeAdrenoLatency.h"
#include "Adreno740/NativeAdrenoAllocationTrace.h"
NativeAdrenoAllocationTrace nativeAdrenoAllocationTrace;
extern "C" {uint64_t (*native_adreno_memory_now_us)(void)=nullptr;}
static uint64_t allocationNow=0;
static uint64_t readAllocationNow(){return allocationNow;}
static struct {uint64_t count,total,max,phase[5],audits;} gHoujiGatePerf;
volatile uint64_t native_adreno_vm_phase_us[2][8];
uint64_t native_adreno_vm_phase_max_us[2][6];
uint64_t native_adreno_vm_alias_paths[2]={7,3};
static uint64_t phaseNow;
static uint64_t readPhaseNow(){return phaseNow;}
uint64_t (*native_adreno_vm_now_us)(void)=readPhaseNow;
static uint64_t gHoujiPresentSync[14];
''' + phase_clock + '\n' + function(provider, 'houji_gpu_gate_snapshot') + '\n' + function(publish, 'native_adreno_present_sync_snapshot') + r'''
static std::string snapshot(const NativeAdrenoLatency &s) {
 std::string result;
 s.snapshot([&](const char *format,auto... args){char line[1024];int n=snprintf(line,sizeof line,format,args...);assert(n>0 && (unsigned)n<sizeof line);result+=line;});
 return result;
}
int main(){
 int allocationStatus=0;
 {NativeAdrenoAllocationTimer disabled(0,4096,allocationStatus);disabled.lap(2);}
 assert(!nativeAdrenoAllocationTrace.counters[0].calls);
 native_adreno_memory_now_us=readAllocationNow;
 {NativeAdrenoAllocationTimer timer(0,16384,allocationStatus);
  allocationNow=1000;timer.lap(0);allocationNow=7000;timer.lap(2);
  allocationNow=9000;timer.lap(3);allocationStatus=9;
 }
 const auto &cost=nativeAdrenoAllocationTrace.counters[0];
 assert(cost.calls==1 && cost.failures==1 && cost.bytes==16384 && cost.total==9000);
 assert(cost.phase[0]==1000 && cost.phase[2]==6000 && cost.phase[3]==2000);
 NativeAdrenoAllocationTrace allocation;std::atomic<unsigned> allocationDone{0};std::vector<std::thread> allocationWriters;
 for(unsigned route=0;route<3;++route)allocationWriters.emplace_back([&,route]{
  for(unsigned n=0;n<5000;++n){uint64_t p[4]={0,10000,0,0};allocation.record(route,4096*(route+1),route,p,route);}
  allocationDone++;
 });
 do {
  allocation.snapshot([&](const char *format,auto... args){
   char line[1024];int n=snprintf(line,sizeof line,format,args...);assert(n>0 && (unsigned)n<sizeof line);
   if(!strncmp(line,"HOUJI BO SLOW:",14)){
    unsigned long long seq,route,bytes,start,elapsed,a,b,c,d,status;
    assert(sscanf(line,"HOUJI BO SLOW: seq=%llu route=%llu bytes=%llu start-us=%llu us=%llu phases=%llu/%llu/%llu/%llu status=%llx",&seq,&route,&bytes,&start,&elapsed,&a,&b,&c,&d,&status)==10);
    assert(route<3 && bytes==4096*(route+1) && start==route && elapsed==10000 && a==0 && b==10000 && c==0 && d==0 && status==route);
   }
  });
 }while(allocationDone.load()!=3);
 for(auto &t:allocationWriters)t.join();
 for(unsigned route=0;route<3;++route)assert(allocation.counters[route].calls==5000 && allocation.counters[route].total==50000000);
 assert(allocation.records+allocation.dropped==15000);
 PhaseClock vmTiming;phaseNow=80000;vmTiming.lap(0,3);phaseNow=80005;vmTiming.lap(0,4);vmTiming.done(0,4096);
 assert(native_adreno_vm_phase_max_us[0][3]==80000 && native_adreno_vm_phase_max_us[0][4]==5);
 PhaseClock shorter;phaseNow+=10;shorter.lap(0,3);shorter.done(0,8192);
 assert(native_adreno_vm_phase_max_us[0][3]==80000 && native_adreno_vm_phase_us[0][0]==2 && native_adreno_vm_phase_us[0][7]==12288);
 native_adreno_vm_now_us=nullptr;PhaseClock disabled;disabled.lap(0,3);disabled.done(0,1);
 assert(native_adreno_vm_phase_us[0][0]==2);
 NativeAdrenoLatency s;uint64_t phases[4]={1000,2000,3000,14000};
 s.record(20,0,20000,phases,0);assert(!s.records);
 s.record(17,1,19999,phases,0);assert(!s.records);
 for(unsigned n=1;n<=17;n++)s.record(17,n*100,20000,phases,0);
 assert(s.methods[17].calls==18 && s.methods[17].total==359999);
 assert(s.methods[17].maximum==20000 && s.methods[17].phaseMax[2]==3000);
 auto text=snapshot(s);assert(text.find("seq=17 id=17 start-us=1700")!=text.npos);
 assert(text.find("seq=10 id=17 start-us=1000")!=text.npos && text.find("seq=9 ")==text.npos);
 s.writing=1;s.record(2,0,25000,phases,0);s.writing=0;assert(s.dropped==1 && s.records==17);
 s.slow[0].sequence=0;assert(snapshot(s).find("seq=17 ")==text.npos);
 NativeAdrenoLatency concurrent;std::atomic<unsigned> done{0};std::vector<std::thread> writers;
 for(unsigned id=1;id<=4;id++)writers.emplace_back([&,id]{
  for(unsigned n=0;n<5000;n++){uint64_t p[4]={id*10000,0,0,0};concurrent.record(id,id,id*10000,p,id);}
  done++;
 });
 do {
  auto output=snapshot(concurrent);size_t at=0;
  while((at=output.find("HOUJI SLOW:",at))!=output.npos){
   unsigned long long seq,id,start,elapsed,lock,gate,core,other,status;
   assert(sscanf(output.c_str()+at,"HOUJI SLOW: seq=%llu id=%llu start-us=%llu us=%llu lock=%llu gate=%llu core=%llu other=%llu status=%llx",&seq,&id,&start,&elapsed,&lock,&gate,&core,&other,&status)==9);
   assert(start==id && status==id && elapsed==id*10000 && lock==elapsed && gate==0 && core==0 && other==0);at++;
  }
 }while(done.load()!=4);
 for(auto &t:writers)t.join();
 for(unsigned id=1;id<=4;id++)assert(concurrent.methods[id].calls==5000 && concurrent.methods[id].total==uint64_t(id)*50000000);
 assert(concurrent.records+concurrent.dropped==15000);
 gHoujiGatePerf.count=42;gHoujiGatePerf.phase[0]=123;gHoujiPresentSync[8]=251000;gHoujiPresentSync[13]=4242;
 for(unsigned capacity=0;capacity<=16384;capacity++)for(auto fn:{houji_gpu_gate_snapshot,native_adreno_present_sync_snapshot}){
  std::vector<char> bytes(capacity+2,char(0x5a));unsigned used=fn(bytes.data()+1,capacity);
  assert(bytes.front()==0x5a && bytes.back()==0x5a && (capacity?used<capacity:used==0));
  if(capacity){assert(bytes[used+1]==0);assert(!used || bytes[used]=='\n');}
  if(capacity==16384){assert(used>100);if(fn==houji_gpu_gate_snapshot)assert(strstr(bytes.data()+1,"n=42") && strstr(bytes.data()+1,"wait-us=123"));else assert(strstr(bytes.data()+1,"max-lock-wait-us=251000") && strstr(bytes.data()+1,"signals=4242"));}
 }
 assert(!houji_gpu_gate_snapshot(nullptr,2) && !native_adreno_present_sync_snapshot(nullptr,2));
 puts("PASS: retained method phases and latest slow records survive concurrency/wrap; cached gate/present snapshots are bounded; no GPU or FPS claim");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-gpu-latency-') as directory:
    source, binary = Path(directory) / 'latency.cpp', Path(directory) / 'latency'
    source.write_text(unit)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pthread',
                    '-fsanitize=address,undefined', '-I', str(GPU), str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=30)
