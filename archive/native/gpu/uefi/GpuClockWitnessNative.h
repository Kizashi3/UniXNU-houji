/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Actual UEFI glue for the read-only target clock witness. The original
 * ClockDxe GetClockFreqHz path (RVA1668->8050->655c, SHA f498e08b...69ba)
 * reads the software active-frequency pointer; it performs no hardware I/O.
 */
#ifndef HOUJI_GPU_CLOCK_WITNESS_NATIVE_H
#define HOUJI_GPU_CLOCK_WITNESS_NATIVE_H
#include "GpuClockWitness.h"
STATIC struct hcw_result mClockWitness[2];
struct hcw_native_cookie {CONST struct gpp_report *power;CONST struct hgb_result *bus;};
STATIC int ClockWitnessOwned(VOID *Cookie,unsigned Mode) {
 CONST struct hcw_native_cookie *C=Cookie;
 if(!mClock || mClock->Version!=0x1000a || !mClock->GetClockFreqHz ||
  mIds[GPP_GMU_RATE]!=mIds[GPP_GMU_CLK] || mIds[GPP_HUB_RATE]!=mIds[GPP_HUB_CLK] ||
  mIds[GPP_GMU_RATE]>UINT32_MAX || mIds[GPP_HUB_RATE]>UINT32_MAX ||
  (mIds[GPP_GMU_RATE]&0xffff0000u)!=0x10000u ||
  (mIds[GPP_HUB_RATE]&0xffff0000u)!=0x10000u)return 1;
 if(!Mode)return !C || !hgb_owned(C->power) || !hgd_bus_complete(C->bus);
 return Mode!=1 || HostPreparationGuard(NULL);
}
STATIC int ClockWitnessRead(VOID *Cookie,uint32_t Address,uint32_t *Value) {
 (VOID)Cookie;return GpuTryRead32(Address,Value)?1:0;
}
STATIC uint64_t ClockWitnessConfigured(VOID *Cookie,unsigned Which,uint32_t *Value) {
 (VOID)Cookie;
 if(Which>1 || !Value || !mClock || !mClock->GetClockFreqHz)return EFI_INVALID_PARAMETER;
 return mClock->GetClockFreqHz(mClock,mIds[Which?GPP_HUB_RATE:GPP_GMU_RATE],Value);
}
STATIC VOID ClockWitnessReport(CONST struct hcw_result *R) {
 Print(L"HOUJI GPU CLOCK WITNESS: R%u code=%u phase=%u reads=%u queries=%u guards=%u stable=%u valid=%x/%x guard-valid=%x/%x; capture status only, not clock readiness; no set/enable/calc/measure or GPU execution claim\n",
  R->mode,R->code,R->phase,R->reads,R->queries,R->guards,R->stable,R->valid[0],R->valid[1],R->guard_valid[0],R->guard_valid[1]);
 Print(L"HOUJI GPU CLOCK CONFIGURED: R%u GMU=%u status=%lx HUB=%u status=%lx; software cache only, Not started means unavailable rather than 0 Hz, not measured\n",
  R->mode,R->configured_hz[0],R->configured_status[0],R->configured_hz[1],R->configured_status[1]);
 for(unsigned I=0;I<2;I++) {
  CONST uint32_t *V=R->raw[I];
  CONST uint32_t *G=R->guard[I];
  Print(L"HOUJI GPU CLOCK GUARD: R%u sample=%u CFG/MEM/DVM/SMMU/CX/CXHW/AHB/RESET=%08x/%08x/%08x/%08x/%08x/%08x/%08x/%08x valid=%x\n",
   R->mode,I,G[0],G[1],G[2],G[3],G[4],G[5],G[6],G[7],R->guard_valid[I]);
  Print(L"HOUJI GPU CLOCK RAW: R%u sample=%u GMU CMD/CFG/CBCR=%08x/%08x/%08x HUB CMD/CFG/AON/CX/div=%08x/%08x/%08x/%08x/%08x valid=%x\n",
   R->mode,I,V[0],V[1],V[2],V[3],V[4],V[5],V[6],V[7],R->valid[I]);
  Print(L"HOUJI GPU CLOCK PLL1: R%u sample=%u MODE/OPMODE/STATUS/L/ALPHA/USER=%08x/%08x/%08x/%08x/%08x/%08x valid=%x\n",
   R->mode,I,V[8],V[9],V[10],V[11],V[12],V[13],R->valid[I]&0x3f00u);
  if(R->valid[I]&0xfc000u)Print(L"HOUJI GPU CLOCK PLL0: R%u sample=%u MODE/OPMODE/STATUS/L/ALPHA/USER=%08x/%08x/%08x/%08x/%08x/%08x valid=%x\n",
   R->mode,I,V[14],V[15],V[16],V[17],V[18],V[19],R->valid[I]&0xfc000u);
 }
 Print(L"HOUJI GPU CLOCK DERIVED: R%u GMU src=%u hid=%u valid=%u nominal-hz=%lu HUB src=%u hid=%u valid=%u nominal-hz=%lu; target mux/PLL formula only, not measured; unknown parent or unstable state is unavailable\n",
  R->mode,R->source[0],R->hid[0],R->derived_valid[0],R->derived_hz[0],R->source[1],R->hid[1],R->derived_valid[1],R->derived_hz[1]);
}
STATIC unsigned GpuClockWitnessR0(CONST struct gpp_report *Power,CONST struct hgb_result *Bus) {
 struct hcw_native_cookie Cookie={Power,Bus};
 CONST struct hcw_io Io={&Cookie,ClockWitnessOwned,ClockWitnessRead,ClockWitnessConfigured};
 unsigned Code=hcw_run(&Io,0,&mClockWitness[0]);ClockWitnessReport(&mClockWitness[0]);return Code;
}
STATIC unsigned GpuClockWitnessR1(VOID) {
 CONST struct hcw_io Io={NULL,ClockWitnessOwned,ClockWitnessRead,ClockWitnessConfigured};
 unsigned Code=hcw_run(&Io,1,&mClockWitness[1]);ClockWitnessReport(&mClockWitness[1]);return Code;
}
#endif
