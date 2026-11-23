#!/usr/bin/env python3
"""Actual host-preparation orchestration, RAM queues and strict stop gates."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1]
program=r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "GpuCpInit.h"
#include "GpuHostProfile.h"
#include "GpuLiveLog.h"
#include "GpuFirmwareMemory.h"
#define HOUJI_GPU_CP_DEVICE_NATIVE_H
#define hsc_run original_hsc_run
#define hsc_run_lpac original_hsc_run_lpac
#include "GpuScratchContext.h"
#undef hsc_run
#undef hsc_run_lpac
#define STATIC static
#define VOID void
#define CONST const
#define TRUE 1
#define Print(...) ((void)0)
static unsigned mHostProfileReady,mGxMapped,mScratchAssigned,mScratchReady,mSharedCount,mSecureAssigned,mSecureTableOwned,mCodeReady;
static struct hsc_result mScratchResult;
static struct {unsigned attached;}mSecureContext;
static struct {unsigned owned;}mSecureMemory;
static struct {unsigned phase,code,record_ready;}mGen7;
static struct {unsigned gx_ready,acked,clear_confirmed;}mGxStart;
static struct hfm_result mFirmwareMemory;
static struct hfm_allocation mCodeMemory,mGpuOnlyMemory;
static uint64_t mScratchTablePhysical,*mScratchTables;
static ArmSmmu4KConfig mScratchConfig;
static ArmSmmu4KResult mScratchBuilt;
static uint32_t hfi[GGH_BYTES/4];
static unsigned calls[5],failure,reads,fail_read,memchecks,fail_mem,saves,tpl,healthy;
static unsigned mappings,map_failure,mapping_tpl,guard_calls,guards_at_mapping,guards_at_save;
static unsigned clock_witnesses,clock_failure,graphics_queries,graphics_failure;
static int StockBootstrapHealthy(void*c){(void)c;return healthy;}
static int ScratchGuard(void*c){(void)c;return failure==5 || !mScratchAssigned;}
static int ScratchAudit(void){return failure==6;}
static int GpuTryRead32(uint64_t a,uint32_t*v){if(++reads==fail_read)return 1;assert(a==0x3da0048 || a==0x3dc0058 || a==0x3dc2058);*v=a==0x3da0048?0:0x400;if(failure==7)*v|=2;return 0;}
static int Gen7Guard(void*c){(void)c;guard_calls++;return failure==8;}
static uint32_t MmioRead32(uint64_t a){assert(a==0x3d02020);return failure==9;}
static void StockHfiBarrier(void*c){(void)c;}
static int FirmwareVerifyPages(uint64_t p,void*c,unsigned n,unsigned nc){(void)p;(void)c;(void)n;(void)nc;return ++memchecks==fail_mem;}
static int FirmwareVerifyPagesQuiet(uint64_t p,void*c,unsigned n,unsigned nc){return FirmwareVerifyPages(p,c,n,nc);}
static unsigned LiveLogTpl(void*c){(void)c;return tpl;}
static void LiveLogLower(void*c){(void)c;assert(tpl==16);tpl=4;}
static int LiveLogRestore(void*c){(void)c;assert(tpl==4);tpl=16;return failure==11;}
static uint64_t ProbeCheckpoint(const char*s){assert(tpl==4 && !strcmp(s,"HOST-ring-normalGPU-OOB-code-config-ready-NO-CP"));assert(mappings==1 && mapping_tpl==4 && guard_calls==2);guards_at_save=guard_calls;saves++;return failure==10?UINT64_C(0x8000000000000015):0;}
static int ContextDelay(void*c,unsigned us){(void)c;(void)us;return 0;}
static int ScratchRead32(void*c,uint32_t a,uint32_t*v){(void)c;(void)a;(void)v;assert(0);return 1;}
static int ScratchRead64(void*c,uint32_t a,uint64_t*v){(void)c;(void)a;(void)v;assert(0);return 1;}
static int ScratchWrite32(void*c,uint32_t a,uint32_t v){(void)c;(void)a;(void)v;assert(0);return 1;}
static int ScratchWrite64(void*c,uint32_t a,uint64_t v){(void)c;(void)a;(void)v;assert(0);return 1;}
static struct hsc_result attached_scratch(void){return (struct hsc_result){.phase=5,.enabled=1,.attached=1,.retained=1,.lpac=1,.sid0_attached=1,.lpac_attached=1,.sid0_smr=0x80000000u,.lpac_smr=0x80000001u};}
static unsigned hsc_run_lpac(const struct hgp_io*i,const ArmSmmu4KConfig*c,const ArmSmmu4KResult*b,struct hsc_result*r){(void)i;(void)c;(void)b;assert(mScratchAssigned && ++calls[0]==1);*r=attached_scratch();r->code=failure==1;r->attached=failure!=1;if(failure==12)r->lpac=0;if(failure==13)r->lpac_attached=0;if(failure==14)r->sid0_attached=0;return failure==1;}
static unsigned RunGxStart(struct hhb_result*);
static unsigned RunCodeBind(void);
static unsigned RunGen7Config(void);
static void GxStartReport(void){}
static void CodeBindReport(void){}
static void Gen7Report(void){}
static int CpDeviceNgNrePrepare(void){assert(tpl==4 && guard_calls==2 && !saves && ++mappings==1);mapping_tpl=tpl;guards_at_mapping=guard_calls;return map_failure;}
static int GpuClockWitnessR1(void){assert(tpl==4 && mappings==1 && !map_failure && !saves && ++clock_witnesses==1);return clock_failure;}
static int PrepareGraphicsPrerequisites(void){assert(tpl==4 && mappings==1 && clock_witnesses==1 && !map_failure && !clock_failure && !saves && ++graphics_queries==1);return graphics_failure;}
#include "GpuHostPreparationNative.h"
static unsigned RunGxStart(struct hhb_result*b){assert(b->completed==5 && mScratchResult.attached && calls[0]==1 && ++calls[1]==1);if(HostContextQualified())return HCI_GUARD;mGxStart.gx_ready=mGxStart.acked=mGxStart.clear_confirmed=failure!=2;return failure==2;}
static unsigned RunCodeBind(void){assert(calls[1]==1 && mGxStart.gx_ready && ++calls[2]==1);return failure==3;}
static unsigned RunGen7Config(void){assert(calls[2]==1 && ++calls[3]==1);mGen7.phase=6;mGen7.record_ready=1;return failure==4;}
static void reset(void){memset(&mHostPrep,0,sizeof mHostPrep);memset(&mScratchResult,0,sizeof mScratchResult);memset(&mGen7,0,sizeof mGen7);memset(&mGxStart,0,sizeof mGxStart);memset(calls,0,sizeof calls);mHostProfileReady=mGxMapped=mScratchReady=mCodeReady=healthy=1;mScratchAssigned=mSharedCount=mSecureAssigned=mSecureContext.attached=mSecureMemory.owned=mSecureTableOwned=0;failure=reads=fail_read=memchecks=fail_mem=saves=mappings=map_failure=mapping_tpl=guard_calls=guards_at_mapping=guards_at_save=clock_witnesses=clock_failure=graphics_queries=graphics_failure=0;tpl=16;mFirmwareMemory.count=1;mFirmwareMemory.memory[5].cpu=hfi;assert(!ggh_init(hfi,sizeof hfi,GGH_IOVA));}
static void mapping_matches_save(void){assert(mappings==saves);if(!saves)assert(!mappings && !mapping_tpl);else assert(mappings==1 && mapping_tpl==4 && guards_at_mapping==2 && guards_at_save==2);}
int main(void){unsigned cases=0;struct hhb_result b;reset();b=(struct hhb_result){.completed=5};assert(!RunHostPreparation(&b) && mHostPrep.phase==6 && mHostPrep.log.phase==5 && mHostPrep.log.restored && saves==1 && tpl==16 && mScratchResult.attached && mScratchResult.lpac && mScratchResult.lpac_attached && !mSecureAssigned && !mSecureTableOwned);assert(mappings==1 && guard_calls==3 && mHostPrep.log.guards==3);mapping_matches_save();unsigned total_reads=reads,total_mem=memchecks;cases++;
 for(unsigned f=1;f<=11;f++){reset();b=(struct hhb_result){.completed=5};failure=f;assert(RunHostPreparation(&b) && mHostPrep.phase!=6 && tpl==16);if(f<=4)for(unsigned i=f;i<4;i++)assert(!calls[i]);mapping_matches_save();if(f==10)assert(mappings==1 && saves==1 && mHostPrep.log.restored && mHostPrep.log.code==HLL_SAVE);cases++;}
 for(unsigned i=1;i<=total_reads;i++){reset();b=(struct hhb_result){.completed=5};fail_read=i;assert(RunHostPreparation(&b) && mHostPrep.phase!=6 && tpl==16);mapping_matches_save();cases++;}
 for(unsigned i=1;i<=total_mem;i++){reset();b=(struct hhb_result){.completed=5};fail_mem=i;assert(RunHostPreparation(&b) && mHostPrep.phase!=6 && tpl==16);mapping_matches_save();cases++;}
 for(unsigned q=0;q<17;q++){reset();b=(struct hhb_result){.completed=5};hfi[6+12*q+11]=4;assert(RunHostPreparation(&b) && !saves && !mappings && tpl==16);cases++;}
 for(unsigned gate=0;gate<11;gate++){reset();b=(struct hhb_result){.completed=5};if(gate==0)b.code=1;if(gate==1)b.completed=4;if(gate==2)mHostProfileReady=0;if(gate==3)mHostPrep.started=1;if(gate==4)mScratchAssigned=1;if(gate==5)mSecureAssigned=1;if(gate==6)mSharedCount=1;if(gate==7)mScratchReady=0;if(gate==8)mCodeReady=0;if(gate==9)healthy=0;if(gate==10)failure=6;assert(RunHostPreparation(&b) && !calls[0] && !saves && !mappings);cases++;}
 for(unsigned gate=0;gate<12;gate++){reset();mScratchAssigned=1;mScratchResult=attached_scratch();if(gate==0)mHostProfileReady=0;if(gate==1)mGxMapped=0;if(gate==2)mScratchAssigned=0;if(gate==3)mScratchResult.attached=0;if(gate==4)mScratchReady=0;if(gate==5)mSharedCount=1;if(gate==6)mSecureAssigned=1;if(gate==7)mSecureContext.attached=1;if(gate==8)mSecureMemory.owned=1;if(gate==9)mSecureTableOwned=1;if(gate==10)healthy=0;if(gate==11)failure=5;assert(HostContextQualified() && !reads);cases++;}
 // A nominally successful wrapper without either live stream proof cannot
 // advance to code/config or publish the preparation checkpoint.
 for(unsigned f=12;f<=14;f++){reset();b=(struct hhb_result){.completed=5};failure=f;assert(RunHostPreparation(&b) && !calls[2] && !calls[3] && !saves && !mappings);cases++;}
 for(unsigned field=0;field<8;field++)for(unsigned variant=0;variant<2;variant++){
  reset();mScratchAssigned=1;mScratchResult=attached_scratch();
  unsigned *proof[]={&mScratchResult.code,&mScratchResult.phase,&mScratchResult.enabled,&mScratchResult.attached,&mScratchResult.retained,&mScratchResult.lpac,&mScratchResult.sid0_attached,&mScratchResult.lpac_attached};
  *proof[field]^=variant?3u:1u;assert(HostContextQualified() && !reads);cases++;
 }
 for(unsigned field=0;field<4;field++)for(unsigned bit=0;bit<32;bit++){
  reset();mScratchAssigned=1;mScratchResult=attached_scratch();
  uint32_t *proof[]={&mScratchResult.sid0_smr,&mScratchResult.sid0_s2cr,&mScratchResult.lpac_smr,&mScratchResult.lpac_s2cr};
  *proof[field]^=1u<<bit;assert(HostContextQualified() && !reads);cases++;
 }
 for(unsigned save_failure=0;save_failure<2;save_failure++) {
  reset();b=(struct hhb_result){.completed=5};map_failure=1;if(save_failure)failure=10;
  assert(RunHostPreparation(&b) && mHostPrep.phase!=6 && saves==1 && mappings==1 && tpl==16);
  assert(mHostPrep.log.phase==5 && mHostPrep.log.restored && mHostPrep.log.guards==3 && guard_calls==3 && mHostPrep.log.code==HLL_SAVE && (mHostPrep.log.status>>63));
  mapping_matches_save();cases++;
 }
 for(unsigned save_failure=0;save_failure<2;save_failure++) {
  reset();b=(struct hhb_result){.completed=5};clock_failure=1;if(save_failure)failure=10;
  assert(RunHostPreparation(&b) && mHostPrep.phase!=6 && saves==1 && mappings==1 && clock_witnesses==1 && tpl==16);
  assert(mHostPrep.log.restored && mHostPrep.log.code==HLL_SAVE);mapping_matches_save();cases++;
 }
 for(unsigned save_failure=0;save_failure<2;save_failure++) {
  reset();b=(struct hhb_result){.completed=5};graphics_failure=1;if(save_failure)failure=10;
  assert(RunHostPreparation(&b) && mHostPrep.phase!=6 && saves==1 && mappings==1 && clock_witnesses==1 && graphics_queries==1 && tpl==16);
  assert(mHostPrep.log.restored && mHostPrep.log.code==HLL_SAVE);mapping_matches_save();cases++;
 }
 reset();b=(struct hhb_result){.completed=5};assert(!RunHostPreparation(&b) && graphics_queries==1 && saves==1);cases++;
 reset();b=(struct hhb_result){.completed=5};map_failure=1;assert(RunHostPreparation(&b) && !graphics_queries && saves==1);cases++;
 reset();b=(struct hhb_result){.completed=5};clock_failure=1;assert(RunHostPreparation(&b) && !graphics_queries && saves==1);cases++;
 printf("PASS: %u actual host-preparation cases; attach/OOB/code/config order, existing real HLL3guards/TPL,17queue drains, every fault/read/attribute/FS failure, TPL4 mapping and read-only clock witness before existing save, witness failure saved then stopped, no secure context or CP\n",cases);
}
'''
with tempfile.TemporaryDirectory() as d:
 f=Path(d);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
