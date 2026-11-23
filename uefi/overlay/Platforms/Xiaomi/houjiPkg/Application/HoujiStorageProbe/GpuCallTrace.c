/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Diagnostic-only call progress. Init runs before the GPU critical section;
 * CallTrace itself stores CPU RAM and, when validated, a few framebuffer words.
 * It never establishes persistence. Report requires a stopped recorder AND
 * the caller's independently established GPU/UFS-safe logging condition.
 */
#include <Uefi.h>
#include <Protocol/GraphicsOutput.h>
#include <Library/UefiBootServicesTableLib.h>
#include "GpuCallTrace.h"

UINTN EFIAPI ProbePrint(CONST CHAR16 *Format,...);
VOID EFIAPI ProbeTraceAppendRecord(UINT64 Sequence,UINT32 Step,UINT64 Counter,UINT64 Address,UINT64 Value);

STATIC struct hct_ring mCallTrace;
STATIC struct hct_failure mCallTraceFirstFailure;
STATIC struct hct_screen mCallTraceScreen;
STATIC uint64_t mCallTraceReported;
STATIC BOOLEAN mCallTraceFirstFailureReported;
STATIC EFI_STATUS mCallTraceGopStatus=EFI_NOT_STARTED;
STATIC unsigned mCallTraceInitReason;
STATIC BOOLEAN mCallTraceNormalScreenSuppressed;
STATIC EFI_GUID mCallTraceGopGuid=EFI_GRAPHICS_OUTPUT_PROTOCOL_GUID;

/* Use only already-writable identity mappings. AT checks are initialization
 * only: no mapping is installed, no framebuffer value is read, and every
 * touched scanline/page is checked before the optional display is enabled.
 */
STATIC BOOLEAN CallTraceScreenWritable(CONST struct hct_screen *Screen) {
  UINT64 El,SavedPar,Par;
  BOOLEAN Good=TRUE;
  __asm__ volatile("mrs %0,CurrentEL":"=r"(El));
  if (((El>>2)&3)!=1) return FALSE;
  EFI_TPL OldTpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);
  __asm__ volatile("mrs %0,par_el1":"=r"(SavedPar));
  for (unsigned Row=0;Good && Row<HCT_ROWS*HCT_CELL_HEIGHT*Screen->scale;Row++) {
    UINTN First=(UINTN)Screen->pixels+
      ((UINTN)(Screen->y+Row)*Screen->stride+Screen->x)*4;
    UINTN Last=First+HCT_COLUMNS*HCT_CELL_WIDTH*Screen->scale*4-1;
    for (UINTN Page=First&~(UINTN)4095;Page<=(Last&~(UINTN)4095);Page+=4096) {
      __asm__ volatile("at s1e1w,%1; isb; mrs %0,par_el1":"=r"(Par):"r"(Page):"memory");
      if ((Par&1) || (Par&0x0000fffffffff000ULL)!=Page) {Good=FALSE;break;}
    }
  }
  __asm__ volatile("msr par_el1,%0; isb"::"r"(SavedPar):"memory");
  gBS->RestoreTPL(OldTpl);
  return Good;
}

