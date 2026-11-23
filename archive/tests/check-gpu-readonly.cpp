// SPDX-License-Identifier: BSD-2-Clause-Patent
// Exercise the actual prerequisite state machine before any physical MMIO.
#include "../native/gpu/GpuReadPolicy.h"
#include "../native/gpu/GpuPowerObserve.h"
#include <assert.h>
#include <stdio.h>
struct Fake {
  unsigned calls=0,fail=0,smmu=0;
  uint32_t cfg=1,cx=0,cxhw=1u<<31,ahb=0,gate=1;
};
static int read(void *cookie,unsigned window,uint32_t offset,uint32_t *value) {
  auto &f=*static_cast<Fake *>(cookie);assert(hgr_allowed(window,offset));
  ++f.calls;if(f.calls==f.fail)return 1;
  if(window==2){++f.smmu;*value=0;return 0;}
  *value=window==0?(offset==4?f.cfg:1):offset==0x9108?f.cx:
    offset==0x9168?f.cxhw:offset==0x911c?f.ahb:f.gate;
  return 0;
}
static ggp_report run(Fake &f){ggp_report r={};ggp_io io={&f,read};ggp_observe(&io,&r);return r;}
int main(){
  unsigned allowed=0;
  for(unsigned w=0;w<3;w++)for(unsigned o=0;o<hgr_size[w];o++)allowed+=hgr_allowed(w,o);
  assert(allowed==13);assert(!hgr_allowed(3,0));assert(!hgr_allowed(0,UINT32_MAX));
  Fake f;auto r=run(f);assert(r.stage==GGP_OBSERVED&&r.valid_fields==0x1fff&&f.calls==13&&f.smmu==5);
  for(unsigned fail=1;fail<=13;fail++){
    Fake e;e.fail=fail;auto result=run(e);assert(result.stage==GGP_IO_ERROR&&e.calls==fail);
  }
  Fake off;off.cfg=0;r=run(off);assert(r.stage==GGP_CFG_OFF&&off.calls==3&&off.smmu==0);
  Fake cx;cx.cx=1;r=run(cx);assert(r.stage==GGP_CX_OFF&&cx.calls==5&&cx.smmu==0);
  Fake hw;hw.cxhw=0;r=run(hw);assert(r.stage==GGP_CX_OFF&&hw.smmu==0);
  Fake ahb;ahb.ahb=1u<<31;r=run(ahb);assert(r.stage==GGP_CLOCK_OFF&&ahb.smmu==0);
  Fake gate;gate.gate=0;r=run(gate);assert(r.stage==GGP_CLOCK_OFF&&gate.smmu==0);
  Fake absent;absent.cfg=UINT32_MAX;r=run(absent);assert(r.stage==GGP_IO_ERROR&&absent.calls==1);
  puts("PASS: exactly 13 whitelisted reads; all injected I/O failures stop; unpowered or unclocked state never reads SMMU");
}
