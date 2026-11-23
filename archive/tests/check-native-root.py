#!/usr/bin/env python3
"""Actual root transport gate, span/RMW implementation and BCB field preservation."""
from pathlib import Path
import argparse,ctypes,struct,subprocess,tempfile
p=Path(__file__).resolve().parents[1];s=p/'native/ufs-root';n=Path('${HOUJI_ARTIFACTS}/native-port')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--gib',type=int,choices=(12,32),default=12)
parser.add_argument('--image',type=Path)
args=parser.parse_args()
image=args.image or n/'ios-userland/full-root-12g/ios16-full.hfsx'
assert image.stat().st_size==args.gib*1024**3
with tempfile.TemporaryDirectory() as td:
 d=Path(td);cpp=d/'root.cpp';so=d/'root.so'
 cpp.write_text('#include <stdint.h>\n#include <cstring>\n#include <map>\n#include <vector>\n#include <cassert>\n'+''.join('#include "'+str(s/f)+'"\n' for f in ('HoujiRootPolicy.h','HoujiRootWindow.h','HoujiRecoveryRecord.h'))+'''
extern "C" int gate(const uint8_t*u,unsigned dir,uint32_t b,bool en,bool arm){return houjiUfsRootCommandAllowed(u,32,dir,b,en,arm);}
extern "C" int bcbgate(const uint8_t*u,unsigned dir,uint32_t b,bool en,bool arm){return houjiUfsRecoveryCommandAllowed(u,32,dir,b,en,arm);}
extern "C" int bcb(uint8_t*p,unsigned n){return houjiRecoveryRecord(p,n);}
extern "C" int hfs(const uint8_t*p,unsigned n){return houjiHfsRootHeader(p,n);}
extern "C" void transfer_test(){
 struct Ops{
  std::map<uint32_t,std::vector<uint8_t>> pages;std::vector<int> trace;int fail=-1;
  bool read(uint32_t lba,unsigned blocks,uint8_t *p){trace.push_back(1);if(int(trace.size()-1)==fail)return false;
   assert(lba>=kHoujiRootFirst&&blocks<=32&&lba+blocks<=kHoujiRootFirst+kHoujiRootBlocks);
   for(unsigned i=0;i<blocks;i++){auto it=pages.find(lba+i);if(it==pages.end())memset(p+i*4096,uint8_t(lba+i),4096);else memcpy(p+i*4096,it->second.data(),4096);}return true;}
  bool write(uint32_t lba,unsigned blocks,const uint8_t *p){trace.push_back(2);if(int(trace.size()-1)==fail)return false;
   assert(lba>=kHoujiRootFirst&&blocks<=32&&lba+blocks<=kHoujiRootFirst+kHoujiRootBlocks);
   for(unsigned i=0;i<blocks;i++)pages[lba+i]=std::vector<uint8_t>(p+i*4096,p+(i+1)*4096);return true;}
 };
 std::vector<uint8_t> scratch(131072),input(262144,0x97),back(262144);
 const uint64_t offsets[]={0,512,3584,4096,kHoujiRootBytes-512,kHoujiRootBytes-262144};
 const uint64_t sizes[]={512,4096,4608,131072,131584,262144};
 for(auto offset:offsets)for(auto bytes:sizes){
  Ops ops;int r=houjiRootTransfer(ops,offset,input.data(),bytes,true,scratch.data());
  if(bytes>kHoujiRootBytes-offset){assert(r==1&&ops.trace.empty());continue;}
  assert(r==0);assert(houjiRootTransfer(ops,offset,back.data(),bytes,false,scratch.data())==0);
  assert(memcmp(input.data(),back.data(),bytes)==0);
  auto first=ops.pages.at(kHoujiRootFirst+uint32_t(offset/4096));
  for(unsigned j=0;j<(offset&4095);j++)assert(first[j]==uint8_t(kHoujiRootFirst+offset/4096));
  uint64_t end=offset+bytes;auto last=ops.pages.at(kHoujiRootFirst+uint32_t((end-1)/4096));
  if(end&4095)for(unsigned j=unsigned(end&4095);j<4096;j++)assert(last[j]==uint8_t(kHoujiRootFirst+(end-1)/4096));
 }
 for(int fail=0;fail<4;fail++){Ops ops;ops.fail=fail;assert(houjiRootTransfer(ops,512,input.data(),8192,true,scratch.data())==2);assert(ops.trace.size()==unsigned(fail+1));}
 Ops ops;assert(houjiRootTransfer(ops,UINT64_MAX,input.data(),512,true,scratch.data())==1&&ops.trace.empty());
 assert(houjiRootTransfer(ops,0,nullptr,512,true,scratch.data())==1);
}
''')
 subprocess.run(['c++','-std=c++14',f'-DHOUJI_ROOT_GIB={args.gib}','-Wall','-Wextra','-Werror','-shared','-fPIC',str(cpp),'-o',str(so)],check=True)
 lib=ctypes.CDLL(str(so));sig=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_bool,ctypes.c_bool];lib.gate.argtypes=sig;lib.bcbgate.argtypes=sig
 def command(op,lba,count,write=False):
  u=bytearray(32);u[0]=1;u[16]=op
  if op!=0x35:u[1]=0x20 if write else 0x40;struct.pack_into('>I',u,12,count*4096);struct.pack_into('>I',u,18,lba);struct.pack_into('>H',u,23,count)
  return u
 def gate(u,write=False,armed=True,enabled=True,bcb=False):
  return bool((lib.bcbgate if bcb else lib.gate)(ctypes.create_string_buffer(bytes(u)),0 if u[16]==0x35 else 1 if write else 2,struct.unpack_from('>I',u,12)[0],enabled,armed))
 first=2260480;end=first+args.gib*262144;cases=0
 for lba in (0,1,1024,4096,first-1,first,first+1,end-33,end-32,end-2,end-1,end,0xffffffff):
  for count in range(0,65):
   for op in (0x28,0x2a):
    for armed in (False,True):
     u=command(op,lba,count,op==0x2a);expect=first<=lba<end and 0<count<=32 and count<=end-lba and (op==0x28 or armed)
     assert gate(u,op==0x2a,armed)==expect,(lba,count,op,armed);cases+=1
 for op in range(256):assert gate(command(op,first,1,True),True)==(op in (0x2a,0x35));cases+=1
 for lun in range(256):
  u=command(0x2a,first,1,True);u[2]=lun;assert gate(u,True)==(lun==0);cases+=1
 for pos in list(range(2,12))+list(range(17,18))+list(range(22,23))+list(range(25,32)):
  u=command(0x2a,first,1,True);u[pos]^=1;assert not gate(u,True),pos
 for lba in range(0,6200):
  for write in (False,True):
   u=command(0x2a if write else 0x28,lba,1,write);assert gate(u,write,bcb=True)==(lba==1024);cases+=1
 assert not gate(command(0x2a,first,1,True),True,enabled=False)
 assert not gate(command(0x2a,1024,1,True),True,armed=False,bcb=True)
 lib.bcb.argtypes=[ctypes.c_void_p,ctypes.c_uint];raw=bytes((i*17)&255 for i in range(4096));buf=ctypes.create_string_buffer(raw,4096);assert lib.bcb(buf,4096);out=buf.raw;assert out[864:]==raw[864:];assert out[:32]==b'boot-recovery'+bytes(19);assert out[32:64]==bytes(32);assert out[64:832]==b'recovery\n'+bytes(759);assert out[832:864]==bytes(32)
 lib.hfs.argtypes=[ctypes.c_void_p,ctypes.c_uint]
 with image.open('rb') as f:page=f.read(4096)
 assert lib.hfs(ctypes.create_string_buffer(page),4096)
 for pos in (1024,1027,1064,1066,1069,1128):
  bad=bytearray(page);bad[pos]^=1;assert not lib.hfs(ctypes.create_string_buffer(bytes(bad)),4096)
 lib.transfer_test()
 print(f'PASS: {cases} root/BCB command cases, real HFSX identity and corrupt-header rejection, actual partial-sector RMW/chunk/end/error paths, BCB fields cleared with reserved/A-B bytes preserved.')
