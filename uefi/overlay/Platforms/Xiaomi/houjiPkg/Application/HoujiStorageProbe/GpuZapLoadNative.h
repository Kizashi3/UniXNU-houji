/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Native adapter for the fixed signed PAS13 image. Preparation alone may use
 * EFI memory services, at TPL_APPLICATION before SQE/store attempts. Runtime
 * callbacks use the retained proof, CPU AT (not target loads), fixed stores,
 * and the existing real SCM transport. They never print or use a filesystem.
 * No GPU mode/PM4/TRUST write or PAS shutdown is provided by this adapter.
 */
#ifndef HOUJI_GPU_ZAP_LOAD_NATIVE_H
#define HOUJI_GPU_ZAP_LOAD_NATIVE_H
#include "GpuZapLoad.h"
#include "GpuZapReservationNative.h"
struct hzl_native_owner {
 VOID *cookie;
 // Exactly 1, from current boot/owner: pre-SQE during Prepare; later the
 // real retained GX/OOB/context/root/fault guards plus fresh CP/GX idle.
 int (*guard)(VOID *,unsigned phase);
};
enum { HZN_OK,HZN_ARGUMENT,HZN_ALREADY_PREPARED,HZN_OWNER,HZN_RESERVATION,
 HZN_ALLOCATE,HZN_METADATA_GCD,HZN_METADATA_ATTRIBUTES,HZN_TRANSLATION,HZN_NOT_PREPARED };
STATIC struct hzl_result mZapLoad;
STATIC struct {
 unsigned prepare_started,prepare_code,prepare_phase,ready,running,run_code;
 unsigned allocation_attempted,metadata_allocated,metadata_retained,metadata_gcd_attempted,metadata_gcd_valid,attributes_attempted;
 unsigned reservation_valid,reservation_code,derived_cache_profile,target_access_closed,target_copy_started,target_copy_completed;
 unsigned at_calls,at_phase,target_at_phase,metadata_at_valid,target_at_valid,native_calls,pending,pending_phase,rejected;
 // target_cache is the expected CPU PAR profile, not a rewritten GCD value.
 UINT64 metadata_original_attributes,target_cache[2],metadata_par[2],target_par[2][2],last_el,last_tcr;
 UINT64 elapsed,total_elapsed,call_elapsed[3],resume_cookie,counter_frequency;
 EFI_STATUS allocation_status,metadata_gcd_status,attribute_status;
 EFI_PHYSICAL_ADDRESS metadata_physical;
 EFI_GCD_MEMORY_SPACE_DESCRIPTOR metadata_gcd;
 struct hzl_config config;
 struct hzl_native_owner owner;
 struct ggs_regs last_input,last_output;
} mZapLoadNative;

