#!/usr/bin/env python3
"""Compile the real PSCI call for Darwin arm64; require both barrier and SMC opcodes."""
from pathlib import Path
import argparse
import re
import subprocess
import tempfile

P=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--kernel',type=Path,help='Also inspect the linked kernel function')
parser.add_argument('--source',type=Path,default=P/'native/smp/SweetCPU.cpp',
                    help='Actual SweetCPU.cpp source, or the original portable reference')
parser.add_argument('--publication-cpu',type=Path,
                    help='Also exercise the real typed helper in actual osfmk/arm64/cpu.c')
args=parser.parse_args()
source=args.source.read_text()
begin=source.index('  register uint64_t x0 __asm__("x0") = 0xc4000003ULL;')
end=source.index('\n  IOLog("HOUJI SMP: PSCI CPU_ON returned',begin)
body=source[begin:end]
program=('typedef unsigned long long uint64_t;\n'
         'extern "C" uint64_t test_cpu_on(unsigned physicalID,uint64_t entry,uint64_t context) {\n'
         +body+'\n  return x0;\n}\n')
with tempfile.TemporaryDirectory() as directory:
    d=Path(directory)
    for name,text,expected in [('fixed',program,True),
                               ('regression',program.replace('dsb sy\\n\\tsmc #0','dsb sy; smc #0'),False)]:
        file=d/(name+'.cpp');obj=d/(name+'.o');file.write_text(text)
        subprocess.run(['xcrun','clang++','-target','arm64-apple-macos14',
                        '-ffreestanding','-O2','-Wall','-Wextra','-Werror',
                        '-c',str(file),'-o',str(obj)],check=True)
        asm=subprocess.check_output(['xcrun','llvm-objdump','-d',str(obj)],text=True)
        found=bool(re.search(r'd4000003\s+smc\s+#0',asm))
        assert found==expected,(name,asm)
        assert 'd5033f9f' in asm and 'dsb\tsy' in asm
        if expected:
            assert asm.index('d5033f9f')<asm.index('d4000003')
    print('PASS: Darwin arm64 emits DSB then SMC; original semicolon regression detected')
if args.publication_cpu:
    cpu=args.publication_cpu.read_text()
    xnu=args.publication_cpu.parents[2]
    internal=(xnu/'osfmk/arm/cpu_data_internal.h').read_text()
    public=(xnu/'osfmk/arm/pmap_public.h').read_text()
    # Use the real definitions, rather than a byte-array/guessed-size facade.
    restore=re.search(r'typedef struct sysreg_restore\s*\{[^}]+\}\s*sysreg_restore_t;',internal)
    physical=re.search(r'typedef uint64_t pmap_paddr_t[^;]*;',public)
    helper=re.search(r'uint32_t\s+houji_publish_secondary_state\([^;{}]*\)\s*\{',cpu)
    assert restore and physical and helper
    pos=helper.end();depth=1
    while depth:
        depth+=(cpu[pos]=='{')-(cpu[pos]=='}');pos+=1
    actual=cpu[helper.start():pos]
    assert 'sizeof(sysreg_restore)' in actual and 'sizeof(cpu_ttep)' in actual
    assert not re.search(r'\b(?:IOLog|printf|kprintf|panic)\s*\(',actual)
    assert source.index('flush_dcache((vm_offset_t)const_boot_args') < source.index('houji_publish_secondary_state(&publishedTcr') < source.index('register uint64_t x0 __asm__("x0") = 0xc4000003ULL;')
    program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define __kernel_ptr_semantics
