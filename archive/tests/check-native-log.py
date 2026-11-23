#!/usr/bin/env python3
"""Exercise actual C++ log bounds, FAT ownership, commit ordering and decoder."""
import ctypes,importlib.util,json,struct,subprocess,tempfile,zlib
from pathlib import Path
p=Path(__file__).resolve().parents[1];s=p/'native/ufs-read'
n=Path('${HOUJI_ARTIFACTS}/native-port/native-log-candidate/r25-allocation-final')
spec=importlib.util.spec_from_file_location('capture',p/'scripts/capture-logfs.py');capture=importlib.util.module_from_spec(spec);spec.loader.exec_module(capture)
l=json.loads((n/'layout.json').read_text());raw=(n/'logfs-after-direct.bin').read_bytes();initial=(n/'XnuLog.initial.bin').read_bytes()
with tempfile.TemporaryDirectory() as td:
 d=Path(td);cpp=d/'test.cpp';so=d/'test.so'
 cpp.write_text('#include <stdint.h>\n#include <cstring>\n#include <vector>\n#include <cassert>\n'+''.join('#include "'+str(s/f)+'"\n' for f in ('HoujiGptCheck.h','HoujiLogPolicy.h','HoujiLogFile.h','HoujiLogCommit.h'))+'''
extern "C" int gate(const uint8_t*u,unsigned d,uint32_t b,bool en,bool arm){return houjiUfsLogCommandAllowed(u,32,d,b,en,arm);}
extern "C" const char *fat(const uint8_t*m,unsigned n){return houjiLogFatError(m,n);}
extern "C" int init(const uint8_t*p,unsigned n){return houjiLogInitialValid(p,n);}
extern "C" void header(uint8_t*h,const uint8_t*p,unsigned n){houjiLogHeader(h,p,n);}
extern "C" void transaction(){
 std::vector<uint8_t> image(65536),media(65536);
 for(unsigned i=4096;i<image.size();i++)image[i]=uint8_t(i*17);
 houjiLogHeader(image.data(),image.data()+4096,61440);
 for(int fail=-1;fail<34;fail++){
  std::fill(media.begin(),media.end(),0);unsigned step=0;std::vector<int> events;
  auto write=[&](unsigned i,const uint8_t*b){events.push_back(int(i));if(int(step++)==fail)return false;memcpy(media.data()+i*4096,b,4096);return true;};
  auto flush=[&](){events.push_back(-1);return int(step++)!=fail;};
  auto read=[&](unsigned i,uint8_t*b){events.push_back(100+int(i));if(int(step++)==fail)return false;memcpy(b,media.data()+i*4096,4096);return true;};
  const char *err=houjiCommitLog(image.data(),65536,write,flush,read);
  if(fail<0){assert(!err && image==media && events.size()==34);}else{assert(err && events.size()==unsigned(fail+1));}
  for(unsigned i=0;i<events.size();i++)assert(events[i]==(i<15?int(i+1):i==15?-1:i==16?0:i==17?-1:100+int(i-18)));
 }
 auto write=[](unsigned,const uint8_t*){return true;};auto flush=[](){return true;};
 auto bad=[](unsigned,uint8_t*b){memset(b,0,4096);return true;};
 assert(houjiCommitLog(image.data(),65536,write,flush,bad));
 assert(houjiCommitLog(nullptr,65536,write,flush,bad));
 assert(houjiCommitLog(image.data(),65535,write,flush,bad));
}
''')
 subprocess.run(['c++','-std=c++14','-Wall','-Wextra','-Werror','-Wno-unused-function','-shared','-fPIC',str(cpp),'-o',str(so)],check=True)
 lib=ctypes.CDLL(str(so));lib.gate.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_uint32,ctypes.c_bool,ctypes.c_bool];lib.fat.restype=ctypes.c_char_p;lib.fat.argtypes=[ctypes.c_void_p,ctypes.c_uint];lib.init.argtypes=lib.fat.argtypes;lib.header.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint]
 def gate(op,lba=4170,blocks=1,lun=0,armed=True,en=True,flags=0):
  u=bytearray(32);u[0]=1;u[2]=lun;u[16]=op;u[17]=flags
  if op!=0x35:u[1]=0x20 if op==0x2a else 0x40;struct.pack_into('>I',u,12,blocks*4096);struct.pack_into('>I',u,18,lba);struct.pack_into('>H',u,23,blocks)
  return bool(lib.gate(ctypes.create_string_buffer(bytes(u)),0 if op==0x35 else 1 if op==0x2a else 2,0 if op==0x35 else blocks*4096,en,armed))
 cases=0
 for armed in (False,True):
  for lba in range(0,6200):
   for op in (0x28,0x2a):
    assert gate(op,lba,armed=armed)==((op==0x28 and (4096<=lba<4103 or lba in l['lbas'])) or (op==0x2a and armed and lba in l['lbas']));cases+=1
 for op in range(256):assert gate(op)==(op in (0x28,0x2a,0x35));cases+=1
 for lun in range(256):assert gate(0x2a,lun=lun)==(lun==0);cases+=1
 for count in range(33):assert gate(0x2a,blocks=count)==(count==1);cases+=1
 for flag in range(256):assert gate(0x2a,flags=flag)==(flag==0);cases+=1
 assert not gate(0x2a,en=False) and not gate(0x35,armed=False)
 meta=raw[:7*4096]
 def fat(b):return lib.fat(ctypes.create_string_buffer(bytes(b)),len(b))
 assert fat(meta) is None
 for pos in (11,13,14,16,17,19,21,22,32,510):
  b=bytearray(meta);b[pos]^=1;assert fat(b),pos
 for c in l['clusters']:
  b=bytearray(meta)
  for base in (4096,8192):b[base+c+c//2]^=(0x80 if c==l["clusters"][-1] else 1)
  assert fat(b),c
 for pos in range(3*4096,7*4096,32):
  if meta[pos:pos+11]==b'XNULOG  BIN':own=pos;break
 for offset in (0,11,26,28):
  b=bytearray(meta);b[own+offset]^=1;assert fat(b),offset
 b=bytearray(meta);other=next(i for i in range(3*4096,own,32) if b[i:i+7]==b'UEFILOG');struct.pack_into('<H',b,other+26,l['clusters'][0]);assert fat(b)
 assert lib.init(ctypes.create_string_buffer(initial),len(initial))
 damaged=bytearray(initial);damaged[16]^=1;assert not lib.init(ctypes.create_string_buffer(bytes(damaged)),len(damaged))
 lib.transaction()
 payload=b'HOUJI NATIVE UFS READ PASS\nXNU test snapshot\n';buf=ctypes.create_string_buffer(4096);lib.header(buf,ctypes.create_string_buffer(payload),len(payload));image=buf.raw+payload+bytes(61440-len(payload));report,text=capture.decode_xnu_snapshot(image,l['run_id']);assert report['valid'] and text==payload
 for pos in (8,12,16,32,36,40,44,4096,65535):
  bad=bytearray(image);bad[pos]^=1;assert not capture.decode_xnu_snapshot(bytes(bad),l['run_id'])[0]['valid'],pos
 assert not capture.decode_xnu_snapshot(image,'0'*32)[0]['valid']
 assert not capture.decode_xnu_snapshot(initial,l['run_id'])[0]['valid']
 assert not capture.decode_xnu_snapshot(image[:-1],l['run_id'])[0]['valid']
 print(f'PASS: {cases} C++ command cases; actual FAT allocation/initial bytes accepted; corrupt/crosslinked FAT refused; all 34 transaction failure points stop immediately; header-last ordering and CRC/run-ID/truncation decoder checks pass.')
