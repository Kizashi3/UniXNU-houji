// SPDX-License-Identifier: BSD-2-Clause-Patent
// Actual stage/vote functions, with only clock, event and register accesses
// replaced. This checks cleanup decisions, not RPMh hardware behavior.
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include "QcomRpmh.h"
struct Window {};
static Window gRsc;
static QcomRscLayout gLayout;
static QcomRpmhResource gLcx,gLmx,gXo;
static constexpr uint32_t kRscTcs=0xd00,kMillisecondScale=1;
static uint32_t regs[0x10000/4],gRscIrqBits;
static volatile uint32_t gRscDone;
static volatile int32_t native_adsp_stats[16];
static bool gProxyHeld;
static int gTcs=-1;
static unsigned writes,checkpoints,events,completeAfter;
static uint64_t now;
static uint32_t base(){return kRscTcs+gLayout.tcs_stride;}
static uint32_t rd(const Window &,uint64_t at){assert(!(at&3) && at<sizeof regs);return regs[at/4];}
static void wr(const Window &,uint64_t at,uint32_t value){
    assert(!(at&3) && at<sizeof regs);++writes;
    if(at==kRscTcs+gLayout.irq_clear)regs[(kRscTcs+gLayout.irq_status)/4]&=~value;
    else regs[at/4]=value;
    if(at==base()+gLayout.control && (value&(1u<<24)))regs[(base()+gLayout.status)/4]=0;
}
static void clock_interval_to_deadline(unsigned ms,unsigned,uint64_t *deadline){*deadline=now+ms;}
static uint64_t mach_absolute_time(){return now;}
static uint32_t waitEvents(uint32_t ms){now+=ms;return 0;}
static void service(uint32_t){
    if(++events==completeAfter){regs[(base()+gLayout.status)/4]=1;regs[(kRscTcs+gLayout.irq_status)/4]|=2;}
}
static void IOLog(const char *,...){}
static void houji_ufs_checkpoint(const char *,unsigned){++checkpoints;}
#include "adsp-functions.inc"
static void reset(){
    memset(regs,0,sizeof regs);gLayout=qcom_rsc_layout(0x30200);regs[(base()+gLayout.status)/4]=1;
    gTcs=-1;gProxyHeld=false;gRscDone=gRscIrqBits=0;writes=events=0;now=0;completeAfter=1;
    gLcx.address=0x30030;gLmx.address=0x30040;gXo.address=0x300d0;
}
int main(){
    stage(12);for(unsigned i=0;i<2000;i++)stage(13);assert(checkpoints==2);
    reset();assert(vote(7,4)==0 && gProxyHeld);assert(!regs[(base()+gLayout.cmd_enable)/4]);
    assert(regs[(base()+gLayout.cmd_data)/4]==7 && regs[(base()+gLayout.cmd_stride+gLayout.cmd_data)/4]==4);
    assert(regs[(base()+2*gLayout.cmd_stride+gLayout.cmd_data)/4]==3);
    events=0;assert(vote(0,0)==0 && !gProxyHeld);
    reset();regs[(base()+gLayout.status)/4]=0;assert(vote(7,4)==-16 && !writes);
    reset();regs[(base()+gLayout.cmd_enable)/4]=1;assert(vote(7,4)==-16 && !writes);
    reset();regs[(kRscTcs+gLayout.irq_status)/4]=2;assert(vote(7,4)==-16 && !writes);
    reset();completeAfter=0;assert(vote(7,4)==-60);
    assert(regs[(base()+gLayout.cmd_enable)/4]==7 && (regs[(base()+gLayout.control)/4]&(1u<<24)));
    auto previous=writes;assert(vote(7,4)==-16 && writes==previous); // Uncertain TCS never recycled.
    reset();completeAfter=10;assert(!vote(7,4) && now==100); // Completion on final event wait.
    puts("PASS: actual ADSP phase checkpoint deduplication and RSC idle/timeout/completion cleanup policy; no hardware");
}
