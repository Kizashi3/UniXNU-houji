#!/usr/bin/env python3
"""Actual prearm/reset-only .inc; no device, firmware build or misc writes."""
from pathlib import Path
import re
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
snippet = p / "native/gpu/handoff/GpuPrearmedRecoveryNative.inc"
source = snippet.read_text()
reset = source[source.index("STATIC BOOLEAN GpuPowerRecoveryResetWithoutIO"):]
# Structural boundary in addition to runtime counters: no unsafe-path logger,
# indirect block hook or filesystem callback may be introduced unnoticed.
code = re.sub(r"/\*.*?\*/|//[^\n]*", "", reset, flags=re.S)
assert set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", code)) == {
    "GpuPowerRecoveryResetWithoutIO", "if", "HoujiGpuMaySave", "ResetSystem"
}
for token in ("ProbeCheckpoint", "ReadBlocks", "WriteBlocks", "Print", "CompareMem", "hgr_record"):
    assert token not in code

program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include "GpuRecoveryRequest.h"
#define STATIC static
#define VOID void
#define TRUE 1
#define FALSE 0
#define UINT8 uint8_t
#define UINT32 uint32_t
#define BOOLEAN unsigned
#define EFI_STATUS uint64_t
#define EFI_SUCCESS UINT64_C(0)
#define EFI_ERROR_STATUS UINT64_C(0x8000000000000007)
#define CompareMem memcmp
#define EfiResetCold 0
typedef struct EFI_BLOCK_IO_MEDIA {
 unsigned MediaPresent,BlockSize,IoAlign;uint64_t LastBlock;uint32_t MediaId;
} EFI_BLOCK_IO_MEDIA;
typedef struct EFI_BLOCK_IO_PROTOCOL EFI_BLOCK_IO_PROTOCOL;
struct EFI_BLOCK_IO_PROTOCOL {
 EFI_BLOCK_IO_MEDIA *Media;
 EFI_STATUS (*ReadBlocks)(EFI_BLOCK_IO_PROTOCOL *,uint32_t,uint64_t,unsigned,void *);
};
static unsigned mXnuUfsRun,may_save;
static EFI_BLOCK_IO_PROTOCOL *mGpuCheckpointParent;
static unsigned reads,commits,resets,prints,cases,may_save_reads;
static unsigned bit_to_flip,tail_change,read_warning,read_error,commit_warning,commit_error;
static unsigned unsafe_read,unsafe_commit,change_parent_read,change_id_commit,reset_reenter;
static EFI_BLOCK_IO_MEDIA media,other_media;
static EFI_BLOCK_IO_PROTOCOL parent,other_parent;
struct runtime {void (*ResetSystem)(unsigned,EFI_STATUS,unsigned,void *);};
static struct runtime runtime,*gRT;
static BOOLEAN HoujiGpuMaySave(void) {may_save_reads++;return may_save;}
static void CapturePrint(const wchar_t *format,...) {assert(format);prints++;}
#define Print CapturePrint
static EFI_STATUS ProbeCheckpoint(const char *);
static void Reset(unsigned,EFI_STATUS,unsigned,void *);
#include "GpuPrearmedRecoveryNative.inc"
static EFI_STATUS Read(EFI_BLOCK_IO_PROTOCOL *io,uint32_t id,uint64_t lba,unsigned bytes,void *out) {
 assert(io==&parent && id==media.MediaId && lba==1024 && bytes==4096 && !((uintptr_t)out&4095));
 assert(mXnuUfsRun && may_save && !commits && !resets);reads++;
 memset(out,0xa5,bytes);assert(hgr_record(out,864));
 if(bit_to_flip<864*8)((uint8_t *)out)[bit_to_flip/8]^=(uint8_t)(1u<<(bit_to_flip%8));
 if(tail_change)((uint8_t *)out)[864]^=1; // Reserved tail is outside the exact request comparison.
 if(unsafe_read)may_save=0;
 if(change_parent_read)mGpuCheckpointParent=&other_parent;
 return read_error?EFI_ERROR_STATUS:read_warning?1:EFI_SUCCESS;
}
static EFI_STATUS ProbeCheckpoint(const char *stage) {
 assert(!strcmp(stage,"gpu-power-prearmed-exact-no-wipe-recovery") && reads==1 &&
  mXnuUfsRun && may_save && !resets);commits++;
 if(unsafe_commit)may_save=0;
 if(change_id_commit)media.MediaId++;
 return commit_error?EFI_ERROR_STATUS:commit_warning?1:EFI_SUCCESS;
}
static void Reset(unsigned kind,EFI_STATUS status,unsigned bytes,void *extra) {
 assert(kind==EfiResetCold && status==EFI_SUCCESS && !bytes && !extra);
 assert(mXnuUfsRun && !may_save && mGpuPowerRecoveryResetAttempted && !mGpuPowerRecoveryArmed);
 unsigned before_reads=reads,before_commits=commits,before_prints=prints;
 resets++;
 if(reset_reenter)assert(!GpuPowerRecoveryResetWithoutIO());
 assert(reads==before_reads && commits==before_commits && prints==before_prints);
}
static void Fresh(void) {
 media=(EFI_BLOCK_IO_MEDIA){1,4096,4096,0x100000,77};other_media=media;
 parent=(EFI_BLOCK_IO_PROTOCOL){&media,Read};other_parent=(EFI_BLOCK_IO_PROTOCOL){&other_media,Read};
 mGpuCheckpointParent=&parent;runtime.ResetSystem=Reset;gRT=&runtime;
 mXnuUfsRun=may_save=1;reads=commits=resets=prints=may_save_reads=0;
 bit_to_flip=864*8;tail_change=read_warning=read_error=commit_warning=commit_error=0;
 unsafe_read=unsafe_commit=change_parent_read=change_id_commit=reset_reenter=0;
 mGpuPowerRecoveryPrearmAttempted=mGpuPowerRecoveryArmed=mGpuPowerRecoveryResetAttempted=0;
}
static void NoReset(void) {
 unsigned r=reads,c=commits,p=prints;
 assert(!GpuPowerRecoveryResetWithoutIO() && !resets && reads==r && commits==c && prints==p);cases++;
}
int main(void) {
 Fresh();assert(GpuPowerRecoveryPrearm() && mGpuPowerRecoveryArmed && reads==1 && commits==1);cases++;
 unsigned r=reads,c=commits,p=prints;
 assert(!GpuPowerRecoveryPrearm() && reads==r && commits==c && prints==p);cases++;
 NoReset(); // Save is still safe: the existing storage-backed helper remains the caller's path.
 may_save=0;reset_reenter=1;
 assert(!GpuPowerRecoveryResetWithoutIO() && resets==1 && reads==r && commits==c && prints==p);cases++;
 assert(!GpuPowerRecoveryResetWithoutIO() && resets==1 && reads==r && commits==c && prints==p);cases++;
 for(unsigned i=0;i<864*8;i++) {
  Fresh();bit_to_flip=i;assert(!GpuPowerRecoveryPrearm() && reads==1 && !commits && !mGpuPowerRecoveryArmed);
  may_save=0;NoReset();
 }
 for(unsigned i=0;i<4;i++) {
  Fresh();if(i==0)read_warning=1;if(i==1)read_error=1;if(i==2)commit_warning=1;if(i==3)commit_error=1;
  assert(!GpuPowerRecoveryPrearm() && !mGpuPowerRecoveryArmed);
  assert(reads==1 && commits==(i>=2));may_save=0;NoReset();
 }
 for(unsigned i=0;i<11;i++) {
  Fresh();
  if(i==0)mXnuUfsRun=0;if(i==1)may_save=0;if(i==2)mGpuCheckpointParent=0;
  if(i==3)parent.Media=0;if(i==4)media.MediaPresent=0;if(i==5)media.BlockSize=512;
  if(i==6)media.IoAlign=8192;if(i==7)media.LastBlock=1023;if(i==8)parent.ReadBlocks=0;
  if(i==9)gRT=0;if(i==10)runtime.ResetSystem=0;
  assert(!GpuPowerRecoveryPrearm() && !reads && !commits && !mGpuPowerRecoveryArmed);NoReset();
 }
 for(unsigned i=0;i<4;i++) {
  Fresh();if(i==0)unsafe_read=1;if(i==1)unsafe_commit=1;if(i==2)change_parent_read=1;if(i==3)change_id_commit=1;
  assert(!GpuPowerRecoveryPrearm() && reads==1 && !mGpuPowerRecoveryArmed);
  assert(commits==(i==1 || i==3));may_save=0;NoReset();
 }
 for(unsigned i=0;i<4;i++) {
  Fresh();assert(GpuPowerRecoveryPrearm());may_save=0;
  if(i==0)mXnuUfsRun=0;if(i==1)mGpuPowerRecoveryArmed=0;
  if(i==2)gRT=0;if(i==3)runtime.ResetSystem=0;
  NoReset();
 }
 Fresh();tail_change=1;media.IoAlign=0;assert(GpuPowerRecoveryPrearm());may_save=0;
 assert(!GpuPowerRecoveryResetWithoutIO() && resets==1);cases++;
 printf("prearmed recovery actual snippet: %u cases PASS; all 6912 BCB bit flips rejected; reset path zero I/O/logging\n",cases);
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="houji-prearmed-recovery-") as tmp:
    f = Path(tmp) / "test.c"
    f.write_text(program)
    binary = Path(tmp) / "test"
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-g",
                    "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-I", str(p / "native/gpu/uefi"),
                    "-I", str(p / "native/gpu/handoff"), str(f), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
