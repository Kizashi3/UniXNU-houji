/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Combined, one-shot pre-2D / post-timeout observations before CP failure or
 * reset. Include after GraphicsRuntimeCheck(unsigned)'s forward declaration.
 * It returns zero on success, as does hcs_io.owned. Busy is allowed here; all
 * current epoch, power, OOB, routes/roots and fault gates remain the owner's.
 * Capture only records CPU RAM: no print, BS/FS, indexed selectors, writes,
 * frequency changes, new fault matcher or relaxation of completion checks.
 *
 * GPUCC source: MiCode Xiaomi_Kernel_OpenSource 317e609aa4fb956c3aff565b62215e5a8041ca0c,
 * drivers/clk/qcom/gpucc-pineapple.c:183-201,338-353,427-470;
 * clk-branch.c:47-72. Live houji FDT:9072-9075 fixes base 0x03d90000.
 * CBCR bit31 means CLK_OFF, not a measured Hz. Bit0 is only HLOS enable;
 * other hardware votes may keep a branch running. CMD/CFG stay undecoded.
 */
#ifndef HOUJI_GPU_GRAPHICS_STALL_NATIVE_H
#define HOUJI_GPU_GRAPHICS_STALL_NATIVE_H
#include "GpuCpStall.h"
enum {HOUJI_GRAPHICS_STALL_NATIVE_STAGES=2,HOUJI_GRAPHICS_STALL_NATIVE_CLOCKS=6,HOUJI_GRAPHICS_STALL_NATIVE_REGS=HCS_REGS+HOUJI_GRAPHICS_STALL_NATIVE_CLOCKS};
struct houji_graphics_stall_native_result {
 unsigned started,stage,code,phase,reported,guards,reads,attempted,valid;
 int owner_code,read_code;
 unsigned failed_read_seen;
 uint32_t failed_read_address,failed_read_returned;
 int failed_read_code;
 struct hcs_result cp;
 uint32_t clock[HOUJI_GRAPHICS_STALL_NATIVE_CLOCKS];
};
STATIC struct houji_graphics_stall_native_result mGraphicsStall[HOUJI_GRAPHICS_STALL_NATIVE_STAGES];
STATIC unsigned mGraphicsStallRunning,mGraphicsStallStage;
STATIC uint32_t GraphicsStallClockAddress(unsigned I) {
 STATIC CONST uint32_t Addresses[]={0x03d990a8,0x03d990c8,0x03d990c0,
  0x03d9914c,0x03d99474,0x03d99478};
 return I<HOUJI_GRAPHICS_STALL_NATIVE_CLOCKS?Addresses[I]:0;
}
STATIC CONST CHAR8 *GraphicsStallClockName(unsigned I) {
 STATIC CONST CHAR8 *CONST Names[]={"GX_GFX3D_CBCR","GX_GFX3D_RDVM_CBCR",
  "GX_FF_CBCR","CX_FF_CBCR","FF_CMD_RCGR","FF_CFG_RCGR"};
 return I<HOUJI_GRAPHICS_STALL_NATIVE_CLOCKS?Names[I]:"invalid";
}
STATIC int GraphicsStallOwned(VOID *Cookie) {
 (VOID)Cookie;
 if(!mGraphicsStallRunning || mGraphicsStallStage>=HOUJI_GRAPHICS_STALL_NATIVE_STAGES ||
  !mGraphicsStall[mGraphicsStallStage].started ||
  !mHostRingUnsafe || mGpuSaveAllowed)return 1;
 return GraphicsRuntimeCheck(0);
}
STATIC int GraphicsStallRead(VOID *Cookie,uint32_t Address,uint32_t *Value) {
 (VOID)Cookie;
 if(!Value || !mGraphicsStallRunning || mGraphicsStallStage>=HOUJI_GRAPHICS_STALL_NATIVE_STAGES ||
  !mGraphicsStall[mGraphicsStallStage].started)return HCS_ARGUMENT;
 unsigned Allowed=0;
 for(unsigned I=0;I<HCS_REGS;I++)if(Address==hcs_address(I))Allowed=1;
 for(unsigned I=0;I<HOUJI_GRAPHICS_STALL_NATIVE_CLOCKS;I++)if(Address==GraphicsStallClockAddress(I))Allowed=1;
 if(!Allowed)return HCS_ARGUMENT;
 int Code=GpuTryRead32(Address,Value);
 if(Code) {
  struct houji_graphics_stall_native_result *R=&mGraphicsStall[mGraphicsStallStage];
  R->failed_read_seen=1;R->failed_read_address=Address;
  // Diagnostic returned bits survive even if the read API wrote them before
  // returning an error. They never enter a valid raw observation slot.
  R->failed_read_returned=*Value;R->failed_read_code=Code;
 }
 return Code;
}
STATIC unsigned CaptureGraphicsStall(unsigned Stage) {
 if(Stage>=HOUJI_GRAPHICS_STALL_NATIVE_STAGES || mGraphicsStallRunning)return HCS_ARGUMENT;
 struct houji_graphics_stall_native_result *R=&mGraphicsStall[Stage];
 if(R->started)return HCS_REUSED;
 *R=(struct houji_graphics_stall_native_result){.started=1,.stage=Stage,.phase=1};
 mGraphicsStallStage=Stage;mGraphicsStallRunning=1;
 CONST struct hcs_io Io={NULL,GraphicsStallOwned,GraphicsStallRead};
 R->code=hcs_capture(&Io,Stage,&R->cp);
 R->guards=R->cp.guards;R->reads=R->cp.reads;
 R->attempted=R->cp.attempted;R->valid=R->cp.valid;
 R->owner_code=R->cp.owner_code;R->read_code=R->cp.read_code;
 if(R->code)goto Done;
 R->phase=2;
 for(unsigned I=0;I<HOUJI_GRAPHICS_STALL_NATIVE_CLOCKS;I++) {
  ++R->guards;R->owner_code=GraphicsStallOwned(NULL);
  if(R->owner_code){R->code=HCS_OWNER;goto Done;}
  uint32_t Value=0;R->attempted|=1u<<(HCS_REGS+I);++R->reads;
  R->read_code=GraphicsStallRead(NULL,GraphicsStallClockAddress(I),&Value);
  if(R->read_code){R->code=HCS_READ;goto Done;}
  R->clock[I]=Value;R->valid|=1u<<(HCS_REGS+I);
 }
 R->phase=3;++R->guards;R->owner_code=GraphicsStallOwned(NULL);
 if(R->owner_code){R->code=HCS_OWNER;goto Done;}
 R->phase=4;
Done:
 mGraphicsStallRunning=0;return R->code;
}
STATIC VOID GraphicsStallReport(VOID) {
 if(mGraphicsStallRunning || mHostRingUnsafe || !mGpuSaveAllowed)return;
 for(unsigned S=0;S<HOUJI_GRAPHICS_STALL_NATIVE_STAGES;S++) {
  struct houji_graphics_stall_native_result *R=&mGraphicsStall[S];
  if(!R->started || R->reported)continue;
  R->reported=1;
  Print(L"HOUJI GPU GRAPHICS STALL: stage=%u code=%u phase=%u guards=%u reads=%u attempted=%x valid=%x owner-code=%d read-code=%d; stage0=pre2D stage1=post-timeout, raw observations before reset, not an idle/frequency qualification\n",
   R->stage,R->code,R->phase,R->guards,R->reads,R->attempted,R->valid,R->owner_code,R->read_code);
  for(unsigned I=0;I<HCS_REGS;I++)Print(L"HOUJI GPU GRAPHICS STALL CP: stage=%u i=%u name=%a address=%x raw=%x attempted=%u valid=%u; IB registers are not an asserted SQE PC\n",
   S,I,hcs_name(I),hcs_address(I),R->cp.raw[I],(R->attempted>>I)&1,(R->valid>>I)&1);
  for(unsigned I=0;I<HOUJI_GRAPHICS_STALL_NATIVE_CLOCKS;I++) {
   unsigned Valid=(R->valid>>(HCS_REGS+I))&1;
   Print(L"HOUJI GPU GRAPHICS STALL CLOCK: stage=%u i=%u name=%a address=%x raw=%x attempted=%u valid=%u CBCR-off-valid=%u clock-off-bit31=%u; no Hz or all-votes inference\n",
    S,I,GraphicsStallClockName(I),GraphicsStallClockAddress(I),R->clock[I],
    (R->attempted>>(HCS_REGS+I))&1,Valid,Valid && I<4,
    Valid && I<4?R->clock[I]>>31:0);
  }
  if(R->failed_read_seen)Print(L"HOUJI GPU GRAPHICS STALL READ ERROR: stage=%u address=%x code=%d returned-raw=%x valid=0; retained error output, not a successful hardware observation\n",
   S,R->failed_read_address,R->failed_read_code,R->failed_read_returned);
 }
}
#endif
