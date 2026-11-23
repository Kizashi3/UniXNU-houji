#!/usr/bin/env python3
"""Actual fixed PAS adapter with EFI/SMC/CPU hardware leaves mocked, no device.

Every policy, reservation, allocation/NC, guard, whitelist, copy-loop and
retention branch is the source header. Only five CPU hardware leaves are
replaced; the production leaves are additionally compiled for AArch64 below.
"""
from pathlib import Path
import re
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
native = p / "native/gpu/uefi/GpuZapLoadNative.h"
text = native.read_text()


def replace_leaf(source, name, replacement):
    start = re.search(r"STATIC (?:int|VOID \*|VOID|UINT64)\s*" + name + r"\([^;]+?\)\s*\{", source)
    assert start, name
    end, depth = source.index("{", start.start()) + 1, 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[:start.start()] + replacement + source[end:]


assert re.findall(r"\bg(?:BS|DS)->([A-Za-z0-9_]+)\s*\(", text) == [
    "AllocatePages", "GetMemorySpaceDescriptor", "SetMemorySpaceAttributes"]
assert "*((volatile UINT8 *)(UINTN)Address)=Value;" in text
assert "return (VOID *)(UINTN)Physical;" in text
assert not re.search(r"\b(?:FreePages|FreePool|memset|MmioRead|MmioWrite)\s*\(", text)
assert text.count("ggs_aarch64_call(NULL,R)") == 1
modified = text
for name, replacement in {
    "ZapLoadNativeAtPage": "STATIC int ZapLoadNativeAtPage(UINT64 p,UINT64*r,UINT64*w){return mock_at(p,r,w);}",
    "ZapLoadNativeBarrier": "STATIC VOID ZapLoadNativeBarrier(VOID){mock_barrier();}",
    "ZapLoadNativeStoreByte": "STATIC VOID ZapLoadNativeStoreByte(UINT64 a,UINT8 v){mock_store(a,v);}",
    "ZapLoadNativeCpuPointer": "STATIC VOID *ZapLoadNativeCpuPointer(UINT64 p){return mock_pointer(p);}",
    "ZapLoadNativeFrequency": "STATIC UINT64 ZapLoadNativeFrequency(VOID){return mock_frequency;}",
}.items():
    modified = replace_leaf(modified, name, replacement)
assert "__asm__" not in modified

