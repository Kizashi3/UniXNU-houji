/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Query-only adapter; include after GpuHostRingNative.h. Its only SMCs are
 * fixed INFO availability and PAS_SUPPORTED(13), including exact resumes.
 * Called from the existing safe HostPreparationSave before its checkpoint.
 */
#ifndef HOUJI_GPU_PAS_PROBE_NATIVE_H
#define HOUJI_GPU_PAS_PROBE_NATIVE_H
#include "GpuPasProbe.h"
STATIC struct hpp_result mPasProbe;
STATIC struct {
 unsigned running,calls,pending,pending_phase,rejected;
 UINT64 cookie,elapsed,total_elapsed,query_elapsed[HPP_QUERY_COUNT];
 struct ggs_regs last_input,last_output;
} mPasProbeNative;

STATIC int PasProbeGuard(VOID *Cookie) {
 (VOID)Cookie;
 if(mHostRingUnsafe || mHostRing.enabled || mHostWriteCalls ||
  !mGpuSaveAllowed || mHostRingPrepared || mHostRing.started ||
  mSecureCx.convention_verified!=1 || mSecureCx.available!=1 ||
  mSecureCx.init_succeeded!=1 || mSecureCx.quarantined)return 0;
 return HostPreparationGuard(NULL)?0:1;
}
STATIC int PasProbeFrameAllowed(CONST struct ggs_regs *R) {
 if(!R || !mPasProbeNative.running || !mPasProbe.started ||
  mPasProbe.phase<1 || mPasProbe.phase>HPP_QUERY_COUNT)return 0;
 unsigned index=mPasProbe.phase-1;
 if(index==HPP_AVAILABILITY_COUNT && !(mPasProbe.available_mask&1u))return 0;
 struct ggs_regs expected;
 if(hpp_frame(index,&expected))return 0;
 if(mPasProbeNative.pending) {
  if(mPasProbeNative.pending_phase!=mPasProbe.phase || R->x[0]!=1 ||
   R->x[6]!=mPasProbeNative.cookie)return 0;
 } else if(R->x[0]!=expected.x[0] || R->x[6])return 0;
 for(unsigned i=1;i<8;i++)if(i!=6 && R->x[i]!=expected.x[i])return 0;
 return 1;
}
STATIC int PasProbeCall(VOID *Cookie,struct ggs_regs *R) {
 (VOID)Cookie;
 if(!PasProbeGuard(NULL)) {
  mPasProbe.guard_failed=1;mPasProbeNative.rejected=1;return 1;
 }
 if(!PasProbeFrameAllowed(R)) {mPasProbeNative.rejected=2;return 1;}
 mPasProbeNative.last_input=*R;++mPasProbeNative.calls;
#ifdef HOUJI_CALL_TRACE
 HOUJI_CALL_TRACE(0x7100u+mPasProbe.phase,R->x[0],R->x[2]);
#endif
 UINT64 Begin=BatchCounter();
 int Code=ggs_aarch64_call(NULL,R);
 UINT64 Elapsed=BatchMicroseconds(Begin);
#ifdef HOUJI_CALL_TRACE
 HOUJI_CALL_TRACE(0x7110u+mPasProbe.phase,R->x[0],R->x[1]);
#endif
 mPasProbeNative.elapsed+=Elapsed;
 mPasProbeNative.query_elapsed[mPasProbe.phase-1]+=Elapsed;
 mPasProbeNative.last_output=*R;
 mPasProbeNative.pending=!Code && R->x[0]==1;
 mPasProbeNative.pending_phase=mPasProbeNative.pending?mPasProbe.phase:0;
 mPasProbeNative.cookie=mPasProbeNative.pending?R->x[6]:0;
 if(!PasProbeGuard(NULL)) {
  mPasProbe.guard_failed=1;mPasProbeNative.rejected=3;return Code?Code:1;
 }
 return Code;
}
STATIC unsigned RunPasProbe(VOID) {
 if(mPasProbe.started)return HPP_ALREADY_STARTED;
 if(!PasProbeGuard(NULL))return mPasProbe.code=HPP_PREREQUISITE;
 CONST struct hpp_io Io={NULL,PasProbeGuard,PasProbeCall,SecureCxDelay};
 mPasProbeNative.running=1;UINT64 Begin=BatchCounter();
 unsigned Code=hpp_run(&Io,&mSecureCx,&mPasProbe);
 mPasProbeNative.total_elapsed=BatchMicroseconds(Begin);
 mPasProbeNative.running=0;
 return Code;
}
STATIC VOID PasProbeReport(VOID) {
 // CPU-only reporting may happen at the original post-stop report site too;
 // it must not re-enter the pre-SQE MMIO guard after SQE has been halted.
 if(mPasProbeNative.running || mHostRingUnsafe || !mGpuSaveAllowed)return;
 Print(L"HOUJI GPU PAS QUERY: started=%u code=%u phase=%u completed=%u attempted=%x valid=%x available=%x supported-valid=%u supported=%u callback-calls=%u native-SMC-calls=%u guard-failed=%u rejected=%u quarantined=%u pending=%u smc-us=%lu total-us=%lu; query-only, no image load/auth or non-secure proof\n",
  mPasProbe.started,mPasProbe.code,mPasProbe.phase,mPasProbe.completed,
  mPasProbe.attempted_mask,mPasProbe.valid_mask,mPasProbe.available_mask,
  mPasProbe.supported_valid,mPasProbe.supported,mPasProbe.actual_calls,
  mPasProbeNative.calls,mPasProbe.guard_failed,mPasProbeNative.rejected,
  mPasProbe.transport.quarantined,mPasProbeNative.pending,mPasProbeNative.elapsed,
  mPasProbeNative.total_elapsed);
 for(unsigned i=0;i<HPP_QUERY_COUNT;i++) {
  CONST struct hpp_observation *O=&mPasProbe.query[i];
  Print(L"HOUJI GPU PAS QUERY ROW: i=%u attempted=%u valid=%u callback-calls=%u transport-code=%u response-present=%u response-transport=%d elapsed-us=%lu\n",
   i,O->attempted,O->valid,O->actual_calls,O->transport_code,
   O->response_present,O->response_transport,mPasProbeNative.query_elapsed[i]);
  Print(L"HOUJI GPU PAS QUERY REQUEST: i=%u x0=%lx x1=%lx x2=%lx x3=%lx x4=%lx x5=%lx x6=%lx x7=%lx\n",
   i,O->request.x[0],O->request.x[1],O->request.x[2],O->request.x[3],
   O->request.x[4],O->request.x[5],O->request.x[6],O->request.x[7]);
  Print(L"HOUJI GPU PAS QUERY LAST INPUT: i=%u x0=%lx x1=%lx x2=%lx x3=%lx x4=%lx x5=%lx x6=%lx x7=%lx\n",
   i,O->last_input.x[0],O->last_input.x[1],O->last_input.x[2],O->last_input.x[3],
   O->last_input.x[4],O->last_input.x[5],O->last_input.x[6],O->last_input.x[7]);
  Print(L"HOUJI GPU PAS QUERY RESPONSE: i=%u present=%u valid=%u x0=%lx x1=%lx x2=%lx x3=%lx x4=%lx x5=%lx x6=%lx x7=%lx\n",
   i,O->response_present,O->valid,O->response.x[0],O->response.x[1],
   O->response.x[2],O->response.x[3],O->response.x[4],O->response.x[5],
   O->response.x[6],O->response.x[7]);
 }
}
#endif