// Hardware leaf: translation instructions only, with PAR and DAIF preserved.
// No speculative/deliberate data load from either translated page is used.
STATIC int ZapLoadNativeAtPage(UINT64 Physical,UINT64 *ReadPar,UINT64 *WritePar) {
 UINT64 El,Tcr,SavedPar,SavedDaif;
 __asm__ volatile("mrs %0,CurrentEL":"=r"(El));
 mZapLoadNative.last_el=El;if(El!=4)return 1;
 __asm__ volatile("mrs %0,tcr_el1":"=r"(Tcr));mZapLoadNative.last_tcr=Tcr;
 if((Physical&4095) || Physical>0x0000fffffffff000ULL ||
  (Tcr&(3ULL<<14)) || (Tcr&(1ULL<<7)) || (Tcr&63)<16 || (Tcr&63)>32)return 1;
 __asm__ volatile("mrs %0,daif\n\tmrs %1,par_el1\n\tmsr daifset,#0xf":"=r"(SavedDaif),"=r"(SavedPar)::"memory");
 __asm__ volatile("at s1e1r,%1\n\tisb\n\tmrs %0,par_el1":"=r"(*ReadPar):"r"(Physical):"memory");
 __asm__ volatile("at s1e1w,%1\n\tisb\n\tmrs %0,par_el1":"=r"(*WritePar):"r"(Physical):"memory");
 __asm__ volatile("msr par_el1,%0\n\tmsr daif,%1\n\tisb"::"r"(SavedPar),"r"(SavedDaif):"memory");
 return 0;
}
STATIC VOID ZapLoadNativeBarrier(VOID) {__asm__ volatile("dsb sy":::"memory");}
STATIC VOID *ZapLoadNativeCpuPointer(UINT64 Physical) {return (VOID *)(UINTN)Physical;}
STATIC UINT64 ZapLoadNativeFrequency(VOID) {
 UINT64 Frequency;__asm__ volatile("mrs %0,cntfrq_el0":"=r"(Frequency));return Frequency;
}
STATIC VOID ZapLoadNativeStoreByte(UINT64 Address,UINT8 Value) {
 *((volatile UINT8 *)(UINTN)Address)=Value;
}
STATIC int ZapLoadNativeParValid(UINT64 Par,UINT64 Physical,UINT64 Cache) {
 if((Par&1) || (Par&0x0000fffffffff000ULL)!=Physical)return 0;
 UINT64 Attr=Par>>56;
 return Cache==EFI_MEMORY_WC?Attr==0x44:Cache==EFI_MEMORY_UC?(Attr==0 || Attr==4):0;
}
STATIC int ZapLoadNativeTranslations(unsigned Phase,unsigned Target) {
 mZapLoadNative.at_phase=Phase;mZapLoadNative.metadata_at_valid=0;
 ++mZapLoadNative.at_calls;
 if(ZapLoadNativeAtPage(mZapLoadNative.metadata_physical,&mZapLoadNative.metadata_par[0],
   &mZapLoadNative.metadata_par[1]) ||
  !ZapLoadNativeParValid(mZapLoadNative.metadata_par[0],mZapLoadNative.metadata_physical,EFI_MEMORY_WC) ||
  !ZapLoadNativeParValid(mZapLoadNative.metadata_par[1],mZapLoadNative.metadata_physical,EFI_MEMORY_WC))return 1;
 mZapLoadNative.metadata_at_valid=1;
 if(!Target)return 0;
 if(mZapLoadNative.target_access_closed)return 1;
 mZapLoadNative.target_at_valid=0;mZapLoadNative.target_at_phase=Phase;
 for(unsigned I=0;I<2;I++) {
  UINT64 Physical=HZL_RESERVATION_BASE+(UINT64)I*4096;++mZapLoadNative.at_calls;
  if(ZapLoadNativeAtPage(Physical,&mZapLoadNative.target_par[I][0],&mZapLoadNative.target_par[I][1]) ||
   !ZapLoadNativeParValid(mZapLoadNative.target_par[I][0],Physical,mZapLoadNative.target_cache[I]) ||
   !ZapLoadNativeParValid(mZapLoadNative.target_par[I][1],Physical,mZapLoadNative.target_cache[I]))return 1;
  mZapLoadNative.target_at_valid|=1u<<I;
 }
 return 0;
}
STATIC int ZapLoadNativeReservation(VOID) {
 CONST struct gzr_result *R=&mZapReservation;
 if(!R->started || R->code || R->unsafe || R->sqe_enabled || R->store_calls ||
  !R->map_valid || R->coverage!=3 || R->duplicate_coverage || !R->allocation_known ||
  R->allocation_overlap || !R->gcd_allocation_known || R->gcd_allocation_overlap ||
  R->record_count!=R->candidate_records)return 1;
 unsigned Coverage=0;
 for(UINTN I=0;I<R->record_count;I++) {
  CONST struct gzr_map_record *M=&R->records[I];
  if(!M->valid || M->reason || !M->coverage || M->raw.Type!=EfiReservedMemoryType)return 1;
  Coverage|=M->coverage;
 }
 if(Coverage!=3)return 1;
 for(unsigned I=0;I<2;I++) {
  CONST struct gzr_gcd_record *G=&R->gcd[I];
  CONST UINT64 CacheMask=EFI_MEMORY_UC|EFI_MEMORY_WC|EFI_MEMORY_WT|EFI_MEMORY_WB|EFI_MEMORY_UCE;
  UINT64 Cache=G->raw.Attributes&CacheMask;
  if(!G->valid || !G->covers_page || G->raw.GcdMemoryType!=EfiGcdMemoryTypeReserved ||
   G->raw.ImageHandle || G->raw.DeviceHandle ||
   (G->raw.Attributes&(EFI_MEMORY_RP|EFI_MEMORY_RO)))return 1;
  if(!Cache) {
   // This single fixed source profile is not permission to treat arbitrary
   // cacheAttrs=0 as writable. houji MemoryMapLib.c:17 gives PIL ResourceAttr
   // 0x400 -> GCD cache capabilities UC (Gcd.c:82). Its arm alias is NormalNC
   // (MemoryMapLib.h:106, ArmMmuLibCore.c:111), converted to CPU WC (Mmu.c:76).
   // CpuMmuCommon.c:153,185 adds protection caps but intersects WC&UC -> 0.
   // Keep every raw field unchanged and require actual R/W PAR=0x44 later.
   if((G->raw.Capabilities&CacheMask)!=EFI_MEMORY_UC ||
    G->raw.BaseAddress<0x8bc00000ULL || G->raw.BaseAddress>=0xa2b80000ULL ||
    G->raw.Length>0xa2b80000ULL-G->raw.BaseAddress)return 1;
   Cache=EFI_MEMORY_WC;mZapLoadNative.derived_cache_profile|=1u<<I;
  } else if(Cache!=EFI_MEMORY_UC && Cache!=EFI_MEMORY_WC)return 1;
  mZapLoadNative.target_cache[I]=Cache;
 }
 return 0;
}

