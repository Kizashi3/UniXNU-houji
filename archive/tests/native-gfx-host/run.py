#!/usr/bin/env python3
from pathlib import Path
import os,ast,json,hashlib,subprocess,shutil
P=Path('${HOUJI_PORT_ROOT}');HERE=Path(__file__).resolve().parent;C=P/'native/gpu/xnu/native-gfx-runtime';B=HERE/'build';B.mkdir(exist_ok=True)
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
alignas(16384) static uint8_t low_meta[16384],low_target[16384];static bool low_at(uint64_t,bool,uint64_t*);

#define HOUJI_FULL_HOST_NATIVE_HOST_TEST 1
#include "HoujiGpuFullHostProbe.inc"
static unsigned full_requests,full_saves,full_holds,full_reads,full_writes,full_fault;
static bool houjiFullHostAt(uint64_t va,bool wr,uint64_t*out){
 if(low_at(va,wr,out))return true;
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
 if(a==0x3d7e650 && v==0x40000000){word(0x3d7e648)|=0x80000000;word(0x3d7e340)=0;word(0x3d8ec40)=0;word(0x3d8ec30)=0;word(0x3d00840)=1;word(0x3d0084c)=0;}
 if(a==0x3d7e644 && v==0x80000000)word(0x3d7e648)&=~0x80000000u;
 if(a==0x3d0047c)word(0x3d00488)=1;
 if(gHoujiCp.active){
  if(a==0x3d00058)word(0x3d0005c)=v&1;
  if(a==0x3d0f114){if(v)word(0x3d0f118)|=v;else word(0x3d0f118)=0;}
  if(a==0x3d0201c){
   CHECK(v==10 || v==12 || v==37 || v==41 || v==46 || v==51);word(0x3d02018)=v;word(0x3d00840)=1;word(0x3d00804)=0;word(0x3d02084)=0;word(0x3d8ec30)=0;
   if(v>=46){volatile uint32_t*ring=houjiCpCpu();unsigned offset=v-5;CHECK(ring[offset]==hhr_pkt7(0x3d,3) && ring[offset+1]==HHR_SCRATCH+4*((v-46)/5) && !ring[offset+2] && ring[offset+4]==hhr_pkt7(0x12,0));ring[HHR_WORDS+(v-46)/5]=ring[offset+3];}
   if(v==41){volatile uint8_t*arena=(volatile uint8_t*)((uintptr_t)gHoujiFullMemory.entry(12).backing.cpu+HGKI_CLASS_CURSOR);for(unsigned i=0;i<8;i++)hzr_w32((void*)(arena+4*i),hgki_marker_value(i));for(unsigned i=0;i<4096;i++)arena[5*4096+i]=(i%4==0 || i%4==3)?255:0;if(full_fault==1)arena[5*4096]^=1;}

  }
 }
 if(full_fault==3 && a==0x3d020c0)word(a)^=4096;
 if(full_fault==4 && a==0x3d0f00c)word(a)^=1;
 if(full_fault==5 && a==0x3da0808)word(a)^=4;
}
static void full_save(const char*,unsigned stop){
 CHECK(!stop);
 if(full_saves==0)CHECK(!gHoujiFull.possible && (gHoujiFull.in_save || (gHoujiFull.code==20 && !gHoujiCp.once && !gHoujiGfx.target_started)) && !full_writes);
 else CHECK(!gHoujiFull.active && gHoujiCp.isolated && gHoujiCp.stop_stage==5 && houjiCpFinalSaveGate());
 ++full_saves;
}
static int houjiCpHostSmc(ggs_regs*r){CHECK(gHoujiCp.active && !r->x[7]);uint64_t fn=r->x[0];r->x[0]=0;if(fn==0x42000601)r->x[1]=1;else CHECK(fn==0x42000c1b);return 0;}
static void full_sleep(unsigned ms){CHECK(ms==8000 && !gHoujiFull.active);++full_holds;}

