/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Fixed-range, observation-only reservation snapshot. Include in the native
 * app after the EFI/gDS/gBS and Print declarations. Call at TPL_APPLICATION,
 * before SQE and before any unsafe/store attempt. The three inputs are caller
 * state snapshots, not independent hardware proof. No allocation, map mutation,
 * target-memory access, PAS call, MMIO, or implicit ownership inference.
 */
#ifndef HOUJI_GPU_ZAP_RESERVATION_NATIVE_H
#define HOUJI_GPU_ZAP_RESERVATION_NATIVE_H
#define GZR_BASE  0x9b09a000ULL
#define GZR_BYTES 0x2000ULL
#define GZR_MAP_BYTES 65536u
#define GZR_RECORDS 8u
enum {
 GZR_GATE=1u, GZR_SERVICES=2u, GZR_MAP_STATUS=4u, GZR_MAP_METADATA=8u,
 GZR_MAP_DESCRIPTOR=16u, GZR_MAP_COVERAGE=32u, GZR_MAP_OVERLAP=64u,
 GZR_GCD_STATUS=128u, GZR_GCD_DESCRIPTOR=256u, GZR_REUSED=512u
};
struct gzr_gcd_record {
 EFI_STATUS status;
 EFI_GCD_MEMORY_SPACE_DESCRIPTOR raw;
 unsigned attempted,valid,covers_page,allocated;
};
struct gzr_map_record {
 EFI_MEMORY_DESCRIPTOR raw;
 UINTN index;
 unsigned valid,reason,coverage;
};
struct gzr_result {
 unsigned started,code,unsafe,sqe_enabled,store_calls;
 EFI_STATUS map_status;
 UINTN map_bytes,map_key,descriptor_bytes;
 UINT32 descriptor_version;
 unsigned map_attempted,map_metadata_valid,map_valid;
 UINTN descriptors,invalid_descriptors,candidate_records,record_count;
 unsigned coverage,duplicate_coverage,allocation_known,allocation_overlap,allocation_unknown_type;
 unsigned nonconventional_known,nonconventional_overlap,gcd_allocation_known,gcd_allocation_overlap;
 struct gzr_gcd_record gcd[2];
 struct gzr_map_record records[GZR_RECORDS];
};
STATIC struct gzr_result mZapReservation;
STATIC union {UINT64 alignment;UINT8 bytes[GZR_MAP_BYTES];} mZapReservationMap;

STATIC unsigned GpuZapReservationCoverage(UINT64 Base,UINT64 Bytes) {
 unsigned Mask=0;
 if(!Bytes || Bytes-1>MAX_UINT64-Base)return 0;
 for(unsigned I=0;I<2;I++) {
  UINT64 Page=GZR_BASE+(UINT64)I*4096;
  if(Page>=Base && Bytes>=4096 && Page-Base<=Bytes-4096)Mask|=1u<<I;
 }
 return Mask;
}
STATIC unsigned GpuZapReservationAllocatedType(UINT32 Type) {
 return Type==EfiLoaderCode || Type==EfiLoaderData || Type==EfiBootServicesCode ||
  Type==EfiBootServicesData || Type==EfiRuntimeServicesCode || Type==EfiRuntimeServicesData ||
  Type==EfiACPIReclaimMemory || Type==EfiACPIMemoryNVS || Type==EfiPalCode;
}
STATIC unsigned GpuZapReservationDescriptorReason(CONST EFI_MEMORY_DESCRIPTOR *D) {
 unsigned Reason=0;
 // OEM/OS-reserved type numbers are permitted by this firmware's UEFI header,
 // but are conservatively non-conventional and not classified as allocations.
 if(D->Type>=EfiMaxMemoryType && D->Type<0x70000000u)Reason|=1;
 if((D->PhysicalStart&4095) || (D->VirtualStart&4095))Reason|=2;
 if(!D->NumberOfPages || D->NumberOfPages>(MAX_UINT64>>12) ||
  (D->NumberOfPages && D->NumberOfPages-1>((MAX_UINT64-D->PhysicalStart)>>12)) ||
  (D->VirtualStart && D->NumberOfPages && D->NumberOfPages-1>((MAX_UINT64-D->VirtualStart)>>12)))Reason|=4;
 return Reason;
}

