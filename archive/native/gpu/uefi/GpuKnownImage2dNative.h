/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Fixed A750 32x32 CP_BLIT binding, included after GpuHostRingNative.h.
 * Prepare is single-shot at application TPL before SQE. It uses the already
 * owned Normal-NC, unprivileged RW/NX class2 range; it never changes a table
 * or a permission. Runtime has no EFI, allocation, filesystem or generic
 * packet/address API. All seven pages remain retained through platform reset.
 */
#ifndef HOUJI_GPU_KNOWN_IMAGE_2D_NATIVE_H
#define HOUJI_GPU_KNOWN_IMAGE_2D_NATIVE_H
#include "GpuKnownImage2d.h"
struct hgki_native_owner {
 VOID *cookie;
 /* Zero is success. These bind the existing live GX/context/fault lease and
  * the existing bounded host-ring submit/idle path, not a second driver. */
 int (*guard)(VOID *,unsigned phase);
 int (*submit_fixed_ib)(VOID *,CONST uint32_t *,unsigned);
 int (*bounded_idle)(VOID *);
};
enum {HGKIN_OK,HGKIN_REUSED,HGKIN_STATE,HGKIN_TPL,HGKIN_OWNER,HGKIN_MEMORY,
 HGKIN_RANGE,HGKIN_TRANSLATION,HGKIN_VIRGIN,HGKIN_PUBLISH,HGKIN_NOT_PREPARED,
 HGKIN_QUALIFICATION,HGKIN_SUBMIT,HGKIN_IDLE,HGKIN_READBACK,HGKIN_VERIFY,HGKIN_ISOLATION};
STATIC struct hgki_result mKnownImage2d;
STATIC struct {
 unsigned prepare_started,prepare_phase,prepare_code,ready,retained,running,run_code;
 unsigned reserved_pages,published_pages,verified_pages,at_calls,at_failed,at_page;
 unsigned source_valid,source_crc,submit_calls,idle_calls,read_pages,rejected;
 unsigned tpl,table_valid,aperture_valid,initial_valid,kmd_preemption_disabled;
 UINT64 physical,table_physical,par[HGKI_PAGES][2];
 VOID *cpu,*tables;
 UINT32 published_crc[HGKI_PAGES];
 unsigned diagnostic_started,diagnostic_code,diagnostic_valid,diagnostic_pages;
 unsigned diagnostic_marker_mask,diagnostic_red_pixels,diagnostic_guards_intact;
 UINT32 diagnostic_marker[8],diagnostic_output_crc,diagnostic_reset,diagnostic_gx_ack,diagnostic_gbif_ack;
 struct hgki_native_owner owner;
} mKnownImage2dNative;
/* CPU-private snapshot, never a GPU destination. The output starts poisoned
 * in the actual NC arena; this buffer cannot fabricate a successful readback. */
STATIC UINT8 mKnownImage2dReadback[HGKI_BYTES];

