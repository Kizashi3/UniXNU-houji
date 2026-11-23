#!/usr/bin/env python3
"""Check the actual cached display snapshot with truncated output buffers."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
text = (ROOT / 'kernel/overlay/iokit/Kernel/arm/SweetFramebuffer.cpp').read_text()
at = text.index('extern "C" unsigned houji_framebuffer_snapshot(')
function = text[at:text.index('\n}\n', at) + 3]
# Compile the real declarations as well as the snapshot function. The clock
# stub converts ticks to ns without exercising hardware or copying pixels.
declarations = text[text.index('static uint64_t houji_fb_copy_bytes'):text.index('struct HoujiRectObservation')]
unit = r'''
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cassert>
#include <vector>
static uint64_t mach_absolute_time(){return 123456789000;}
static void absolutetime_to_nanoseconds(uint64_t ticks,uint64_t *ns){*ns=ticks;}
''' + declarations + r'''
struct Colour {uint32_t sequence,values[12];};
struct Rect {uint32_t sequence,values[15];};
static Colour houji_fb_colour_peaks[4];
static Rect houji_fb_rects[8];
static unsigned long long houji_fb_colour_frames=42,houji_fb_colour_purple=23,houji_fb_colour_zero_alpha=17;
''' + function + r'''
int main(){
 assert(houji_framebuffer_snapshot(nullptr,0)==0);
 for(auto &s:houji_fb_colour_peaks){s.sequence=1;s.values[2]=0x42475241;s.values[7]=64;}
 for(auto &s:houji_fb_rects){s.sequence=1;s.values[6]=uint32_t(-10);}
 houji_fb_config_hz=120;houji_fb_started_at=1000000000;
 sweet_fb_swap_count=99;houji_fb_present_count=97;
 houji_fb_history_count=51; // retain recent intervals after the ring wraps
 for(unsigned n=48;n<=51;n++){auto &s=houji_fb_history[(n-1)%40];s.sequence=n;s.values[3]=96;}
 houji_fb_history[(50-1)%40].sequence=0; // an in-progress writer is omitted
 for(unsigned capacity=0;capacity<=4096;capacity++){
  std::vector<char> buffer(capacity+2,char(0x5a));
  unsigned used=houji_framebuffer_snapshot(buffer.data()+1,capacity);
  assert(buffer.front()==0x5a && buffer.back()==0x5a);
  assert(capacity ? used<capacity : used==0);
  if(capacity){assert(buffer[used+1]==0);assert(!used || buffer[used]=='\n');}
  if(capacity==4096){
   const char *s=buffer.data()+1;
   assert(strstr(s,"fmt=42475241") && strstr(s,"src=-10,"));
   assert(strstr(s,"configured-hz=120") && strstr(s,"swaps=99 completed=97"));
   assert(strstr(s,"sample=51 ") && strstr(s,"sample=48 "));
   assert(!strstr(s,"sample=50 ") && !strstr(s,"sample=47 "));
   assert(strstr(s,"not panel FPS") && strstr(s,"not panel vblank"));
  }
 }
 puts("PASS: display timing/copy/queue and wrapped history retained with colour/crop; complete rows at every capacity; no framebuffer or MMIO");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-display-snapshot-') as directory:
    source, binary = Path(directory) / 'snapshot.cpp', Path(directory) / 'snapshot'
    source.write_text(unit)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-Wno-unused-variable',
                    '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
