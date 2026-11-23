// SPDX-License-Identifier: MIT
#include "../native/gpu/metal/BlockTextureMemory.h"
#include <assert.h>
#include <vector>
using namespace native_linear;
int main() {
    BlockLayout p;
    assert(!blockPlan(UINT64_MAX,UINT64_MAX,4,4,16,16384,p));
    for(uint64_t width:{1,4,5,215,216,217,1200})for(uint64_t height:{1,4,5,216,2670}) {
        assert(blockPlan(width,height,4,4,16,16384,p));
        auto &l=p.blocks;std::vector<uint8_t> src(l.bytes+32),dst(l.bytes+32,0xa7),back(l.bytes+32,0x2a);
        for(size_t i=0;i<src.size();i++)src[i]=uint8_t(i*13);
        Region r={0,0,0,width,height,1};
        assert(blockCopy(p,dst.data(),src.data(),0,l.row,l.row*l.height,0,0,r,true));
        assert(blockCopy(p,dst.data(),back.data(),0,l.row,l.row*l.height,0,0,r,false));
        assert(!memcmp(src.data(),back.data(),size_t(l.row*l.height)));
        for(size_t i=size_t(l.row*l.height);i<dst.size();i++)assert(dst[i]==0xa7);
        const auto before=dst;
        assert(!blockCopy(p,dst.data(),src.data(),UINT64_MAX,l.row,0,0,0,r,true));
        assert(!blockCopy(p,dst.data(),src.data(),0,l.row-1,0,0,0,r,true));
        assert(!blockCopy(p,dst.data(),src.data(),0,l.row,0,1,0,r,true));
        for(auto bad:{Region{1,0,0,width,1,1},Region{0,1,0,1,height,1},Region{0,0,0,width,height,2}})
            assert(!blockCopy(p,dst.data(),src.data(),0,l.row,0,0,0,bad,true));
        assert(before==dst);
    }
    assert(blockPlan(216,216,4,4,16,16384,p));
    assert(p.blocks.row==864 && p.blocks.height==54 && p.blocks.bytes==49152);
    assert(blockPlan(217,215,4,4,16,16384,p));
    std::vector<uint8_t> source(64,0x33),target(p.blocks.bytes,0xa7);
    Region edge={216,212,0,1,3,1};
    assert(blockCopy(p,target.data(),source.data(),0,16,16,0,0,edge,true));
    size_t at=53*p.blocks.row+54*16;
    for(size_t i=0;i<target.size();i++)assert(target[i]==(i>=at && i<at+16?0x33:0xa7));
}
