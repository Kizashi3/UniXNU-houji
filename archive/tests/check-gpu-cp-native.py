#!/usr/bin/env python3
"""Actual scalar SCM whitelist/resume and CP diagnostic read/health callbacks."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1];s=(p/'native/gpu/uefi/GpuCpInitNative.h').read_text()
def fn(name):
 a=s.index('STATIC int '+name+'(');b=s.index('{',a)+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b].replace('__asm__ volatile("dsb sy":::"memory");','')
body='\n'.join(fn(name) for name in ('CpLeaseOwned','CpFastHealth','CpHealth','CpReady','CpApertureCall','CpAperture','CpRead'))
program=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#define GG_HOST_TEST 1
#include "GpuCpInit.h"
#include "GpuCpPoll.h"
#include "vendor/Ace5Gmu/giulia_gpu_scm.h"
#define STATIC static
#define VOID void
#define CONST const
#define NULL ((void*)0)
typedef uint64_t UINT64;
static unsigned mCpPollArmed;
static uint64_t mCpPollRoots[HCF_ROOTS];
static struct hcf_result mCpPoll;
static unsigned mGxMapped=1,mFirmwareHeld=1,mStockCalled=1,mScratchAssigned=1,mScratchReady=1,mDmaZeroRetained=1,mSecureAssigned=1,mSecureDomainReady=1,mSecureTableOwned=1;
enum {HFM_ALL=0xff};
static struct {unsigned retained;}mFirmwareMemory={HFM_ALL};
static struct {unsigned fw_ready,hfi_ready,query_ack;}mStockResult={1,1,1};
static struct {unsigned attached;}mScratchResult={1},mSecureContext={1};
static uint32_t fast_regs[HCF_REGS];
static uint64_t fast_roots[HCF_ROOTS];
static unsigned roots_read;
static unsigned mGen7Mapped=1,mCodeReady=1,qualified_bad,pre_ready_bad,hw_power,hw_fence,hw_busy,mmios,actual_smc,cases,scenario;
static struct {unsigned code,phase,record_ready;} mGen7={0,6,1};
static struct {unsigned gx_ready,acked,clear_confirmed;} mGxStart={1,1,1};
static struct {unsigned available,owned,revoked,result_valid,status_a0,status_a1;} mSecureMemory={2,1,1,1,0,0};
static struct ggs_state mSecureCx={.convention_verified=1,.init_succeeded=1},mCpAperture;
static unsigned mCpApertureCalled,mCpApertureResult,mCpApertureValid;
static uint64_t mCpApertureElapsed;
static unsigned pre_raw_calls;
static unsigned CpPreRawCheckpoint(void){pre_raw_calls++;return 0;}
static int GxQualified(void*c){(void)c;return (int)qualified_bad;}
static int Gen7Guard(void*c){(void)c;return (int)pre_ready_bad;}
static int SecureCxDelay(void*c,unsigned ms){(void)c;assert(ms==30);return 0;}
static uint64_t BatchCounter(void){return 10;}
static uint64_t BatchMicroseconds(uint64_t from){(void)from;return 1;}
static uint32_t MmioRead32(uint32_t a){mmios++;if(mCpPollArmed){for(unsigned i=0;i<HCF_REGS;i++)if(hcf_reg(i)==a)return fast_regs[i];assert(0);}if(a==0x3d7e340)return hw_power;if(a==0x3d8ec40)return hw_fence;if(a==0x3d8ec30)return hw_busy;return 0;}
static uint64_t MmioRead64(uint32_t a){assert(mCpPollArmed);roots_read++;for(unsigned i=0;i<HCF_ROOTS;i++)if(hcf_root(i)==a)return fast_roots[i];assert(0);return 0;}
static uint32_t fail_guarded_read;
static int GpuTryRead32(uint64_t a,uint32_t*v){if(a==fail_guarded_read)return 2;*v=MmioRead32((uint32_t)a);return 0;}
static int GpuTryRead64(uint64_t a,uint64_t*v){if(a==fail_guarded_read)return 2;*v=MmioRead64((uint32_t)a);return 0;}
static int ggs_aarch64_call(void*c,struct ggs_regs*r){(void)c;actual_smc++;
 if(scenario==1 && actual_smc==1){r->x[0]=(uint64_t)-12;return 0;}
 if(scenario==2 && actual_smc==1){r->x[0]=1;r->x[6]=0x123abc;return 0;}
 if(scenario==2 && actual_smc==2)assert(r->x[0]==1 && r->x[6]==0x123abc);
 if(scenario==3){r->x[0]=2;return 0;}
 if(scenario==4){r->x[0]=(uint64_t)-1;return 0;}
 if(scenario==5)return 1;
 r->x[0]=0;r->x[1]=0xdeadbeef;return 0;
}
'''+body+r'''
int main(void){struct ggs_regs fixed={{0x42000c1b,4,0xffff0000u,0xffffffffu,0xffffffffu,0xffffffffu,0,0}};
 for(unsigned i=0;i<8;i++)for(unsigned bit=0;bit<64;bit++) {
  struct ggs_regs r=fixed;r.x[i]^=UINT64_C(1)<<bit;unsigned old=actual_smc;mCpApertureValid=1;
  assert(CpApertureCall(0,&r) && actual_smc==old && !mCpApertureValid);cases++;
 }
 for(unsigned i=0;i<6;i++) {
  scenario=i;actual_smc=0;mCpAperture=(struct ggs_state){0};
  unsigned before=pre_raw_calls;unsigned result=CpAperture(0);assert((result==0)==(i<3));assert(pre_raw_calls==before+(i<3));assert(actual_smc==(i==1 || i==2?2:1));
  if(i==3 || i==5)assert(mCpAperture.quarantined);
  if(i<3)assert(mCpApertureValid && mCpAperture.last_output.x[1]==0xdeadbeef);cases++;
 }
 scenario=0;mCpAperture=(struct ggs_state){0};hw_busy=1u<<23;assert(CpHealth(0));cases++;
 for(unsigned bit=0;bit<2;bit++){hw_power=1u<<bit;assert(!CpHealth(0));cases++;}hw_power=0;
 for(unsigned bit=0;bit<32;bit++){hw_fence=1u<<bit;assert(!CpHealth(0));cases++;}hw_fence=0;
 qualified_bad=1;assert(!CpHealth(0));qualified_bad=0;cases++;
 for(uint32_t a=0x3d00000;a<0x3e00000;a+=4) {
  unsigned allowed=a==0x3d8ec30 || a==0x3d00840 || a==0x3d02020 || a==0x3d00804;uint32_t value;
  assert((!CpRead(0,a,&value))==allowed);cases++;
 }
 mCpAperture.quarantined=1;unsigned old=actual_smc;assert(CpAperture(0) && actual_smc==old);cases++;
 mCpAperture.quarantined=0;mCpPollArmed=1;
 uint32_t good[HCF_REGS]={1,1,1,1,0,0x80000000,0,0,0,0,0,0,0,1u<<23,0x100,1,0x1027,0x1027,0x1027};
 memcpy(fast_regs,good,sizeof good);
 for(unsigned i=0;i<HCF_ROOTS;i++)fast_roots[i]=mCpPollRoots[i]=UINT64_C(0x751000000400000)+i*4096;
 assert(CpHealth(0) && roots_read==6);cases++;
 const uint32_t masks[HCF_REGS]={0x80000003,0x80000003,0x80000001,0x80000001,1,0x80000000,0x80000000,0xffffffff,0xc00001fe,0xc00001fe,0xc00001fe,3,0xffffffff,0,0x1ff,1,0xffffefff,0xffffefff,0xffffefff};
 for(unsigned i=0;i<HCF_REGS;i++)for(unsigned bit=0;bit<32;bit++) {
  memcpy(fast_regs,good,sizeof good);fast_regs[i]^=1u<<bit;mCpPoll=(struct hcf_result){0};roots_read=0;
  unsigned bad=!!(masks[i]&(1u<<bit));assert((!CpHealth(0))==bad);
  if(bad){assert(mCpPoll.failed && mCpPoll.failed_index==i);if(i<HCF_POWER_REGS)assert(!roots_read && mCpPoll.last.valid_regs==127 && !mCpPoll.last.valid_roots);}
  cases++;
 }
 memcpy(fast_regs,good,sizeof good);
 for(unsigned i=0;i<HCF_ROOTS;i++)for(unsigned bit=0;bit<64;bit++) {
  fast_roots[i]^=UINT64_C(1)<<bit;mCpPoll=(struct hcf_result){0};assert(!CpHealth(0) && mCpPoll.failed_index==HCF_REGS+i && mCpPoll.reason==4);
  fast_roots[i]^=UINT64_C(1)<<bit;cases++;
 }
 mCpPoll=(struct hcf_result){0};fast_regs[8]=2;assert(!CpHealth(0));struct hcf_snapshot first=mCpPoll.first_fault;
 fast_regs[8]=4;assert(!CpHealth(0) && !memcmp(&first,&mCpPoll.first_fault,sizeof first));memcpy(fast_regs,good,sizeof good);assert(CpHealth(0) && mCpPoll.failed);cases++;
 unsigned *owned[]={&mGen7Mapped,&mCodeReady,&mGen7.phase,&mGen7.record_ready,&mGxMapped,&mGxStart.gx_ready,&mGxStart.acked,&mGxStart.clear_confirmed,&mFirmwareHeld,&mStockCalled,&mFirmwareMemory.retained,&mStockResult.fw_ready,&mStockResult.hfi_ready,&mStockResult.query_ack,&mScratchAssigned,&mScratchReady,&mScratchResult.attached,&mDmaZeroRetained,&mSecureAssigned,&mSecureDomainReady,&mSecureTableOwned,&mSecureContext.attached,&mSecureMemory.owned,&mSecureMemory.revoked,&mSecureMemory.result_valid,&mSecureCx.init_succeeded};
 for(unsigned i=0;i<sizeof owned/sizeof owned[0];i++){unsigned saved=*owned[i],before=mmios;*owned[i]=0;assert(!CpHealth(0) && mmios==before);*owned[i]=saved;cases++;}
 unsigned *zero[]={&mGen7.code,&mSecureMemory.status_a0,&mSecureMemory.status_a1,&mSecureCx.quarantined,&mCpAperture.quarantined};
 for(unsigned i=0;i<sizeof zero/sizeof zero[0];i++){unsigned before=mmios;*zero[i]=1;assert(!CpHealth(0) && mmios==before);*zero[i]=0;cases++;}
 for(unsigned i=0;i<HCF_REGS+HCF_ROOTS;i++){
  fail_guarded_read=i<HCF_REGS?hcf_reg(i):hcf_root(i-HCF_REGS);mCpPoll=(struct hcf_result){0};
  assert(!CpHealth(0) && mCpPoll.failed && mCpPoll.reason==6 && mCpPoll.failed_index==i);
  if(i<HCF_REGS)assert(mCpPoll.last.valid_regs==((1u<<i)-1) && !mCpPoll.last.valid_roots);
  else assert(mCpPoll.last.valid_roots==((1u<<(i-HCF_REGS))-1));cases++;
 }
 fail_guarded_read=0;assert(CpHealth(0));
 struct hcf_snapshot sample=mCpPoll.last;unsigned index;
 for(unsigned i=0;i<HCF_REGS;i++){struct hcf_snapshot t=sample;t.valid_regs^=1u<<i;assert(hcf_check(&t,mCpPollRoots,&index)==2);cases++;}
 for(unsigned i=0;i<HCF_ROOTS;i++){struct hcf_snapshot t=sample;t.valid_roots^=1u<<i;assert(hcf_check(&t,mCpPollRoots,&index)==2);cases++;}
 printf("PASS: %u actual native scalar/read/health and fast-lease cases; full retained ownership, clock checks before gated reads, every register/root bit, first fault retained, busy allowed\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu'),'-I',str(p/'native/gpu/uefi'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
