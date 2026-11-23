#include "../native/power/interactive-runtime/iokit/Kernel/arm/HoujiDvfsPolicy.h"
#include <cassert>
#include <cstdio>

int main() {
 const uint32_t khz[]={499200,998400,1497600,1996800,2496000,2956800};
 unsigned quiet=0,low=0;
 // A touch must reach the existing cap immediately, even after idle at the floor.
 unsigned f=houjiDvfsInteractiveFloor(khz,6,0,true,true,false,&quiet);
 assert(f==5 && houjiDvfsChoose(khz,6,0,0,f,&low)==5);
 // Continued animation retains headroom after the finger leaves the screen.
 for(unsigned n=0;n<20;n++){
  f=houjiDvfsInteractiveFloor(khz,6,0,true,false,true,&quiet);
  assert(khz[f]*100ULL>=khz[5]*60ULL && f<6);
 }
 // Once both activity sources expire, four low samples must actually lower it.
 unsigned cur=5;low=0;
 for(unsigned n=0;n<4;n++){
  f=houjiDvfsInteractiveFloor(khz,6,0,true,false,false,&quiet);
  cur=houjiDvfsChoose(khz,6,cur,0,f,&low);
  assert(cur==(n<3?5u:0u));
 }
 // E cores are not pinned to their cap just by a touch; high load still raises them.
 quiet=0;f=houjiDvfsInteractiveFloor(khz,6,0,false,true,false,&quiet);assert(f==0);
 assert(houjiDvfsChoose(khz,6,0,1000,f,&low)==5);
 // Hysteresis is cancelled by renewed demand, not by its own held return value.
 cur=5;low=0;assert(houjiDvfsChoose(khz,6,cur,0,0,&low)==5 && low==1);
 assert(houjiDvfsChoose(khz,6,cur,1000,0,&low)==5 && low==0);
 for(unsigned busy=0;busy<=1200;busy++)for(unsigned index=0;index<6;index++){
  quiet=0;low=0;f=houjiDvfsInteractiveFloor(khz,6,busy,true,false,false,&quiet);
  const unsigned target=houjiDvfsChoose(khz,6,index,busy,f,&low);assert(target<6);
 }
 std::puts("PASS: bounded factory indices; immediate touch rise; frame tail; idle downshift; renewed-load hysteresis");
}