// Return zero only for a complete, internally consistent *observation*. A
// conventional/free observation is NOT a reservation and does not authorize a
// later load/write. The caller must separately acquire/prove the resource and
// authenticate firmware. All returned raw metadata is retained even on error.
STATIC unsigned GpuZapReservationCapture(unsigned Unsafe,unsigned SqeEnabled,unsigned StoreCalls) {
 struct gzr_result *R=&mZapReservation;
 if(R->started)return GZR_REUSED;
 ZeroMem(R,sizeof(*R));R->started=1;
 R->unsafe=Unsafe;R->sqe_enabled=SqeEnabled;R->store_calls=StoreCalls;
 R->map_status=EFI_NOT_READY;
 for(unsigned I=0;I<2;I++)R->gcd[I].status=EFI_NOT_READY;
 if(Unsafe || SqeEnabled || StoreCalls)return R->code=GZR_GATE;
 if(!gBS || !gDS || !gBS->GetMemoryMap || !gDS->GetMemorySpaceDescriptor)return R->code=GZR_SERVICES;

 // Single bounded map request. No query/allocate/retry cycle; a larger map is
 // explicitly unknown and its required size and all other outputs survive.
 SetMem(mZapReservationMap.bytes,sizeof(mZapReservationMap.bytes),0xa5);
 R->map_bytes=sizeof(mZapReservationMap.bytes);
 R->map_key=MAX_UINTN;R->descriptor_bytes=MAX_UINTN;R->descriptor_version=0xffffffffu;
 R->map_attempted=1;
 R->map_status=gBS->GetMemoryMap(&R->map_bytes,(EFI_MEMORY_DESCRIPTOR *)mZapReservationMap.bytes,
  &R->map_key,&R->descriptor_bytes,&R->descriptor_version);
 if(R->map_status!=EFI_SUCCESS)R->code|=GZR_MAP_STATUS;
 else if(!R->map_bytes || R->map_bytes>sizeof(mZapReservationMap.bytes) ||
  R->descriptor_bytes<sizeof(EFI_MEMORY_DESCRIPTOR) || (R->descriptor_bytes&7) ||
  R->descriptor_bytes>R->map_bytes || R->map_bytes%R->descriptor_bytes ||
  R->descriptor_version!=EFI_MEMORY_DESCRIPTOR_VERSION)R->code|=GZR_MAP_METADATA;
 else {
  R->map_metadata_valid=1;R->descriptors=R->map_bytes/R->descriptor_bytes;
  for(UINTN I=0;I<R->descriptors;I++) {
   EFI_MEMORY_DESCRIPTOR D;
   CopyMem(&D,mZapReservationMap.bytes+I*R->descriptor_bytes,sizeof(D));
   unsigned Reason=GpuZapReservationDescriptorReason(&D),Coverage=0;
   if(Reason) {R->invalid_descriptors++;R->code|=GZR_MAP_DESCRIPTOR;}
   else Coverage=GpuZapReservationCoverage(D.PhysicalStart,D.NumberOfPages<<12);
   if(Reason || Coverage) {
    R->candidate_records++;
    if(R->record_count<GZR_RECORDS) {
     struct gzr_map_record *Record=&R->records[R->record_count++];
     Record->raw=D;Record->index=I;Record->reason=Reason;
     Record->valid=!Reason;Record->coverage=Coverage;
    }
   }
   if(!Reason && Coverage) {
    R->duplicate_coverage|=R->coverage&Coverage;R->coverage|=Coverage;
    R->allocation_overlap|=GpuZapReservationAllocatedType(D.Type);
    R->allocation_unknown_type|=D.Type>=EfiMaxMemoryType;
    R->nonconventional_overlap|=D.Type!=EfiConventionalMemory;
   }
  }
  if(R->coverage!=3)R->code|=GZR_MAP_COVERAGE;
  if(R->duplicate_coverage)R->code|=GZR_MAP_OVERLAP;
  R->map_valid=!(R->code&(GZR_MAP_STATUS|GZR_MAP_METADATA|GZR_MAP_DESCRIPTOR|GZR_MAP_COVERAGE|GZR_MAP_OVERLAP));
  R->nonconventional_known=R->map_valid;
  R->allocation_known=R->map_valid && !R->allocation_unknown_type;
 }
 for(unsigned I=0;I<2;I++) {
  struct gzr_gcd_record *G=&R->gcd[I];
  // Keep error output distinguishable from legitimate zero fields. Values
  // returned on an error are printed raw but never treated as descriptors.
  SetMem(&G->raw,sizeof(G->raw),0xa5);G->attempted=1;
  G->status=gDS->GetMemorySpaceDescriptor(GZR_BASE+(UINT64)I*4096,&G->raw);
  if(G->status!=EFI_SUCCESS)R->code|=GZR_GCD_STATUS;
  else {
   unsigned Coverage=GpuZapReservationCoverage(G->raw.BaseAddress,G->raw.Length);
   G->covers_page=!!(Coverage&(1u<<I));
   G->valid=(UINT32)G->raw.GcdMemoryType<EfiGcdMemoryTypeMaximum && G->covers_page;
   if(!G->valid)R->code|=GZR_GCD_DESCRIPTOR;
   else G->allocated=G->raw.ImageHandle!=NULL;
  }
 }
 R->gcd_allocation_known=R->gcd[0].valid && R->gcd[1].valid;
 R->gcd_allocation_overlap=R->gcd[0].allocated || R->gcd[1].allocated;
 return R->code;
}