// Single preparation, including its own current-boot reservation snapshot.
// Root must not separately consume the one-shot observer immediately before
// this call. A failed/ambiguous preparation never frees or restores pages.
STATIC unsigned ZapLoadNativePrepare(CONST struct hzl_native_owner *Owner,
 unsigned Unsafe,unsigned SqeEnabled,unsigned StoreCalls) {
 if(mZapLoadNative.prepare_started)return HZN_ALREADY_PREPARED;
 mZapLoadNative.prepare_started=1;mZapLoadNative.prepare_phase=1;
 mZapLoadNative.allocation_status=mZapLoadNative.metadata_gcd_status=
  mZapLoadNative.attribute_status=EFI_NOT_READY;
 if(!Owner || !Owner->guard || Unsafe || SqeEnabled || StoreCalls || !gBS || !gDS ||
  !gBS->AllocatePages || !gDS->GetMemorySpaceDescriptor || !gDS->SetMemorySpaceAttributes)
  return mZapLoadNative.prepare_code=HZN_ARGUMENT;
 mZapLoadNative.counter_frequency=ZapLoadNativeFrequency();
 if(!mZapLoadNative.counter_frequency || mZapLoadNative.counter_frequency>1000000000ULL)
  return mZapLoadNative.prepare_code=HZN_ARGUMENT;
 mZapLoadNative.owner=*Owner;
 if(Owner->guard(Owner->cookie,HZL_PHASE_QUALIFY)!=1)return mZapLoadNative.prepare_code=HZN_OWNER;
 mZapLoadNative.reservation_code=GpuZapReservationCapture(Unsafe,SqeEnabled,StoreCalls);
 if(mZapLoadNative.reservation_code || ZapLoadNativeReservation())
  return mZapLoadNative.prepare_code=HZN_RESERVATION;
 mZapLoadNative.reservation_valid=1;mZapLoadNative.prepare_phase=2;
 if(Owner->guard(Owner->cookie,HZL_PHASE_QUALIFY)!=1)return mZapLoadNative.prepare_code=HZN_OWNER;
 mZapLoadNative.metadata_physical=0xffffffffULL;mZapLoadNative.allocation_attempted=1;
 mZapLoadNative.allocation_status=gBS->AllocatePages(AllocateMaxAddress,EfiBootServicesData,1,
  &mZapLoadNative.metadata_physical);
 if(mZapLoadNative.allocation_status!=EFI_SUCCESS)return mZapLoadNative.prepare_code=HZN_ALLOCATE;
 mZapLoadNative.metadata_allocated=mZapLoadNative.metadata_retained=1;
 UINT64 Physical=mZapLoadNative.metadata_physical;
 if(!Physical || (Physical&4095) || Physical>0xfffff000ULL ||
  hzl_overlap(Physical,4096,HZL_RESERVATION_BASE,HZL_RESERVATION_BYTES))
  return mZapLoadNative.prepare_code=HZN_ALLOCATE;
 mZapLoadNative.config=(struct hzl_config){ZapLoadNativeCpuPointer(Physical),Physical,4096,
  HZL_RESERVATION_BASE,HZL_RESERVATION_BYTES};
 if(!hzl_config_valid(&mZapLoadNative.config))return mZapLoadNative.prepare_code=HZN_ALLOCATE;
 mZapLoadNative.prepare_phase=3;
 SetMem(&mZapLoadNative.metadata_gcd,sizeof(mZapLoadNative.metadata_gcd),0xa5);
 mZapLoadNative.metadata_gcd_attempted=1;
 mZapLoadNative.metadata_gcd_status=gDS->GetMemorySpaceDescriptor(Physical,&mZapLoadNative.metadata_gcd);
 CONST EFI_GCD_MEMORY_SPACE_DESCRIPTOR *D=&mZapLoadNative.metadata_gcd;
 if(mZapLoadNative.metadata_gcd_status!=EFI_SUCCESS || D->GcdMemoryType!=EfiGcdMemoryTypeSystemMemory ||
  Physical<D->BaseAddress || D->Length<4096 || Physical-D->BaseAddress>D->Length-4096 ||
  D->Length-1>MAX_UINT64-D->BaseAddress || !(D->Capabilities&EFI_MEMORY_WC) ||
  (D->Attributes&(EFI_MEMORY_UC|EFI_MEMORY_WC|EFI_MEMORY_WT|EFI_MEMORY_WB|EFI_MEMORY_UCE))!=EFI_MEMORY_WB ||
  (D->Attributes&(EFI_MEMORY_RP|EFI_MEMORY_RO)))return mZapLoadNative.prepare_code=HZN_METADATA_GCD;
 mZapLoadNative.metadata_gcd_valid=1;mZapLoadNative.metadata_original_attributes=D->Attributes;
 if(Owner->guard(Owner->cookie,HZL_PHASE_QUALIFY)!=1)return mZapLoadNative.prepare_code=HZN_OWNER;
 mZapLoadNative.prepare_phase=4;mZapLoadNative.attributes_attempted=1;
 mZapLoadNative.attribute_status=gDS->SetMemorySpaceAttributes(Physical,4096,
  (D->Attributes&~(EFI_MEMORY_UC|EFI_MEMORY_WC|EFI_MEMORY_WT|EFI_MEMORY_WB|EFI_MEMORY_UCE))|EFI_MEMORY_WC);
 if(mZapLoadNative.attribute_status!=EFI_SUCCESS)return mZapLoadNative.prepare_code=HZN_METADATA_ATTRIBUTES;
 mZapLoadNative.prepare_phase=5;
 if(ZapLoadNativeTranslations(HZL_PHASE_QUALIFY,1))return mZapLoadNative.prepare_code=HZN_TRANSLATION;
 if(Owner->guard(Owner->cookie,HZL_PHASE_QUALIFY)!=1)return mZapLoadNative.prepare_code=HZN_OWNER;
 mZapLoadNative.ready=1;mZapLoadNative.prepare_phase=6;
 return mZapLoadNative.prepare_code=HZN_OK;
}

