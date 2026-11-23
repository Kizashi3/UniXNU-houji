#!/usr/bin/env python3
"""Exercise the actual read-only DSI0 register selection and cached formatter."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = r'''
#include <cstdio>
#include <cstring>
#include <cassert>
#include <vector>
#include "HoujiDisplayTiming.h"
using namespace HoujiDisplayTiming;
static std::vector<uint32_t> offsets;
static uint32_t read(void *ctx,uint32_t offset) {
 assert(ctx==&offsets && offset<Bytes && !(offset&3));offsets.push_back(offset);return offset;
}
int main() {
 static_assert(Base+Interface==0x0ae36000 && Base+Control==0x0ae16000);
 Snapshot s{};readConfiguration(s,&offsets,read);assert(offsets.size()==55);
 for(unsigned i=0;i<5;++i)assert(readCounts(s,i,&offsets,read,1000000ull*i));
 assert(offsets.size()==75 && !readCounts(s,5,&offsets,read,0) && offsets.size()==75);
 assert(s.config[8]==Interface+0x2b4 && s.counts[4][2]==Interface+0x298);
 assert(s.pipes[0][1]==0x5014 && s.pipes[9][1]==0x2f014);
 assert(format(s,3,nullptr,0)==0);
 for(unsigned state=0;state<=4;++state)for(unsigned size=0;size<=4096;++size) {
  std::vector<char> out(size+2,char(0x5a));unsigned n=format(s,state,out.data()+1,size);
  assert(out.front()==0x5a && out.back()==0x5a);
  if(size){assert(n<size && out[n+1]==0);assert(!n || out[n]=='\n');}else assert(!n);
  if(size==4096){
   assert(strstr(out.data()+1,"no refresh or scanout writes"));
   assert(bool(strstr(out.data()+1,"sample=4"))==(state==3));
   if(state==3)assert(strstr(out.data()+1,"not rendered FPS") && strstr(out.data()+1,"offset=2f000"));
  }
 }
 puts("PASS: DSI0/MDSS read-only offsets, bounded samples and cached/truncated timing output; no hardware");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-display-timing-') as temp:
    path = Path(temp)
    (path / 'check.cpp').write_text(source)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-I' + str(ROOT / 'kernel/overlay/iokit/Kernel/arm'),
                    str(path / 'check.cpp'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
