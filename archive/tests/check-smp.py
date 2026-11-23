#!/usr/bin/env python3
"""Exercise the actual CPU policy and generated ADT before a hardware SMP test."""
from pathlib import Path
import hashlib
import json
import struct
import subprocess
import sys
import tempfile

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')
reference = P / '.cache/ios16-reference/vermeer'
sys.path.insert(0, str(reference / 'tools'))
import adt

program = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "HoujiCpuPolicy.h"
int main() {
  unsigned accepted=0;
  for (unsigned total=0; total<=9; ++total)
    for (unsigned id=0; id<9; ++id)
      for (unsigned affinity=0; affinity<=0x800; ++affinity)
        for (unsigned enabled=0; enabled<2; ++enabled) {
          bool expected=(total==1 && id==0 && affinity==0) ||
            (enabled && total>=2 && total<=8 && id<total && affinity==id*0x100);
          assert(houjiCpuNodeAllowed(id,affinity,total,enabled)==expected);
          accepted+=expected;
        }
  assert(accepted==37);
  assert(houjiCpuPart(0)==0xd80 && houjiCpuPart(1)==0xd80);
  assert(houjiCpuPart(2)==0xd81 && houjiCpuPart(6)==0xd81 && houjiCpuPart(7)==0xd82);
  uint64_t value;
  for (unsigned a3=0; a3<=255; a3+=17)
    for (unsigned a2=0; a2<=255; a2+=17)
      for (unsigned a1=0; a1<=255; a1+=17)
        for (unsigned a0=0; a0<16; ++a0) {
          uint64_t affinity=(uint64_t(a3)<<32)|(uint64_t(a2)<<16)|(a1<<8)|a0;
          assert(houjiSgiValue(affinity,&value));
          uint64_t expected=(uint64_t(a3)<<48)|(uint64_t(a2)<<32)|
            (uint64_t(a1)<<16)|(1ULL<<24)|(1ULL<<a0);
          assert(value==expected);
        }
  for (unsigned bit=0;bit<64;bit++)
    if ((1ULL<<bit)&~0xff00ffffffULL)
      assert(!houjiSgiValue(1ULL<<bit,&value));
  for (unsigned id=16;id<256;id++) assert(!houjiSgiValue(id,&value));
  assert(!houjiSgiValue(0,nullptr));
  assert(houjiSgiValue(0,&value)&&value==0x01000001);
  assert(houjiSgiValue(0x100,&value)&&value==0x01010001);
  puts("PASS: CPU allowlist exhaustively checked; 65536 SGI encodings and invalid affinities");
}
'''

def walk(node, prefix=''):
    path=prefix+'/'+node.name
    yield path,node
    for child in node.children:
        yield from walk(child,path)

with tempfile.TemporaryDirectory() as directory:
    d=Path(directory)
    (d/'check.cpp').write_text(program)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror',
                    '-fsanitize=address,undefined','-I',str(P/'native/smp'),
                    str(d/'check.cpp'),'-o',str(d/'check')],check=True)
    subprocess.run([str(d/'check')],check=True)
    product=N/'native-ios-candidate/houji-ios-gui-uuid8192.adt'
    fdt=N/'device-baseline/live-fdt.dtb'
    identity=json.loads((N/'native-ios-candidate/houji-platform-uuid.json').read_text())['platform_uuid']
    command=[sys.executable,str(P/'scripts/make-houji-adt.py'),
             '--reference',str(reference),'--output',str(d/'result.adt'),
             '--ios-gui','--product-adt',str(product),'--memory-mib','8192',
             '--platform-uuid',identity]
    for count in (1,2):
        arguments=command+['--cpus',str(count),'--live-fdt',str(fdt)]
        subprocess.run(arguments,check=True)
        raw=(d/'result.adt').read_bytes()
        tree,used=adt.parse(raw); assert used==len(raw)
        nodes=dict(walk(tree)); cpus=nodes['/device-tree/cpus'].children
        assert len(cpus)==count
        assert [c.prop('reg') for c in cpus]==[struct.pack('<I',i*0x100) for i in range(count)]
        assert [c.prop('cpu-id') for c in cpus]==[struct.pack('<I',i) for i in range(count)]
        assert [c.prop('cluster-core-id') for c in cpus]==[struct.pack('<I',i) for i in range(count)]
        handles=[node.prop('AAPL,phandle') for node in nodes.values()]
        assert len(handles)==len(set(handles)) and None not in handles
        if count==2:
            assert cpus[1].prop('state')==b'waiting\0'
            assert all(c.prop('clock-frequency') is None for c in cpus)
            assert nodes['/device-tree/psci'].prop('method')==b'smc\0'
            assert nodes['/device-tree/arm-io/gic'].prop('redistributor-stride')==struct.pack('<Q',0x40000)
        else:
            assert '/device-tree/psci' not in nodes
            assert nodes['/device-tree/arm-io/gic'].prop('redistributor-stride') is None
    assert subprocess.run(command+['--cpus','2'],capture_output=True).returncode!=0
    corrupt=bytearray(fdt.read_bytes());corrupt[-1]^=1;(d/'bad.dtb').write_bytes(corrupt)
    assert subprocess.run(command+['--cpus','2','--live-fdt',str(d/'bad.dtb')],capture_output=True).returncode!=0
    assert subprocess.run(command+['--cpus','8'],capture_output=True).returncode!=0
    print('PASS: ADT affinity, unique phandles, PSCI, GIC stride, single-CPU defaults and hardware rejection guards')
