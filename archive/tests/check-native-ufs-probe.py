#!/usr/bin/env python3
"""Test actual native read policy/GPT checker and SMMU plan on real r23 state."""
import argparse,ctypes,re,struct,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=Path,required=True);p.add_argument('--artifacts',type=Path,required=True);a=p.parse_args();s=a.port/'native/ufs-read'
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);c=root/'probe.cpp';so=root/'probe.so'
 c.write_text('#include <stdint.h>\n#include "'+str(s/'HoujiReadPolicy.h')+'"\n#include "'+str(s/'HoujiGptCheck.h')+'"\n'+'''extern "C" int allowed(const uint8_t *u,unsigned n,unsigned d,uint32_t b){return houjiUfsReadCommandAllowed(u,n,d,b);}
extern "C" const char *gpt(const uint8_t *h,unsigned hn,const uint8_t *e,unsigned en){return houjiGptError(h,hn,e,en);}
''')
 subprocess.run(['c++','-std=c++14','-Wall','-Wextra','-Werror','-shared','-fPIC',str(c),'-o',str(so)],check=True)
 lib=ctypes.CDLL(str(so));lib.allowed.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint,ctypes.c_uint];lib.gpt.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint];lib.gpt.restype=ctypes.c_char_p
 def allowed(u,d=2,b=4096):return bool(lib.allowed(ctypes.create_string_buffer(bytes(u)),len(u),d,b))
 u=bytearray(32);u[0]=1;u[1]=0x40;u[16]=0x28;struct.pack_into('>I',u,12,4096);struct.pack_into('>I',u,18,1);struct.pack_into('>H',u,23,1)
 assert allowed(u)
 cases=0
 for op in range(256):
  v=bytearray(u);v[16]=op;assert allowed(v)==(op==0x28);cases+=1
 for lun in range(256):
  v=bytearray(u);v[2]=lun;assert allowed(v)==(lun==0);cases+=1
 for lba in range(8):
  for blocks in range(33):
   v=bytearray(u);struct.pack_into('>I',v,12,blocks*4096);struct.pack_into('>I',v,18,lba);struct.pack_into('>H',v,23,blocks)
   assert allowed(v,b=blocks*4096)==((lba,blocks) in ((1,1),(2,2)));cases+=1
 for d in range(4):assert allowed(u,d=d)==(d==2)
 for field in (3,8,10,11,17,22,25,26,31):
  v=bytearray(u);v[field]=1;assert not allowed(v)
 assert not lib.allowed(None,32,2,4096)
 for n in (0,16,31):assert not lib.allowed(ctypes.create_string_buffer(bytes(u)),n,2,4096)
 tur=bytearray(32);tur[0]=1;assert allowed(tur,0,0)
 active=bytearray(tur);active[2]=0xd0;active[16]=0x1b
 for power in range(256):active[20]=power;assert allowed(active,0,0)==(power==0x10);cases+=1
 q=bytearray(32);q[0]=0x16;q[3]=1;q[5]=1;q[13]=2
 for op in range(256):q[12]=op;assert allowed(q,0,0)==(op==3);cases+=1
 nop=bytearray(32);nop[3]=1;assert allowed(nop,0,0)
 for v in (u,tur,active,q,nop):assert not allowed(v,1,0)
 data=(a.artifacts/'partition-backup-20261024/sda-primary.bin').read_bytes();h=data[4096:8192];e=data[8192:16384]
 def gpt(h,e):return lib.gpt(ctypes.create_string_buffer(bytes(h)),len(h),ctypes.create_string_buffer(bytes(e)),len(e))
 assert gpt(h,e) is None
 for i in range(92):v=bytearray(h);v[i]^=1;assert gpt(v,e),i
 for i in range(0,8192,127):v=bytearray(e);v[i]^=1;assert gpt(h,v),i
 assert gpt(h[:-1],e) and gpt(h,e[:-1])
 print('PASS:',cases,'native policy cases; pinned actual GPT accepted, altered headers/entries and wrong sizes refused.')
 log=(a.artifacts/'evidence/logfs-adb-capture-r23/UniXNU.log').read_text();pairs={int(at,16)-0x15000000:int(value,16) for at,value in re.findall(r'\[([0-9A-F]{8})\]=([0-9A-F]{8})',log) if 0x15000000<=int(at,16)<0x150d0000}
 entries=','.join('{'+str(k)+','+str(v)+'U}' for k,v in sorted(pairs.items()))
 c=root/'smmu.cpp';exe=root/'smmu'
 c.write_text('#include <stdint.h>\n#include <map>\n#include <vector>\n#include <utility>\n#include <cassert>\n#include <cstring>\n#include <cstdio>\n#include "'+str(s/'GiuliaSmmuTakeover.h')+'"\n'+'''int main(){
 std::map<unsigned,uint32_t> original={'''+entries+'''};
 auto m=original;std::vector<std::pair<unsigned,uint32_t>> writes;
 auto read=[&](unsigned at){assert(m.count(at));return m.at(at);};
 auto write=[&](unsigned at,uint32_t value){writes.push_back({at,value});m[at]=value;};
 auto plan=planGiuliaSmmu(0x60,0xc4000000ULL,139264,read);
 assert(!plan.target.error && plan.retarget && plan.target.slot==0 && plan.target.bank==70 && plan.target.pages==128 && plan.oldS2cr==0);
 assert(configureGiuliaSmmu(plan,0x60,false,read,write));assert(writes.empty());
 assert(!configureGiuliaSmmu(plan,0x60,true,read,write));
 std::map<unsigned,uint32_t> expected={{0xc6000,0},{0x1918,1},{0x1118,0x10000},{0xc00,70},{0x800,0x80000060U}};
 assert(writes.size()==expected.size());
 for(auto w:writes)assert(expected.count(w.first)&&expected.at(w.first)==w.second);
 for(auto p:original)if(!expected.count(p.first))assert(m.at(p.first)==p.second);
 m=original;writes.clear();m[0x800]^=1;assert(configureGiuliaSmmu(plan,0x60,true,read,write));assert(writes.empty());
 m=original;m[0x80c]=0x80010060U;assert(planGiuliaSmmu(0x60,0xc4000000ULL,139264,read).target.error);
 m=original;m[0x828]=0x80000040U;m[0xc28]=70;auto lower=planGiuliaSmmu(0x60,0xc4000000ULL,139264,read);assert(!lower.target.error&&lower.target.bank==69);
 m=original;assert(planGiuliaSmmu(0x60,1ULL<<40,139264,read).target.error);
 puts("PASS: real r23 107-group/71-bank snapshot selects exclusive bank70, preserves old bank0/display mapping, refuses live queue/changed stream/ambiguous mask/width, and uses bank69 when 70 occupied. Hardware writes untested.");
}''')
 subprocess.run(['c++','-std=c++14','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
