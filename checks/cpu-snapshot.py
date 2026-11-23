#!/usr/bin/env python3
"""Compile the real CPU interval formatter; no clocks, firmware or device I/O."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / 'kernel/overlay/iokit/Kernel/arm/HoujiCpuDvfs.inc').read_text()
start = text.index('struct LatestWindow')
declaration = text[start:text.index('\nstatic uint32_t read', start)]
start = text.index('extern "C" unsigned houji_cpu_dvfs_snapshot(')
function = text[start:text.index('\n}\n', start) + 3]
unit = r'''
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cassert>
#include <vector>
namespace HoujiCpuDvfs {
''' + declaration + '\n}\n' + function + r'''
int main(){
 assert(!houji_cpu_dvfs_snapshot(nullptr,0));
 char pending[128];houji_cpu_dvfs_snapshot(pending,sizeof pending);
 assert(strstr(pending,"pending"));
 auto &s=HoujiCpuDvfs::latest;
 s.sequence=70; // five-second intervals continue beyond the first 48
 s.values[0]=350000;s.values[1]=5000000;s.values[2]=1000000;s.values[3]=3000000;
 for(unsigned i=0;i<8;i++)s.values[5+i]=100*i;
 for(unsigned i=0;i<4;i++){
  s.values[13+i]=2000000;s.values[17+i]=499200;s.values[21+i]=3302400;
  s.values[25+i]=i;s.values[29+i]=10;
 }
 for(unsigned capacity=0;capacity<=1024;capacity++){
  std::vector<char> out(capacity+2,'Z');
  unsigned used=houji_cpu_dvfs_snapshot(out.data()+1,capacity);
  assert(out.front()=='Z' && out.back()=='Z');
  assert(capacity?used<capacity:used==0);
  if(capacity){assert(out[used+1]==0);assert(!used || out[used]=='\n');}
  if(capacity==1024){
   const char *p=out.data()+1;
   assert(strstr(p,"n=70 up-ms=350000 span-us=5000000"));
   assert(strstr(p,"core-permille=0,100,200,300,400,500,600,700"));
   for(unsigned id=0;id<4;id++){char expected[32];snprintf(expected,sizeof expected,"DOMAIN: id=%u ",id);assert(strstr(p,expected));}
   assert(strstr(p,"not power measurement"));
  }
 }
 puts("PASS: actual CPU last-interval formatter; late sample, four domains, load, bounds, complete rows; no device I/O");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-cpu-snapshot-') as temporary:
    source, binary = Path(temporary) / 'snapshot.cpp', Path(temporary) / 'snapshot'
    source.write_text(unit)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