STATIC int ZapLoadNativeGuard(VOID *Cookie,unsigned Phase) {
 (VOID)Cookie;
 if(!mZapLoadNative.running || !mZapLoadNative.ready || mZapLoadNative.prepare_code ||
  !mZapLoadNative.reservation_valid || !mZapLoadNative.metadata_allocated ||
  !mZapLoadNative.metadata_retained || !mZapLoadNative.owner.guard ||
  Phase<HZL_PHASE_QUALIFY || Phase>HZL_PHASE_DONE || Phase!=mZapLoad.phase ||
  !hzl_config_valid(&mZapLoadNative.config) ||
  mZapLoadNative.config.metadata_physical!=mZapLoadNative.metadata_physical ||
  mZapLoadNative.config.metadata_cpu!=ZapLoadNativeCpuPointer(mZapLoadNative.metadata_physical) ||
  mZapLoadNative.owner.guard(mZapLoadNative.owner.cookie,Phase)!=1)return 0;
 if(Phase>=HZL_PHASE_AUTH && (!mZapLoadNative.target_access_closed ||
  !mZapLoadNative.target_copy_completed || !mZapLoad.segment_published))return 0;
 if(mZapLoadNative.target_access_closed && Phase<HZL_PHASE_COPY)return 0;
 return ZapLoadNativeTranslations(Phase,!mZapLoadNative.target_access_closed)?0:1;
}
STATIC int ZapLoadNativePublish(VOID *Cookie,VOID *Cpu,uint64_t Physical,unsigned Bytes) {
 (VOID)Cookie;
 if(mZapLoad.phase!=HZL_PHASE_PUBLISH || !mZapLoad.metadata_copied ||
  Cpu!=mZapLoadNative.config.metadata_cpu || Physical!=mZapLoadNative.metadata_physical ||
  Bytes!=HZL_METADATA_BYTES || ZapLoadNativeGuard(NULL,HZL_PHASE_PUBLISH)!=1)return 1;
 // Owned Normal-NC metadata needs store completion, not a cache flush that
 // accesses the reserved image range. It stays pinned through reset.
 ZapLoadNativeBarrier();return 0;
}
STATIC int ZapLoadNativeCopy(VOID *Cookie,uint64_t Destination,CONST uint8_t *Source,unsigned Bytes) {
 (VOID)Cookie;
 if(mZapLoad.phase!=HZL_PHASE_COPY || !mZapLoad.init_succeeded || !mZapLoad.mem_setup_succeeded ||
  !mZapLoad.segment_copy_attempted || mZapLoadNative.target_copy_started ||
  mZapLoadNative.target_access_closed || Destination!=HZL_RESERVATION_BASE ||
  Source!=mHoujiZapSegment || Bytes!=HZL_SEGMENT_BYTES ||
  ZapLoadNativeGuard(NULL,HZL_PHASE_COPY)!=1)return 1;
 // Retire authority before the first potentially partial store. This is only
 // software authority; no hardware CPU mapping/revoke claim is made.
 mZapLoadNative.target_copy_started=1;mZapLoadNative.target_access_closed=1;
 for(unsigned I=0;I<HZL_SEGMENT_BYTES;I++)ZapLoadNativeStoreByte(Destination+I,Source[I]);
 ZapLoadNativeBarrier();mZapLoadNative.target_copy_completed=1;return 0;
}
STATIC int ZapLoadNativeFrameAllowed(CONST struct ggs_regs *R) {
 if(!R || !mZapLoadNative.running || !mZapLoad.started)return 0;
 struct ggs_regs E={{0}};
 if(mZapLoad.phase==HZL_PHASE_INIT && mZapLoad.init_attempted && mZapLoad.metadata_published)
  E=(struct ggs_regs){{0x42000201,0x82,13,mZapLoadNative.metadata_physical,0,0,0,0}};
 else if(mZapLoad.phase==HZL_PHASE_MEM_SETUP && mZapLoad.init_succeeded && mZapLoad.mem_setup_attempted)
  E=(struct ggs_regs){{0x42000202,3,13,HZL_RESERVATION_BASE,HZL_LOAD_SPAN,0,0,0}};
 else if(mZapLoad.phase==HZL_PHASE_AUTH && mZapLoad.auth_attempted && mZapLoad.segment_published &&
  mZapLoadNative.target_access_closed && mZapLoadNative.target_copy_completed)
  E=(struct ggs_regs){{0x42000205,1,13,0,0,0,0,0}};
 else return 0;
 if(mZapLoadNative.pending) {
  if(mZapLoadNative.pending_phase!=mZapLoad.phase || R->x[0]!=1 || R->x[6]!=mZapLoadNative.resume_cookie)return 0;
 } else if(R->x[0]!=E.x[0] || R->x[6])return 0;
 for(unsigned I=1;I<8;I++)if(I!=6 && R->x[I]!=E.x[I])return 0;
 return 1;
}
STATIC int ZapLoadNativeCall(VOID *Cookie,struct ggs_regs *R) {
 (VOID)Cookie;
 if(ZapLoadNativeGuard(NULL,mZapLoad.phase)!=1){mZapLoadNative.rejected=1;return 1;}
 if(!ZapLoadNativeFrameAllowed(R)){mZapLoadNative.rejected=2;return 1;}
 mZapLoadNative.last_input=*R;++mZapLoadNative.native_calls;
 unsigned Index=mZapLoad.phase==HZL_PHASE_INIT?0:mZapLoad.phase==HZL_PHASE_MEM_SETUP?1:2;
#ifdef HOUJI_CALL_TRACE
 HOUJI_CALL_TRACE(0x7200u+mZapLoad.phase,R->x[0],R->x[3]);
#endif
 UINT64 Begin=BatchCounter();int Code=ggs_aarch64_call(NULL,R);UINT64 Elapsed=BatchMicroseconds(Begin);
#ifdef HOUJI_CALL_TRACE
 HOUJI_CALL_TRACE(0x7210u+mZapLoad.phase,R->x[0],R->x[1]);
#endif
 mZapLoadNative.elapsed+=Elapsed;mZapLoadNative.call_elapsed[Index]+=Elapsed;
 mZapLoadNative.last_output=*R;mZapLoadNative.pending=!Code && R->x[0]==1;
 mZapLoadNative.pending_phase=mZapLoadNative.pending?mZapLoad.phase:0;
 mZapLoadNative.resume_cookie=mZapLoadNative.pending?R->x[6]:0;
 if(ZapLoadNativeGuard(NULL,mZapLoad.phase)!=1){mZapLoadNative.rejected=3;return Code?Code:1;}
 return Code;
}
STATIC int ZapLoadNativeDelay(VOID *Cookie,unsigned Ms) {
 (VOID)Cookie;
 if(Ms!=GGS_BUSY_DELAY_MS || ZapLoadNativeGuard(NULL,mZapLoad.phase)!=1)return 1;
 UINT64 Frequency=mZapLoadNative.counter_frequency;
 if(!Frequency || Frequency>1000000000ULL)return 1;
 UINT64 Begin=BatchCounter(),Ticks=(Frequency*Ms+999)/1000;unsigned Complete=0;
 // Architectural-counter delay without Stall/other boot services. The CPU
 // iteration cap also fails closed if the counter unexpectedly stops.
 for(unsigned I=0;I<16000000u;I++)if(BatchCounter()-Begin>=Ticks){Complete=1;break;}
 return !Complete || ZapLoadNativeGuard(NULL,mZapLoad.phase)!=1?1:0;
}
STATIC unsigned RunZapLoadNative(CONST struct ggs_state *Qualified,CONST struct hpp_result *Capabilities) {
 if(!mZapLoadNative.ready || mZapLoadNative.prepare_code)return HZN_NOT_PREPARED;
 if(mZapLoad.started)return HZL_ALREADY_STARTED;
 CONST struct hzl_io Io={NULL,ZapLoadNativeGuard,ZapLoadNativePublish,ZapLoadNativeCopy,
  ZapLoadNativeCall,ZapLoadNativeDelay};
 mZapLoadNative.running=1;UINT64 Begin=BatchCounter();
 unsigned Code=hzl_run(&Io,&mZapLoadNative.config,Qualified,Capabilities,&mZapLoad);
 mZapLoadNative.total_elapsed=BatchMicroseconds(Begin);mZapLoadNative.running=0;
 mZapLoadNative.run_code=Code;return Code;
}
STATIC VOID ZapLoadNativeReport(VOID) {
 if(mZapLoadNative.running || !mZapLoadNative.prepare_started)return;
 GpuZapReservationReport();
 Print(L"HOUJI GPU ZAP NATIVE: prepare-code=%u phase=%u ready=%u run-code=%u reservation-valid=%u reservation-code=%x derived-PIL-NC-mask=%x metadata-allocated=%u retained=%u PA=%lx original-attrs=%lx allocate-status=%r gcd-status=%r NC-attempted=%u NC-status=%r; fixed signed PAS13, derived mask is CPU PAR expectation only, raw GCD unchanged, no mode packet or PAS shutdown\n",
  mZapLoadNative.prepare_code,mZapLoadNative.prepare_phase,mZapLoadNative.ready,mZapLoadNative.run_code,
  mZapLoadNative.reservation_valid,mZapLoadNative.reservation_code,mZapLoadNative.derived_cache_profile,mZapLoadNative.metadata_allocated,
  mZapLoadNative.metadata_retained,mZapLoadNative.metadata_physical,mZapLoadNative.metadata_original_attributes,
  mZapLoadNative.allocation_status,mZapLoadNative.metadata_gcd_status,mZapLoadNative.attributes_attempted,mZapLoadNative.attribute_status);
 Print(L"HOUJI GPU ZAP METADATA GCD RAW: attempted=%u status=%r accepted=%u type=%u base=%lx bytes=%lx attributes=%lx capabilities=%lx image=%lx device=%lx; error output is raw and not an ownership proof\n",
  mZapLoadNative.metadata_gcd_attempted,mZapLoadNative.metadata_gcd_status,
  mZapLoadNative.metadata_gcd_valid,(UINT32)mZapLoadNative.metadata_gcd.GcdMemoryType,
  mZapLoadNative.metadata_gcd.BaseAddress,mZapLoadNative.metadata_gcd.Length,
  mZapLoadNative.metadata_gcd.Attributes,mZapLoadNative.metadata_gcd.Capabilities,
  (UINT64)(UINTN)mZapLoadNative.metadata_gcd.ImageHandle,(UINT64)(UINTN)mZapLoadNative.metadata_gcd.DeviceHandle);
 Print(L"HOUJI GPU ZAP AT: calls=%u last-phase=%u EL=%lx TCR=%lx metadata-valid=%u R=%lx W=%lx target-last-phase=%u target-valid=%x target0-R=%lx W=%lx target1-R=%lx W=%lx; target observations latched before software access close, translation only, no reserved-memory readback\n",
  mZapLoadNative.at_calls,mZapLoadNative.at_phase,mZapLoadNative.last_el,mZapLoadNative.last_tcr,
  mZapLoadNative.metadata_at_valid,mZapLoadNative.metadata_par[0],mZapLoadNative.metadata_par[1],
  mZapLoadNative.target_at_phase,mZapLoadNative.target_at_valid,mZapLoadNative.target_par[0][0],mZapLoadNative.target_par[0][1],
  mZapLoadNative.target_par[1][0],mZapLoadNative.target_par[1][1]);
 Print(L"HOUJI GPU ZAP LOAD: started=%u code=%u phase=%u retained=%u metadata-copy=%u published=%u init-attempt=%u success=%u mem-attempt=%u success=%u segment-attempt=%u published=%u native-copy-started=%u completed=%u target-access-closed=%u auth-attempt=%u authenticated=%u callbacks=%u native-calls=%u guard-failed=%u rejected=%u pending=%u quarantined=%u smc-us=%lu total-us=%lu; target-access-closed is software policy, not hardware revoke\n",
  mZapLoad.started,mZapLoad.code,mZapLoad.phase,mZapLoad.retained,mZapLoad.metadata_copied,
  mZapLoad.metadata_published,mZapLoad.init_attempted,mZapLoad.init_succeeded,mZapLoad.mem_setup_attempted,
  mZapLoad.mem_setup_succeeded,mZapLoad.segment_copy_attempted,mZapLoad.segment_published,
  mZapLoadNative.target_copy_started,mZapLoadNative.target_copy_completed,mZapLoadNative.target_access_closed,
  mZapLoad.auth_attempted,mZapLoad.authenticated,mZapLoad.actual_calls,mZapLoadNative.native_calls,
  mZapLoad.guard_failed,mZapLoadNative.rejected,mZapLoadNative.pending,mZapLoad.transport.quarantined,
  mZapLoadNative.elapsed,mZapLoadNative.total_elapsed);
 for(unsigned I=0;I<3;I++) {
  CONST struct hpp_observation *O=&mZapLoad.call[I];
  Print(L"HOUJI GPU ZAP PAS ROW: i=%u attempted=%u valid=%u callbacks=%u transport-code=%u response-present=%u response-transport=%d elapsed-us=%lu publish-code=%d copy-code=%d\n",
   I,O->attempted,O->valid,O->actual_calls,O->transport_code,O->response_present,O->response_transport,
   mZapLoadNative.call_elapsed[I],mZapLoad.publish_code,mZapLoad.copy_code);
  Print(L"HOUJI GPU ZAP PAS REQUEST: i=%u x0=%lx x1=%lx x2=%lx x3=%lx x4=%lx x5=%lx x6=%lx x7=%lx\n",
   I,O->request.x[0],O->request.x[1],O->request.x[2],O->request.x[3],O->request.x[4],O->request.x[5],O->request.x[6],O->request.x[7]);
  Print(L"HOUJI GPU ZAP PAS LAST INPUT: i=%u x0=%lx x1=%lx x2=%lx x3=%lx x4=%lx x5=%lx x6=%lx x7=%lx\n",
   I,O->last_input.x[0],O->last_input.x[1],O->last_input.x[2],O->last_input.x[3],O->last_input.x[4],O->last_input.x[5],O->last_input.x[6],O->last_input.x[7]);
  Print(L"HOUJI GPU ZAP PAS RESPONSE: i=%u valid=%u x0=%lx x1=%lx x2=%lx x3=%lx x4=%lx x5=%lx x6=%lx x7=%lx\n",
   I,O->valid,O->response.x[0],O->response.x[1],O->response.x[2],O->response.x[3],O->response.x[4],O->response.x[5],O->response.x[6],O->response.x[7]);
 }
}
#endif
