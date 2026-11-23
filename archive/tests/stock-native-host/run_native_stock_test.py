#!/usr/bin/env python3
"""Real Native BO/NC+SCM preparation, real HSN/HGF and new Native MMIO adapter.
Only MRS/DC/DSB/AT/IOKit/MMIO device-boundary peers; no real device operations.
"""
from pathlib import Path
import os,hashlib,json,subprocess,shutil
HERE=Path(__file__).resolve().parent;P=HERE.parents[1];AD=P/'native/gpu/xnu';B=HERE/'build';B.mkdir(exist_ok=True)
BR=AD/'hfi-inactive'
source=(P/'tests/stock-native-host/base-secure-peer.cpp').read_text().split('int main(){unsigned cases=0;')[0]
source='static int stock_boot=1;static bool stock_mode;static void host_stock_delay(unsigned);static void host_stock_sleep(unsigned);static void host_stock_checkpoint(const char*,unsigned);\n'+source
source=source.replace('static std::vector<uint32_t> backing[6];static IOMemoryMap mappings[6];',r'''struct AlignedWords {uint32_t*p=nullptr;void assign(size_t n,unsigned v){free(p);void*mem=nullptr;CHECK(!posix_memalign(&mem,16384,((n*4+16383)/16384)*16384));p=(uint32_t*)mem;for(size_t i=0;i<n;i++)p[i]=v;}uint32_t*data(){return p;}uint32_t&operator[](size_t i){return p[i];}};
static AlignedWords backing[9];static IOMemoryMap mappings[9];''')
source=source.replace('0x3d6c000,0x3d8c000};','0x3d6c000,0x3d8c000,0x3d50000,0xb284000,0x3d0c000};').replace('0x40000,0x10000,0x4000};','0x40000,0x10000,0x4000,0x4000,0x4000,0x4000};')
source=source.replace('i<6;i++)if(address>=mock_base[i]','i<9;i++)if(address>=mock_base[i]').replace('i<6;i++)if(base==mock_base[i]','i<9;i++)if(base==mock_base[i]').replace('CHECK(i<6);mapping_order','CHECK(i<9);mapping_order')
source=source.replace('for(unsigned i=0;i<6;i++){backing[i].assign','for(unsigned i=0;i<9;i++){backing[i].assign')
source=source.replace('static IOMemoryMap secure_maps[6];auto&m=secure_mode?secure_maps[index]:mappings[index];','static IOMemoryMap secure_maps[9],stock_maps[9];auto&m=stock_mode?stock_maps[index]:secure_mode?secure_maps[index]:mappings[index];')
source=source.replace('(secure_mode?kIOMapReadOnly:','(stock_mode?(index<2?kIOMapReadOnly:0):secure_mode?kIOMapReadOnly:')
source=source.replace('static bool PE_parse_boot_argn(const char*name,void*out,int bytes){','static bool PE_parse_boot_argn(const char*name,void*out,int bytes){if(!strcmp(name,"houji_gpu_stock_probe")){*(int*)out=stock_boot;return true;}')
source=source.replace('static void IOSleep(unsigned ms){','static void IOSleep(unsigned ms){if(stock_mode){host_stock_sleep(ms);return;}')
source=source.replace('static void IODelay(unsigned us){','static void IODelay(unsigned us){if(stock_mode){host_stock_delay(us);return;}')
source=source.replace('extern "C" void houji_ufs_checkpoint(const char*label,unsigned stop){','extern "C" void houji_ufs_checkpoint(const char*label,unsigned stop){if(stock_mode){host_stock_checkpoint(label,stop);return;}')
source+=r'''
struct StockPanic{};
[[noreturn]]static void panic(const char*,...){throw StockPanic{};}
#include "vendor/Ace5Gmu/giulia_gpu_hfi.h"
#define HOUJI_GPU_STOCK_FIRMWARE_HOST_TEST 1
#include "HoujiGpuStockFirmwareProbe.inc"
static unsigned stock_saves,stock_holds,stock_mode_id,stock_reads,stock_stores,stock_delay,stock_requests;
static unsigned lose_at_store,lose_at_read,cache_after_exec;
static void houjiStockReadBarrier(){
 ++barriers;auto&p=gHoujiGpuStock;if(p.in_observe)return;
 ++stock_reads;if(p.last_address==0x3d7e200 && stock_mode_id!=8)++word(0x3d7e200);
 if(stock_reads==lose_at_read)p.lost=1;
}
static void host_reply(){
 auto&p=gHoujiFirmwareMemory;volatile uint32_t*b=(volatile uint32_t*)p.bo[5].mapping(),*cmd=b+6,*ring=b+GGH_RING_OFFSET/4;
 const unsigned rd=cmd[10],head=ring[rd],id=head&255,n=(head>>8)&255;CHECK(n && n<=160);++stock_requests;
 if(stock_requests==1){CHECK(id==12 && n==3 && ring[(rd+1)%1024]==125 && !ring[(rd+2)%1024]);}
 else {const unsigned ids[]={4,3,14,10,12},counts[]={59,160,2,1,3};CHECK(stock_requests<=6 && id==ids[stock_requests-2] && n==counts[stock_requests-2]);}
 cmd[10]=cmd[11];if(stock_mode_id==3)return;
 volatile uint32_t*h=b+6+12,*to=ring+1024;const unsigned w=h[11];unsigned count=(stock_mode_id==40 && id!=12)?3:4;
 uint32_t reply[11]={(1u<<20)|(1u<<16)|(count<<8)|id,head,id==12?1u:0u,0};
 if(stock_mode_id==4)reply[1]^=1;if(stock_mode_id==5)reply[2]=0;if(stock_mode_id==6)reply[3]=1;if(stock_mode_id==7)reply[0]&=~(1u<<16);
 if(stock_mode_id>=21 && stock_mode_id<=25 && stock_requests==stock_mode_id-19)reply[3]=1;
 if(stock_mode_id==30 && id==10){count=11;reply[0]=(1u<<20)|(11u<<8)|20;reply[4]=0x39;reply[5]=2;reply[7]=1;reply[9]=4096;reply[10]=4096;}
 for(unsigned i=0;i<count;i++)to[(w+i)%1024]=reply[i];h[11]=(w+((count+3u)&~3u))%1024;
}
static void houjiStockWriteBarrier(){
 ++barriers;auto&p=gHoujiGpuStock;CHECK(p.pending_write && p.held_mask==511 && p.zero_held);++stock_stores;
 const uint32_t a=p.last_address,v=(uint32_t)p.last_value;
 CHECK(hsnp_allowed_write(&p.bindings,a,p.last_width*8,p.last_value));
 CHECK(a<0x3d00000 || a>=0x3d40000 || a==0x3d0f114);
 if(a==HGP_CB(0x10))word(a)|=0x60;if(a==HGP_CB(0))word(a)&=~0x1000u;if(a==0x3d8ec18)word(a)&=0x7f;
 if(a==0x3d7e000 && !v){CHECK(p.possible_execution && p.checkpoints==2 && p.publishes==2);if(stock_mode_id!=1)word(0x3d7e070)=0x100;}
 if(a==0x3d7e618 && v && stock_mode_id!=2)word(0x3d7e600)=1;
 if(a==0x3d7e650)host_reply();if(stock_stores==lose_at_store)p.lost=1;
}
static void houjiStockFullBarrier(){++barriers;}
static void host_stock_checkpoint(const char*,unsigned stop){auto&p=gHoujiGpuStock;CHECK(stop==0 && p.in_save && !p.possible_execution && !p.actual_writes && p.checkpoints==1 && !p.lost);++stock_saves;}
static void host_stock_sleep(unsigned ms){CHECK(ms==8000 && !gHoujiGpuStock.active);++stock_holds;}
static void host_stock_delay(unsigned us){CHECK(us==10);++stock_delay;}
static std::vector<unsigned char> saved_secure;
static void stock_setup(unsigned mode=0,unsigned protocol=1){stock_boot=protocol;
 stock_mode=false;setup();CHECK(houjiGpuSecureCxProbeOnce());
 saved_secure.assign((unsigned char*)&gHoujiGpuSecureCx,(unsigned char*)&gHoujiGpuSecureCx+sizeof(gHoujiGpuSecureCx));
 memset((void*)&gHoujiGpuStock,0,sizeof(gHoujiGpuStock));gHoujiGpuStockOnce=0;
 stock_saves=stock_holds=stock_reads=stock_stores=stock_delay=lose_at_store=lose_at_read=cache_after_exec=0;stock_mode_id=mode;stock_requests=0;stock_mode=true;
}
static void attempt(){bool caught=false;try{houjiGpuStockFirmwareProbeOnce();}catch(const StockPanic&){caught=true;}CHECK(caught && stock_holds==1 && !gHoujiGpuStock.active);CHECK(!memcmp(saved_secure.data(),&gHoujiGpuSecureCx,saved_secure.size()));}
int main(){unsigned profiles=0;
 stock_setup();attempt();auto&p=gHoujiGpuStock;
 if(!p.complete){for(auto&l:logs)fputs(l.c_str(),stderr);fprintf(stderr,"native=%u bridge=%u phase=%u addr=%x op=%u\n",p.code,p.bridge_status,p.summary.hgf_phase,p.first_address,p.first_operation);}
 CHECK(p.complete && !p.code && !p.bridge_status && !p.stock_code && p.summary.hgf_phase==10 && p.summary.fw_ready && p.summary.hfi_ready && p.summary.query_ack && p.summary.query_value==1 && !p.summary.query_status);
 CHECK(stock_saves==1 && p.possible_execution && p.reset_attempted && p.reset_returned && p.post_reset_observed && p.post_reset==1 && p.held_mask==511 && p.zero_held);
 CHECK(p.summary.tcm_backup_words==8192 && p.summary.tcm_loaded_words==135 && p.summary.receive_records==1 && !p.summary.receive_overflow);
 for(unsigned i=0;i<9;i++)CHECK(gHoujiFirmwareMemory.bo[i].deviceReferences()==1 && !gHoujiFirmwareMemory.bo[i].quarantined());CHECK(gHoujiGpuExternalCanary.bo[2].deviceReferences()==2);
 const unsigned writes=stock_stores,reads=stock_reads;profiles++;
 for(unsigned mode=1;mode<=8;mode++){stock_setup(mode);attempt();CHECK(!p.complete && p.stock_code && p.held_mask==511 && p.zero_held && stock_saves==1);profiles++;}
 for(unsigned n:{1u,19u,20u,153u,160u,170u,180u}){stock_setup();lose_at_store=n;attempt();CHECK(!p.complete && p.lost && p.held_mask==511 && p.zero_held && stock_saves<=1);profiles++;}
 for(unsigned n:{1u,2u,100u,8192u,8500u,8700u}){stock_setup();lose_at_read=n;attempt();CHECK(!p.complete && p.lost && stock_saves<=1);profiles++;}
 for(unsigned field=0;field<7;field++){stock_setup();if(field==0)gHoujiGpuSecureCx.complete=0;if(field==1)gHoujiFirmwareMemory.complete=0;if(field==2)gHoujiFirmwareMemory.bo[5].holdForDevice();if(field==3)gHoujiGpuExternalCanary.bo[2].holdForDevice();if(field==4)attributes[(ppnum_t)(gHoujiFirmwareMemory.info[5].pa>>14)]=VM_WIMG_DEFAULT;if(field==5)gHoujiFirmwareMemory.info[8].read_par[0]^=1;if(field==6)word(0x171004)=0;
  if(field==0)saved_secure.assign((unsigned char*)&gHoujiGpuSecureCx,(unsigned char*)&gHoujiGpuSecureCx+sizeof(gHoujiGpuSecureCx));attempt();CHECK(!p.complete && !stock_stores && !stock_saves);profiles++;}

 for(unsigned mode:{0u,40u}){stock_setup(mode,2);attempt();if(!p.complete){fprintf(stderr,"HOST mode=%u native=%u bridge=%u stock=%u profile=%u/%u/%u complete=%u req=%u stores=%u base=%u\n",mode,p.code,p.bridge_status,p.stock_code,p.profile.code,p.profile.return_code,p.profile.stage,p.profile.completed,stock_requests,stock_stores,writes);for(auto&line:logs)if(line.find("HOUJI STOCK STOP")!=std::string::npos || line.find("HOUJI HOST")!=std::string::npos)fputs(line.c_str(),stderr);}CHECK(p.complete && p.profile.requested && p.profile.attempted && p.profile.qualified && p.profile.stage==5 && p.profile.completed==5 && !p.profile.code && !p.profile.return_code && !p.profile.resource_count && stock_requests==6 && p.summary.receive_records==6 && !p.summary.receive_overflow && stock_stores==writes+5 && stock_saves==1);profiles++;}
 for(unsigned mode:{21u,22u,23u,24u,25u,30u}){stock_setup(mode,2);attempt();CHECK(!p.complete && !p.profile.qualified && p.stock_code && stock_saves==1 && p.held_mask==511 && p.zero_held);profiles++;}
 printf("PASS: %u real Native/HSN/HGF stock profiles; baseline %u writes/%u reads, real host-profile5ACK/legacy/badACK/resource refusal, one pre-exec save, post-exec noFS and retained refs; device boundaries mocked, no hardware execution\n",profiles,writes,reads);
 stock_mode=secure_mode=false;discardHostAfterReset();
}
'''
(B/'probe.cpp').write_text(source)
(B/'XnuMemoryFixture.h').write_text((P/'native/gpu/xnu/Adreno740/tests/XnuMemoryFixture.h').read_text())
for name in ['IOKit/IOTypes.h','IOKit/IOBufferMemoryDescriptor.h','IOKit/IOLib.h','kern/task.h','kern/cpu_data.h','vm/vm_map.h','mach/vm_param.h','kern/clock.h','vm/memory_types.h']:
 dest=B/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text('#include "XnuMemoryFixture.h"\n')