// The integrator invokes this only while filesystem/console use is safe. No
// live memory-map or target-memory reads occur here; all data is the snapshot.
STATIC VOID GpuZapReservationReport(VOID) {
 CONST struct gzr_result *R=&mZapReservation;if(!R->started)return;
 Print(L"HOUJI GPU ZAP RESERVATION: fixed-PA=%lx bytes=%lx code=%x unsafe=%u SQE=%u store-calls=%u; observation-only PAS-owned=UNKNOWN no-target-memory-access no-allocation\n",
  (UINT64)GZR_BASE,(UINT64)GZR_BYTES,R->code,R->unsafe,R->sqe_enabled,R->store_calls);
 Print(L"HOUJI GPU ZAP EFI MAP: attempted=%u status=%r returned-bytes=%lu capacity=%u key=%lx descriptor-bytes=%lu version=%u metadata-valid=%u map-valid=%u descriptors=%lu invalid=%lu coverage=%x duplicate=%x allocation-known=%u allocation-overlap=%u nonconventional-known=%u nonconventional-overlap=%u records=%lu stored=%lu\n",
  R->map_attempted,R->map_status,(UINT64)R->map_bytes,GZR_MAP_BYTES,(UINT64)R->map_key,
  (UINT64)R->descriptor_bytes,R->descriptor_version,R->map_metadata_valid,R->map_valid,
  (UINT64)R->descriptors,(UINT64)R->invalid_descriptors,R->coverage,R->duplicate_coverage,
  R->allocation_known,R->allocation_overlap,R->nonconventional_known,R->nonconventional_overlap,
  (UINT64)R->candidate_records,(UINT64)R->record_count);
 for(UINTN I=0;I<R->record_count;I++) {
  CONST struct gzr_map_record *M=&R->records[I];
  Print(L"HOUJI GPU ZAP EFI RAW: index=%lu valid=%u reason=%x coverage=%x type=%u physical=%lx virtual=%lx pages=%lx attributes=%lx\n",
   (UINT64)M->index,M->valid,M->reason,M->coverage,M->raw.Type,M->raw.PhysicalStart,
   M->raw.VirtualStart,M->raw.NumberOfPages,M->raw.Attribute);
 }
 for(unsigned I=0;I<2;I++) {
  CONST struct gzr_gcd_record *G=&R->gcd[I];
  Print(L"HOUJI GPU ZAP GCD RAW: page=%u attempted=%u status=%r valid=%u covers-page=%u type=%u base=%lx bytes=%lx attributes=%lx capabilities=%lx image=%lx device=%lx allocated=%u; allocation-known=%u\n",
   I,G->attempted,G->status,G->valid,G->covers_page,(UINT32)G->raw.GcdMemoryType,G->raw.BaseAddress,
   G->raw.Length,G->raw.Attributes,G->raw.Capabilities,(UINT64)(UINTN)G->raw.ImageHandle,
   (UINT64)(UINTN)G->raw.DeviceHandle,G->allocated,G->valid);
 }
 Print(L"HOUJI GPU ZAP GCD ALLOCATION: known=%u overlap=%u; EFI attributes are descriptor capabilities, GCD attributes are current; neither establishes secure-world PAS ownership or a reservation lease\n",
  R->gcd_allocation_known,R->gcd_allocation_overlap);
}
#endif
