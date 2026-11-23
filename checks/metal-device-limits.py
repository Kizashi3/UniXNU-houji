#!/usr/bin/env python3
"""Check runtime limits-record decoding; no Apple framework or GPU emulation."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = r'''
#include "NativeDeviceLimits.h"
#include <array>
#include <cassert>
#include <string>
using houji_device_limits::populate;
int main() {
    // The Photos consumer loads its uint32 dimensions at 0x84 and 0x88.
    // Unrelated synthetic fields include floats and a 64-bit aligned tail.
    std::string type="{?=";
    for(unsigned i=0;i<33;i++) type+="\"unused"+std::to_string(i)+"\""+(i==26||i==27?"f":"I");
    type+="\"maxTextureWidth2D\"I\"maxTextureHeight2D\"I\"tail\"Q}";
    std::array<uint8_t,152> record;record.fill(0x7e);
    assert(populate(record.data(),record.size(),type.c_str(),16384,8192));
    uint32_t dimensions[2];memcpy(dimensions,record.data()+0x84,sizeof dimensions);
    assert(dimensions[0]==16384 && dimensions[1]==8192);
    // A 1x1 image must remain 1x1 when clamped by these actual answers.
    assert(std::min(1u,dimensions[0])==1 && std::min(1u,dimensions[1])==1);
    for(size_t i=0;i<record.size();i++)if(i<0x84||i>=0x8c)assert(record[i]==0x7e);
    const auto before=record;
    for(auto invalid:{"", "{?", "{?=", "{?=\"broken", "{?=\"maxTextureWidth2D\"Q}",
                      "{?=\"maxTextureWidth2D\"I\"maxTextureWidth2D\"I}",
                      "{?=\"unknown\"@}", "{?=\"unknown\"[4I]}"}) {
        assert(!populate(record.data(),record.size(),invalid,16384,8192));assert(record==before);
    }
    for(size_t size=0;size<record.size();size++) {
        assert(!populate(record.data(),size,type.c_str(),16384,8192));assert(record==before);
    }
    for(uint64_t bad:std::array<uint64_t,3>{0,0x100000000ull,UINT64_MAX}) {
        assert(!populate(record.data(),record.size(),type.c_str(),bad,8192));
        assert(!populate(record.data(),record.size(),type.c_str(),16384,bad));assert(record==before);
    }
    assert(!populate(nullptr,record.size(),type.c_str(),1,1));
    assert(!populate(record.data(),record.size(),nullptr,1,1));
    assert(populate(record.data(),record.size(),type.c_str(),1,1));
    memcpy(dimensions,record.data()+0x84,sizeof dimensions);assert(dimensions[0]==1 && dimensions[1]==1);
}
'''
with tempfile.TemporaryDirectory(prefix='houji-metal-limits-') as tmp:
    folder = Path(tmp)
    cpp = folder / 'check.cpp'
    cpp.write_text(source)
    binary = folder / 'check'
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I'+str(ROOT/'graphics/metal/AdrenoMetal'),
                    str(cpp), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print('PASS: limits record offsets, field preservation, malformed ABI, bounds, overflow and 1x1 clamp; no device claim')
