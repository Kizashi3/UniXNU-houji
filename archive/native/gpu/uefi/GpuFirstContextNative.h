/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * OFFLINE native adapter for the fixed Linux first-context prefix. Include
 * after the existing scratch/host state and GraphicsRuntimeCheck declaration.
 * This adapter only reads the current bank0 roots and builds 25 CPU-private
 * DWORDs. It never publishes, submits, writes MMIO, allocates or accesses FS.
 * A ready result is a qualified packet image, not GPU execution evidence.
 */
#ifndef HOUJI_GPU_FIRST_CONTEXT_NATIVE_H
#define HOUJI_GPU_FIRST_CONTEXT_NATIVE_H
#include "GpuFirstContext.h"
STATIC int GraphicsRuntimeCheck(unsigned RequireIdle);
enum {HFCN_OK,HFCN_REUSED,HFCN_POLICY,HFCN_STATE,HFCN_ROOT,HFCN_BUILD,HFCN_ARGUMENT};
STATIC struct hfc_result mFirstContext;
STATIC struct {
 unsigned started,phase,code,running,ready,reported,kmd_preemption_disabled;
 unsigned actual_reads,rejected_reads,identity_valid,portable_return_code;
 UINT64 root_physical,built_root_physical,config_root,host_root[2];
 VOID *tables;
 uint32_t words[HFC_WORDS];
} mFirstContextNative;

STATIC int FirstContextNativeModeReady(VOID) {
 return mHostMode.started!=1 || mHostMode.code || mHostMode.phase!=5 || mHostMode.authenticated!=1 ||
  mHostMode.published!=1 || mHostMode.submitted!=1 || mHostMode.idle!=1 || mHostMode.complete!=1;
}
STATIC int FirstContextNativeRootQualified(VOID) {
 UINT64 Root=mScratchTablePhysical;
 return !mScratchTables || !Root || (Root&4095) || Root>=(1ULL<<36) ||
  Root!=mScratchBuilt.root_physical || Root!=mScratchConfig.table_physical ||
  mHostRingRoots[0]!=((UINT64)HFC_ASID<<48|Root) ||
  mHostRingRoots[1]!=((UINT64)HFC_ASID<<48);
}
STATIC int FirstContextNativeIdentity(VOID) {
 return mFirstContextNative.identity_valid!=1 || FirstContextNativeRootQualified() ||
  mFirstContextNative.root_physical!=mScratchTablePhysical ||
  mFirstContextNative.built_root_physical!=mScratchBuilt.root_physical ||
  mFirstContextNative.config_root!=mScratchConfig.table_physical ||
  mFirstContextNative.tables!=mScratchTables ||
  mFirstContextNative.host_root[0]!=mHostRingRoots[0] ||
  mFirstContextNative.host_root[1]!=mHostRingRoots[1];
}
STATIC int FirstContextNativeOwned(VOID *Cookie) {
 (VOID)Cookie;
 if(!mFirstContextNative.started || !mFirstContextNative.running ||
  mFirstContextNative.ready || mFirstContextNative.code ||
  mFirstContextNative.kmd_preemption_disabled!=1 ||
  FirstContextNativeModeReady() || FirstContextNativeIdentity())return 1;
 // Zero success is intentional. This is the existing fresh, full running
 // lease with actual RPTR/WPTR/RBBM/GMU idle, never a cached ready flag.
 int Code=GraphicsRuntimeCheck(1);if(Code)return Code;
 return FirstContextNativeModeReady() || FirstContextNativeIdentity();
}
STATIC int FirstContextNativeReadRoot(VOID *Cookie,uint32_t Address,uint64_t *Value) {
 (VOID)Cookie;
 if(!Value || (Address!=0x3dc0020 && Address!=0x3dc0028) ||
  !mFirstContextNative.started || !mFirstContextNative.running ||
  mFirstContextNative.ready || mFirstContextNative.code ||
  !mFirstContext.started || mFirstContext.phase!=1 ||
  FirstContextNativeModeReady() || FirstContextNativeIdentity()) {
  ++mFirstContextNative.rejected_reads;return HFCN_ARGUMENT;
 }
 // hfc_build calls the fresh owner immediately before and after these reads.
 // No caller-supplied address reaches any other register or write primitive.
 ++mFirstContextNative.actual_reads;
 return GpuTryRead64(Address,Value);
}
STATIC unsigned FirstContextNativeBuild(unsigned KmdPreemptionDisabled) {
 if(mFirstContextNative.started)return HFCN_REUSED;
 mFirstContextNative=(__typeof__(mFirstContextNative)){
  .started=1,.phase=1,.kmd_preemption_disabled=KmdPreemptionDisabled};
 // CPU source snapshots remain reportable even when initial qualification
 // fails. identity_valid is set only after all three roots qualify.
 mFirstContextNative.root_physical=mScratchTablePhysical;
 mFirstContextNative.built_root_physical=mScratchBuilt.root_physical;
 mFirstContextNative.config_root=mScratchConfig.table_physical;
 mFirstContextNative.tables=mScratchTables;
 mFirstContextNative.host_root[0]=mHostRingRoots[0];
 mFirstContextNative.host_root[1]=mHostRingRoots[1];
 if(KmdPreemptionDisabled!=1)return mFirstContextNative.code=HFCN_POLICY;
 if(FirstContextNativeModeReady())return mFirstContextNative.code=HFCN_STATE;
 if(FirstContextNativeRootQualified())return mFirstContextNative.code=HFCN_ROOT;
 mFirstContextNative.identity_valid=1;mFirstContextNative.running=1;
 mFirstContextNative.phase=2;
 // One logical context and KMD preemption disabled are explicit fixed-driver
 // policy, as in the known-image test. The owner proves the retained sole
 // normal bank0 mapping and actual full idle after authenticated mode exit.
 CONST struct hfc_config Config={mFirstContextNative.root_physical,
  mFirstContextNative.built_root_physical,1,1,1,1,KmdPreemptionDisabled};
 CONST struct hfc_io Io={NULL,FirstContextNativeOwned,FirstContextNativeReadRoot};
 unsigned Code=hfc_build(&Io,&Config,mFirstContextNative.words,HFC_WORDS,&mFirstContext);
 mFirstContextNative.portable_return_code=Code;
 mFirstContextNative.running=0;
 if(Code)return mFirstContextNative.code=HFCN_BUILD;
 mFirstContextNative.ready=1;mFirstContextNative.phase=3;
 return HFCN_OK;
}
/* True means a complete canonical match; zero rejects. CPU-only validation is
 * intentionally separate from the integrator's fresh live guard before kick.
 * Even Words == mFirstContextNative.words is checked against an independently
 * regenerated image, never against another pointer to that mutable buffer.
 */
