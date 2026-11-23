/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Optional capture-only glue, included after GpuHostRingNative.h. Integrator
 * chooses pre/post aperture and post-CP_INIT-idle hooks; the stage is a caller
 * label, not independent execution evidence. No PAS/PM4/MMIO-write callback.
 */
#ifndef HOUJI_GPU_GRAPHICS_READINESS_NATIVE_H
#define HOUJI_GPU_GRAPHICS_READINESS_NATIVE_H
#include "GpuGraphicsReadiness.h"
STATIC struct hgr_result mGraphicsReadiness[HGR_STAGES];
STATIC int GraphicsReadinessOwned(VOID *Cookie,unsigned Stage) {
 (VOID)Cookie;
 if(Stage>=HGR_STAGES || !mHostRingPrepared || mHostBusStop.stage || mHostRing.code ||
  mHostRingCpFailed || mHostWriteFaults || HostRingGuard(NULL))return 1;
 // HostRingGuard just observed this busy value under the retained GX lease.
 // Do not inspect security registers during active execution or after reset.
 return !mHostRingBusy.valid || !!(mHostRingBusy.last&(1u<<23));
}
STATIC int GraphicsReadinessRead(VOID *Cookie,uint32_t Address,uint32_t *Value) {
 (VOID)Cookie;unsigned Allowed=0;
 for(unsigned I=0;I<HGR_REGS;I++)if(Address==hgr_address(I))Allowed=1;
 return !Allowed || !Value?1:GpuTryRead32(Address,Value);
}
STATIC unsigned GraphicsReadinessCapture(unsigned Stage) {
 if(Stage>=HGR_STAGES)return HGR_ARGUMENT;
 CONST struct hgr_io Io={NULL,GraphicsReadinessOwned,GraphicsReadinessRead};
 return hgr_capture(&Io,Stage,&mGraphicsReadiness[Stage]);
}
STATIC VOID GraphicsReadinessReport(VOID) {
 if(mHostRingUnsafe)return;
 for(unsigned S=0;S<HGR_STAGES;S++) {
  CONST struct hgr_result *R=&mGraphicsReadiness[S];if(!R->started)continue;
  Print(L"HOUJI GPU GRAPHICS STATE: stage-label=%u code=%u phase=%u guards=%u reads=%u attempted=%x valid=%x owner-code=%d read-code=%d; capture only, no nonsecure/ZAP/graphics-ready inference\n",R->stage,R->code,R->phase,R->guards,R->reads,R->attempted,R->valid,R->owner_code,R->read_code);
  for(unsigned I=0;I<HGR_REGS;I++)Print(L"HOUJI GPU GRAPHICS STATE RAW: stage-label=%u i=%u address=%x value=%x valid=%u; TRUST_CNTL bits unspecified, TSB_LO/HI are a non-atomic error-state pair\n",S,I,hgr_address(I),R->raw[I],(R->valid>>I)&1);
 }
}
#endif
