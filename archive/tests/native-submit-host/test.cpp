#include "NativeAdrenoRing.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <initializer_list>
#define CHECK(x) do {if(!(x)){fprintf(stderr,"line%d %s\n",__LINE__,#x);abort();}}while(0)
static uint32_t regs[4096],ring[8192],fence[16];static unsigned writes,publishes,acquires;static bool finish;static uint64_t clock_us;
static int rd(void*,uint32_t reg,uint32_t*out){CHECK(reg<4096);*out=regs[reg];return 0;}
static int wr(void*,uint32_t reg,uint32_t v){CHECK(reg==0x807);++writes;regs[reg]=v;if(finish){fence[1]=fence[3]=1;regs[0x806]=v;}return 0;}
static int bar(void*){return 0;}
static int pub(void*,const volatile uint32_t*p,size_t n){CHECK(p==ring && n==sizeof ring);++publishes;CHECK(ring[51]==0x70970001 && ring[52]==0x80000001);return 0;}
static int acq(void*,volatile uint32_t*p,size_t n){CHECK(p==fence && n==64);++acquires;return 0;}
static uint64_t now(void*){clock_us+=100;return clock_us;}
static void setup(){memset(regs,0,sizeof regs);memset(ring,0,sizeof ring);memset(fence,0,sizeof fence);writes=publishes=acquires=0;clock_us=0;regs[0x800]=0x620c0000;regs[0x802]=0x20c;regs[0x804]=0x620c8100;regs[0xa98]=0x620c8108;regs[0x806]=regs[0x807]=51;regs[0x808]=1;fence[0]=51;}
int main(){const NativeAdrenoRingIo io={nullptr,wr,rd,bar};const NativeAdrenoRingCache cache={nullptr,pub,acq};const NativeAdrenoRingClock clock={nullptr,now,nullptr};unsigned cases=0;
 for(unsigned bad=0;bad<10;bad++){setup();NativeAdrenoRing r;const unsigned reg[]={0x800,0x801,0x802,0x804,0x805,0xa98,0xa99,0x806,0x807,0x808};regs[reg[bad]]^=1;CHECK(r.adoptLive(&io,&cache,ring,sizeof ring,0x620c0000,fence,sizeof fence,0x620c8100,51)!=0 && !writes && !publishes && fence[0]==51);++cases;}
 for(unsigned slot:{1u,3u}){setup();NativeAdrenoRing r;fence[slot]=123;CHECK(r.adoptLive(&io,&cache,ring,sizeof ring,0x620c0000,fence,sizeof fence,0x620c8100,51)!=0 && !writes && fence[slot]==123);++cases;}
 for(bool completed:{false,true}){setup();finish=completed;NativeAdrenoRing r;CHECK(!r.adoptLive(&io,&cache,ring,sizeof ring,0x620c0000,fence,sizeof fence,0x620c8100,51) && !writes && !publishes && fence[0]==51);const uint32_t ib[]={0x70bf8003,0x62084000,0,287};uint32_t sequence=0,observed=0;CHECK(!r.submitFramed(ib,4,&sequence) && sequence==1 && writes==1 && publishes==1 && regs[0x807]==97);auto code=r.wait(1,&clock,1000,&observed);CHECK(code==(completed?NativeAdrenoRingFenceComplete:NativeAdrenoRingFenceTimeout));CHECK(observed==(completed?1u:0u));CHECK(r.completedFence()==(completed?1u:0u));++cases;}
 printf("PASS %u real NativeAdrenoRing adoption/fence boundary cases; synthetic MMIO/completion peer, no GPU emulation\n",cases);
}