#ifdef HGKI_NATIVE_HOST_TEST
STATIC int KnownImage2dAtPage(UINT64 Physical,UINT64 *ReadPar,UINT64 *WritePar);
STATIC VOID KnownImage2dBarrier(VOID);
#else
STATIC int KnownImage2dAtPage(UINT64 Physical,UINT64 *ReadPar,UINT64 *WritePar) {
 UINT64 El,Tcr,SavedDaif,SavedPar;
 __asm__ volatile("mrs %0,CurrentEL":"=r"(El));if(El!=4)return 1;
 __asm__ volatile("mrs %0,tcr_el1":"=r"(Tcr));
 if((Physical&4095) || Physical>0x0000fffffffff000ULL || (Tcr&(3ULL<<14)) ||
  (Tcr&(1ULL<<7)) || (Tcr&63)<16 || (Tcr&63)>32)return 1;
 __asm__ volatile("mrs %0,daif\n\tmrs %1,par_el1\n\tmsr daifset,#0xf"
  :"=r"(SavedDaif),"=r"(SavedPar)::"memory");
 __asm__ volatile("at s1e1r,%1\n\tisb\n\tmrs %0,par_el1":"=r"(*ReadPar):"r"(Physical):"memory");
 __asm__ volatile("at s1e1w,%1\n\tisb\n\tmrs %0,par_el1":"=r"(*WritePar):"r"(Physical):"memory");
 __asm__ volatile("msr par_el1,%0\n\tmsr daif,%1\n\tisb"::"r"(SavedPar),"r"(SavedDaif):"memory");
 return 0;
}
STATIC VOID KnownImage2dBarrier(VOID) {__asm__ volatile("dsb sy":::"memory");}
#endif
STATIC int KnownImage2dParValid(UINT64 Par,UINT64 Physical) {
 return !(Par&1) && (Par&0x0000fffffffff000ULL)==Physical && (Par>>56)==0x44;
}
STATIC int KnownImage2dTranslation(unsigned Page) {
 if(Page>=HGKI_PAGES)return 1;
 UINT64 Physical=mKnownImage2dNative.physical+HGKI_CLASS_CURSOR+(UINT64)Page*HGKI_PAGE;
 mKnownImage2dNative.at_page=Page;++mKnownImage2dNative.at_calls;
 if(KnownImage2dAtPage(Physical,&mKnownImage2dNative.par[Page][0],
   &mKnownImage2dNative.par[Page][1]) ||
  !KnownImage2dParValid(mKnownImage2dNative.par[Page][0],Physical) ||
  !KnownImage2dParValid(mKnownImage2dNative.par[Page][1],Physical)) {
  mKnownImage2dNative.at_failed=1;return 1;
 }
 return 0;
}
STATIC int KnownImage2dBindings(VOID) {
 CONST ArmSmmu4KRange *Range=&mScratchRanges[HSC_CLASSES+3];
 return !mGpuOnlyMemory.cpu || !mGpuOnlyMemory.physical || (mGpuOnlyMemory.physical&4095) ||
  mGpuOnlyMemory.physical>=(1ULL<<36) || HSC_POOL_BYTES>(1ULL<<36)-mGpuOnlyMemory.physical ||
  (UINTN)mGpuOnlyMemory.cpu>MAX_UINTN-HSC_POOL_BYTES ||
  mGpuOnlyMemory.pages!=HSC_POOL_PAGES || mGpuOnlyMemory.nc!=1 ||
  mGpuOnlyMemory.iova!=HSC_GPU_ONLY_IOVA || HSC_GPU_ONLY_IOVA+HGKI_CLASS_CURSOR!=HGKI_BASE ||
  2*HSC_CLASS_BYTES!=HGKI_CLASS_CURSOR || HGKI_BYTES>HSC_CLASS_BYTES ||
  HGKI_BASE+HGKI_BYTES>HGKI_CLASS_END || HGKI_CLASS_END!=HHR_RING ||
  Range->iova!=HGKI_BASE || Range->physical!=mGpuOnlyMemory.physical+HGKI_CLASS_CURSOR ||
  Range->bytes!=HSC_CLASS_BYTES || Range->permissions!=(ArmSmmu4KRead|ArmSmmu4KWrite) ||
  Range->writeback || Range->shareability!=3 || !mScratchTables ||
  !mScratchTablePhysical || mScratchBuilt.root_physical!=mScratchTablePhysical ||
  mScratchConfig.table_physical!=mScratchTablePhysical;
}
STATIC volatile UINT8 *KnownImage2dCpu(unsigned Page) {
 return (volatile UINT8 *)((UINTN)mKnownImage2dNative.cpu+HGKI_CLASS_CURSOR+(UINTN)Page*HGKI_PAGE);
}
STATIC int KnownImage2dPreparedBindings(VOID) {
 return KnownImage2dBindings() || mGpuOnlyMemory.physical!=mKnownImage2dNative.physical ||
  mGpuOnlyMemory.cpu!=mKnownImage2dNative.cpu || mScratchTables!=mKnownImage2dNative.tables ||
  mScratchTablePhysical!=mKnownImage2dNative.table_physical ||
  mGpuOnlyNext[2]!=HGKI_CLASS_CURSOR+HGKI_BYTES;
}
STATIC int KnownImage2dPrepareGuard(VOID) {
 return mHostRingUnsafe || mHostRing.enabled || mHostWriteCalls ||
  mHostRingPrepared || mHostRing.started || !mGpuSaveAllowed || HostPreparationGuard(NULL);
}
STATIC unsigned KnownImage2dNativePrepare(VOID) {
 if(mKnownImage2dNative.prepare_started)return HGKIN_REUSED;
 mKnownImage2dNative.prepare_started=1;mKnownImage2dNative.prepare_phase=1;
 if(KnownImage2dPrepareGuard())return mKnownImage2dNative.prepare_code=HGKIN_STATE;
 mKnownImage2dNative.tpl=LiveLogTpl(NULL);
 if(mKnownImage2dNative.tpl!=TPL_APPLICATION)return mKnownImage2dNative.prepare_code=HGKIN_TPL;
 if(KnownImage2dBindings() || mGpuOnlyNext[2]!=HGKI_CLASS_CURSOR)
  return mKnownImage2dNative.prepare_code=HGKIN_RANGE;
 if(FirmwareVerifyPages(mGpuOnlyMemory.physical,mGpuOnlyMemory.cpu,HSC_POOL_PAGES,1) || ScratchAudit())
  return mKnownImage2dNative.prepare_code=HGKIN_MEMORY;
 mKnownImage2dNative.table_valid=1;
 mKnownImage2dNative.physical=mGpuOnlyMemory.physical;mKnownImage2dNative.cpu=mGpuOnlyMemory.cpu;
 mKnownImage2dNative.table_physical=mScratchTablePhysical;mKnownImage2dNative.tables=mScratchTables;
 mKnownImage2dNative.prepare_phase=2;
 /* Reserve only a completely virgin fixed range. A partial publication is
  * retained, never restored to a free cursor after a failure. */
 for(unsigned Page=0;Page<HGKI_PAGES;Page++) {
  if(KnownImage2dPrepareGuard())return mKnownImage2dNative.prepare_code=HGKIN_OWNER;
  if(KnownImage2dTranslation(Page))return mKnownImage2dNative.prepare_code=HGKIN_TRANSLATION;
  KnownImage2dBarrier();volatile UINT8 *Cpu=KnownImage2dCpu(Page);
  for(unsigned I=0;I<HGKI_PAGE;I++)if(Cpu[I])return mKnownImage2dNative.prepare_code=HGKIN_VIRGIN;
 }
 if(KnownImage2dPrepareGuard() || KnownImage2dBindings() || mGpuOnlyNext[2]!=HGKI_CLASS_CURSOR)
  return mKnownImage2dNative.prepare_code=HGKIN_OWNER;
 mKnownImage2dNative.retained=1;mKnownImage2dNative.reserved_pages=HGKI_PAGES;
 mGpuOnlyNext[2]=HGKI_CLASS_CURSOR+HGKI_BYTES;mKnownImage2dNative.prepare_phase=3;
 if(hgki_build(mKnownImage2dReadback,sizeof mKnownImage2dReadback))
  return mKnownImage2dNative.prepare_code=HGKIN_PUBLISH;
 for(unsigned Page=0;Page<HGKI_PAGES;Page++) {
  if(KnownImage2dPrepareGuard() || KnownImage2dPreparedBindings())
   return mKnownImage2dNative.prepare_code=HGKIN_OWNER;
  if(KnownImage2dTranslation(Page))return mKnownImage2dNative.prepare_code=HGKIN_TRANSLATION;
  volatile UINT8 *Cpu=KnownImage2dCpu(Page);
  for(unsigned I=0;I<HGKI_PAGE;I++)Cpu[I]=mKnownImage2dReadback[Page*HGKI_PAGE+I];
  KnownImage2dBarrier();++mKnownImage2dNative.published_pages;
  if(KnownImage2dPrepareGuard())return mKnownImage2dNative.prepare_code=HGKIN_OWNER;
  for(unsigned I=0;I<HGKI_PAGE;I++)if(Cpu[I]!=mKnownImage2dReadback[Page*HGKI_PAGE+I])
   return mKnownImage2dNative.prepare_code=HGKIN_PUBLISH;
  mKnownImage2dNative.published_crc[Page]=hgki_crc32(mKnownImage2dReadback+Page*HGKI_PAGE,HGKI_PAGE);
  ++mKnownImage2dNative.verified_pages;
 }
 if(KnownImage2dPrepareGuard() || KnownImage2dPreparedBindings())
  return mKnownImage2dNative.prepare_code=HGKIN_OWNER;
 mKnownImage2dNative.source_crc=hgki_crc32(mKnownImage2dReadback,HGKI_BYTES);
 mKnownImage2dNative.source_valid=mKnownImage2dNative.ready=1;
 mKnownImage2dNative.prepare_phase=4;return mKnownImage2dNative.prepare_code=HGKIN_OK;
}
STATIC int KnownImage2dRuntimeGuard(unsigned Phase) {
 ++mKnownImage2d.guards;
 if(!mKnownImage2dNative.running || !mKnownImage2dNative.ready ||
  mKnownImage2dNative.prepare_code || !mKnownImage2dNative.retained ||
  mKnownImage2dNative.reserved_pages!=HGKI_PAGES ||
  mKnownImage2dNative.published_pages!=HGKI_PAGES ||
  mKnownImage2dNative.verified_pages!=HGKI_PAGES || !mKnownImage2dNative.source_valid ||
  !mKnownImage2dNative.table_valid || KnownImage2dPreparedBindings() ||
  !mKnownImage2dNative.owner.guard || !mHostRingUnsafe || mGpuSaveAllowed ||
  !mHostRingPrepared || !mHostRing.enabled || !mHostRing.init_idle ||
  mHostRing.phase!=4 || mHostRing.code || mHostRing.stopped || mHostRingCpFailed ||
  mHostBusStop.stage || mHostWriteFaults || mHostMode.code ||
  !mHostMode.authenticated || !mHostMode.submitted || !mHostMode.idle ||
  mHostMode.phase<4 || mHostMode.phase>5 || mHostApertureKind!=2 ||
  !mHostApertureAvailable || !mHostApertureValid || mHostApertureCode ||
  mHostAperture.quarantined || mHostAperture.last_output.x[0])return 1;
 mKnownImage2d.callback_code=mKnownImage2dNative.owner.guard(mKnownImage2dNative.owner.cookie,Phase);
 if(mKnownImage2d.callback_code)return 1;
 mKnownImage2dNative.aperture_valid=1;return 0;
}
STATIC int KnownImage2dReadPages(unsigned Phase,unsigned Initial) {
 for(unsigned Page=0;Page<HGKI_PAGES;Page++) {
  if(KnownImage2dRuntimeGuard(Phase) || KnownImage2dTranslation(Page))return 1;
  KnownImage2dBarrier();volatile UINT8 *Cpu=KnownImage2dCpu(Page);
  for(unsigned I=0;I<HGKI_PAGE;I++)mKnownImage2dReadback[Page*HGKI_PAGE+I]=Cpu[I];
  ++mKnownImage2dNative.read_pages;
  if(KnownImage2dRuntimeGuard(Phase))return 1;
 }
 if(Initial) {
  for(unsigned I=0;I<HGKI_BYTES;I++)if(mKnownImage2dReadback[I]!=hgki_initial_byte(I))return 1;
  if(hgki_crc32(mKnownImage2dReadback,HGKI_BYTES)!=mKnownImage2dNative.source_crc)return 1;
  mKnownImage2dNative.initial_valid=1;
 }
 return 0;
}
STATIC unsigned RunKnownImage2d(CONST struct hgki_native_owner *Owner,unsigned KmdPreemptionDisabled) {
 if(mKnownImage2d.started)return HGKIN_REUSED;
 mKnownImage2d=(struct hgki_result){.started=1,.retained=mKnownImage2dNative.retained,.first_bad=UINT32_MAX};
 if(!mKnownImage2dNative.ready || mKnownImage2dNative.prepare_code) {
  mKnownImage2d.code=HGKI_QUALIFICATION;return mKnownImage2dNative.run_code=HGKIN_NOT_PREPARED;
 }
 if(!Owner || !Owner->guard || !Owner->submit_fixed_ib || !Owner->bounded_idle || KmdPreemptionDisabled!=1) {
  mKnownImage2d.code=HGKI_QUALIFICATION;return mKnownImage2dNative.run_code=HGKIN_QUALIFICATION;
 }
 mKnownImage2dNative.kmd_preemption_disabled=KmdPreemptionDisabled;
 mKnownImage2dNative.owner=*Owner;mKnownImage2dNative.running=1;
 unsigned Code=HGKIN_OWNER;mKnownImage2d.phase=1;
 if(KnownImage2dRuntimeGuard(1))goto done;
 if(mHostRing.rptr!=mHostRing.wptr || !mHostRing.busy_valid || (mHostRing.busy&(1u<<23)))goto done;
 mKnownImage2d.phase=2;Code=HGKIN_READBACK;
 if(KnownImage2dReadPages(2,1))goto done;
 mKnownImage2d.phase=3;Code=HGKIN_OWNER;if(KnownImage2dRuntimeGuard(3))goto done;
 /* No pointer or count from a caller reaches the submission callback. */
 mKnownImage2d.submit_attempted=1;++mKnownImage2dNative.submit_calls;
#ifdef HOUJI_CALL_TRACE
 HOUJI_CALL_TRACE(0x7300,HGKI_COMMAND,HGKI_SELECTED_COMMAND_WORDS);
#endif
 mKnownImage2d.callback_code=Owner->submit_fixed_ib(Owner->cookie,hgki_ib,4);
 Code=HGKIN_SUBMIT;if(mKnownImage2d.callback_code)goto done;
 mKnownImage2d.submit_returned=1;mKnownImage2d.phase=4;Code=HGKIN_OWNER;
 if(KnownImage2dRuntimeGuard(4))goto done;
 ++mKnownImage2dNative.idle_calls;mKnownImage2d.callback_code=Owner->bounded_idle(Owner->cookie);
 Code=HGKIN_IDLE;if(mKnownImage2d.callback_code)goto done;
 if(mHostRing.rptr!=mHostRing.wptr || !mHostRing.busy_valid || (mHostRing.busy&(1u<<23)))goto done;
 mKnownImage2d.completed=1;mKnownImage2d.phase=5;Code=HGKIN_READBACK;
 if(KnownImage2dReadPages(5,0))goto done;
 mKnownImage2d.readback_valid=1;mKnownImage2d.phase=6;
 mKnownImage2d.code=hgki_verify(mKnownImage2dReadback,HGKI_BYTES,&mKnownImage2d);
 Code=mKnownImage2d.code?HGKIN_VERIFY:HGKIN_OK;
 if(!Code)mKnownImage2d.phase=8;
done:
 mKnownImage2dNative.running=0;mKnownImage2dNative.run_code=Code;
 if(Code && !mKnownImage2d.code)mKnownImage2d.code=Code==HGKIN_OWNER?HGKI_OWNER:
  Code==HGKIN_SUBMIT?HGKI_SUBMIT:Code==HGKIN_IDLE?HGKI_COMPLETION:HGKI_READBACK;
 return Code;
}
/* A post-failure snapshot is deliberately separate from the runtime success
 * verifier. It may run only after actual CM3 reset and all three GX/client/arb
 * acknowledgements, with the roots/routes and retained NC ownership still
 * valid. It never reads CP/SQE, reopens the engine, or changes completion bits.
 */