source = r'''
#include <assert.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#define STATIC static
#define CONST const
#define VOID void
#define GG_HOST_TEST 1
typedef uint8_t UINT8;
typedef uint32_t UINT32;
typedef uint64_t UINT64,EFI_STATUS,EFI_PHYSICAL_ADDRESS,EFI_VIRTUAL_ADDRESS;
typedef uintptr_t UINTN;
typedef void *EFI_HANDLE;
#define MAX_UINT64 UINT64_MAX
#define MAX_UINTN UINTPTR_MAX
#define EFI_SUCCESS UINT64_C(0)
#define EFI_NOT_READY (UINT64_C(0x8000000000000000)|6)
#define EFI_DEVICE_ERROR (UINT64_C(0x8000000000000000)|7)
#define EFI_MEMORY_DESCRIPTOR_VERSION 1
#define EFI_MEMORY_UC UINT64_C(1)
#define EFI_MEMORY_WC UINT64_C(2)
#define EFI_MEMORY_WT UINT64_C(4)
#define EFI_MEMORY_WB UINT64_C(8)
#define EFI_MEMORY_UCE UINT64_C(16)
#define EFI_MEMORY_RP UINT64_C(0x2000)
#define EFI_MEMORY_XP UINT64_C(0x4000)
#define EFI_MEMORY_RO UINT64_C(0x20000)
enum {AllocateAnyPages,AllocateMaxAddress};
enum {EfiReservedMemoryType,EfiLoaderCode,EfiLoaderData,EfiBootServicesCode,EfiBootServicesData,
 EfiRuntimeServicesCode,EfiRuntimeServicesData,EfiConventionalMemory,EfiUnusableMemory,
 EfiACPIReclaimMemory,EfiACPIMemoryNVS,EfiMemoryMappedIO,EfiMemoryMappedIOPortSpace,EfiPalCode,
 EfiPersistentMemory,EfiUnacceptedMemoryType,EfiMaxMemoryType};
typedef struct {UINT32 Type;EFI_PHYSICAL_ADDRESS PhysicalStart;EFI_VIRTUAL_ADDRESS VirtualStart;UINT64 NumberOfPages,Attribute;} EFI_MEMORY_DESCRIPTOR;
typedef enum {EfiGcdMemoryTypeNonExistent,EfiGcdMemoryTypeReserved,EfiGcdMemoryTypeSystemMemory,
 EfiGcdMemoryTypeMemoryMappedIo,EfiGcdMemoryTypePersistent,EfiGcdMemoryTypeMoreReliable,
 EfiGcdMemoryTypeUnaccepted,EfiGcdMemoryTypeMaximum} EFI_GCD_MEMORY_TYPE;
typedef struct {EFI_PHYSICAL_ADDRESS BaseAddress;UINT64 Length,Capabilities,Attributes;
 EFI_GCD_MEMORY_TYPE GcdMemoryType;EFI_HANDLE ImageHandle,DeviceHandle;} EFI_GCD_MEMORY_SPACE_DESCRIPTOR;
static void ZeroMem(void*p,size_t n){memset(p,0,n);}
static void SetMem(void*p,size_t n,unsigned char v){memset(p,v,n);}
static void CopyMem(void*d,const void*s,size_t n){memcpy(d,s,n);}
static unsigned prints;
static void Print(const wchar_t*f,...){assert(f);prints++;}
struct bs {
 EFI_STATUS(*GetMemoryMap)(UINTN*,EFI_MEMORY_DESCRIPTOR*,UINTN*,UINTN*,UINT32*);
 EFI_STATUS(*AllocatePages)(unsigned,unsigned,UINTN,EFI_PHYSICAL_ADDRESS*);
};
struct ds {
 EFI_STATUS(*GetMemorySpaceDescriptor)(EFI_PHYSICAL_ADDRESS,EFI_GCD_MEMORY_SPACE_DESCRIPTOR*);
 EFI_STATUS(*SetMemorySpaceAttributes)(EFI_PHYSICAL_ADDRESS,UINT64,UINT64);
};
static EFI_STATUS getmap(UINTN*,EFI_MEMORY_DESCRIPTOR*,UINTN*,UINTN*,UINT32*);
static EFI_STATUS allocate(unsigned,unsigned,UINTN,EFI_PHYSICAL_ADDRESS*);
static EFI_STATUS getgcd(EFI_PHYSICAL_ADDRESS,EFI_GCD_MEMORY_SPACE_DESCRIPTOR*);
static EFI_STATUS setattr(EFI_PHYSICAL_ADDRESS,UINT64,UINT64);
static struct bs boot={getmap,allocate},*gBS=&boot;
static struct ds dxe={getgcd,setattr},*gDS=&dxe;
static int mock_at(UINT64,UINT64*,UINT64*);
static void mock_barrier(void),mock_store(UINT64,UINT8);
static void* mock_pointer(UINT64);
static UINT64 mock_frequency=19200000;
static UINT64 BatchCounter(void);
static UINT64 BatchMicroseconds(UINT64);
struct ggs_regs;
static int ggs_aarch64_call(void*,struct ggs_regs*);
''' + modified + r'''
static _Alignas(4096) uint8_t metadata[4096];
static uint8_t target[8192];
static unsigned maps,gcds,allocs,attrsets,at_calls,owner_calls,barriers,stores,smcs,delays;
static unsigned fail_owner,fail_at,at_bad,frozen_counter,query_invalid;
static unsigned scm_phase,busy_once,interrupt_once,scm_error,smc_transport,post_auth_at;
static unsigned service_fail,meta_bad,reservation_bad;
static UINT64 allocated_pa,frequency_step,counter;
static unsigned initial_target_at,target_attr_override[2];
static EFI_MEMORY_DESCRIPTOR map_descriptor;
static EFI_GCD_MEMORY_SPACE_DESCRIPTOR target_gcd,metadata_gcd;
static struct ggs_state qualified;
static struct hpp_result capability;
static UINT64 BatchCounter(void){UINT64 c=counter;if(!frozen_counter)counter+=frequency_step;return c;}
static UINT64 BatchMicroseconds(UINT64 begin){return (BatchCounter()-begin)*1000000/mock_frequency;}
static int owner(void*c,unsigned phase){assert(c==(void*)(uintptr_t)0x777 && phase>=1 && phase<=8);owner_calls++;return owner_calls==fail_owner?0:1;}
static const struct hzl_native_owner ownership={(void*)(uintptr_t)0x777,owner};
static void services_safe(void){assert(!mZapLoadNative.running && !mZapLoad.started && !smcs && !stores && !prints);}
static EFI_STATUS getmap(UINTN*n,EFI_MEMORY_DESCRIPTOR*b,UINTN*k,UINTN*s,UINT32*v){
 services_safe();maps++;assert(*n==GZR_MAP_BYTES);*n=sizeof map_descriptor;*s=sizeof map_descriptor;*k=0x1234;*v=1;*b=map_descriptor;return service_fail==1?EFI_DEVICE_ERROR:0;
}
static EFI_STATUS allocate(unsigned a,unsigned t,UINTN n,EFI_PHYSICAL_ADDRESS*p){
 services_safe();allocs++;assert(a==AllocateMaxAddress && t==EfiBootServicesData && n==1 && *p==0xffffffffULL);*p=allocated_pa;return service_fail==2?EFI_DEVICE_ERROR:0;
}
static EFI_STATUS getgcd(EFI_PHYSICAL_ADDRESS p,EFI_GCD_MEMORY_SPACE_DESCRIPTOR*d){
 services_safe();gcds++;
 if(p==HZL_RESERVATION_BASE || p==HZL_RESERVATION_BASE+4096){*d=target_gcd;return service_fail==3?EFI_DEVICE_ERROR:0;}
 assert(p==allocated_pa && allocs==1);*d=metadata_gcd;return service_fail==4?EFI_DEVICE_ERROR:0;
}
static EFI_STATUS setattr(EFI_PHYSICAL_ADDRESS p,UINT64 b,UINT64 a){
 services_safe();attrsets++;assert(p==allocated_pa && b==4096 && a==((metadata_gcd.Attributes&~UINT64_C(31))|EFI_MEMORY_WC));
 return service_fail==5?EFI_DEVICE_ERROR:0;
}
static void*mock_pointer(UINT64 p){assert(p==allocated_pa);return metadata;}
static int mock_at(UINT64 p,UINT64*r,UINT64*w){
 assert(r && w && !prints);at_calls++;mZapLoadNative.last_el=4;mZapLoadNative.last_tcr=0x580803510ULL;
 unsigned is_target=p==HZL_RESERVATION_BASE || p==HZL_RESERVATION_BASE+4096;
 if(is_target){assert(!mZapLoadNative.target_access_closed && mZapLoad.phase<HZL_PHASE_AUTH);initial_target_at++;}
 else assert(p==allocated_pa);
 if(smcs && mZapLoad.phase>=HZL_PHASE_AUTH){assert(!is_target);post_auth_at++;}
 UINT64 attr=is_target?(mZapLoadNative.target_cache[(p-HZL_RESERVATION_BASE)/4096]==EFI_MEMORY_UC?0:0x44):0x44;
 *r=*w=p|(attr<<56);
 if(is_target){if(target_attr_override[0]<256)*r=p|((UINT64)target_attr_override[0]<<56);if(target_attr_override[1]<256)*w=p|((UINT64)target_attr_override[1]<<56);}
 if(at_calls==fail_at){
  if(at_bad==0)return 1;if(at_bad==1)*r|=1;if(at_bad==2)*w|=1;
  if(at_bad==3)*r^=4096;if(at_bad==4)*w^=4096;
  if(at_bad==5)*r^=UINT64_C(0xff)<<56;if(at_bad==6)*w^=UINT64_C(0xff)<<56;
 }
 return 0;
}
static void mock_barrier(void){assert(!prints);barriers++;}
static void mock_store(UINT64 a,UINT8 v){
 assert(mZapLoadNative.running && mZapLoad.phase==HZL_PHASE_COPY && mZapLoad.init_succeeded && mZapLoad.mem_setup_succeeded && !mZapLoad.auth_attempted);
 assert(mZapLoadNative.target_access_closed && !mZapLoadNative.target_copy_completed && a==HZL_RESERVATION_BASE+stores && stores<HZL_SEGMENT_BYTES);
 target[stores++]=v;
}
static int ggs_aarch64_call(void*c,struct ggs_regs*r){
 assert(!c && mZapLoadNative.running && !prints && !ZapLoadNativeFrameAllowed(NULL) && ZapLoadNativeFrameAllowed(r));smcs++;
 if(mZapLoad.phase==HZL_PHASE_AUTH){assert(stores==HZL_SEGMENT_BYTES && mZapLoadNative.target_access_closed && !memcmp(target,mHoujiZapSegment,HZL_SEGMENT_BYTES));for(unsigned i=HZL_SEGMENT_BYTES;i<sizeof target;i++)assert(target[i]==0xa5);}
 if(mZapLoad.phase==scm_phase && interrupt_once){interrupt_once=0;r->x[0]=1;r->x[6]=0xbada55;return 0;}
 if(mZapLoad.phase==scm_phase && busy_once){busy_once=0;delays++;r->x[0]=(uint64_t)(int64_t)-12;return 0;}
 if(mZapLoad.phase==scm_phase && smc_transport)return 17;
 r->x[0]=0;r->x[1]=mZapLoad.phase==scm_phase?scm_error:0;return 0;
}
static void reset(void){
 memset(&mZapLoadNative,0,sizeof mZapLoadNative);memset(&mZapLoad,0,sizeof mZapLoad);memset(&mZapReservation,0,sizeof mZapReservation);
 memset(metadata,0xa5,sizeof metadata);memset(target,0xa5,sizeof target);
 maps=gcds=allocs=attrsets=at_calls=owner_calls=barriers=stores=smcs=delays=prints=0;
 fail_owner=fail_at=at_bad=frozen_counter=query_invalid=scm_phase=busy_once=interrupt_once=scm_error=smc_transport=post_auth_at=service_fail=meta_bad=reservation_bad=initial_target_at=0;
 allocated_pa=0x90000000;mock_frequency=19200000;frequency_step=19200;counter=0;
 target_attr_override[0]=target_attr_override[1]=256;
 boot=(struct bs){getmap,allocate};dxe=(struct ds){getgcd,setattr};gBS=&boot;gDS=&dxe;
 map_descriptor=(EFI_MEMORY_DESCRIPTOR){EfiReservedMemoryType,HZL_RESERVATION_BASE,0,2,0x400};
 target_gcd=(EFI_GCD_MEMORY_SPACE_DESCRIPTOR){HZL_RESERVATION_BASE,8192,EFI_MEMORY_UC,EFI_MEMORY_UC|EFI_MEMORY_XP,EfiGcdMemoryTypeReserved,NULL,NULL};
 metadata_gcd=(EFI_GCD_MEMORY_SPACE_DESCRIPTOR){allocated_pa,4096,EFI_MEMORY_WB|EFI_MEMORY_WC,EFI_MEMORY_WB|EFI_MEMORY_XP,EfiGcdMemoryTypeSystemMemory,(void*)1,NULL};
 qualified=(struct ggs_state){.convention_verified=1,.available=1,.init_succeeded=1};
 capability=(struct hpp_result){.started=1,.phase=6,.completed=5,.attempted_mask=31,.valid_mask=31,.available_mask=15,.supported_valid=1,.supported=1,.actual_calls=5};
 for(unsigned i=0;i<5;i++){struct hpp_observation*o=&capability.query[i];assert(!hpp_frame(i,&o->request));o->attempted=o->valid=o->actual_calls=o->response_present=1;o->response.x[1]=1;}
}
static void prepared(void){assert(!ZapLoadNativePrepare(&ownership,0,0,0));assert(mZapLoadNative.ready && mZapLoadNative.prepare_phase==6 && mZapLoadNative.metadata_retained && mZapLoadNative.reservation_valid && mZapLoadNative.metadata_at_valid && mZapLoadNative.target_at_valid==3 && maps==1 && gcds==3 && allocs==1 && attrsets==1 && !prints && !stores && !smcs);}
static void succeeded(void){
 assert(!RunZapLoadNative(&qualified,&capability));assert(mZapLoad.authenticated && mZapLoad.phase==HZL_PHASE_DONE && mZapLoad.retained && mZapLoadNative.metadata_retained && !mZapLoadNative.running);
 assert(stores==HZL_SEGMENT_BYTES && smcs>=3 && barriers==2 && mZapLoadNative.target_access_closed && mZapLoadNative.target_copy_completed && post_auth_at);
 assert(!memcmp(metadata,mHoujiZapMetadata,HZL_METADATA_BYTES) && !memcmp(target,mHoujiZapSegment,HZL_SEGMENT_BYTES));
 for(unsigned i=HZL_METADATA_BYTES;i<sizeof metadata;i++)assert(metadata[i]==0xa5);
 assert(maps==1 && gcds==3 && allocs==1 && attrsets==1 && !prints);
}
int main(void){unsigned cases=0;
 reset();prepared();succeeded();unsigned owner_total=owner_calls,at_total=at_calls;assert(mZapLoadNative.target_at_phase==HZL_PHASE_COPY);
 unsigned target_ats=initial_target_at;assert(RunZapLoadNative(&qualified,&capability)==HZL_ALREADY_STARTED && initial_target_at==target_ats);ZapLoadNativeReport();assert(prints==22);cases++;
 for(unsigned bad=0;bad<7;bad++){reset();if(!bad)gBS=NULL;if(bad==1)gDS=NULL;if(bad==2)boot.AllocatePages=NULL;if(bad==3)dxe.GetMemorySpaceDescriptor=NULL;if(bad==4)dxe.SetMemorySpaceAttributes=NULL;if(bad==5)mock_frequency=0;if(bad==6)mock_frequency=1000000001;
  assert(ZapLoadNativePrepare(&ownership,0,0,0)==HZN_ARGUMENT && !maps && !allocs && !stores && !smcs);cases++;}
 reset();assert(ZapLoadNativePrepare(NULL,0,0,0)==HZN_ARGUMENT);cases++;
 for(unsigned gate=0;gate<3;gate++){reset();unsigned v[3]={0};v[gate]=1;assert(ZapLoadNativePrepare(&ownership,v[0],v[1],v[2])==HZN_ARGUMENT && !owner_calls && !allocs && !maps);cases++;}
 reset();prepared();struct hzl_config saved=mZapLoadNative.config;assert(ZapLoadNativePrepare(&ownership,0,0,0)==HZN_ALREADY_PREPARED && !memcmp(&saved,&mZapLoadNative.config,sizeof saved));cases++;
 for(unsigned f=1;f<=5;f++){reset();service_fail=f;assert(ZapLoadNativePrepare(&ownership,0,0,0) && !mZapLoadNative.ready && !stores && !smcs);assert(mZapLoadNative.metadata_retained==(f>=4));cases++;}
 for(unsigned bad=0;bad<14;bad++){
  reset();if(bad==0)map_descriptor.Type=EfiConventionalMemory;if(bad==1)map_descriptor.Type=EfiBootServicesData;
  if(bad==2)map_descriptor.NumberOfPages=1;if(bad==3)target_gcd.GcdMemoryType=EfiGcdMemoryTypeSystemMemory;
  if(bad==4)target_gcd.ImageHandle=(void*)1;if(bad==5)target_gcd.DeviceHandle=(void*)2;
  if(bad==6)target_gcd.Attributes=EFI_MEMORY_WB;if(bad==7)target_gcd.Attributes=EFI_MEMORY_WT;
  if(bad==8)target_gcd.Attributes=EFI_MEMORY_UC|EFI_MEMORY_WC;if(bad==9)target_gcd.Attributes|=EFI_MEMORY_RP;
  if(bad==10)target_gcd.Attributes|=EFI_MEMORY_RO;if(bad==11)target_gcd.Length=4096;
  if(bad==12)target_gcd.BaseAddress+=4096;if(bad==13){assert(!GpuZapReservationCapture(0,0,0));}
  assert(ZapLoadNativePrepare(&ownership,0,0,0)==HZN_RESERVATION && !allocs && !smcs && !stores && !mZapLoadNative.ready);cases++;
 }
 reset();target_gcd.Attributes=EFI_MEMORY_WC;prepared();succeeded();cases++;
 // Source-qualified PIL cache mismatch: raw caps UC while raw cache attrs
 // are zero after CPU WC&Capabilities synchronization. Do not modify either
 // raw field or conflate the derived CPU PAR=44 profile with GCD attributes.
 for(unsigned extra=0;extra<2;extra++){
  reset();target_gcd.BaseAddress=0x8bc00000;target_gcd.Length=0x16f80000;
  target_gcd.Attributes=EFI_MEMORY_XP;target_gcd.Capabilities=EFI_MEMORY_UC|(extra?(UINT64_C(1)<<63)|EFI_MEMORY_RO|EFI_MEMORY_RP|EFI_MEMORY_XP:0);
  prepared();assert(mZapLoadNative.derived_cache_profile==3 && mZapReservation.gcd[0].raw.Attributes==EFI_MEMORY_XP && mZapReservation.gcd[1].raw.Capabilities==target_gcd.Capabilities);
  assert(mZapLoadNative.target_cache[0]==EFI_MEMORY_WC && mZapLoadNative.target_cache[1]==EFI_MEMORY_WC);succeeded();cases++;
 }
 const UINT64 badcaps[]={0,EFI_MEMORY_WC,EFI_MEMORY_WT,EFI_MEMORY_WB,EFI_MEMORY_UCE,EFI_MEMORY_UC|EFI_MEMORY_WC,EFI_MEMORY_UC|EFI_MEMORY_WB};
 for(unsigned i=0;i<sizeof badcaps/sizeof badcaps[0];i++){
  reset();target_gcd.Attributes=0;target_gcd.Capabilities=badcaps[i]|EFI_MEMORY_RO|EFI_MEMORY_RP|EFI_MEMORY_XP;
  assert(ZapLoadNativePrepare(&ownership,0,0,0)==HZN_RESERVATION && !allocs && !smcs && !stores);cases++;
 }
 for(unsigned bad=0;bad<8;bad++){
  reset();target_gcd.BaseAddress=0x8bc00000;target_gcd.Length=0x16f80000;target_gcd.Attributes=0;
  if(!bad){target_gcd.BaseAddress-=4096;target_gcd.Length+=4096;}
  if(bad==1)target_gcd.Length+=4096;if(bad==2)target_gcd.GcdMemoryType=EfiGcdMemoryTypeSystemMemory;
  if(bad==3)target_gcd.ImageHandle=(void*)1;if(bad==4)target_gcd.DeviceHandle=(void*)1;
  if(bad==5)map_descriptor.Type=EfiConventionalMemory;if(bad==6)map_descriptor.Type=EfiBootServicesData;
  if(bad==7)target_gcd.Attributes=EFI_MEMORY_RO;
  assert(ZapLoadNativePrepare(&ownership,0,0,0)==HZN_RESERVATION && !allocs && !smcs && !stores);cases++;
 }
 const unsigned badparattr[]={0,4,0xff,0xbb};
 for(unsigned rw=0;rw<2;rw++)for(unsigned i=0;i<sizeof badparattr/sizeof badparattr[0];i++){
  reset();target_gcd.Attributes=0;target_attr_override[rw]=badparattr[i];
  assert(ZapLoadNativePrepare(&ownership,0,0,0)==HZN_TRANSLATION && mZapLoadNative.derived_cache_profile==3 && mZapLoadNative.metadata_retained && !mZapLoadNative.ready && !smcs && !stores);cases++;
 }
 reset();target_attr_override[0]=target_attr_override[1]=4;prepared();assert(!mZapLoadNative.derived_cache_profile);succeeded();cases++;
 const UINT64 badpa[]={0,1,0x100000000ULL,HZL_RESERVATION_BASE,HZL_RESERVATION_BASE+4096};
 for(unsigned i=0;i<sizeof badpa/sizeof badpa[0];i++){reset();allocated_pa=badpa[i];assert(ZapLoadNativePrepare(&ownership,0,0,0)==HZN_ALLOCATE && mZapLoadNative.metadata_retained && !attrsets && !stores);cases++;}
 for(unsigned bad=0;bad<10;bad++){
  reset();if(!bad)metadata_gcd.GcdMemoryType=EfiGcdMemoryTypeReserved;if(bad==1)metadata_gcd.BaseAddress++;
  if(bad==2)metadata_gcd.Length=4095;if(bad==3)metadata_gcd.Capabilities&=~EFI_MEMORY_WC;
  if(bad==4)metadata_gcd.Attributes=EFI_MEMORY_WC;if(bad==5)metadata_gcd.Attributes|=EFI_MEMORY_UC;
  if(bad==6)metadata_gcd.Attributes|=EFI_MEMORY_RP;if(bad==7)metadata_gcd.Attributes|=EFI_MEMORY_RO;
  if(bad==8)metadata_gcd.Length=MAX_UINT64;if(bad==9)metadata_gcd.BaseAddress=allocated_pa-4096;
  assert(ZapLoadNativePrepare(&ownership,0,0,0)==HZN_METADATA_GCD && mZapLoadNative.metadata_retained && !attrsets && !stores);cases++;
 }
 // Reject every actual owner/translation failure in Prepare and Execute.
 for(unsigned n=1;n<=owner_total;n++){
  reset();fail_owner=n;unsigned c=ZapLoadNativePrepare(&ownership,0,0,0);
  if(!c)c=RunZapLoadNative(&qualified,&capability);
  assert(c && owner_calls>=n && !mZapLoadNative.running && !prints);
  if(stores)assert(stores==1072 && mZapLoad.mem_setup_succeeded && mZapLoadNative.target_access_closed);
  if(mZapLoad.init_attempted)assert(mZapLoad.retained && mZapLoadNative.metadata_retained);cases++;
 }
 for(unsigned n=1;n<=at_total;n++)for(unsigned bad=0;bad<7;bad++){
  reset();fail_at=n;at_bad=bad;unsigned c=ZapLoadNativePrepare(&ownership,0,0,0);if(!c)c=RunZapLoadNative(&qualified,&capability);
  assert(c && at_calls>=n && !mZapLoadNative.running && !prints);if(stores)assert(stores==1072 && mZapLoadNative.target_access_closed);cases++;
 }
 const unsigned phases[]={HZL_PHASE_INIT,HZL_PHASE_MEM_SETUP,HZL_PHASE_AUTH};
 for(unsigned i=0;i<3;i++)for(unsigned kind=0;kind<4;kind++){
  reset();prepared();scm_phase=phases[i];if(!kind)interrupt_once=1;if(kind==1)busy_once=1;
  if(kind==2)scm_error=1;if(kind==3)smc_transport=1;
  if(kind<2){succeeded();assert(smcs==4 && mZapLoadNative.native_calls==4 && !mZapLoadNative.pending);if(kind==1)assert(delays==1);}
  else {assert(RunZapLoadNative(&qualified,&capability) && mZapLoad.retained && mZapLoadNative.metadata_retained && !mZapLoad.authenticated);assert(stores==(i==2?1072:0));}
  cases++;
 }
 reset();prepared();scm_phase=HZL_PHASE_INIT;busy_once=1;frozen_counter=1;assert(RunZapLoadNative(&qualified,&capability) && smcs==1 && !stores && mZapLoad.retained);cases++;
 // All eight full-width arguments are exact, including interrupted cookies.
 for(unsigned i=0;i<3;i++){
  reset();prepared();mZapLoadNative.running=1;mZapLoad=(struct hzl_result){.started=1,.phase=phases[i],.metadata_published=1,.init_attempted=1,.init_succeeded=1,.mem_setup_attempted=1,.mem_setup_succeeded=1,.segment_published=1,.auth_attempted=1};
  if(i==2)mZapLoadNative.target_access_closed=mZapLoadNative.target_copy_completed=1;
  struct ggs_regs frame=i==0?(struct ggs_regs){{0x42000201,0x82,13,allocated_pa,0,0,0,0}}:i==1?(struct ggs_regs){{0x42000202,3,13,HZL_RESERVATION_BASE,4096,0,0,0}}:(struct ggs_regs){{0x42000205,1,13,0,0,0,0,0}};
  assert(ZapLoadNativeFrameAllowed(&frame));
  for(unsigned arg=0;arg<8;arg++)for(unsigned bit=0;bit<64;bit++){struct ggs_regs wrong=frame;wrong.x[arg]^=UINT64_C(1)<<bit;assert(!ZapLoadNativeFrameAllowed(&wrong));cases++;}
  for(unsigned arg=0;arg<8;arg++){struct ggs_regs wrong=frame;wrong.x[arg]^=UINT64_C(1)<<63;assert(ZapLoadNativeCall(NULL,&wrong) && mZapLoadNative.rejected==2 && !smcs && !stores);cases++;}
  mZapLoadNative.pending=1;mZapLoadNative.pending_phase=phases[i];mZapLoadNative.resume_cookie=0x1234567812345678ULL;frame.x[0]=1;frame.x[6]=mZapLoadNative.resume_cookie;assert(ZapLoadNativeFrameAllowed(&frame));
  for(unsigned bit=0;bit<64;bit++){frame.x[6]^=UINT64_C(1)<<bit;assert(!ZapLoadNativeFrameAllowed(&frame));frame.x[6]^=UINT64_C(1)<<bit;cases++;}
  mZapLoadNative.pending_phase++;assert(!ZapLoadNativeFrameAllowed(&frame));cases++;
 }
 // The retained allocation/config must remain the original exact identity
 // binding; passing the portable structural validator alone is insufficient.
 for(unsigned bad=0;bad<12;bad++){
  reset();prepared();mZapLoadNative.running=1;mZapLoad=(struct hzl_result){.started=1,.phase=HZL_PHASE_PUBLISH,.metadata_copied=1};
  if(!bad)mZapLoadNative.ready=0;if(bad==1)mZapLoadNative.prepare_code=1;
  if(bad==2)mZapLoadNative.reservation_valid=0;if(bad==3)mZapLoadNative.metadata_allocated=0;
  if(bad==4)mZapLoadNative.metadata_retained=0;if(bad==5)mZapLoadNative.owner.guard=NULL;
  if(bad==6)mZapLoadNative.config.metadata_physical+=4096;if(bad==7)mZapLoadNative.config.metadata_cpu=metadata+4096;
  if(bad==8)mZapLoadNative.config.metadata_capacity=4044;if(bad==9)mZapLoadNative.config.reservation_base+=4096;
  if(bad==10)mZapLoadNative.config.reservation_bytes=4096;if(bad==11)mZapLoadNative.target_access_closed=1;
  assert(!ZapLoadNativeGuard(NULL,HZL_PHASE_PUBLISH) && !stores && !smcs && !barriers);cases++;
 }
 for(unsigned bad=0;bad<5;bad++){
  reset();prepared();mZapLoadNative.running=1;mZapLoad=(struct hzl_result){.started=1,.phase=HZL_PHASE_PUBLISH,.metadata_copied=1};
  void*cpu=metadata;UINT64 pa=allocated_pa;unsigned bytes=4044;
  if(!bad)cpu=metadata+1;if(bad==1)pa+=4096;if(bad==2)bytes--;
  if(bad==3)mZapLoad.metadata_copied=0;if(bad==4)mZapLoad.phase=HZL_PHASE_INIT;
  assert(ZapLoadNativePublish(NULL,cpu,pa,bytes) && !barriers && !stores && !smcs);cases++;
 }
 // Never write an alias/different source/size or attempt a second copy.
 for(unsigned bad=0;bad<7;bad++){
  reset();prepared();mZapLoadNative.running=1;mZapLoad=(struct hzl_result){.started=1,.phase=HZL_PHASE_COPY,.init_succeeded=1,.mem_setup_succeeded=1,.segment_copy_attempted=1};
  UINT64 dst=HZL_RESERVATION_BASE;const uint8_t*src=mHoujiZapSegment;unsigned bytes=HZL_SEGMENT_BYTES;
  if(!bad)dst++;if(bad==1)src++;if(bad==2)bytes--;if(bad==3)mZapLoad.mem_setup_succeeded=0;
  if(bad==4)mZapLoadNative.target_access_closed=1;if(bad==5)mZapLoadNative.target_copy_started=1;if(bad==6)mZapLoad.segment_copy_attempted=0;
  assert(ZapLoadNativeCopy(NULL,dst,src,bytes) && !stores && !barriers && !smcs);cases++;
 }
 reset();assert(RunZapLoadNative(&qualified,&capability)==HZN_NOT_PREPARED && !maps && !smcs && !stores);cases++;
 printf("PASS: %u actual native PAS13 adapter cases; bounded EFI reservation/NC prepare, every owner/AT failure, exact full-frame/resume whitelist, real policy copy order, no runtime BS/FS, software-only target access close, no cleanup after auth\n",cases);
}
'''
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    (folder / "test.c").write_text(source)
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-I", str(native.parent),
                    "-I", str(p / "native/gpu"), str(folder / "test.c"),
                    "-o", str(folder / "test")], check=True)
    subprocess.run([str(folder / "test")], check=True)
