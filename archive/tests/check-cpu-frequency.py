#!/usr/bin/env python3
"""Compile the real read-only frequency conversion with wrap and invalid samples."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
header = root / 'native/ufs-root/HoujiCpuFrequency.h'
program = r'''
#include <cstdint>
#include <cassert>
#include <cstdio>
#include "HoujiCpuFrequency.h"
int main() {
  uint32_t khz=123;
  unsigned cases=0;
  for(uint32_t mhz=50;mhz<=5000;mhz+=50) {
    uint32_t delta=mhz*100000;
    for(uint32_t before : {0U,0xfffffff0U}) {
      assert(houjiCpuFrequencyKHz(before,uint32_t(before+delta),1920000,19200000,&khz));
      assert(khz==mhz*1000); ++cases;
    }
  }
  assert(!houjiCpuFrequencyKHz(0,0,1920000,19200000,&khz));
  assert(!houjiCpuFrequencyKHz(0,600000000,1920000,19200000,&khz));
  assert(!houjiCpuFrequencyKHz(0,1,0,19200000,&khz));
  assert(!houjiCpuFrequencyKHz(0,1,1,0,&khz));
  assert(!houjiCpuFrequencyKHz(0,1,1,1000000001ULL,&khz));
  assert(!houjiCpuFrequencyKHz(0,1,19200000,19200000,&khz));
  assert(!houjiCpuFrequencyKHz(0,1,1,19200000,nullptr));
  assert(cases==200);
  puts("CPU frequency: 200 normal/wrap samples and 7 invalid cases PASS");
}
'''.replace('#include <cstdio>', '#include <cstdio>\n#include <initializer_list>')
with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / 'check.cpp'
    binary = Path(directory) / 'check'
    source.write_text(program)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I', str(header.parent),
                    str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
