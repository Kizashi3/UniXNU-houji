#!/usr/bin/env python3
"""Compile a frozen copy of the real CPU-only adapter; only host boundaries differ."""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import re
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
ap=argparse.ArgumentParser()
ap.add_argument('--repo',type=Path,default=HERE.parents[1])
ap.add_argument('--bridge',type=Path,default=HERE.parents[1]/'native/gpu/xnu/hfi-inactive')
ap.add_argument('--generated',type=Path,default=Path('${HOUJI_ARTIFACTS}/native-port/native-ios-candidate/r149-generated'))
ap.add_argument('--record-known-gaps',action='store_true')
args=ap.parse_args()
P=args.repo.resolve();X=P/'native/gpu/xnu';A=X/'Adreno740';V=P/'native/gpu/vendor';U=P/'native/gpu/uefi'
B=HERE/'build';S=B/'snapshot';B.mkdir(exist_ok=True);S.mkdir(exist_ok=True)
source_hashes={}
def copy(src,dst):
    dst.parent.mkdir(parents=True,exist_ok=True)
    data=src.read_bytes();source_hashes[str(src)]=hashlib.sha256(data).hexdigest();dst.write_bytes(data)
    return dst
for src in A.glob('*.h'):copy(src,S/'Adreno740'/src.name)
for name in ['NativeAdrenoMemory.cpp','NativeAdrenoCpu.cpp','NativeAdrenoSha256.cpp','NativeAdrenoFirmware.cpp']:
    copy(A/name,S/'Adreno740'/name)
for src in U.glob('*.h'):copy(src,S/'uefi'/src.name)
for group in ['AdrenoFirmware','Ace5Gmu','ArmSmmu4K']:
    for src in (V/group).glob('*'):
        if src.suffix in ('.h','.c'):copy(src,S/'vendor'/group/src.name)
copy(X/'HoujiGpuFirmwareMemoryProbe.inc',S/'HoujiGpuFirmwareMemoryProbe.inc')
copy(A/'tests/XnuMemoryFixture.h',S/'XnuMemoryFixture.h')
for name in ['houji_hfi_inactive.h','houji_hfi_inactive.c']:copy(args.bridge/name,S/name)
copy(args.generated/'HoujiGmuFirmwareImage.h',S/'HoujiGmuFirmwareImage.h')
generated=(S/'HoujiGmuFirmwareImage.h').read_text()
array=generated.split('gHoujiGmuFirmwareImage[]={',1)[1].split('};',1)[0]
blob=bytes(int(x,16) for x in re.findall(r'0x([0-9a-fA-F]{2})(?=[,\s])',array))
assert len(blob)==78588 and hashlib.sha256(blob).hexdigest()=='9685f62c42543befcaee68d25355e16bf55cdb0d573bddcc9f6633f59eec3f72'
script=A/'tests/check_page_geometry.py';source_hashes[str(script)]=hashlib.sha256(script.read_bytes()).hexdigest()
tree=ast.parse(script.read_text())
literals={n.targets[0].id:n.value.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)}
prefix=literals['prefix']
prefix='#include <cstdint>\nstatic void native_cache_hook(uintptr_t,unsigned);\nstatic unsigned host_alloc_attempts,host_fail_alloc;\nbool host_allocation_refused(){return ++host_alloc_attempts==host_fail_alloc;}\n'+prefix
prefix=prefix.replace('cache_lines.push_back({address,op});','cache_lines.push_back({address,op});native_cache_hook(address,op);')
prefix=prefix.replace('uint64_t gPhysBase=0x10000000,gPhysSize=0x100000000','uint64_t gPhysBase=UINT64_C(0x800000000),gPhysSize=UINT64_C(0x800000000)')
prefix=prefix.replace('return pa;}','return UINT64_C(0xffff000000000000)|pa;}')
fixture=(S/'XnuMemoryFixture.h').read_text()
fixture=fixture.replace('class IOBufferMemoryDescriptor;','extern bool host_allocation_refused();\nclass IOBufferMemoryDescriptor;',1)
needle='if(fixture.allocation_fail)return nullptr;'
fixture=fixture.replace(needle,'if(host_allocation_refused())return nullptr;\n        '+needle,1)
(S/'XnuMemoryFixture.h').write_text(fixture)
cpu=(S/'Adreno740/NativeAdrenoCpu.cpp').read_text()
for field,reg in [('tcr','tcr_el1'),('ttbr0','ttbr0_el1'),('ttbr1','ttbr1_el1'),('sctlr','sctlr_el1')]:
    old=f'__asm__ volatile("mrs %0, {reg}" : "=r"(out->{field}));';assert old in cpu;cpu=cpu.replace(old,f'out->{field}=cpu_{field};')
