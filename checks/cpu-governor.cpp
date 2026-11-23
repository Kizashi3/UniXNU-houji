#include "../kernel/overlay/iokit/Kernel/arm/HoujiDvfsPolicy.h"
#include <cassert>
#include <cstdio>

int main() {
 const uint32_t khz[]={499200,998400,1497600,1996800,2496000,2956800};
 unsigned quiet=0,low=0;
 // Touch gives a busy domain headroom without forcing its factory maximum.
 unsigned f=houjiDvfsInteractiveFloor(khz,6,100,true,true,false,&quiet);
 assert(f<5 && khz[f]*100ULL>=khz[5]*60ULL);
 assert(houjiDvfsChoose(khz,6,0,100,f,&low)==f);
 // Continued animation retains headroom while this domain is doing work.
 for(unsigned n=0;n<20;n++){
  f=houjiDvfsInteractiveFloor(khz,6,100,true,false,true,&quiet);
  assert(khz[f]*100ULL>=khz[5]*60ULL && f<6);
 }
 // Global activity on another domain must not pin this idle domain. Exercise
 // touch AND frame throughout: the old policy never released its maximum.
 unsigned cur=5;low=0;
 for(unsigned n=0;n<20;n++){
  f=houjiDvfsInteractiveFloor(khz,6,0,true,true,true,&quiet);
  cur=houjiDvfsChoose(khz,6,cur,0,f,&low);
 }
 assert(quiet==12 && f==0 && cur==0);
 // Demand after that idle transition must still rise immediately to the cap.
 f=houjiDvfsInteractiveFloor(khz,6,1000,true,true,true,&quiet);
 assert(houjiDvfsChoose(khz,6,cur,1000,f,&low)==5 && quiet==0);
 // E cores are not pinned to their cap just by a touch; high load still raises them.
 quiet=0;f=houjiDvfsInteractiveFloor(khz,6,0,false,true,false,&quiet);assert(f==0);
 assert(houjiDvfsChoose(khz,6,0,1000,f,&low)==5);
 // After UI hints expire, modest background load must not recreate the old
 // unconditional 50% floor. The load governor still owns frequency demand.
 quiet=0;cur=5;low=0;
 for(unsigned n=0;n<24;n++){
  f=houjiDvfsInteractiveFloor(khz,6,200,true,false,false,&quiet);
  assert(f==0 && quiet==0);
  cur=houjiDvfsChoose(khz,6,cur,200,f,&low);
 }
 assert(cur==0);
 // Hint expiry doesn't hide real CPU saturation, and a renewed interaction
 // restores the already-qualified UI headroom immediately.
 f=houjiDvfsInteractiveFloor(khz,6,1000,true,false,false,&quiet);
 assert(f==0 && houjiDvfsChoose(khz,6,cur,1000,f,&low)==5);
 f=houjiDvfsInteractiveFloor(khz,6,200,true,true,false,&quiet);
 assert(khz[f]*100ULL>=khz[5]*60ULL);
 // Hysteresis is cancelled by renewed demand, not by its own held return value.
 cur=5;low=0;assert(houjiDvfsChoose(khz,6,cur,0,0,&low)==5 && low==1);
 assert(houjiDvfsChoose(khz,6,cur,1000,0,&low)==5 && low==0);
 for(unsigned busy=0;busy<=1200;busy++)for(unsigned index=0;index<6;index++){
  quiet=0;low=0;f=houjiDvfsInteractiveFloor(khz,6,busy,true,false,false,&quiet);
  const unsigned target=houjiDvfsChoose(khz,6,index,busy,f,&low);assert(target<6);
 }
 std::puts("PASS: bounded factory indices; UI-only headroom; background load releases floor after hint expiry; immediate loaded rise; hysteresis");
}