void HoujiGpuCallTraceInit(void) {
  if (mCallTrace.enabled) return;
  hct_reset(&mCallTrace);
  hct_failure_reset(&mCallTraceFirstFailure);
  mCallTraceReported=0;
  mCallTraceFirstFailureReported=FALSE;
  mCallTraceNormalScreenSuppressed=FALSE;
  (void)hct_screen_init(&mCallTraceScreen,0,0,0,0,0,2);
  EFI_GRAPHICS_OUTPUT_PROTOCOL *Gop=NULL;
  mCallTraceInitReason=1;
  mCallTraceGopStatus=gBS->LocateProtocol(&mCallTraceGopGuid,NULL,(VOID **)&Gop);
  if (EFI_ERROR(mCallTraceGopStatus) || !Gop || !Gop->Mode || !Gop->Mode->Info ||
      Gop->Mode->SizeOfInfo<sizeof(*Gop->Mode->Info)) return;
  mCallTraceInitReason=2;
  CONST EFI_GRAPHICS_OUTPUT_MODE_INFORMATION *Info=Gop->Mode->Info;
  if (Gop->Mode->FrameBufferBase>UINTPTR_MAX ||
      !hct_screen_init(&mCallTraceScreen,(uintptr_t)Gop->Mode->FrameBufferBase,
        Gop->Mode->FrameBufferSize,Info->HorizontalResolution,Info->VerticalResolution,
        Info->PixelsPerScanLine,(unsigned)Info->PixelFormat)) return;
  mCallTraceInitReason=3;
  if (!CallTraceScreenWritable(&mCallTraceScreen)) {
    mCallTraceScreen.enabled=0;
    return;
  }
  mCallTraceInitReason=0;
}

void HoujiGpuCallTraceStart(void) {
  if (mCallTrace.enabled) return;
  mCallTraceScreen.cache_valid=0;
  mCallTraceReported=0;
  hct_failure_reset(&mCallTraceFirstFailure);
  mCallTraceFirstFailureReported=FALSE;
  hct_start(&mCallTrace);
}

void HoujiGpuCallTraceStop(void) {
  hct_stop(&mCallTrace);
}

void HoujiGpuCallTraceResume(void) {
  if (mCallTrace.enabled) return;
  /* Normal console output while stopped may have covered this tiny strip. */
  mCallTraceScreen.cache_valid=0;
  hct_resume(&mCallTrace);
}

/* A one-way choice for this initialization: normal recording stays CPU RAM
 * only across Start/Stop/Resume. An explicit fatal terminal display remains
 * permitted after the recorder is stopped. No framebuffer store occurs here. */
void HoujiGpuCallTraceRamOnly(void) {
  mCallTraceNormalScreenSuppressed=TRUE;
}

unsigned HoujiGpuCallTraceConsoleSuppressed(void) {
  return mCallTraceNormalScreenSuppressed && mCallTrace.enabled;
}

void HoujiGpuCallTraceFreezeFirstFailure(void) {
  hct_freeze_first_failure(&mCallTrace,&mCallTraceFirstFailure);
}

/* Keep this path independent from all UEFI output/storage/event services.
 * The counter read has only a compiler memory clobber, not an ISB or DSB;
 * timestamps are diagnostic CPU samples, not completion fences.
 */
void HoujiGpuCallTrace(uint32_t Step,uint64_t Address,uint64_t Value) {
  if (!mCallTrace.enabled) return;
  UINT64 Counter;
  __asm__ volatile("mrs %0,cntpct_el0":"=r"(Counter)::"memory");
  uint64_t Sequence=hct_push(&mCallTrace,Step,Address,Value,Counter);
  /* Show call boundaries only, not each low-level RAM trace event. No flush.
   * A DSB can still wait for earlier CPU framebuffer stores: the stage identifies
   * the blocked call but alone does not identify the hardware root cause. */
  if (!mCallTraceNormalScreenSuppressed && Sequence &&
      ((Step>=0x1000 && Step<=0x1013) ||
      (Step>=0x1200 && Step<=0x1207) || (Step>=0x2000 && Step<=0x2031) ||
      (Step>=0x3000 && Step<=0x3129) || (Step>=0x4012 && Step<=0x4015) ||
      (Step>=0x5002 && Step<=0x5007) || (Step>=0x8000 && Step<=0x8008) ||
      Step==0x7000 || Step==0x7001))
    hct_screen_show(&mCallTraceScreen,Sequence,Step,Address,Value);
}

/* Unmatched-fatal terminal display only. No services or hardware readbacks.
 * Freeze the CPU ring before drawing; a second call only redraws after the
 * existing console reporter and cannot fabricate resumed execution. */