cpu=cpu.replace('__asm__ volatile("mrs %0, ctr_el0":"=r"(ctr));','ctr=cpu_ctr;')
for name,op in [('cvac',0),('civac',1),('ivac',2)]:
    cpu=cpu.replace(f'__asm__ volatile("dc {name}, %0"::"r"(address):"memory");',f'cache_line(address,{op});')
cpu=cpu.replace('__asm__ volatile("dsb sy":::"memory");','++barriers;');assert '__asm__' not in cpu
for name in ['IOKit/IOTypes.h','IOKit/IOBufferMemoryDescriptor.h','IOKit/IOLib.h','kern/task.h','kern/cpu_data.h','vm/vm_map.h','mach/vm_param.h','kern/clock.h','vm/memory_types.h']:
    p=S/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('#include "XnuMemoryFixture.h"\n')
native=prefix+cpu
for name in ['NativeAdrenoMemory.cpp','NativeAdrenoSha256.cpp','NativeAdrenoFirmware.cpp']:
    native+='\n'+(S/'Adreno740'/name).read_text()
native+='\n'+(HERE/'test_native_peer.cpp').read_text()
(B/'native_test.cpp').write_text(native)
common=['-g','-O1','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-unused-const-variable','-Wno-misleading-indentation','-Wno-sign-compare','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(S),'-I',str(S/'Adreno740'),'-I',str(S/'uefi'),'-I',str(S/'vendor/ArmSmmu4K')]
commands=[]
def run(cmd):
    commands.append(cmd);return subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
objects=[]
for index,path in enumerate([S/'houji_hfi_inactive.c',S/'vendor/AdrenoFirmware/AdrenoFirmware.c',*[S/'vendor/ArmSmmu4K'/name for name in ['ArmSmmu4K.c','ArmSmmu4KContext.c','ArmSmmu4KProgram.c','ArmSmmu4KAudit.c']]]):
    obj=B/f'{index}.o';result=run(['clang','-std=c11',*common,'-c',str(path),'-o',str(obj)])
    if result.returncode:print(result.stdout);raise SystemExit(result.returncode)
    objects.append(str(obj))
exe=B/'native_test'
result=run(['clang++','-std=c++17','-DPAGE_SIZE=16384',*common,str(B/'native_test.cpp'),*objects,'-o',str(exe)])
if result.returncode:
    (B/'compile_failure.txt').write_text(result.stdout);print(result.stdout);raise SystemExit(result.returncode)
cmd=[str(exe)]
if args.record_known_gaps:cmd.append('--record-known-gaps')
result=run(cmd);print(result.stdout,end='');(B/'test-output.txt').write_text(result.stdout)
manifest={'scope':'host CPU-only; production adapter/Memory/Firmware/Sha256 logic unchanged; MRS/DC/DSB/AT/IOKit are boundary peers',
 'result':('DIAGNOSTIC_PENDING_CONTENT_VERIFIER' if 'GAP:' in result.stdout else 'PASS') if result.returncode==0 else 'FAIL','exit_code':result.returncode,'commands':commands,'sources':source_hashes,
 'firmware_bytes':len(blob),'firmware_sha256':hashlib.sha256(blob).hexdigest(),
 'architecture_replacements':['MRS TCR/TTBR/SCTLR/CTR','DC CVAC/CIVAC/IVAC','DSB','AT via host-test hook'],
 'fixture_extension':'allocation failure at a selected descriptor attempt; original fixture otherwise retained',
 'test_source_sha256':hashlib.sha256((HERE/'test_native_peer.cpp').read_bytes()).hexdigest()}
(B/'verification.json').write_text(json.dumps(manifest,indent=2)+'\n')
raise SystemExit(result.returncode)