import ast
tree=ast.parse((P/'tests/check-houji-gpu-handoff-probe.py').read_text());producer=next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='producer');(B/'producer.c').write_text(producer)
flags=['-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=address,undefined','-fno-omit-frame-pointer'];commands=[]
def run(cmd):
 commands.append(cmd);r=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'});print(r.stdout,end='');return r
X=P/'native/gpu/xnu';V=P/'native/gpu/vendor';U=P/'native/gpu/uefi'
objects=[]
for src in [*[V/'ArmSmmu4K'/(n+'.c') for n in ['ArmSmmu4K','ArmSmmu4KAudit','ArmSmmu4KContext','ArmSmmu4KProgram']],V/'AdrenoFirmware/AdrenoFirmware.c',BR/'houji_hfi_inactive.c',BR/'houji_stock_native.c',B/'producer.c']:
 obj=B/(src.stem+'.o');r=run(['clang','-std=c11',*flags,'-I',str(P/'native/gpu'),'-I',str(U),'-I',str(BR),'-I',str(P/'tests'),'-c',str(src),'-o',str(obj)]);assert not r.returncode;objects.append(str(obj))
assert (AD/'HoujiStockMmioPolicy.h').is_file()
private_header=Path(os.environ.get('HOUJI_GMU_FIRMWARE_HEADER','${HOUJI_ARTIFACTS}/native-port/native-ios-candidate/r149-generated/HoujiGmuFirmwareImage.h'));shutil.copy2(private_header,B/'HoujiGmuFirmwareImage.h')
exe=B/'probe';r=run(['clang++','-std=c++17',*flags,'-DPAGE_SIZE=16384','-I',str(B),'-I',str(AD),'-I',str(BR),'-I',str(X/'Adreno740/tests'),'-I',str(X/'Adreno740'),'-I',str(X),'-I',str(X/'hfi-inactive'),'-I',str(P/'native/gpu'),'-I',str(V/'ArmSmmu4K'),'-I',str(U),str(B/'probe.cpp'),*objects,'-o',str(exe)]);(B/'compile-output.txt').write_text(r.stdout)
if r.returncode:raise SystemExit(r.returncode)
r=run([str(exe)]);(B/'test-output.txt').write_text(r.stdout)
(B/'verification.json').write_text(json.dumps({'exit_code':r.returncode,'commands':commands,'adapter_sha256':hashlib.sha256((AD/'HoujiGpuStockFirmwareProbe.inc').read_bytes()).hexdigest(),'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'HSN_sha256':hashlib.sha256((BR/'houji_stock_native.c').read_bytes()).hexdigest(),'policy_sha256':hashlib.sha256((AD/'HoujiStockMmioPolicy.h').read_bytes()).hexdigest(),'scope':'real Native Memory/Cpu + actual GEC-NC/SCM prep + real HSN/untouched HGF; architectural/device boundaries only mocked, no hardware'},indent=2)+'\n')
raise SystemExit(r.returncode)
