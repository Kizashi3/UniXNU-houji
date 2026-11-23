#!/usr/bin/env python3
from pathlib import Path
import os,ast,json,hashlib,subprocess,shutil
P=Path('${HOUJI_PORT_ROOT}');HERE=Path(__file__).resolve().parent;C=P/'native/gpu/xnu/native-cp-runtime';B=HERE/'build';B.mkdir(exist_ok=True)
old=P/'tests/stock-native-host/run_native_stock_test.py'
scope={'__file__':str(old)};exec(old.read_text().split("(B/'probe.cpp').write_text(source)")[0],scope)
s=scope['source'].split('int main(){unsigned profiles=0;')[0]
s='static bool full_mode;static void full_read_hook();static void full_write_hook();static void full_sleep(unsigned);static void full_save(const char*,unsigned);\n'+s
s=s.replace('backing[9];static IOMemoryMap mappings[9];','backing[10];static IOMemoryMap mappings[10];')
s=s.replace('0x3d50000,0xb284000,0x3d0c000};','0x3d50000,0xb284000,0x3d0c000,0x3d00000};').replace('0x4000,0x4000,0x4000};','0x4000,0x4000,0x4000,0x40000};')
s=s.replace('i<9;i++)if(address>=mock_base[i]','i<10;i++)if(address>=mock_base[i]').replace('i<9;i++)if(base==mock_base[i]','i<10;i++)if(base==mock_base[i]').replace('CHECK(i<9);mapping_order','CHECK(i<10);mapping_order').replace('for(unsigned i=0;i<9;i++){backing[i].assign','for(unsigned i=0;i<10;i++){backing[i].assign')
s=s.replace('static IOMemoryMap secure_maps[9],stock_maps[9]','static IOMemoryMap secure_maps[10],stock_maps[10]')
s=s.replace('stock_mode?(index<2?', '(stock_mode || full_mode)?(index<2?')
s=s.replace('static void houjiStockReadBarrier(){','static void houjiStockReadBarrier(){if(full_mode){full_read_hook();return;}')
s=s.replace('static void houjiStockWriteBarrier(){','static void houjiStockWriteBarrier(){if(full_mode){full_write_hook();return;}')
s=s.replace('static void IOSleep(unsigned ms){','static void IOSleep(unsigned ms){if(full_mode){full_sleep(ms);return;}')
s=s.replace('static void IODelay(unsigned us){','static void IODelay(unsigned us){if(full_mode){CHECK(us==1 || us==10 || us==100);return;}')
s=s.replace('extern "C" void houji_ufs_checkpoint(const char*label,unsigned stop){','extern "C" void houji_ufs_checkpoint(const char*label,unsigned stop){if(full_mode){full_save(label,stop);return;}')
s+=r'''
#define HOUJI_FULL_HOST_NATIVE_HOST_TEST 1
#include "HoujiGpuFullHostProbe.inc"
static unsigned full_requests,full_saves,full_holds,full_reads,full_writes,full_fault;
static bool houjiFullHostAt(uint64_t va,bool wr,uint64_t*out){
 if((va>>48)!=0xffff)for(unsigned i=0;i<10;i++){const uint64_t start=(uintptr_t)backing[i].data();if(va>=start && va-start<mock_size[i]){*out=(mock_base[i]+va-start)&UINT64_C(0x0000fffffffff000);return true;}}
 return houjiGpuExternalAt(va,wr,out);
}
static void houjiFullHostBarrier(){++barriers;}
static void full_read_hook(){++barriers;++full_reads;if(gHoujiFull.last_address==0x3d7e200)++word(0x3d7e200);}
static void full_reply(){
 auto&mem=gHoujiFullMemory;volatile uint32_t*b=(volatile uint32_t*)mem.entry(5).backing.cpu,*cmd=b+6,*ring=b+GGH_RING_OFFSET/4;
 const unsigned rd=cmd[10],head=ring[rd],id=head&255,n=(head>>8)&255;CHECK(n && n<=160);++full_requests;
 const unsigned ids[]={12,4,3,14,10,12,30};CHECK(full_requests<=7 && id==ids[full_requests-1]);cmd[10]=cmd[11];
 volatile uint32_t*h=b+6+12,*to=ring+1024;unsigned w=h[11];const unsigned count=id==12?4:3;
 uint32_t reply[4]={(1u<<20)|(1u<<16)|(count<<8)|id,head,id==12?1u:0u,0};
 
 for(unsigned i=0;i<count;i++)to[(w+i)%1024]=reply[i];h[11]=(w+4)%1024;
}
static void full_write_hook(){
 auto&p=gHoujiFull;++barriers;++full_writes;uint32_t a=p.last_address,v=(uint32_t)p.last_value;
 CHECK(p.held==FHG_ALL && p.zero_held);
 if(a==0x3dc2010 || a==0x3dc0010)word(a)|=0x60;
 if(a==0x3dc2000 || a==0x3dc0000)word(a)&=~0x1000u;
 if(a==0x3d8ec18)word(a)&=0x7f;
 if(a==0x3d7e000 && !v)word(0x3d7e070)=0x100;
 if(a==0x3d7e618 && v)word(0x3d7e600)=1;
 if(a==0x3d7e650 && v==1)full_reply();
 if(a==0x3d7e650 && v==0x40000000){if(full_fault!=2)word(0x3d7e648)|=0x80000000;word(0x3d7e340)=0;word(0x3d8ec40)=0;word(0x3d8ec30)=0;word(0x3d00840)=1;word(0x3d0084c)=0;}
 if(a==0x3d7e644 && v==0x80000000)word(0x3d7e648)&=~0x80000000u;
 if(a==0x3d0047c)word(0x3d00488)=1;
 if(gHoujiCp.active){
  if(a==0x3d00058)word(0x3d0005c)=v&1;
  if(a==0x3d0f114){if(v)word(0x3d0f118)|=v;else word(0x3d0f118)=0;}
  if(a==0x3d0201c){
   CHECK(v==10 || v==15 || v==20);word(0x3d02018)=v;word(0x3d00840)=1;word(0x3d00804)=0;word(0x3d02084)=0;word(0x3d8ec30)=0;
   if(v>10){volatile uint32_t*ring=houjiCpCpu();unsigned offset=v-5;CHECK(ring[offset]==hhr_pkt7(0x3d,3) && ring[offset+1]==HHR_SCRATCH+4*((v-15)/5) && !ring[offset+2] && ring[offset+4]==hhr_pkt7(0x12,0));ring[HHR_WORDS+(v-15)/5]=ring[offset+3]^(full_fault==1?1u:0u);}
  }
 }
 if(full_fault==3 && a==0x3d020c0)word(a)^=4096;
 if(full_fault==4 && a==0x3d0f00c)word(a)^=1;
 if(full_fault==5 && a==0x3da0808)word(a)^=4;
}
static void full_save(const char*,unsigned stop){
 CHECK(!stop);
 if(full_saves==0)CHECK(!gHoujiFull.possible && gHoujiFull.in_save && !full_writes);
 else CHECK(!gHoujiFull.active && gHoujiCp.isolated && gHoujiCp.stop_stage==5 && houjiCpFinalSaveGate());
 ++full_saves;
}
static int houjiCpHostSmc(ggs_regs*r){CHECK(gHoujiCp.active && !r->x[7]);uint64_t fn=r->x[0];r->x[0]=0;if(fn==0x42000601)r->x[1]=1;else CHECK(fn==0x42000c1b);return 0;}
static void full_sleep(unsigned ms){CHECK(ms==8000 && !gHoujiFull.active);++full_holds;}
int main(int argc,char**argv){
 CHECK(argc==2);full_fault=atoi(argv[1]);stock_setup(0,4);stock_mode=false;secure_mode=false;firmware_mode=true;
 full_mode=true;word(0x3dc0004)=3;word(0x3d02020)=0;word(0x3d8ec30)=0;word(0x3d8ec40)=0;
 bool caught=false;try{houjiGpuFullHostProbeOnce();}catch(const StockPanic&){caught=true;}
 auto&p=gHoujiFull;CHECK(caught && full_holds==1);
 for(auto&l:logs)if(l.find("HOUJI NATIVE CP")!=std::string::npos || l.find("HOUJI FULL STOP")!=std::string::npos)fputs(l.c_str(),stdout);
 auto&cp=gHoujiCp;
 CHECK(cp.once && p.summary.cp_attempted && p.summary.pre_cp_boundary && cp.enabled && cp.isolated && cp.stop_stage==5);
 CHECK(cp.save_attempted && cp.save_returned && full_saves==2 && cp.ring.stopped && p.held==FHG_ALL && p.zero_held && p.reset_returned);
 if(!full_fault)CHECK(p.complete && !cp.ring.code && cp.ring.init_idle && cp.ring.writebacks==2 && cp.ring.observed[0]==0xc0ffee00 && cp.ring.observed[1]==0xc0ffee01 && cp.ring.kicks==3);
 else CHECK(!p.complete && cp.ring.code==HHR_WRITEBACK && cp.ring.writebacks==0 && cp.ring.observed[0]==0xc0ffee01);
 CHECK(houjiCpFinalSaveGate());word(0x3d0f118)=1;CHECK(!houjiCpFinalSaveGate());word(0x3d0f118)=3;CHECK(houjiCpFinalSaveGate());
 for(unsigned i=0;i<15;i++)CHECK(gHoujiFullMemory.bo(i).deviceReferences()==1);
 printf("PASS Native CP boundary peer mode%u: code=%u kicks=%u GPU-peer-written=%u save=%u retained=%x; hardware_tested=false\n",full_fault,cp.ring.code,cp.ring.kicks,cp.ring.writebacks,full_saves,p.held);
 full_mode=stock_mode=secure_mode=firmware_mode=false;discardHostAfterReset();
}
'''
(B/'probe.cpp').write_text(s)
X=P/'native/gpu/xnu';V=P/'native/gpu/vendor';U=P/'native/gpu/uefi';BR=X/'hfi-inactive'
shutil.copy2(X/'Adreno740/tests/XnuMemoryFixture.h',B/'XnuMemoryFixture.h')
for name in ['IOKit/IOTypes.h','IOKit/IOBufferMemoryDescriptor.h','IOKit/IOLib.h','kern/task.h','kern/cpu_data.h','vm/vm_map.h','mach/vm_param.h','kern/clock.h','vm/memory_types.h']:
 f=B/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('#include "XnuMemoryFixture.h"\n')