#define FALSE 0
typedef uintptr_t vm_offset_t;
'''+restore.group()+'\n'+physical.group()+r'''
static sysreg_restore_t sysreg_restore;
static pmap_paddr_t cpu_ttep;
static unsigned calls;
static void flush_dcache(vm_offset_t address,unsigned length,int physical) {
 assert(!physical);
 if(!calls)assert(address==(uintptr_t)&sysreg_restore && length==sizeof(sysreg_restore));
 else assert(calls==1 && address==(uintptr_t)&cpu_ttep && length==sizeof(cpu_ttep));
 calls++;
 // Deliberate changes distinguish pre-publication snapshots from post-flush
 // observations. The real helper must return the former, on CPU0 only.
 sysreg_restore.tcr_el1^=UINT64_C(0xaaaa000055550000);cpu_ttep^=UINT64_C(0x55550000aaaa0000);
}
'''+actual+r'''
int main(void) {
 unsigned cases=0;
 static const uint64_t values[]={0,UINT64_C(0x226511a511),UINT64_C(0x8c223c000),UINT64_MAX};
 for(unsigned i=0;i<4;i++)for(unsigned output=0;output<4;output++) {
  uint64_t tcr=0x11,root=0x22;calls=0;sysreg_restore.tcr_el1=values[i];cpu_ttep=values[3-i];
  assert(houji_publish_secondary_state(output&1?&tcr:0,output&2?&root:0)==sizeof(sysreg_restore)+sizeof(cpu_ttep));
  assert(calls==2 && tcr==(output&1?values[i]:0x11) && root==(output&2?values[3-i]:0x22));cases++;
 }
 assert(sizeof(sysreg_restore)==8 && sizeof(cpu_ttep)==8);
 printf("PASS: %u actual typed publication cases; two exact entity ranges, pre-flush snapshots, no console (ASAN/UBSAN)\n",cases);
}
'''
    with tempfile.TemporaryDirectory(prefix='houji-secondary-publication-') as directory:
        d=Path(directory);file=d/'test.c';exe=d/'test';file.write_text(program)
        subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',
                        '-fsanitize=address,undefined',str(file),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
if args.kernel:
    symbols=subprocess.check_output(['xcrun','nm',str(args.kernel)],text=True)
    parsed=[(int(m[1],16),m[2]) for line in symbols.splitlines()
            if (m:=re.fullmatch(r'([0-9a-f]+) [SsTt] (\S+)',line))]
    start=next(address for address,name in parsed if name=='__ZN8SweetCPU8startCPUEmm')
    stop=min(address for address,name in parsed if address>start)
    asm=subprocess.check_output(['xcrun','llvm-objdump','-d',
        '--start-address='+hex(start),'--stop-address='+hex(stop),str(args.kernel)],text=True)
    assert len(re.findall(r'd4000003\s+smc\s+#0',asm))==1,asm
    assert asm.index('d5033f9f')<asm.index('d4000003')
    print('PASS: linked SweetCPU::startCPU contains exactly one real SMC after DSB')
    if args.publication_cpu:
        assert asm.count('<_houji_publish_secondary_state>')==1,asm
        assert asm.index('<_houji_publish_secondary_state>')<asm.index('d5033f9f')<asm.index('d4000003'),asm
        pub=next(address for address,name in parsed if name=='_houji_publish_secondary_state')
        end=min(address for address,name in parsed if address>pub)
        publication=subprocess.check_output(['xcrun','llvm-objdump','-d',
            '--start-address='+hex(pub),'--stop-address='+hex(end),str(args.kernel)],text=True)
        assert publication.count('<_flush_dcache>')==2,publication
        assert not re.search(r'<_(IOLog|printf|kprintf|console_write)>',publication),publication
        print('PASS: linked typed publication calls both real cache flushes before CPU_ON; no helper console')
    start=next(address for address,name in parsed if name=='__ZN8SweetCPU7initCPUEb')
    stop=min(address for address,name in parsed if address>start)
    asm=subprocess.check_output(['xcrun','llvm-objdump','-d',
        '--start-address='+hex(start),'--stop-address='+hex(stop),str(args.kernel)],text=True)
    assert not re.search(r'<_(IOLog|printf|kprintf|console_write)>',asm),asm
    print('PASS: linked secondary initCPU has no direct console output; diagnostics deferred')
    if any(name=='_houji_smp_capture_gic' for address,name in parsed):
        start=next(address for address,name in parsed if name=='_houji_smp_capture_gic')
        stop=min(address for address,name in parsed if address>start)
        asm=subprocess.check_output(['xcrun','llvm-objdump','-d',
            '--start-address='+hex(start),'--stop-address='+hex(stop),str(args.kernel)],text=True)
        assert not re.search(r'<_(IOLog|printf|kprintf|console_write)>',asm),asm
        print('PASS: masked-IRQ GIC capture contains no direct console output')
