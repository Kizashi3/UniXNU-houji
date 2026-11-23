#!/usr/bin/env python3
"""Exercise actual input-burst capture and GPU policy; no clocks or GPU emulated."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'kernel/overlay/iokit/Kernel/arm/HoujiCpuDvfs.inc').read_text()
start = source.index('static uint64_t houjiTouchTime;')
capture = source[start:source.index('namespace HoujiCpuDvfs', start)]
gpu = (ROOT / 'kernel/overlay/iokit/Kernel/houji-ufs-root/HoujiGpuDvfs.inc').read_text()
record_start = gpu.index('struct HoujiGpuTouchWakeRecord ')
records = gpu[record_start:gpu.index('static bool houjiDvfsRead', record_start)]
formatter = gpu[gpu.index('extern "C" unsigned houji_gpu_dvfs_snapshot'):]
unit = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include "kernel/overlay/iokit/Kernel/houji-ufs-root/HoujiGpuGovernorPolicy.h"
static uint64_t ticks;
static uint64_t mach_absolute_time(){return ticks;}
static void absolutetime_to_nanoseconds(uint64_t v,uint64_t *out){*out=v;}
''' + capture + r'''
static struct {
 unsigned ready=1,bad=0,level=1,cap=HCO_COUNT,changes=0,failed=0,busyPermille=0;
 HoujiGpuGovernorPolicy policy={};uint64_t at[HCO_COUNT+1]={};
 unsigned touchPrewarms=1,touchBursts=3,touchActive=1,touchLate=1;
} gHoujiDvfs;
static unsigned houji_thermal_gpu_cap(){return HCO_COUNT;}
''' + records + formatter + r'''
int main(){
 auto contact=[](uint64_t ns){ticks=ns;houji_dvfs_touch();};
 contact(1000000);
 assert(houji_dvfs_touch_time()==1000000 && houji_dvfs_touch_burst_time()==1000000);
 // The governor can miss several reports. Continuous input must retain the
 // real burst start, not look like a new contact after the delayed poll.
 for(uint64_t ns=9000000;ns<100000000;ns+=8000000)contact(ns);
 assert(houji_dvfs_touch_burst_time()==1000000);
 uint64_t seen=0,until=0;
 assert(!houjiGpuArmTouchWake(110000,1000,true,&seen,&until) && seen==1000 && !until);
 contact(200000000);uint64_t burst=houji_dvfs_touch_burst_time()/1000;
 assert(burst==200000 && houjiGpuArmTouchWake(210000,burst,true,&seen,&until));
 assert(until==250000);
 for(uint64_t now=210001;now<=260000;now+=1000)
  assert(!houjiGpuArmTouchWake(now,burst,true,&seen,&until) && until==250000);
 for(uint64_t ns=208000000;ns<=400000000;ns+=8000000)contact(ns);
 assert(houji_dvfs_touch_burst_time()==200000000);
 contact(1000000);assert(houji_dvfs_touch_time()==400000000);
 assert(houji_dvfs_touch_burst_time()==200000000); // backwards timestamp ignored
 assert(!houjiGpuArmTouchWake(500000,600000,true,&seen,&until) && seen==200000);
 assert(!houjiGpuArmTouchWake(600000,600000,false,&seen,&until) && seen==600000);
 assert(!houjiGpuArmTouchWake(610000,600000,true,&seen,&until)); // no replay after becoming idle
 assert(!houjiGpuArmTouchWake(UINT64_MAX-5,UINT64_MAX-5,true,&seen,&until));
 for(unsigned cap=1;cap<=HCO_COUNT;cap++){
  HoujiGpuGovernorPolicy p={};unsigned cur=1;
  // Headroom starts with no GPU work at all, is bounded by this cap and
  // cannot keep an idle GPU boosted once the pulse has expired.
  cur=houjiGpuChoose(&p,cur,cap,0,0,1,2,0);
  assert(cur==hco_at_least((uint64_t)hco_opp(cap)->khz*3/5,cap));
  if(cap==HCO_COUNT)assert(cur==6 && cur<cap);
  assert(houjiGpuChoose(&p,cur,1,0,0,1,2,0)==1);
  for(unsigned n=0;n<100;n++)cur=houjiGpuChoose(&p,cur,cap,0,0,1,0,0);
  assert(cur==1);
 }
 houjiGpuTouchWakeRecords[0]={1,210000,10000,1,6,HCO_COUNT,0,0};
 for(unsigned capacity=0;capacity<=4096;capacity++){
  std::vector<char> b(capacity+2,'Z');unsigned used=houji_gpu_dvfs_snapshot(b.data()+1,capacity);
  assert(b.front()=='Z' && b.back()=='Z' && (capacity?used<capacity:used==0));
  if(capacity)assert(b[used+1]==0);
  if(capacity==4096){assert(strstr(b.data()+1,"count=1 bursts=3 already-active=1 late=1"));assert(strstr(b.data()+1,"before-level=1 after-level=6"));}
 }
 assert(!houji_gpu_dvfs_snapshot(nullptr,1));
 puts("PASS: actual input burst survives delayed polling; held contact cannot renew prewarm; stale/future/replayed input rejected; 50 ms deadline and every thermal cap preserved (host only)");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-input-prewarm-') as directory:
    src, binary = Path(directory) / 'input.cpp', Path(directory) / 'input'
    src.write_text(unit)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I', str(ROOT), str(src),
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
