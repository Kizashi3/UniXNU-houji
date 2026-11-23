#!/usr/bin/env python3
"""Offline actual GEC-NC + inactive Native FW preparation + fixed SCM helper."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess
HERE=Path(__file__).resolve().parent;P=HERE.parents[1];B=HERE/'build';S=B/'snapshot';B.mkdir(exist_ok=True)
if S.exists():shutil.rmtree(S)
for sub in ['native/gpu/xnu','native/gpu/vendor','native/gpu/uefi']:shutil.copytree(P/sub,S/sub)
A=S/'native/gpu/xnu/Adreno740';X=S/'native/gpu/xnu';V=S/'native/gpu/vendor';U=S/'native/gpu/uefi'
base=(HERE/'base-native-peer.cpp').read_text().split('int main(){unsigned cases=0;')[0]
assert (A/'NativeAdrenoMemory.cpp').read_text() in base
cpu=(A/'NativeAdrenoCpu.cpp').read_text()
for field,reg in [('tcr','tcr_el1'),('ttbr0','ttbr0_el1'),('ttbr1','ttbr1_el1'),('sctlr','sctlr_el1')]:
 cpu=cpu.replace(f'__asm__ volatile("mrs %0, {reg}" : "=r"(out->{field}));',f'out->{field}=cpu_{field};')
cpu=cpu.replace('__asm__ volatile("mrs %0, ctr_el0":"=r"(ctr));','ctr=cpu_ctr;')
for name,op in [('cvac',0),('civac',1),('ivac',2)]:cpu=cpu.replace(f'__asm__ volatile("dc {name}, %0"::"r"(address):"memory");',f'cache_line(address,{op});')
cpu=cpu.replace('__asm__ volatile("dsb sy":::"memory");','++barriers;')
assert '__asm__' not in cpu and cpu in base
base='static bool secure_mode,firmware_mode;static int scm_boot=1;static void host_secure_checkpoint(const char*,unsigned);\n'+base
base=base.replace('auto&m=mappings[index];','static IOMemoryMap secure_maps[6];auto&m=secure_mode?secure_maps[index]:mappings[index];')
base=base.replace('CHECK(options==(unsigned)(kIOMapAnywhere|kIOMapInhibitCache|((index==2 || index==3 || index==4 || index==5)?0:kIOMapReadOnly)));','CHECK(options==(unsigned)(kIOMapAnywhere|kIOMapInhibitCache|(secure_mode?kIOMapReadOnly:((index==2 || index==3 || index==4 || index==5)?0:kIOMapReadOnly))));')
base=base.replace('static bool PE_parse_boot_argn(const char*name,void*out,int bytes){', 'static bool PE_parse_boot_argn(const char*name,void*out,int bytes){if(!strcmp(name,"houji_gpu_scm_probe")){*(int*)out=scm_boot;return true;}if(!strcmp(name,"houji_gpu_fw_mem_probe")){*(int*)out=1;return true;}')
base=base.replace('auto&p=gHoujiGpuExternalCanary;CHECK(attr==VM_WIMG_WCOMB', 'if(firmware_mode){CHECK(attr==VM_WIMG_WCOMB);return;}auto&p=gHoujiGpuExternalCanary;CHECK(attr==VM_WIMG_WCOMB')
base=base.replace('static void IOSleep(unsigned ms){','static void IOSleep(unsigned ms){if(secure_mode){CHECK(ms==30);return;}')
base=base.replace('extern "C" void houji_ufs_checkpoint(const char*label,unsigned stop){','extern "C" void houji_ufs_checkpoint(const char*label,unsigned stop){if(secure_mode){host_secure_checkpoint(label,stop);return;}')
# Existing baseline compiles exact Native Memory/Cpu with its established host
# MRS/DC/DSB/AT/IOKit boundary replacements; no production control flow replaced.
source=base+'\n'+(A/'NativeAdrenoSha256.cpp').read_text()+'\n'+(A/'NativeAdrenoFirmware.cpp').read_text()+r'''
#define HOUJI_GPU_FIRMWARE_MEMORY_HOST_TEST 1
#include "HoujiGpuFirmwareMemoryProbe.inc"
static bool houjiFirmwareAt(uint64_t va,bool wr,uint64_t*par){return houjiGpuExternalAt(va,wr,par);}
static void houjiFirmwareBarrier(){++barriers;}
#define HOUJI_GPU_SECURE_CX_HOST_TEST 1
#include "HoujiGpuSecureCxProbe.inc"
static unsigned smc_calls,checkpoint_secure,fail_transport,mutate_smc,mutate_save,damage_owner,fail_secure_at;
static unsigned fail_secure_read,secure_reads,secure_at_calls,secure_saves,final_saves,profile,fail_observation_kind,test_address;
static std::vector<ggs_regs> host_frames;
static std::vector<unsigned char> immutable_gec,immutable_fw;
static bool houjiSecureCxAt(uint64_t va,bool wr,uint64_t*par){
 if(++secure_at_calls==fail_secure_at){*par=1;return true;}return houjiGpuExternalAt(va,wr,par);
}
static void houjiSecureCxReadBarrier(){++barriers;if(++secure_reads==fail_secure_read || (fail_observation_kind && gHoujiGpuSecureCx.observations[gHoujiGpuSecureCx.current_observation].kind==fail_observation_kind))gRootEnabled=false;}
static void host_secure_checkpoint(const char*label,unsigned stop){
 auto&p=gHoujiGpuSecureCx;CHECK(stop==0 && p.in_save && !p.in_observe && !p.lost && !p.scm.quarantined);
 CHECK(!memcmp(immutable_gec.data(),&gHoujiGpuExternalCanary,sizeof(gHoujiGpuExternalCanary)));
 CHECK(!memcmp(immutable_fw.data(),&gHoujiFirmwareMemory,sizeof(gHoujiFirmwareMemory)));
 if(smc_calls){unsigned raw=0,proof=0;for(auto&line:logs){if(line.find("POST_COLD_PENDING")!=std::string::npos)++raw;if(line.find("POST_COLD_PROVEN")!=std::string::npos)++proof;}CHECK(raw>=smc_calls && proof>=smc_calls);}
 ++secure_saves;++checkpoint_secure;if(strstr(label,"INIT returned"))++final_saves;
 if(checkpoint_secure==mutate_save)word(0x171004)=0;
}
static int houjiSecureCxSmc(ggs_regs*r){
 auto&p=gHoujiGpuSecureCx;CHECK(p.active && p.calls[p.call_count-1].ready && !p.lost);
 const auto&o=p.observations[p.calls[p.call_count-1].ready-1];CHECK(o.returned && !o.code && !o.recheck && o.gates==255 && o.lease_before && o.lease_after);
 CHECK(stores.size()==179 && !gHoujiGpuExternalCanary.active && !gHoujiFirmwareMemory.active);
 host_frames.push_back(*r);++smc_calls;
 for(unsigned i=0;i<8;i++)r->x[i]=UINT64_C(0xabcd123400000000)+i;
 r->x[0]=0;r->x[1]=1;
 if(profile==1 && smc_calls==1){r->x[0]=1;r->x[6]=UINT64_C(0xfeedbeef12345678);}
 if(profile==2 && smc_calls==1)r->x[0]=(uint64_t)(int64_t)-12;
 if(profile==3)r->x[0]=1;
 if(profile==4)r->x[0]=(uint64_t)(int64_t)-12;
 if(profile==5)r->x[0]=2;
 if(profile==6)r->x[0]=3;
 if(profile==7)r->x[0]=UINT64_C(0x100000000);
 if(profile==8 && smc_calls==1)r->x[1]=UINT64_C(0x100000001);
 if(profile==9 && smc_calls==2)r->x[1]=0;
 if(profile==10 && smc_calls==3)r->x[0]=UINT64_C(0xffffffffffffffff);
 if(profile==11 && smc_calls==1)r->x[0]=UINT64_C(0xfffffff4);
 if(smc_calls==mutate_smc)word(HGP_CB(0x20))=4096;
 if(smc_calls==damage_owner)gReturnRecovery=false;
 return smc_calls==fail_transport?1:0;
}
static void setup(){
 secure_mode=firmware_mode=false;fixture_record((unsigned char*)&original);reset();memset((void*)&gHoujiFirmwareMemory,0,sizeof(gHoujiFirmwareMemory));gHoujiFirmwareMemoryOnce=0;
 memset((void*)&gHoujiGpuSecureCx,0,sizeof(gHoujiGpuSecureCx));gHoujiGpuSecureCxOnce=0;
 CHECK(contract());firmware_mode=true;CHECK(houjiGpuFirmwareMemoryProbeOnce());firmware_mode=false;
 secure_mode=true;scm_boot=1;smc_calls=checkpoint_secure=fail_transport=mutate_smc=mutate_save=damage_owner=fail_secure_at=fail_secure_read=secure_reads=secure_at_calls=secure_saves=final_saves=profile=fail_observation_kind=test_address=0;host_frames.clear();
 immutable_gec.assign((unsigned char*)&gHoujiGpuExternalCanary,(unsigned char*)&gHoujiGpuExternalCanary+sizeof(gHoujiGpuExternalCanary));
 immutable_fw.assign((unsigned char*)&gHoujiFirmwareMemory,(unsigned char*)&gHoujiFirmwareMemory+sizeof(gHoujiFirmwareMemory));
}
static void unchanged(){CHECK(!memcmp(immutable_gec.data(),&gHoujiGpuExternalCanary,sizeof(gHoujiGpuExternalCanary)));CHECK(!memcmp(immutable_fw.data(),&gHoujiFirmwareMemory,sizeof(gHoujiFirmwareMemory)));CHECK(stores.size()==179 && fixture.live.size()==12 && !fixture.released);}
static void bad(){bool safe=houjiGpuSecureCxProbeOnce();if(safe || gHoujiGpuSecureCx.complete || final_saves)fprintf(stderr,"Unexpected safe: profile=%u address=%x smcs=%u saves=%u final=%u\n",profile,test_address,smc_calls,secure_saves,final_saves);CHECK(!safe && !gHoujiGpuSecureCx.complete && !final_saves);unchanged();unsigned count=smc_calls,saves=secure_saves;CHECK(!houjiGpuSecureCxProbeOnce() && smc_calls==count && secure_saves==saves);}
int main(){unsigned cases=0;
 setup();CHECK(houjiGpuSecureCxProbeOnce());auto&p=gHoujiGpuSecureCx;CHECK(p.complete && !p.active && !p.lost && !p.scm.quarantined && p.scm.init_succeeded && smc_calls==3 && secure_saves==4 && final_saves==1 && p.actual_calls==p.returned_calls && p.report_saved && p.report_returned);
 CHECK(host_frames[0].x[0]==0xc2000601 && host_frames[0].x[2]==0x02000601 && host_frames[1].x[0]==0x42000601 && host_frames[1].x[2]==0x02002801 && host_frames[2].x[0]==0x42002801 && host_frames[2].x[2]==11);
 for(auto&r:host_frames)CHECK(r.x[1]==1 && !r.x[3] && !r.x[4] && !r.x[5] && !r.x[6] && !r.x[7]);
 CHECK(p.calls[2].output.x[7]==UINT64_C(0xabcd123400000007));unchanged();const unsigned observations=p.observation_count,ats=secure_at_calls,reads=secure_reads;CHECK(houjiGpuSecureCxProbeOnce() && smc_calls==3 && p.observation_count==observations);++cases;
 for(int arg:{0,2,-1}){setup();scm_boot=arg;if(!arg)CHECK(houjiGpuSecureCxProbeOnce());else CHECK(!houjiGpuSecureCxProbeOnce());CHECK(!smc_calls && !secure_saves);unchanged();++cases;}
 for(unsigned mode=1;mode<=11;mode++){setup();profile=mode;if(mode==1 || mode==2 || mode==11){CHECK(houjiGpuSecureCxProbeOnce() && p.complete && smc_calls==4);if(mode==1)CHECK(host_frames[1].x[0]==1 && host_frames[1].x[6]==UINT64_C(0xfeedbeef12345678));else CHECK(host_frames[1].x[0]==0xc2000601 && !host_frames[1].x[6]);unchanged();}else bad();++cases;}
 for(unsigned i=1;i<=3;i++){setup();fail_transport=i;bad();CHECK(p.scm.quarantined && smc_calls==i);++cases;setup();mutate_smc=i;bad();CHECK(smc_calls==i && p.lost && p.calls[i-1].post && !p.calls[i-1].post_ok);++cases;setup();damage_owner=i;CHECK(!houjiGpuSecureCxProbeOnce() && !p.complete && smc_calls==i && !final_saves);++cases;}
 for(unsigned i=1;i<=3;i++){setup();mutate_save=i;bad();CHECK(smc_calls==i-1);++cases;}
 // Boundary peers refuse each AT position in the first complete lease; all
 // other input snapshots are actual successful Native prep, never fake tokens.
 for(unsigned n:{1u,2u,15u,16u,17u,48u,49u,128u,512u,704u}){setup();fail_secure_at=n;bad();CHECK(!smc_calls);++cases;}
 for(unsigned n:{1u,2u,8u,9u,32u,64u,128u,256u}){setup();fail_secure_read=n;CHECK(!houjiGpuSecureCxProbeOnce() && !smc_calls && !final_saves && !p.complete);++cases;}
 for(unsigned field=0;field<9;field++){setup();if(field==0)gHoujiGpuExternalCanary.result.safe_to_save=0;if(field==1)gHoujiGpuExternalCanary.memory_profile=0;if(field==2)gHoujiGpuExternalCanary.active=1;if(field==3)gHoujiFirmwareMemory.active=1;if(field==4)gHoujiFirmwareMemory.complete=0;if(field==5)gHoujiFirmwareMemory.bo[5].holdForDevice();if(field==6)gHoujiGpuExternalCanary.bo[1].quarantine();if(field==7)attributes[(ppnum_t)(gHoujiGpuExternalCanary.info[1].pa>>14)]=VM_WIMG_DEFAULT;if(field==8)gHoujiFirmwareMemory.info[5].read_par[0]^=1;
  CHECK(!houjiGpuSecureCxProbeOnce() && !smc_calls && !secure_saves && !p.complete);++cases;}
 for(unsigned window=1;window<=4;window++){setup();fail_alloc=window;bad();CHECK(!smc_calls);++cases;setup();fail_map=window;bad();CHECK(!smc_calls);++cases;}
 for(unsigned kind=0;kind<3;kind++)for(unsigned n=0;n<(kind==2?22u:24u);n++){setup();word(kind==0?0x3da0800+4*n:kind==1?0x3da0c00+4*n:0x3dc0000+4096*n)=kind==0?0x80000005:kind==1?2:1;bad();CHECK(!smc_calls);++cases;}
 for(uint32_t address:{0x3d7e000u,0x3d7e070u,0x3d7e600u,HGP_CB(4),0x3da6008u,0x3da600cu,HGP_CB(0x20),HGP_CB(0x24),HGP_CB(0x28),HGP_CB(0x2c),HGP_CB(0x58),0x171004u,0x171010u,0x171018u,0x3d99144u}){setup();test_address=address;word(address)^=address==HGP_CB(0x58)?2u:1u;bad();CHECK(!smc_calls);++cases;}
 setup();fail_observation_kind=4;bad();CHECK(smc_calls==3 && !p.report_saved && !p.report_returned && !final_saves);++cases;
 setup();fail_observation_kind=5;CHECK(!houjiGpuSecureCxProbeOnce() && final_saves==1 && p.report_saved && !p.report_returned && !p.complete && p.lost && smc_calls==3);unchanged();++cases;
 setup();mutate_save=4;CHECK(!houjiGpuSecureCxProbeOnce() && final_saves==1 && p.report_saved && !p.report_returned && !p.complete && p.lost);unchanged();++cases;
 // Malformed ownership cannot exploit cross-graph metadata. Test the small
 // lease helper directly as these intentionally replace frozen old metadata.
 setup();{auto&f=gHoujiFirmwareMemory;f.info[0].pa=gHoujiGpuExternalCanary.info[0].pa;CHECK(!houjiGpuSecureCxProbeOnce() && !smc_calls);++cases;}
 setup();{auto&f=gHoujiFirmwareMemory;f.info[0].va=gHoujiGpuExternalCanary.info[0].va;CHECK(!houjiGpuSecureCxProbeOnce() && !smc_calls);++cases;}
 setup();{
  auto&f=gHoujiFirmwareMemory;const uint64_t pa=gHoujiGpuExternalCanary.info[2].pa;auto&b=f.info[7];auto&bo=f.bo[7];
  b.pa=pa;bo.descriptor()->physical_base=pa;const_cast<NativeAdrenoPhysicalSpan*>(bo.spans())[0].physical=pa;const_cast<NativeAdrenoPhysicalSpan*>(bo.ownedSpans())[0].physical=pa;
  for(unsigned row=0;row<4;row++){const uint64_t mask=UINT64_C(0x0000fffffffff000),page=pa+4096*row;b.read_par[row]=(b.read_par[row]&~mask)|page;b.write_par[row]=(b.write_par[row]&~mask)|page;b.alias_read_par[row]=(b.alias_read_par[row]&~mask)|page;b.alias_write_par[row]=(b.alias_write_par[row]&~mask)|page;}
  CHECK(houjiSecureCxBo(bo,b,0,true,false,7,b.read_par,b.write_par,b.alias_read_par,b.alias_write_par));
  CHECK(!houjiSecureCxLease() && !houjiGpuSecureCxProbeOnce() && !smc_calls);++cases;
 }
 setup();word(HGP_CB(0x20))=4096;bad();CHECK(!smc_calls);++cases;
 printf("PASS: %u secure-CX actual Native/ggs host profiles (ASan/UBSan), baseline3fixedSMC/%uobservations/%uAT/%uRO; all BOs retained, old owners byte-identical, no new GPU MMIO stores, no real SMC/firmware execution\n",cases,observations,ats,reads);secure_mode=false;discardHostAfterReset();
}
'''
(B/'probe.cpp').write_text(source)
(B/'XnuMemoryFixture.h').write_text((A/'tests/XnuMemoryFixture.h').read_text())
for name in ['IOKit/IOTypes.h','IOKit/IOBufferMemoryDescriptor.h','IOKit/IOLib.h','kern/task.h','kern/cpu_data.h','vm/vm_map.h','mach/vm_param.h','kern/clock.h','vm/memory_types.h']:
 out=B/name;out.parent.mkdir(parents=True,exist_ok=True);out.write_text('#include "XnuMemoryFixture.h"\n')
flags=['-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=address,undefined','-fno-omit-frame-pointer'];commands=[]
def run(cmd):
 commands.append(cmd);r=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'});print(r.stdout,end='');return r
objects=[]
for src in [*[V/'ArmSmmu4K'/(n+'.c') for n in ['ArmSmmu4K','ArmSmmu4KAudit','ArmSmmu4KContext','ArmSmmu4KProgram']],V/'AdrenoFirmware/AdrenoFirmware.c',X/'hfi-inactive/houji_hfi_inactive.c']:
 obj=B/(src.stem+'.o');r=run(['clang','-std=c11',*flags,'-I',str(P/'native/gpu'),'-I',str(S/'native/gpu'),'-I',str(U),'-I',str(X/'hfi-inactive'),'-c',str(src),'-o',str(obj)]);assert not r.returncode;objects.append(str(obj))
# C producer is taken from the same actual handoff fixture as the baseline.
import ast
f=ast.parse((P/'tests/check-houji-gpu-handoff-probe.py').read_text());producer=next(n.value.value for n in f.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='producer')
(B/'producer.c').write_text(producer);obj=B/'producer.o';r=run(['clang','-std=c11',*flags,'-I',str(U),'-I',str(P/'tests'),'-c',str(B/'producer.c'),'-o',str(obj)]);assert not r.returncode;objects.append(str(obj))
exe=B/'probe';r=run(['clang++','-std=c++17',*flags,'-DPAGE_SIZE=16384','-I',str(B),'-I',str(A/'tests'),'-I',str(A),'-I',str(X),'-I',str(X/'hfi-inactive'),'-I',str(S/'native/gpu'),'-I',str(V/'ArmSmmu4K'),'-I',str(U),str(B/'probe.cpp'),*objects,'-o',str(exe)]);(B/'compile-output.txt').write_text(r.stdout)
if r.returncode:raise SystemExit(r.returncode)
r=run([str(exe)]);(B/'test-output.txt').write_text(r.stdout)
helper=B/'check-gpu-scm';h=run(['clang','-std=c11',*flags,'-I',str(S/'native/gpu'),str(P/'tests/check-gpu-scm.c'),'-o',str(helper)])
if h.returncode:raise SystemExit(h.returncode)
h=run([str(helper)]);(B/'helper-test-output.txt').write_text(h.stdout)
if h.returncode:raise SystemExit(h.returncode)
(B/'verification.json').write_text(json.dumps({'commands':commands,'exit_code':r.returncode,'sources':{str(p.relative_to(S)):hashlib.sha256(p.read_bytes()).hexdigest() for p in S.rglob('*') if p.is_file()},'fixture_sha256':{name:hashlib.sha256((P/'tests'/name).read_bytes()).hexdigest() for name in ['check-gpu-scm.c','check-houji-gpu-handoff-probe.py','check-gpu-power-only-handoff.c']},'base_peer_sha256':hashlib.sha256((HERE/'base-native-peer.cpp').read_bytes()).hexdigest(),'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'boundaries':'existing Native baseline MRS/DC/DSB/AT/IOKit peers; new real SMC and RO Device boundary peers only; no real SMC/firmware'},indent=2)+'\n')
raise SystemExit(r.returncode)
