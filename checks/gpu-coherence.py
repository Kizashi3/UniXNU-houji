#!/usr/bin/env python3
"""Check the real two-way proof verdict and source-bound CP copy packets.

This is not a cache/GPU simulation and cannot establish hardware coherence.
"""
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
GPU = ROOT / 'kernel/overlay/iokit/Kernel/houji-ufs-root'
unit = r'''
#include <cassert>
#include <cstdio>
#define HGKI_PROGRESS 1
#include "HoujiGpuCoherencePolicy.h"
int main(){
 for(unsigned attr=0;attr<256;attr++){
  bool uncached=attr==0 || attr==4 || attr==8 || attr==12 || attr==0x44;
  assert(houjiCoherenceUncachedAttribute(attr)==uncached);
 }
 uint32_t words[7]{};
 assert(!houjiCoherenceCopyPlan(2,words));
 assert(!houjiCoherenceCopyPlan(0,nullptr));
 for(unsigned direction=0;direction<2;direction++){
  assert(houjiCoherenceCopyPlan(direction,words));
  assert(((words[0]>>16)&0x7f)==0x75 && (words[0]&0x3fff)==5);
  assert(((words[6]>>16)&0x7f)==0x12 && (words[6]&0x3fff)==0);
  uint64_t source=words[2]|((uint64_t)words[3]<<32),dest=words[4]|((uint64_t)words[5]<<32);
  assert(words[1]==1024 && source==HoujiCoherenceVa+direction*32768);
  assert(dest==source+16384 && dest+words[1]*4<=HoujiCoherenceVa+65536);
  assert(!(source&16383) && !(dest&16383));
 }
 assert(HoujiCoherenceCommandVa+16384<=HoujiCoherenceVa);
 assert(HGKI_OUTPUT_BYTES==4096 && HGKI_SELECTED_COMMAND_WORDS*4<=HoujiCoherencePage);
 for(unsigned direction=2;direction<4;direction++){
  unsigned changes=0;uint32_t word=0;
  for(unsigned i=0;i<HGKI_SELECTED_COMMAND_WORDS;i++){
   assert(houjiCoherenceDrawWord(direction,i,&word));
   if(hgki_command_word(i)==HGKI_OUTPUT){
    assert(word==HoujiCoherenceVa+(direction==2?1:3)*HoujiCoherencePage);++changes;
   }else assert(word==hgki_command_word(i));
  }
  assert(changes==1);
  assert(!houjiCoherenceDrawWord(direction,HGKI_SELECTED_COMMAND_WORDS,&word));
 }
 uint32_t invalid=0;
 assert(!houjiCoherenceDrawWord(1,0,&invalid));assert(!houjiCoherenceDrawWord(4,0,&invalid));
 assert(!houjiCoherenceDrawWord(2,0,nullptr));
 assert(houjiCoherenceProved(6,48,1024,0,1024,1024,0));
 assert(houjiCoherenceProved(6,64,1024,0,1024,1024,0));
 // A successful copy with no dirty-source evidence is inconclusive.
 for(unsigned dirty=0;dirty<48;dirty++)assert(!houjiCoherenceProved(6,dirty,1024,0,1024,1024,0));
 assert(!houjiCoherenceProved(6,65,1024,0,1024,1024,0));
 for(unsigned count=0;count<1024;count++){
  assert(!houjiCoherenceProved(6,64,count,0,1024,1024,0));
  assert(!houjiCoherenceProved(6,64,1024,0,count,1024,0));
  assert(!houjiCoherenceProved(6,64,1024,0,1024,count,0));
 }
 assert(!houjiCoherenceProved(5,64,1024,0,1024,1024,0));
 assert(!houjiCoherenceProved(6,64,1024,1,1024,1024,0));
 assert(!houjiCoherenceProved(6,64,1024,0,1024,1024,1));
 puts("PASS: two-way coherence proof rejects vacuous/partial/stale/error results; fixed CP copy packets stay within exclusive CPU16K pages; no hardware coherence claim");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-coherence-') as d:
    d=Path(d);src=d/'proof.cpp';binary=d/'proof';obj=d/'pm4.o';src.write_text(unit)
    subprocess.run(['clang','-std=c11','-fsanitize=address,undefined','-I',str(GPU),'-c',str(GPU/'AdrenoPM4.c'),'-o',str(obj)],check=True)
    # This C header intentionally zero-initializes omitted aggregate fields.
    # Clang 18 warns when it is included by the C++ fixture, unlike a C TU.
    subprocess.run(['clang++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-missing-field-initializers','-fsanitize=address,undefined','-I',str(GPU),str(src),str(obj),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
