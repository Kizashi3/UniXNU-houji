// SPDX-License-Identifier: MIT
#include "../native/gpu/metal/LinearTextureMemory.h"
#include <assert.h>
#include <vector>
using namespace native_linear;
int main() {
    Layout l;
    assert(!plan(UINT64_MAX,4,4,UINT64_MAX,16384,l));
    assert(!plan(16,16,4,63,16384,l));
    assert(!plan(16,UINT64_MAX,4,64,16384,l));
    assert(!plan(16,16,4,64,123,l));
    for(uint64_t bpp:{1,2,4,8,16})for(uint64_t width:{1,3,19,1200}){
        assert(plan(width,7,bpp,(width*bpp+63)&~63ull,16384,l));
        std::vector<uint8_t> source(size_t(width*bpp*7+31),0x2a),texture(size_t(l.bytes+32),0x91),back(source.size(),0x33);
        for(size_t i=0;i<source.size();i++)source[i]=uint8_t(i*17);
        Region r={0,1,0,width,5,1};const uint64_t row=width*bpp,offset=13;
        assert(copy(l,texture.data(),source.data(),offset,row,row*5,0,0,r,true));
        assert(copy(l,texture.data(),back.data(),offset,row,row*5,0,0,r,false));
        assert(!memcmp(source.data()+offset,back.data()+offset,size_t(row*5)));
        for(uint64_t y=0;y<7;y++)for(uint64_t x=0;x<l.row;x++){
            const bool written=y>=1 && y<6 && x<row;
            if(!written)assert(texture[size_t(y*l.row+x)]==0x91);
        }
        const auto original=texture;
        for(auto bad:{Region{width,0,0,1,1,1},Region{0,7,0,1,1,1},Region{0,0,1,1,1,1},Region{0,0,0,1,1,2}})
            assert(!copy(l,texture.data(),source.data(),0,row,row*5,0,0,bad,true));
        assert(!copy(l,texture.data(),source.data(),UINT64_MAX,row,row*5,0,0,r,true));
        assert(!copy(l,texture.data(),source.data(),0,row,row*5,1,0,r,true));
        assert(!copy(l,texture.data(),source.data(),0,row,row*5,0,1,r,true));
        assert(original==texture);
    }
}
