#!/usr/bin/env python3
"""Compile the real descriptor guard; invalid geometry must never permit mailbox reads."""
from pathlib import Path
import subprocess
import tempfile
p = Path(__file__).resolve().parents[1]
s = (p / 'native/gpu/HoujiGpuProbe.inc').read_text()
guard = s[s.index('  uint32_t remoteBytes='):s.index('\n  IOLog("HOUJI GPU QMP RO: magic=')]
program = '#include <stdint.h>\n#include <assert.h>\n#include <stdio.h>\n'
program += 'static bool valid(uint32_t words[15]){\n' + guard + '\nreturn geometry;}\n'
program += r'''
int main(){
 uint32_t w[15]={0x4d41494c,1}; w[7]=128;w[8]=0x40;w[13]=128;w[14]=0xc0;
 assert(valid(w));w[0]^=1;assert(!valid(w));w[0]^=1;
 w[1]=2;assert(!valid(w));w[1]=1;
 const uint32_t bad[]={0,1,7,127,0x401,UINT32_MAX,UINT32_MAX-3};
 for(uint32_t b:bad){auto old=w[7];w[7]=b;assert(!valid(w));w[7]=old;}
 for(uint32_t b:bad){auto old=w[13];w[13]=b;assert(!valid(w));w[13]=old;}
 const uint32_t offsets[]={0,4,0x38,0x3d,0x400,0x401,UINT32_MAX,UINT32_MAX-3};
 for(uint32_t b:offsets){auto old=w[8];w[8]=b;assert(!valid(w));w[8]=old;}
 for(uint32_t b:offsets){auto old=w[14];w[14]=b;assert(!valid(w));w[14]=old;}
 w[14]=0x80;assert(!valid(w));w[14]=0xc0;assert(valid(w));
 w[8]=0x380;w[7]=0x80;assert(valid(w));w[7]=0x84;assert(!valid(w));
 puts("PASS: real QMP descriptor guard rejects malformed, unaligned, overlapping and overflowing mailbox ranges");
}
'''
with tempfile.TemporaryDirectory() as directory:
    d = Path(directory); (d/'check.cpp').write_text(program)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    str(d/'check.cpp'),'-o',str(d/'check')],check=True)
    subprocess.run([str(d/'check')],check=True)