static bool low_at(uint64_t va,bool,uint64_t*out){for(unsigned i=0;i<2;i++){uint64_t start=(uintptr_t)(i?low_target:low_meta);if(va>=start && va-start<16384){CHECK(!i || !gHoujiGfx.target_closed);*out=UINT64_C(0x4400000000000800)|((i?HZR_TARGET_PAGE:UINT64_C(0xd1ce4000))+((va-start)&~UINT64_C(4095)));return true;}}return false;}
static void*houjiGfxHostMap(uint64_t pa,unsigned which){CHECK(pa==(which?HZR_TARGET_PAGE:UINT64_C(0xd1ce4000)));return which?low_target:low_meta;}
static const HzrRecord*houjiGfxHostRecord(){
 static HzrRecord r;memset(&r,0,sizeof r);hzr_set64(&r,HZR_MAGIC_O,HZR_MAGIC);hzr_set32(&r,HZR_VERSION_O,1);hzr_set32(&r,HZR_LENGTH_O,512);memcpy(r.bytes+16,kHoujiZapTrial,16);hzr_set32(&r,HZR_FLAGS_O,31);
 const uint64_t meta=0xd1ce4000,raw=0xd1ce1000;
 const unsigned off[]={HZR_METADATA_PA_O,HZR_OWNED_O,HZR_LOGICAL_O,HZR_TARGET_PAGE_O,HZR_TARGET_BYTES_O,HZR_GPU_BASE_O,HZR_GPU_BYTES_O,HZR_COPY_BASE_O,HZR_COPY_BYTES_O,HZR_RAW_BASE_O,HZR_RAW_BYTES_O,HZR_META_GCD_BASE_O,HZR_META_GCD_BYTES_O,HZR_META_ATTR_O,HZR_META_CAP_O,HZR_META_ORIGINAL_O,HZR_TARGET_GCD_BASE_O,HZR_TARGET_GCD_BYTES_O,HZR_TARGET_ATTR_O,HZR_TARGET_CAP_O,HZR_MAP_KEY_O,HZR_MAP_BYTES_O,HZR_MAP_STRIDE_O};
 const uint64_t value[]={meta,16384,4096,HZR_TARGET_PAGE,16384,HZR_TARGET_GPU,8192,HZR_TARGET_GPU,1072,raw,7*4096,0xd1c00000,0x200000,2,UINT64_C(0x800000000002700f),8,HZR_PIL_BASE,HZR_PIL_BYTES,0,UINT64_C(0x8000000000026001),19,80,40};
 for(unsigned i=0;i<sizeof(off)/sizeof(*off);i++)hzr_set64(&r,off[i],value[i]);
 hzr_set32(&r,HZR_META_EFI_O,2);hzr_set32(&r,HZR_TARGET_EFI_O,0);hzr_set32(&r,HZR_META_GCD_O,2);hzr_set32(&r,HZR_TARGET_GCD_O,1);hzr_set32(&r,HZR_MAP_VERSION_O,1);hzr_set32(&r,HZR_META_COVERAGE_O,15);hzr_set32(&r,HZR_TARGET_COVERAGE_O,15);hzr_set32(&r,HZR_TARGET_RECORDS_O,1);
 for(unsigned i=0;i<4;i++){uint64_t mp=UINT64_C(0x4400000000000800)|(meta+i*4096),tp=UINT64_C(0x4400000000000800)|(HZR_TARGET_PAGE+i*4096);hzr_set64(&r,HZR_META_RPAR_O+8*i,mp);hzr_set64(&r,HZR_META_WPAR_O+8*i,mp);hzr_set64(&r,HZR_TARGET_RPAR_O+8*i,tp);hzr_set64(&r,HZR_TARGET_WPAR_O+8*i,tp);}
 hzr_finish(&r);CHECK(hzr_valid(&r,sizeof r,kHoujiZapTrial));if(full_fault==2)r.bytes[16]^=1;return &r;
}
static int houjiGfxHostSmc(ggs_regs*r){uint64_t fn=r->x[0];CHECK(fn==0x42000601 || fn==0x42000207 || fn==0x42000201 || fn==0x42000202 || fn==0x42000205);r->x[0]=0;r->x[1]=(fn==0x42000601 || fn==0x42000207)?1:0;return 0;}
int main(int argc,char**argv){
 CHECK(argc==2);full_fault=atoi(argv[1]);stock_setup(0,5);stock_mode=false;secure_mode=false;firmware_mode=true;memset(low_meta,0,sizeof low_meta);memset(low_target,0xa5,sizeof low_target);
 full_mode=true;word(0x3dc0004)=3;word(0x3d02020)=0;word(0x3d8ec30)=0;word(0x3d8ec40)=0;
 bool caught=false;try{houjiGpuFullHostProbeOnce();}catch(const StockPanic&){caught=true;}
 auto&p=gHoujiFull;auto&cp=gHoujiCp;auto&g=gHoujiGfx;CHECK(caught && full_holds==1);
 for(auto&l:logs)if(l.find("HOUJI NATIVE GFX")!=std::string::npos || l.find("HOUJI NATIVE CP RESULT")!=std::string::npos)fputs(l.c_str(),stdout);
 if(full_fault==2){CHECK(!g.imported && !cp.once && !cp.enabled && !full_writes && full_saves==1 && p.code==20);}
 else {
 CHECK(cp.once && p.summary.cp_attempted && p.summary.pre_cp_boundary && cp.enabled && cp.isolated && cp.stop_stage==5 && cp.save_attempted && cp.save_returned && full_saves==2);
 CHECK(g.zap.authenticated && g.mode_idle && g.context_idle && g.image_idle && g.target_complete && g.target_closed && cp.ring.stopped);
 if(!full_fault)CHECK(p.complete && g.complete && g.image.verified && g.image.output_crc==0xe843b26a && cp.ring.kicks==6 && cp.ring.writebacks==2 && cp.ring.wptr==51);
 else CHECK(!p.complete && !g.complete && g.code==HGKI_COLOR && cp.ring.code==HHR_POST_INIT && !cp.ring.writebacks);
 for(unsigned i=0;i<16384;i++)CHECK(low_target[i]==(i>=0x2000 && i<0x2000+HZL_SEGMENT_BYTES?mHoujiZapSegment[i-0x2000]:0xa5));
 CHECK(!houjiGfxTranslations(1));CHECK(houjiCpFinalSaveGate());word(0x3d0f118)=1;CHECK(!houjiCpFinalSaveGate());word(0x3d0f118)=3;
 for(unsigned i=0;i<15;i++)CHECK(gHoujiFullMemory.bo(i).deviceReferences()==1);
 }
 printf("PASS Native GFX boundary peer mode%u: code=%u complete=%u GPU-peer-CRC=%08x finalsave=%u; hardware_tested=false\n",full_fault,g.code,g.complete,g.image.output_crc,full_saves);
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
for mode in range(3):run([str(exe),str(mode)])
(B/'output.txt').write_text(''.join(outputs));(B/'verification.json').write_text(json.dumps({'hardware_tested':False,'scope':'real Native/full FHR/hgf/hhp/hsc/hgx/hcb/h7c; mocked architectural/IOKit/MMIO boundaries','commands':commands,'source_sha256':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [C/'HoujiGpuFullHostProbe.inc',C/'houji_full_host_runtime.c',C/'houji_full_host_runtime.h']}},indent=2)+'\n')
