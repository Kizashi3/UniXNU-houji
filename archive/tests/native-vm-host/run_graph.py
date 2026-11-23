from pathlib import Path
import subprocess,os
p=Path('${HOUJI_PORT_ROOT}');s=Path('/tmp/houji-native-vm-runtime');b=Path('/tmp/houji-native-vm-check');b.mkdir(exist_ok=True)
flags=['-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-function','-fsanitize=address,undefined','-fno-omit-frame-pointer']
incs=['-I'+str(s),'-I'+str(p/'tests/full-host-graph'),'-I'+str(p/'native/gpu'),'-I'+str(p/'native/gpu/uefi'),'-I'+str(p/'native/gpu/xnu/Adreno740'),'-I'+str(p/'native/gpu/xnu/hfi-inactive')]
src=(p/'tests/full-host-graph/test_full_host_graph.c').read_text();src=src.replace('256,64,7};','256,64,1028};');at=src.index('int main(');src=src[:at]+'''int main(int argc,char**argv){CHECK(argc==4);for(unsigned i=0;i<3;i++)assets[i]=file(argv[i+1],lengths[i]);reset(16384);CHECK(!prepare());FhgGraph g={0};CHECK(!fhg_graph(&storage,sizeof storage,1,&g,sizeof g));CHECK(g.table_pages==1027 && g.leaf_pages==1567 && g.descriptor_reads==1027*512 && g.leaf_budget==524288 && g.audit_complete);uint32_t code=99;CHECK(!fhg_verify(&storage,sizeof storage,&code) && !code);((uint64_t*)model.alloc[14])[0]^=4096;CHECK(!fhg_verify(&storage,sizeof storage,&code) && code);printf("PASS new whole seeded graph and descriptor corruption refusal; %u callback/owned-span checks; no GPU emulation\\n",checks);return 0;}\n''';(b/'graph.c').write_text(src)
objects=[]
for f in [s/'houji_native_full_host_graph.c',s/'ArmSmmu4K.c',s/'ArmSmmu4KAudit.c',s/'ArmSmmu4KContext.c',s/'ArmSmmu4KProgram.c',s/'ArmSmmu4KLive.c',p/'native/gpu/vendor/AdrenoFirmware/AdrenoFirmware.c',b/'graph.c',p/'tests/full-host-graph/sha_peer.cpp',p/'native/gpu/xnu/Adreno740/NativeAdrenoSha256.cpp']:
 o=b/(f.stem+'.o');cxx=f.suffix=='.cpp';subprocess.run(['clang++' if cxx else 'clang','-std=c++14' if cxx else '-std=c11',*flags,*incs,'-c',str(f),'-o',str(o)],check=True);objects.append(str(o))
# Compile the actual enclosing FHR TU: included FHG is not linked twice.
subprocess.run(['clang','-std=c11',*flags,*incs,'-c',str(s/'houji_full_host_runtime.c'),'-o',str(b/'fhr.o')],check=True)
exe=b/'graph';subprocess.run(['clang++',*flags,*objects,'-o',str(exe)],check=True)
a=Path('${HOUJI_ARTIFACTS}/native-research/houji-gpu-firmware-20261025')
r=subprocess.run([str(exe),str(a/'gmu_gen70900.bin'),str(a/'gen70900_sqe.fw'),str(a/'gen70900_aqe.fw')],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env={**os.environ,'ASAN_OPTIONS':'detect_leaks=0'});print(r.stdout);(b/'test.log').write_text(r.stdout);r.check_returncode()