tree=ast.parse((P/'tests/check-houji-gpu-handoff-probe.py').read_text());producer=next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='producer');(B/'producer.c').write_text(producer)
private=Path('${HOUJI_ARTIFACTS}/native-port/native-ios-candidate');shutil.copy2(private/'r149-generated/HoujiGmuFirmwareImage.h',B/'HoujiGmuFirmwareImage.h');shutil.copy2(private/'r154-generated/HoujiCpFirmwareImages.h',B/'HoujiCpFirmwareImages.h')
flags=['-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=address,undefined','-fno-omit-frame-pointer'];inc=['-I',str(B),'-I',str(HERE),'-I',str(C),'-I',str(X/'full-host-graph'),'-I',str(X),'-I',str(X/'Adreno740'),'-I',str(X/'Adreno740/tests'),'-I',str(BR),'-I',str(P/'native/gpu'),'-I',str(P/'tests'),'-I',str(V/'ArmSmmu4K'),'-I',str(U)]
commands=[];outputs=[]
def run(cmd):
 commands.append(cmd);r=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'});print(r.stdout,end='');outputs.append(r.stdout)
 if r.returncode:raise SystemExit(r.returncode)
objs=[]
for src in [C/'houji_full_host_runtime.c',BR/'houji_hfi_inactive.c',BR/'houji_stock_native.c',V/'AdrenoFirmware/AdrenoFirmware.c',*[V/'ArmSmmu4K'/f'{n}.c' for n in ['ArmSmmu4K','ArmSmmu4KAudit','ArmSmmu4KContext','ArmSmmu4KProgram']],B/'producer.c']:
 obj=B/f'{src.stem}.o';run(['clang','-std=c11',*flags,*inc,'-c',str(src),'-o',str(obj)]);objs.append(str(obj))
exe=B/'probe';run(['clang++','-std=c++17',*flags,*inc,'-DPAGE_SIZE=16384',str(B/'probe.cpp'),*objs,'-o',str(exe)])
for mode in range(2):run([str(exe),str(mode)])
(B/'output.txt').write_text(''.join(outputs));(B/'verification.json').write_text(json.dumps({'hardware_tested':False,'scope':'real Native/full FHR/hgf/hhp/hsc/hgx/hcb/h7c; mocked architectural/IOKit/MMIO boundaries','commands':commands,'source_sha256':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [C/'HoujiGpuFullHostProbe.inc',C/'houji_full_host_runtime.c',C/'houji_full_host_runtime.h']}},indent=2)+'\n')