void HoujiGpuCallTraceFatal(uint64_t Pc,uint64_t Esr,uint64_t Far,uint64_t Lr) {
  if (mCallTrace.enabled) {
    UINT64 Counter;
    __asm__ volatile("mrs %0,cntpct_el0":"=r"(Counter)::"memory");
    (void)hct_push(&mCallTrace,0x700e,Far,Lr,Counter);
    (void)hct_push(&mCallTrace,0x700f,Pc,Esr,Counter);
    hct_stop(&mCallTrace);
  }
  if (!mCallTrace.sequence) return;
  mCallTraceScreen.cache_valid=0;
  hct_screen_fault(&mCallTraceScreen,mCallTrace.sequence,Pc,Esr,Far,Lr);
}

void HoujiGpuCallTraceReport(void) {
  if (mCallTrace.enabled) return;
  uint64_t Last=mCallTrace.sequence,First=hct_unreported_first(&mCallTrace,mCallTraceReported);
  uint64_t Lost=First && First>mCallTraceReported ? First-mCallTraceReported-1 : 0;
  ProbePrint(L"HOUJI GPU CALL TRACE: stopped=1 new-first=%lu last=%lu previously-reported=%lu capacity=%u unreported-lost=%lu saturated=%u screen=%u normal-screen-suppressed=%u init-reason=%u GOP=%r; single-writer volatile CPU RAM, no persistence or GPU-completion proof\n",
    First,Last,mCallTraceReported,HCT_CAPACITY,Lost,
    mCallTrace.saturated,mCallTraceScreen.enabled,mCallTraceNormalScreenSuppressed,
    mCallTraceInitReason,mCallTraceGopStatus);
  if (First) {
  uint64_t Sequence=First,FirstInvalid=0;
  unsigned Emitted=0,Invalid=0;
  for (;;) {
    struct hct_record Record;
    if (hct_get(&mCallTrace,Sequence,&Record)) {
      ProbeTraceAppendRecord(Record.sequence,Record.step,Record.counter,Record.address,Record.value);
      Emitted++;
    } else {
      if (!Invalid) FirstInvalid=Sequence;
      Invalid++;
    }
    if (Sequence==Last) break;
    Sequence++;
  }
  mCallTraceReported=Last;
  ProbePrint(L"HOUJI GPU CALL TRACE END: appended=%u invalid=%u first-invalid=%lu through=%lu; record lines appended to CPU RAM only, no per-record console output\n",
    Emitted,Invalid,FirstInvalid,Last);
  }
  if (mCallTraceFirstFailure.state!=2 || mCallTraceFirstFailureReported) return;
  /* Report only in the same stopped, independently safe context as the live
   * window. Mark once before output; a recursive report must not duplicate it.
   * 512 record lines add under 68 KiB even with maximum-width scalar values. */
  mCallTraceFirstFailureReported=TRUE;
  ProbePrint(L"HOUJI GPU CALL TRACE FIRST FAILURE: first=%lu last=%lu count=%u invalid=%u capacity=%u; independent frozen CPU RAM window, same record schema, no persistence or GPU-completion proof\n",
    mCallTraceFirstFailure.first,mCallTraceFirstFailure.last,mCallTraceFirstFailure.count,
    mCallTraceFirstFailure.invalid,HCT_FAILURE_CAPACITY);
  unsigned EmittedFrozen=0,InvalidFrozen=0;
  for (unsigned Index=0;Index<mCallTraceFirstFailure.count && Index<HCT_FAILURE_CAPACITY;Index++) {
    struct hct_record Record;
    if (hct_failure_get(&mCallTraceFirstFailure,Index,&Record)) {
      ProbeTraceAppendRecord(Record.sequence,Record.step,Record.counter,Record.address,Record.value);
      EmittedFrozen++;
    } else InvalidFrozen++;
  }
  ProbePrint(L"HOUJI GPU CALL TRACE FIRST FAILURE END: appended=%u invalid=%u through=%lu; one-time frozen window retained across cleanup and Resume\n",
    EmittedFrozen,InvalidFrozen,mCallTraceFirstFailure.last);
}
