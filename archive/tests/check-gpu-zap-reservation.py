#!/usr/bin/env python3
"""Exercise the actual fixed-range native observer; mock only EFI services.

No firmware build, phone, target PA mapping/access, or PAS operation is used.
The mocked tables deliberately expose no allocation or memory-write services.
"""
from pathlib import Path
import re
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
header = p / "native/gpu/uefi/GpuZapReservationNative.h"
text = header.read_text()
# Keep this narrowly read-only if the implementation is later edited.
service_calls = re.findall(r"g(?:BS|DS)->([A-Za-z0-9_]+)\s*\(", text)
assert service_calls == ["GetMemoryMap", "GetMemorySpaceDescriptor"]
assert not re.search(r"\b(?:Mmio|Allocate|Free|SetMemorySpace|ArmSet|CopyMemTo|Smc)[A-Za-z0-9_]*\s*\(", text)
assert not re.search(r"\([^)]*\*[^)]*\)\s*GZR_BASE", text)

source = r'''
#include <assert.h>
#include <stdint.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#define STATIC static
#define CONST const
#define VOID void
typedef uint8_t UINT8;
typedef uint32_t UINT32;
typedef uint64_t UINT64,EFI_STATUS,EFI_PHYSICAL_ADDRESS,EFI_VIRTUAL_ADDRESS;
typedef uintptr_t UINTN;
typedef void *EFI_HANDLE;
#define MAX_UINT64 UINT64_MAX
#define MAX_UINTN UINTPTR_MAX
#define EFI_SUCCESS UINT64_C(0)
#define EFI_NOT_READY (UINT64_C(0x8000000000000000)|6)
#define EFI_BUFFER_TOO_SMALL (UINT64_C(0x8000000000000000)|5)
#define EFI_DEVICE_ERROR (UINT64_C(0x8000000000000000)|7)
#define EFI_MEMORY_DESCRIPTOR_VERSION 1
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
static unsigned print_calls;
static void Print(const wchar_t*f,...){assert(f);print_calls++;}
struct bs {EFI_STATUS (*GetMemoryMap)(UINTN*,EFI_MEMORY_DESCRIPTOR*,UINTN*,UINTN*,UINT32*);};
struct ds {EFI_STATUS (*GetMemorySpaceDescriptor)(EFI_PHYSICAL_ADDRESS,EFI_GCD_MEMORY_SPACE_DESCRIPTOR*);};
static EFI_STATUS getmap(UINTN*,EFI_MEMORY_DESCRIPTOR*,UINTN*,UINTN*,UINT32*);
static EFI_STATUS getgcd(EFI_PHYSICAL_ADDRESS,EFI_GCD_MEMORY_SPACE_DESCRIPTOR*);
static struct bs boot={getmap},*gBS=&boot;
static struct ds dxe={getgcd},*gDS=&dxe;
#include "GpuZapReservationNative.h"
static unsigned maps,gcds,omit_map_outputs,gcd_write_mask;
static EFI_STATUS map_status,gcd_status[2];
static EFI_MEMORY_DESCRIPTOR desc[64];
static EFI_GCD_MEMORY_SPACE_DESCRIPTOR gcd_desc[2];
static UINTN returned_bytes,returned_stride,returned_key,desc_count;
static UINT32 returned_version;
static EFI_STATUS getmap(UINTN*n,EFI_MEMORY_DESCRIPTOR*b,UINTN*k,UINTN*s,UINT32*v){
 assert(n && b && k && s && v && !maps && !gcds);
 assert((void*)b==(void*)mZapReservationMap.bytes && *n==GZR_MAP_BYTES);
 assert(*k==MAX_UINTN && *s==MAX_UINTN && *v==0xffffffffu);maps++;
 // A service may return errors with partially written metadata. Fill only the
 // bounded map entries, independently of deliberately malformed output sizes.
 if(returned_stride>=sizeof(*b) && returned_stride<=GZR_MAP_BYTES){
  for(UINTN i=0;i<desc_count && i<GZR_MAP_BYTES/returned_stride;i++)
   memcpy((unsigned char*)b+i*returned_stride,&desc[i],sizeof(*b));
 }
 if(!(omit_map_outputs&1))*n=returned_bytes;
 if(!(omit_map_outputs&2))*k=returned_key;
 if(!(omit_map_outputs&4))*s=returned_stride;
 if(!(omit_map_outputs&8))*v=returned_version;
 return map_status;
}
static EFI_STATUS getgcd(EFI_PHYSICAL_ADDRESS a,EFI_GCD_MEMORY_SPACE_DESCRIPTOR*d){
 assert(maps==1 && gcds<2 && a==GZR_BASE+(UINT64)gcds*4096);
 unsigned i=gcds++;
 if(gcd_write_mask&(1u<<i))*d=gcd_desc[i];
 return gcd_status[i];
}
static void reset(void){
 memset(&mZapReservation,0,sizeof mZapReservation);memset(&mZapReservationMap,0,sizeof mZapReservationMap);
 maps=gcds=print_calls=omit_map_outputs=0;gcd_write_mask=3;
 boot.GetMemoryMap=getmap;dxe.GetMemorySpaceDescriptor=getgcd;gBS=&boot;gDS=&dxe;
 map_status=gcd_status[0]=gcd_status[1]=EFI_SUCCESS;
 returned_stride=sizeof(EFI_MEMORY_DESCRIPTOR);desc_count=1;returned_bytes=returned_stride;
 returned_key=0x12345678;returned_version=1;
 memset(desc,0,sizeof desc);desc[0]=(EFI_MEMORY_DESCRIPTOR){EfiConventionalMemory,GZR_BASE,0,2,0x8000000000000008ULL};
 for(unsigned i=0;i<2;i++)gcd_desc[i]=(EFI_GCD_MEMORY_SPACE_DESCRIPTOR){GZR_BASE,GZR_BYTES,0xf,8,EfiGcdMemoryTypeReserved,NULL,NULL};
}
static void complete(void){
 assert(maps==1 && gcds==2 && !print_calls && mZapReservation.started && mZapReservation.map_valid);
 assert(mZapReservation.coverage==3 && !mZapReservation.duplicate_coverage);
 assert(mZapReservation.map_metadata_valid && mZapReservation.nonconventional_known);
 assert(mZapReservation.gcd_allocation_known && mZapReservation.gcd[0].covers_page && mZapReservation.gcd[1].covers_page);
}
int main(void){unsigned cases=0;assert(!((uintptr_t)mZapReservationMap.bytes&7));
 reset();assert(!GpuZapReservationCapture(0,0,0));complete();assert(mZapReservation.allocation_known && !mZapReservation.allocation_overlap && !mZapReservation.nonconventional_overlap && !mZapReservation.gcd_allocation_overlap);
 assert(mZapReservation.records[0].raw.Attribute==0x8000000000000008ULL && mZapReservation.gcd[0].raw.Attributes==8 && mZapReservation.gcd[0].raw.Capabilities==15);
 struct gzr_result saved=mZapReservation;assert(GpuZapReservationCapture(1,1,1)==GZR_REUSED && !memcmp(&saved,&mZapReservation,sizeof saved) && maps==1 && gcds==2);GpuZapReservationReport();assert(print_calls==6 && maps==1 && gcds==2);cases++;
 for(unsigned gate=0;gate<3;gate++)for(unsigned v=1;v<=3;v++){
  reset();unsigned a[3]={0};a[gate]=v;assert(GpuZapReservationCapture(a[0],a[1],a[2])==GZR_GATE && !maps && !gcds && !print_calls);
  assert(mZapReservation.unsafe==a[0] && mZapReservation.sqe_enabled==a[1] && mZapReservation.store_calls==a[2]);GpuZapReservationReport();assert(print_calls==5);cases++;
 }
 for(unsigned s=0;s<4;s++){
  reset();if(!s)gBS=NULL;if(s==1)gDS=NULL;if(s==2)boot.GetMemoryMap=NULL;if(s==3)dxe.GetMemorySpaceDescriptor=NULL;
  assert(GpuZapReservationCapture(0,0,0)==GZR_SERVICES && !maps && !gcds && !print_calls);cases++;
 }
 const EFI_STATUS badstatus[]={EFI_BUFFER_TOO_SMALL,EFI_DEVICE_ERROR,1};
 for(unsigned i=0;i<sizeof badstatus/sizeof badstatus[0];i++){
  reset();map_status=badstatus[i];returned_bytes=GZR_MAP_BYTES+4096;returned_stride=48;returned_key=0x1122334455667788ULL;returned_version=7;
  assert(GpuZapReservationCapture(0,0,0)==GZR_MAP_STATUS && maps==1 && gcds==2 && !mZapReservation.map_metadata_valid && !mZapReservation.map_valid && !mZapReservation.record_count);
  assert(mZapReservation.map_status==badstatus[i] && mZapReservation.map_bytes==GZR_MAP_BYTES+4096 && mZapReservation.descriptor_bytes==48 && mZapReservation.map_key==0x1122334455667788ULL && mZapReservation.descriptor_version==7 && !mZapReservation.allocation_known);cases++;
 }
 // Key is opaque: all-ones is a legitimate returned key, not an error code.
 reset();returned_key=MAX_UINTN;assert(!GpuZapReservationCapture(0,0,0) && mZapReservation.map_key==MAX_UINTN);complete();cases++;
 for(unsigned field=0;field<4;field++)for(unsigned i=0;i<5;i++){
  reset();const UINTN values[]={0,1,39,GZR_MAP_BYTES+1,MAX_UINTN};
  if(field==0)returned_bytes=values[i];if(field==1)returned_stride=values[i];
  if(field==2)returned_version=(UINT32)(i?i+1:0);if(field==3)omit_map_outputs=1u<<(i%3==0?0:i%3==1?2:3);
  assert(GpuZapReservationCapture(0,0,0)==GZR_MAP_METADATA && maps==1 && gcds==2 && !mZapReservation.map_metadata_valid && !mZapReservation.record_count && !mZapReservation.allocation_known);cases++;
 }
 reset();returned_stride=48;returned_bytes=48;assert(!GpuZapReservationCapture(0,0,0));complete();cases++;
 reset();returned_stride=41;returned_bytes=41;assert(GpuZapReservationCapture(0,0,0)==GZR_MAP_METADATA);cases++;
 reset();returned_stride=48;returned_bytes=49;assert(GpuZapReservationCapture(0,0,0)==GZR_MAP_METADATA);cases++;
 for(UINT32 t=0;t<EfiMaxMemoryType;t++){
  reset();desc[0].Type=t;assert(!GpuZapReservationCapture(0,0,0));complete();
  assert(mZapReservation.allocation_known && mZapReservation.allocation_overlap==GpuZapReservationAllocatedType(t));
  assert(mZapReservation.nonconventional_overlap==(t!=EfiConventionalMemory));cases++;
 }
 const UINT32 oddtypes[]={EfiMaxMemoryType,0x6fffffffu,0x70000000u,0x7fffffffu,0x80000000u,0xffffffffu};
 for(unsigned i=0;i<sizeof oddtypes/sizeof oddtypes[0];i++){
  reset();desc[0].Type=oddtypes[i];unsigned code=GpuZapReservationCapture(0,0,0);
  if(i<2)assert((code&(GZR_MAP_DESCRIPTOR|GZR_MAP_COVERAGE))==(GZR_MAP_DESCRIPTOR|GZR_MAP_COVERAGE) && !mZapReservation.records[0].valid);
  else {assert(!code && mZapReservation.map_valid && !mZapReservation.allocation_known && mZapReservation.nonconventional_overlap);complete();}cases++;
 }
 for(unsigned bad=0;bad<7;bad++){
  reset();if(bad==0)desc[0].PhysicalStart++;if(bad==1)desc[0].VirtualStart=1;
  if(bad==2)desc[0].NumberOfPages=0;if(bad==3)desc[0].NumberOfPages=UINT64_C(1)<<52;
  if(bad==4)desc[0].NumberOfPages=MAX_UINT64;if(bad==5)desc[0].PhysicalStart=0xfffffffffffff000ULL;
  if(bad==6)desc[0].VirtualStart=0xfffffffffffff000ULL;
  unsigned code=GpuZapReservationCapture(0,0,0);assert(code&GZR_MAP_DESCRIPTOR);
  assert(mZapReservation.invalid_descriptors==1 && !mZapReservation.records[0].valid && mZapReservation.records[0].reason && !mZapReservation.allocation_known && !mZapReservation.map_valid);cases++;
 }
 reset();desc_count=2;returned_bytes=returned_stride*2;desc[0].PhysicalStart=0xfffffffffffff000ULL;desc[0].NumberOfPages=1;desc[1]=(EFI_MEMORY_DESCRIPTOR){EfiConventionalMemory,GZR_BASE,0,2,8};
 assert(!GpuZapReservationCapture(0,0,0));complete();cases++;
 reset();desc[0].PhysicalStart=GZR_BASE-4096;desc[0].NumberOfPages=4;assert(!GpuZapReservationCapture(0,0,0));complete();cases++;
 reset();desc_count=2;returned_bytes=2*returned_stride;desc[0].NumberOfPages=1;desc[1]=(EFI_MEMORY_DESCRIPTOR){EfiBootServicesData,GZR_BASE+4096,0,1,4};
 assert(!GpuZapReservationCapture(0,0,0));complete();assert(mZapReservation.record_count==2 && mZapReservation.allocation_overlap && mZapReservation.nonconventional_overlap && mZapReservation.records[0].coverage==1 && mZapReservation.records[1].coverage==2);cases++;
 for(unsigned missing=0;missing<3;missing++){
  reset();desc[0].NumberOfPages=1;if(missing==1)desc[0].PhysicalStart+=4096;if(missing==2)desc[0].PhysicalStart-=4096;
  assert(GpuZapReservationCapture(0,0,0)==GZR_MAP_COVERAGE && mZapReservation.coverage==(missing==0?1:missing==1?2:0) && !mZapReservation.map_valid && !mZapReservation.allocation_known);cases++;
 }
 reset();desc_count=64;returned_bytes=desc_count*returned_stride;for(unsigned i=1;i<desc_count;i++)desc[i]=desc[0];
 assert(GpuZapReservationCapture(0,0,0)==GZR_MAP_OVERLAP && mZapReservation.duplicate_coverage==3 && mZapReservation.candidate_records==64 && mZapReservation.record_count==GZR_RECORDS && !mZapReservation.allocation_known);
 GpuZapReservationReport();assert(print_calls==5+GZR_RECORDS);cases++;
 for(unsigned page=0;page<2;page++){
  reset();gcd_status[page]=EFI_DEVICE_ERROR;gcd_desc[page].ImageHandle=(void*)(uintptr_t)0x12345678;
  assert(GpuZapReservationCapture(0,0,0)==GZR_GCD_STATUS && mZapReservation.gcd[page].raw.ImageHandle==(void*)(uintptr_t)0x12345678 && !mZapReservation.gcd[page].valid && !mZapReservation.gcd[page].allocated && !mZapReservation.gcd_allocation_known);cases++;
  reset();gcd_status[page]=EFI_DEVICE_ERROR;gcd_write_mask&=~(1u<<page);assert(GpuZapReservationCapture(0,0,0)==GZR_GCD_STATUS);
  assert(mZapReservation.gcd[page].raw.BaseAddress==0xa5a5a5a5a5a5a5a5ULL && !mZapReservation.gcd[page].valid);cases++;
  for(unsigned bad=0;bad<7;bad++){
   reset();if(!bad)gcd_desc[page].Length=0;if(bad==1)gcd_desc[page].Length=4095;
   if(bad==2)gcd_desc[page].BaseAddress=GZR_BASE+4096*(page+1);
   if(bad==3)gcd_desc[page].Length=MAX_UINT64;
   if(bad==4)gcd_desc[page].GcdMemoryType=EfiGcdMemoryTypeMaximum;
   if(bad==5)gcd_desc[page].GcdMemoryType=(EFI_GCD_MEMORY_TYPE)-1;
   if(bad==6)gcd_write_mask&=~(1u<<page);
   assert(GpuZapReservationCapture(0,0,0)==GZR_GCD_DESCRIPTOR && !mZapReservation.gcd[page].valid && !mZapReservation.gcd_allocation_known);cases++;
  }
 }
 for(unsigned t=0;t<EfiGcdMemoryTypeMaximum;t++)for(unsigned which=0;which<4;which++){
  reset();for(unsigned i=0;i<2;i++){gcd_desc[i].BaseAddress=GZR_BASE+i*4096;gcd_desc[i].Length=4096;gcd_desc[i].GcdMemoryType=(EFI_GCD_MEMORY_TYPE)t;
   gcd_desc[i].ImageHandle=which&(1u<<i)?(void*)(uintptr_t)(0x1111+i):NULL;gcd_desc[i].DeviceHandle=(void*)(uintptr_t)(0x2222+i);}
  assert(!GpuZapReservationCapture(0,0,0));complete();assert(mZapReservation.gcd_allocation_overlap==!!which && mZapReservation.gcd[0].allocated==!!(which&1) && mZapReservation.gcd[1].allocated==!!(which&2));cases++;
 }
 // Error reporting never queries services again or touches an asserted PA.
 reset();map_status=EFI_BUFFER_TOO_SMALL;returned_bytes=100000;gcd_status[0]=EFI_DEVICE_ERROR;assert(GpuZapReservationCapture(0,0,0)==(GZR_MAP_STATUS|GZR_GCD_STATUS));
 GpuZapReservationReport();assert(maps==1 && gcds==2 && print_calls==5);cases++;
 printf("PASS: %u fixed ZAP reservation observer cases; actual native header, bounded map/no allocations, fail-closed metadata, page coverage/overlap, raw failure retention, EFI/GCD allocation distinction, PAS remains unknown\n",cases);
}
'''
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    (folder / "test.c").write_text(source)
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-I", str(header.parent),
                    str(folder / "test.c"), "-o", str(folder / "test")], check=True)
    subprocess.run([str(folder / "test")], check=True)