STATIC int KnownImage2dIsolationGuard(VOID) {
 if(!HGKI_PROGRESS || mHostRingUnsafe || !mGpuSaveAllowed || !mHostRing.stopped ||
  mKnownImage2dNative.running || !mKnownImage2d.started || !mKnownImage2d.submit_attempted ||
  !mKnownImage2dNative.ready || !mKnownImage2dNative.retained ||
  !mKnownImage2dNative.table_valid || KnownImage2dPreparedBindings() ||
  mHostBusStop.stage!=5 || !mHostBusStop.stopped || !mHostBusStop.cm3_reset ||
  !(mHostBusStop.ack[0]&1) || !(mHostBusStop.ack[1]&1) || !(mHostBusStop.ack[2]&2))return 1;
 if(HostRingBusLease() || StockRead32(NULL,0x3d7e000,&mKnownImage2dNative.diagnostic_reset) ||
  mKnownImage2dNative.diagnostic_reset!=1)return 1;
 if(HostRingBusLease() || GpuTryRead32(0x3d0005c,&mKnownImage2dNative.diagnostic_gx_ack) ||
  !(mKnownImage2dNative.diagnostic_gx_ack&1))return 1;
 if(HostRingBusLease() || GpuTryRead32(0x3d0f118,&mKnownImage2dNative.diagnostic_gbif_ack) ||
  (mKnownImage2dNative.diagnostic_gbif_ack&3)!=3)return 1;
 return 0;
}
STATIC unsigned KnownImage2dIsolatedCapture(VOID) {
 if(mKnownImage2dNative.diagnostic_started)return HGKIN_REUSED;
 mKnownImage2dNative.diagnostic_started=1;
 if(KnownImage2dIsolationGuard())return mKnownImage2dNative.diagnostic_code=HGKIN_ISOLATION;
 if(FirmwareVerifyPages(mGpuOnlyMemory.physical,mGpuOnlyMemory.cpu,HSC_POOL_PAGES,1) || ScratchAudit())
  return mKnownImage2dNative.diagnostic_code=HGKIN_MEMORY;
 for(unsigned Page=0;Page<HGKI_PAGES;Page++) {
  if(KnownImage2dIsolationGuard())return mKnownImage2dNative.diagnostic_code=HGKIN_ISOLATION;
  if(KnownImage2dTranslation(Page))return mKnownImage2dNative.diagnostic_code=HGKIN_TRANSLATION;
  KnownImage2dBarrier();volatile UINT8 *Cpu=KnownImage2dCpu(Page);
  for(unsigned I=0;I<HGKI_PAGE;I++)mKnownImage2dReadback[Page*HGKI_PAGE+I]=Cpu[I];
  ++mKnownImage2dNative.diagnostic_pages;
  if(KnownImage2dIsolationGuard())return mKnownImage2dNative.diagnostic_code=HGKIN_ISOLATION;
 }
 for(unsigned M=0;M<HGKI_PROGRESS_MARKERS;M++) {
  uint32_t V=0;for(unsigned B=0;B<4;B++)V|=(uint32_t)mKnownImage2dReadback[4*M+B]<<(8*B);
  mKnownImage2dNative.diagnostic_marker[M]=V;
  if(V==hgki_marker_value(M))mKnownImage2dNative.diagnostic_marker_mask|=1u<<M;
 }
 mKnownImage2dNative.diagnostic_output_crc=hgki_crc32(mKnownImage2dReadback+5*HGKI_PAGE,HGKI_OUTPUT_BYTES);
 for(unsigned I=0;I<HGKI_OUTPUT_BYTES;I+=4) {
  CONST UINT8 *P=mKnownImage2dReadback+5*HGKI_PAGE+I;
  if(P[0]==255 && P[1]==0 && P[2]==0 && P[3]==255)++mKnownImage2dNative.diagnostic_red_pixels;
 }
 unsigned Intact=1;
 for(unsigned I=HGKI_MARKER_BYTES;I<HGKI_BYTES;I++) {
  if(I>=5*HGKI_PAGE && I<6*HGKI_PAGE)continue;
  if(mKnownImage2dReadback[I]!=hgki_initial_byte(I)){Intact=0;break;}
 }
 mKnownImage2dNative.diagnostic_guards_intact=Intact;
 mKnownImage2dNative.diagnostic_valid=1;return mKnownImage2dNative.diagnostic_code=HGKIN_OK;
}
STATIC VOID KnownImage2dReport(VOID) {
 if(mKnownImage2dNative.running || mHostRingUnsafe || !mGpuSaveAllowed)return;
 Print(L"HOUJI GPU KNOWN IMAGE 2D: prepare=%u/%u ready=%u retained=%u pages=%u published=%u verified=%u source-valid=%u source-crc=%08x table-proof=%u aperture-proof=%u initial-valid=%u; fixed class2 unprivilegedRW/NX seven pages, no table edits\n",
  mKnownImage2dNative.prepare_code,mKnownImage2dNative.prepare_phase,mKnownImage2dNative.ready,
  mKnownImage2dNative.retained,mKnownImage2dNative.reserved_pages,mKnownImage2dNative.published_pages,
  mKnownImage2dNative.verified_pages,mKnownImage2dNative.source_valid,mKnownImage2dNative.source_crc,
  mKnownImage2dNative.table_valid,mKnownImage2dNative.aperture_valid,mKnownImage2dNative.initial_valid);
 Print(L"HOUJI GPU KNOWN IMAGE 2D RESULT: started=%u native-code=%u policy-code=%u phase=%u submit=%u/%u completed=%u readback-valid=%u verified=%u output-crc=%08x first-bad=%x expected=%x actual=%x callback-code=%d guards=%u pages-read=%u AT-calls=%u AT-failed=%u; real CP_BLIT pixel verification required, no shader/Metal/desktop acceleration claim\n",
  mKnownImage2d.started,mKnownImage2dNative.run_code,mKnownImage2d.code,mKnownImage2d.phase,
  mKnownImage2d.submit_attempted,mKnownImage2d.submit_returned,mKnownImage2d.completed,
  mKnownImage2d.readback_valid,mKnownImage2d.verified,mKnownImage2d.output_crc,
  mKnownImage2d.first_bad,mKnownImage2d.expected,mKnownImage2d.actual,mKnownImage2d.callback_code,
  mKnownImage2d.guards,mKnownImage2dNative.read_pages,mKnownImage2dNative.at_calls,mKnownImage2dNative.at_failed);
 Print(L"HOUJI GPU KNOWN IMAGE 2D POLICY: KMD-preemption-disabled=%u; caller qualification of fixed CP_INIT94b and no context-switch submissions, not a measured hardware state\n",
  mKnownImage2dNative.kmd_preemption_disabled);
 Print(L"HOUJI GPU KNOWN IMAGE 2D ISOLATED DIAGNOSTIC: enabled=%u words=%u started=%u code=%u valid=%u pages=%u marker-mask=%x raw-output-crc=%08x red-pixels=%u guards-intact=%u reset=%x GX-ACK=%x GBIF-ACK=%x; after actual three-ACK isolation only, never sets runtime completed/readback/verified\n",
  HGKI_PROGRESS,HGKI_SELECTED_COMMAND_WORDS,mKnownImage2dNative.diagnostic_started,
  mKnownImage2dNative.diagnostic_code,mKnownImage2dNative.diagnostic_valid,mKnownImage2dNative.diagnostic_pages,
  mKnownImage2dNative.diagnostic_marker_mask,mKnownImage2dNative.diagnostic_output_crc,
  mKnownImage2dNative.diagnostic_red_pixels,mKnownImage2dNative.diagnostic_guards_intact,
  mKnownImage2dNative.diagnostic_reset,mKnownImage2dNative.diagnostic_gx_ack,mKnownImage2dNative.diagnostic_gbif_ack);
 for(unsigned M=0;M<HGKI_PROGRESS_MARKERS;M++)Print(L"HOUJI GPU KNOWN IMAGE 2D MARKER: id=%u source-boundary=%u raw=%08x expected=%08x valid=%u; command progress only, not RB completion\n",
  M+1,hgki_marker_boundary(M),mKnownImage2dNative.diagnostic_marker[M],hgki_marker_value(M),
  mKnownImage2dNative.diagnostic_valid && !!(mKnownImage2dNative.diagnostic_marker_mask&(1u<<M)));
}
#endif