STATIC int FirstContextNativePacketMatches(CONST uint32_t *Words,unsigned Count) {
 if(!Words || Count!=HFC_WORDS || mFirstContextNative.started!=1 ||
  mFirstContextNative.running || mFirstContextNative.ready!=1 ||
  mFirstContextNative.phase!=3 || mFirstContextNative.code ||
  mFirstContextNative.portable_return_code || mFirstContextNative.kmd_preemption_disabled!=1 ||
  mFirstContext.started!=1 || mFirstContext.code || mFirstContext.phase!=3 ||
  mFirstContext.ready!=1 || mFirstContext.valid!=3 ||
  FirstContextNativeModeReady() || FirstContextNativeIdentity() ||
  mFirstContext.ttbr0!=mFirstContextNative.host_root[0] ||
  mFirstContext.ttbr1!=mFirstContextNative.host_root[1])return 0;
 for(unsigned I=0;I<HFC_WORDS;I++)
  if(Words[I]!=hfc_word(mFirstContextNative.root_physical,I))return 0;
 return 1;
}
STATIC VOID FirstContextNativeReport(VOID) {
 if(!mFirstContextNative.started || mFirstContextNative.reported ||
  mFirstContextNative.running || mHostRingUnsafe || !mGpuSaveAllowed)return;
 mFirstContextNative.reported=1;
 Print(L"HOUJI GPU FIRST CONTEXT BUILD: code=%u phase=%u ready=%u policy-preemption-disabled=%u identity-valid=%u packet-DW=%u owner-code=%d read-code=%d guards=%u callback-reads=%u actual-reads=%u rejected-reads=%u root-valid=%x; CPU construction only, no publication/submission/execution\n",
  mFirstContextNative.code,mFirstContextNative.phase,mFirstContextNative.ready,
  mFirstContextNative.kmd_preemption_disabled,mFirstContextNative.identity_valid,
  mFirstContextNative.ready?HFC_WORDS:0,mFirstContext.owner_code,mFirstContext.read_code,
  mFirstContext.guards,mFirstContext.reads,mFirstContextNative.actual_reads,
  mFirstContextNative.rejected_reads,mFirstContext.valid);
 Print(L"HOUJI GPU FIRST CONTEXT ROOT: source=%lx built=%lx config=%lx host-TTBR=%lx/%lx actual-TTBR=%lx/%lx portable-code=%u return-code=%u; ASID=751 bank=0, unchanged-root candidate\n",
  mFirstContextNative.root_physical,mFirstContextNative.built_root_physical,
  mFirstContextNative.config_root,mFirstContextNative.host_root[0],
  mFirstContextNative.host_root[1],mFirstContext.ttbr0,mFirstContext.ttbr1,mFirstContext.code,
  mFirstContextNative.portable_return_code);
}
#endif
