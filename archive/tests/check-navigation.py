#!/usr/bin/env python3
"""Exercise the real HID contact method and inspect the linked syscall table."""
from pathlib import Path
import argparse
import re
import struct
import subprocess
import tempfile

P = Path(__file__).resolve().parents[1]
a = argparse.ArgumentParser(description=__doc__)
a.add_argument('--kernel', type=Path)
args = a.parse_args()
source = (P / 'native/display/SweetHID.cpp').read_text()
method = source[source.index('void\nSweetHIDTouch::touch('):source.index('/* key: 0 power')]
edge = re.search(r'#define HOUJI_TOUCH_EDGE_PX \d+', source)[0]
program = r'''
#include <stdint.h>
#include <assert.h>
#include <vector>
#include <stdio.h>
using UInt32=uint32_t; using IOFixed=int32_t;
#define SWEET_TOUCH_FINGERS 10
#define TRUE 1
enum {kIOHIDDigitizerTransducerTypeHand,kIOHIDDigitizerTransducerTypeFinger,
kIOHIDEventFieldDigitizerCollection,kIOHIDEventFieldDigitizerIndex,
kIOHIDEventFieldDigitizerIdentity,kIOHIDEventFieldDigitizerTouch,
kIOHIDEventFieldDigitizerEventMask,kIOHIDEventFieldDigitizerX,
kIOHIDEventFieldDigitizerY,kIOHIDEventFieldDigitizerRange,kIOHIDEventFieldDigitizerButtonMask};
enum {kIOHIDDigitizerEventTouch=1,kIOHIDDigitizerEventRange=2,
kIOHIDDigitizerEventPosition=4,kIOHIDDigitizerEventIdentity=8,
kIOHIDDigitizerEventFromEdgeTip=1<<11};
static int locked;
static uint64_t mach_absolute_time(){return 1;}
static void IOLockLock(void*){assert(!locked);locked=1;}
static void IOLockUnlock(void*){assert(locked);locked=0;}
template<class... T> void IOLog(const char*,T...){ }
struct IOHIDEvent {
 UInt32 mask=0,index=0; std::vector<IOHIDEvent> children;
 static IOHIDEvent* digitizerEvent(uint64_t,UInt32,int,bool,int,IOFixed,IOFixed){return new IOHIDEvent;}
 void setIntegerValue(int key,UInt32 v){if(key==kIOHIDEventFieldDigitizerEventMask)mask=v;
  if(key==kIOHIDEventFieldDigitizerIndex)index=v;}
 void setFixedValue(int,IOFixed){}
 void appendChild(IOHIDEvent* v){children.push_back(*v);}
 void release(){delete this;}
};
class SweetHIDTouch {
public:
 void* fLock=nullptr; bool fDown[10]={},fEdge[10]={};IOFixed fX[10]={},fY[10]={};
 IOHIDEvent last; unsigned dispatched=0;
 void touch(int,bool,int,int);
 void dispatchEvent(IOHIDEvent* e){assert(!locked);last=*e;dispatched++;}
 UInt32 mask(unsigned i){for(auto& c:last.children)if(c.index==i)return c.mask;assert(false);return 0;}
};
''' + edge + '\n' + method + r'''
int main(){
 const UInt32 E=kIOHIDDigitizerEventFromEdgeTip;
 // Every physical edge, exact inner boundary, and corners.
 const int points[][3]={{600,2669,1},{0,1335,1},{1199,1335,1},{600,0,1},
 {48,48,0},{1151,2621,0},{1152,1335,1},{600,2622,1},{600,1335,0}};
 for(auto& p:points){SweetHIDTouch t;t.touch(0,true,p[0],p[1]);assert(bool(t.mask(0)&E)==bool(p[2]));
  t.touch(0,true,600,1335);assert(bool(t.mask(0)&E)==bool(p[2]));
  t.touch(0,false,600,1335);assert(bool(t.mask(0)&E)==bool(p[2]));
  t.touch(0,true,600,1335);assert(!(t.mask(0)&E));}
 SweetHIDTouch t;t.touch(0,true,600,1335);t.touch(0,true,600,2669);assert(!(t.mask(0)&E));
 t.touch(1,true,600,2669);assert(t.mask(1)&E);assert(!(t.mask(0)&E));
 t.touch(1,false,600,1335);assert(t.mask(1)&E);assert(!(t.mask(0)&E));
 unsigned n=t.dispatched;t.touch(-1,true,0,0);t.touch(10,true,0,0);assert(t.dispatched==n);
 puts("PASS: real HID method preserves edge origin through move/lift, isolates contacts and resets on next contact");
}
'''
with tempfile.TemporaryDirectory() as directory:
    d = Path(directory)
    (d / 'check.cpp').write_text(program)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(d / 'check.cpp'), '-o', str(d / 'check')], check=True)
    subprocess.run([str(d / 'check')], check=True)

if args.kernel:
    binary = args.kernel.read_bytes()
    assert struct.unpack_from('<I', binary)[0] == 0xfeedfacf
    nm = subprocess.check_output(['xcrun', 'nm', str(args.kernel)], text=True)
    syms = {m[2]: int(m[1], 16) for line in nm.splitlines()
            if (m := re.fullmatch(r'([0-9a-f]+) [SsTt] (\S+)', line))}
    cursor = 32
    segments = []
    for _ in range(struct.unpack_from('<I', binary, 16)[0]):
        cmd, size = struct.unpack_from('<II', binary, cursor)
        if cmd == 0x19:
            vm, vm_size, offset, file_size = struct.unpack_from('<QQQQ', binary, cursor + 24)
            segments.append((vm, offset, file_size))
        cursor += size
    def read_pointer(address):
        vm, offset, size = next(s for s in segments if s[0] <= address < s[0] + s[2])
        return struct.unpack_from('<Q', binary, offset + address - vm)[0]
    table = syms['_sysent']
    strides = [size for size in (16, 24) if
               read_pointer(table + 433 * size) == syms['_pid_suspend'] and
               read_pointer(table + 434 * size) == syms['_pid_resume']]
    assert len(strides) == 1, 'Cannot identify actual syscall table layout'
    assert read_pointer(table + 435 * strides[0]) == syms['_pid_hibernate']
    print('PASS: linked syscall 435 points to native pid_hibernate, not nosys')
