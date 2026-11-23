#!/usr/bin/env python3
"""Compile the actual touch transform and timer deadline block with mocks."""
from pathlib import Path
import re
import subprocess
import tempfile

P = Path(__file__).resolve().parents[1]
fb = (P / 'native/display/SweetFramebuffer.cpp').read_text()
hid = (P / 'native/display/SweetHID.cpp').read_text()
assert re.search(r'#define HOUJI_LOGICAL_W 1200\b', fb)
assert re.search(r'#define HOUJI_LOGICAL_H 2670\b', fb)
clamp = hid[hid.index('\tx = x < 0'):hid.index('\n\tIOLockLock(fLock);', hid.index('\tx = x < 0'))]
begin = hid.index('\t/* The native iOS canvas covers')
transform = hid[begin:hid.index('\n\tbool moved =', begin)]
begin = fb.index('\tuint64_t next = fb->fNextVsync')
deadline = fb[begin:fb.index('\n\tfb->fNextVsync = next;', begin)]
assert 'IOMalloc' not in fb[fb.index('AppleCLCD::vsyncFired'):fb.index('AppleCLCD::addClient')]
program = r'''
#include <stdint.h>
#include <assert.h>
#include <limits.h>
#include <stdio.h>
typedef int32_t IOFixed;
static uint64_t houji_fb_missed_timer_ticks;
struct Timer { uint64_t fNextVsync, fVsyncPeriod, fVsyncCount; };
static void touch(int x, int y, int32_t *out) {
''' + clamp + transform + r'''
 out[0]=nx;out[1]=ny;
}
static uint64_t next_timer(uint64_t base,uint64_t period,uint64_t now) {
 Timer timer={base,period,0};Timer *fb=&timer;
''' + deadline + r'''
 return next;
}
int main() {
 int32_t out[2];
 touch(INT_MIN,INT_MIN,out);assert(out[0]==0&&out[1]==0);
 touch(INT_MAX,INT_MAX,out);
 assert(out[0]==((1199LL<<16)/1200)&&out[1]==((2669LL<<16)/2670));
 int previous=-1;
 for(int x=0;x<1200;x++) {touch(x,1335,out);assert(out[0]>previous);previous=out[0];assert(out[1]==32768);}
 previous=-1;
 for(int y=0;y<2670;y++) {touch(600,y,out);assert(out[1]>previous);previous=out[1];assert(out[0]==32768);}
 for(uint64_t p=1;p<1000;p+=7) for(uint64_t n=100;n<10000;n+=31) {
  uint64_t next=next_timer(100,p,n);
  assert(next>n && next-n<=p && (next-100)%p==0);
 }
 assert(next_timer(0,10,0)==10);assert(next_timer(0,10,9)==10);
 assert(next_timer(0,10,10)==20);assert(next_timer(0,10,1000)==1010);
 puts("PASS: physical touch covers the native canvas; absolute deadlines retain phase, skip stale ticks and never schedule in the past; no per-frame allocation");
}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / 'check.cpp').write_text(program)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(path / 'check.cpp'),
                    '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
