// SPDX-License-Identifier: MIT
#include "../native/display/SurfaceUseCount.h"
#include <assert.h>
#include <thread>
#include <vector>
#include <cstring>
int main(){
    alignas(16) uint8_t state[64];memset(state,0x91,sizeof state);
    auto *count=reinterpret_cast<volatile uint64_t *>(state+0x18);*count=0;
    uint64_t after;
    assert(houjiSurfaceUseAdjust(count,false,after)==HoujiSurfaceUseResult::Underflow && !after);
    assert(houjiSurfaceUseAdjust(count,true,after)==HoujiSurfaceUseResult::Updated && after==1);
    assert(houjiSurfaceUseAdjust(count,false,after)==HoujiSurfaceUseResult::Updated && !after);
    *count=UINT64_MAX;
    assert(houjiSurfaceUseAdjust(count,true,after)==HoujiSurfaceUseResult::Overflow && after==UINT64_MAX);
    *count=0;std::vector<std::thread> threads;
    for(unsigned i=0;i<8;i++)threads.emplace_back([&]{for(unsigned j=0;j<10000;j++){
        uint64_t result;
        assert(houjiSurfaceUseAdjust(count,true,result)==HoujiSurfaceUseResult::Updated);
        assert(houjiSurfaceUseAdjust(count,false,result)==HoujiSurfaceUseResult::Updated);
    }});
    for(auto &thread:threads)thread.join();assert(!*count);
    for(unsigned i=0;i<sizeof state;i++)if(i<0x18 || i>=0x20)assert(state[i]==0x91);
}
