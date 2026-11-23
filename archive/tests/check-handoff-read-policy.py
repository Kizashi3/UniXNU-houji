#!/usr/bin/env python3
"""Check that only the diagnostic stub's exact read abort can be recovered."""
import argparse,ctypes
from pathlib import Path
import subprocess,tempfile
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--uefi',type=Path,required=True);a=p.parse_args()
h=a.uefi/'Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe/HandoffReadPolicy.h'
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);c=root/'policy.c';so=root/'policy.so'
 c.write_text('''#include <stdint.h>
typedef uint32_t UINT32;typedef uint64_t UINT64;typedef int BOOLEAN;
#define STATIC static
#define TRUE 1
#define FALSE 0
'''+ '#include "'+str(h)+'"\n'+'''
int address(UINT64 a){return HandoffAddressAllowed(a);}
int fault(int armed,UINT64 want,UINT64 a,UINT64 pc,UINT64 esr,UINT64 far,UINT32 op){return HandoffFaultExpected(armed,want,a,pc,esr,far,op);}
''')
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-shared','-fPIC',str(c),'-o',str(so)],check=True)
 lib=ctypes.CDLL(str(so));lib.address.argtypes=[ctypes.c_uint64];lib.fault.argtypes=[ctypes.c_int,*([ctypes.c_uint64]*5),ctypes.c_uint32]
 for at in (0,0x1d83ffc,0x1d84000,0x1d84001,0x1d86ffc,0x1d87000,0x14fffffc,0x15000000,0x150cfffC,0x150d0000,0xffffffffffffffff):
  wanted=at%4==0 and (0x1d84000<=at<0x1d87000 or 0x15000000<=at<0x150d0000)
  assert bool(lib.address(at))==wanted
 good=[1,0xb8001000,0x15000800,0xb8001000,0x96000010,0x15000800,0xb9400000]
 assert lib.fault(*good)
 assert lib.fault(*[1,good[1],0x1d84000,good[3],good[4],0x1d84000,good[6]])
 for field in range(len(good)):
  for bit in range(32 if field in (4,6) else 64):
   bad=list(good);bad[field]^=1<<bit
   if field==4 and bit>=11 and bit<26: continue # irrelevant ISS syndrome details
   if field==4 and bit>=32: continue
   if field==0: bad[field]=0
   assert not lib.fault(*bad),(field,bit)
 print('PASS: aligned MMIO windows; exact stub PC/LDR/FAR; armed-only same-EL synchronous external read abort; write, translation, page-walk, invalid FAR, other opcode/PC and asynchronous exception do not recover.')
