#!/usr/bin/env python3
from pathlib import Path
import subprocess,hashlib,json,os
HERE=Path(__file__).resolve().parent
CORE=HERE.parents[1]/'native/gpu/xnu/full-host-graph'
P=Path('${HOUJI_PORT_ROOT}')
A=Path('${HOUJI_ARTIFACTS}/native-research/houji-gpu-firmware-20261025')
B=HERE/'build/core';B.mkdir(parents=True,exist_ok=True)
assets=[A/'gmu_gen70900.bin',A/'gen70900_sqe.fw',A/'gen70900_aqe.fw']
hashes=['9685f62c42543befcaee68d25355e16bf55cdb0d573bddcc9f6633f59eec3f72','8e2c5ce74140de7e161f14654b44de999855bce01b690fdd18c3358a73498cd1','25237c161d727b8ea92b4beb837a31651b44ea78bfc34d95672af8f346a45825']
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
for p,h in zip(assets,hashes):assert sha(p)==h
commands=[];outputs=[]
def run(cmd):
 commands.append(cmd);r=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'});outputs.append(r.stdout);print(r.stdout,end='');assert r.returncode==0,(cmd,r.returncode);return r.stdout
flags=['-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=address,undefined','-fno-omit-frame-pointer']
inc=['-I',str(CORE),'-I',str(HERE),'-I',str(P/'native/gpu'),'-I',str(P/'native/gpu/uefi'),'-I',str(P/'native/gpu/xnu/Adreno740'),'-I',str(P/'native/gpu/xnu/hfi-inactive')]
sources=[CORE/'houji_native_full_host_graph.c',*[P/'native/gpu/vendor/ArmSmmu4K'/(n+'.c') for n in ['ArmSmmu4K','ArmSmmu4KAudit','ArmSmmu4KContext','ArmSmmu4KProgram']],P/'native/gpu/vendor/AdrenoFirmware/AdrenoFirmware.c']
objects=[]
for src in sources:
 obj=B/(src.stem+'.o');run(['clang','-std=c11',*flags,*inc,'-c',str(src),'-o',str(obj)]);objects.append(str(obj))
for src in [HERE/'sha_peer.cpp',P/'native/gpu/xnu/Adreno740/NativeAdrenoSha256.cpp']:
 obj=B/(src.stem+'.o');run(['clang++','-std=c++14',*flags,*inc,'-c',str(src),'-o',str(obj)]);objects.append(str(obj))
test_obj=B/'test.o';run(['clang','-std=c11',*flags,*inc,'-c',str(HERE/'test_full_host_graph.c'),'-o',str(test_obj)])
exe=B/'full_graph';run(['clang++',*flags,str(test_obj),*objects,'-o',str(exe)]);run([str(exe),*map(str,assets)])
cpp=B/'cpp14';run(['clang++','-std=c++14','-pedantic-errors',*flags,*inc,str(HERE/'test_cpp14.cpp'),*objects,'-o',str(cpp)]);run([str(cpp)])
for name,extra,args in [('check-gpu-firmware-memory',['-DHFM_WITH_SCRATCH=1'],assets[:1]),('check-gpu-code-memory',[],assets[1:])]:
 obj=B/(name+'.o');run(['clang','-std=c11',*flags,*inc,*extra,'-c',str(P/'tests'/(name+'.c')),'-o',str(obj)]);exe=B/name;run(['clang++',*flags,str(obj),*objects,'-o',str(exe)]);run([str(exe),*map(str,args)])
(B/'test-output.txt').write_text(''.join(outputs))
tracked=[*sources,HERE/'sha_peer.cpp',HERE/'test_full_host_graph.c',HERE/'test_cpp14.cpp',Path(__file__),CORE/'houji_native_full_host_graph.h',P/'native/gpu/uefi/GpuFirmwareMemory.h',P/'native/gpu/uefi/GpuScratchContext.h',P/'native/gpu/uefi/GpuSharedMemory.h',P/'native/gpu/uefi/GpuCodeMemory.h',P/'native/gpu/vendor/Ace5Gmu/giulia_gpu_firmware.h',P/'native/gpu/vendor/Ace5Gmu/giulia_gpu_memory.h',P/'native/gpu/vendor/Ace5Gmu/giulia_gpu_hfi.h',P/'native/gpu/xnu/Adreno740/NativeAdrenoSha256.cpp']
report={'status':'PASS','hardware_tested':False,'scope':'offline CPU-only full graph; test artifacts only; no live kernel/device modification, MMIO/SMC/execution/FS/ref acquisition','commands':commands,'command_sha256':hashlib.sha256(json.dumps(commands,separators=(',',':')).encode()).hexdigest(),'source_hashes':{str(p):sha(p) for p in tracked},'asset_hashes':{str(p):sha(p) for p in assets},'output_sha256':sha(B/'test-output.txt')}
(B/'source-manifest.json').write_text(json.dumps(report,indent=2)+'\n')
print('manifest SHA256',sha(B/'source-manifest.json'))
