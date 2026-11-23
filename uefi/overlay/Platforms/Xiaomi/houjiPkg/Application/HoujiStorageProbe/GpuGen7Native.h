/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_GEN7_NATIVE_H
#define HOUJI_GPU_GEN7_NATIVE_H
#include "GpuGen7Config.h"
STATIC struct h7c_result mGen7;
STATIC BOOLEAN mGen7Mapped;
STATIC int Gen7PrepareMapping(VOID) {
 UINT64 SavedPar,Par=0;BOOLEAN Good=TRUE;EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);
 __asm__ volatile("mrs %0,par_el1":"=r"(SavedPar));
 for(unsigned I=0;I<H7C_OPS+H7C_PAIRS;I++) {
  UINT64 Address=I<H7C_OPS?h7c_ops[I].address:h7c_power_regs[I-H7C_OPS].address;
  __asm__ volatile("at s1e1r,%1; isb; mrs %0,par_el1":"=r"(Par):"r"(Address):"memory");
  if((Par&1) || (Par&0x0000fffffffff000ULL)!=(Address&~4095ULL) || ((Par>>56)!=0 && (Par>>56)!=4))Good=FALSE;
  if(I<H7C_OPS && h7c_ops[I].kind!=3) {
   __asm__ volatile("at s1e1w,%1; isb; mrs %0,par_el1":"=r"(Par):"r"(Address):"memory");
   if((Par&1) || (Par&0x0000fffffffff000ULL)!=(Address&~4095ULL) || ((Par>>56)!=0 && (Par>>56)!=4))Good=FALSE;
  }
 }
 __asm__ volatile("msr par_el1,%0; isb"::"r"(SavedPar):"memory");gBS->RestoreTPL(Tpl);
 mGen7Mapped=Good;Print(L"HOUJI GPU GEN7 MAP: actual CPU identity Device read/write=%u operations=%u record-pairs=%u last-PAR=%lx; AT only\n",Good,H7C_OPS,H7C_PAIRS,Par);return Good?0:1;
}
STATIC int Gen7Guard(VOID *Cookie) {
 (VOID)Cookie;return !mGen7Mapped || mCodeBind.code || mCodeBind.phase!=6 || mCodeBind.verified!=15 || CodeBindGuard(NULL);
}
STATIC int Gen7Read(VOID *Cookie,uint32_t Address,uint32_t *Value) {
 (VOID)Cookie;BOOLEAN Allowed=Address==0x3d02020;
 for(unsigned I=0;I<H7C_OPS;I++)if(h7c_ops[I].kind!=2 && h7c_ops[I].address==Address)Allowed=TRUE;
 for(unsigned I=0;I<H7C_PAIRS;I++)if(h7c_power_regs[I].address==Address)Allowed=TRUE;
 if(!Value || !Allowed || Gen7Guard(NULL))return 1;
 *Value=MmioRead32(Address);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int Gen7Write(VOID *Cookie,uint32_t Address,uint32_t Value) {
 (VOID)Cookie;if(mGen7.phase!=2 || mGen7.step>=H7C_OPS)return 1;
 CONST struct h7c_op *Op=&h7c_ops[mGen7.step];CONST struct h7c_record *R=&mGen7.records[mGen7.step];
 if(Op->kind==3 || Op->address!=Address || !(R->valid&2) || R->expected!=Value ||
  (Op->kind==1 && (!(R->valid&1) || Value!=((R->before&~Op->mask)|Op->value))) ||
  (Op->kind!=1 && Value!=Op->value) || Gen7Guard(NULL))return 1;
 MmioWrite32(Address,Value);__asm__ volatile("dsb sy":::"memory");return 0;
}
STATIC int Gen7Publish(VOID *Cookie,CONST uint32_t *Words,unsigned Count) {
 (VOID)Cookie;if(!Words || Count!=H7C_WORDS || mGen7.power_pairs!=H7C_PAIRS ||
  mGen7.completed!=H7C_OPS || Gen7Guard(NULL) || ScratchAudit())return 1;
 if(Words[0] || Words[1] || Words[2] || Words[3]!=(H7C_IFPC|(H7C_PREEMPT<<8)))return 1;
 for(unsigned I=0;I<H7C_PAIRS;I++)if(Words[4+I*2]!=(h7c_power_regs[I].address-0x3d00000)/4 || Words[5+I*2]!=mGen7.power_values[I])return 1;
 volatile uint32_t *To=(volatile uint32_t *)((UINTN)mCodeMemory.cpu+HCC_RECORD_OFFSET);
 for(unsigned I=0;I<1024;I++)if(To[I])return 1; // Own virgin record; no CP has written it.
 for(unsigned I=0;I<Count;I++)To[I]=Words[I];
 for(unsigned I=0;I<1024;I++)if(To[I]!=(I<Count?Words[I]:0))return 1;
 __asm__ volatile("dsb sy":::"memory");
 if(FirmwarePublish(NULL,&mCodeMemory))return 1;
 mGen7.record_crc=hcc_crc32((CONST uint8_t *)(UINTN)To,4096);return Gen7Guard(NULL)?1:0;
}
STATIC unsigned RunGen7Config(VOID) {
 CONST struct h7c_io Io={NULL,Gen7Guard,Gen7Read,Gen7Write,ContextDelay,Gen7Publish};return h7c_run(&Io,&mGen7);
}
STATIC VOID Gen7Report(VOID) {
 Print(L"HOUJI GPU GEN7 CONFIG: code=%u phase=%u step=%u completed=%u/%u reads=%u writes=%u record=%u pairs=%u/%u crc=%x SQE=%x last=%x/%x op=%u observed-valid=%u; no CP enable/RAW/PAS/trust bypass\n",
 mGen7.code,mGen7.phase,mGen7.step,mGen7.completed,H7C_OPS,mGen7.reads,mGen7.writes,mGen7.record_ready,mGen7.power_pairs,H7C_PAIRS,mGen7.record_crc,mGen7.control_after,mGen7.last_address,mGen7.last_value,mGen7.last_operation,mGen7.observed_valid);
 for(unsigned I=0;I<H7C_OPS && I<=mGen7.step;I++) {
  CONST struct h7c_record *R=&mGen7.records[I];CONST struct h7c_op *Op=&h7c_ops[I];
  Print(L"HOUJI GPU GEN7 ROW: i=%u %a address=%x kind=%u valid=%x before=%x wanted=%x observed=%x verify-mask=%x written=%u polls=%u\n",I,Op->name,Op->address,Op->kind,R->valid,R->before,R->expected,R->after,Op->verify,R->written,R->polls);
 }
 for(unsigned I=0;I<mGen7.power_pairs && I<H7C_PAIRS;I++)Print(L"HOUJI GPU GEN7 RECORD: i=%u %a offset=%x value=%x\n",I,h7c_power_regs[I].name,(h7c_power_regs[I].address-0x3d00000)/4,mGen7.power_values[I]);
}
#endif
