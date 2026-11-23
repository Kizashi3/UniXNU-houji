#!/usr/bin/env python3
"""Exact halt_all_cpus mode gates and PSCI-return fallback; never reboots.

Only the architectural DSB/SMC leaf is replaced by a host call. All original
reboot/bootarg/board/PE ordering is compiled directly from the actual source.
"""
from pathlib import Path
import re
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parent.parent
SOURCE = PROJECT / '.cache/ios16-reference/dxb-ios/xnu/osfmk/arm64/machine_routines.c'
source = SOURCE.read_text()
begin = source.index('void\nhalt_all_cpus(boolean_t reboot)')
brace = source.index('{', begin)
end, depth = brace + 1, 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
body = source[begin:end]
assert body.count('"houji_panic_recovery"') == 1
assert '#if defined(SWEET) && SWEET' in body
assert 'houji_panic_recovery == 1' in body
assert body.index('printf("MACH Reboot\\n");') < body.index('"houji_panic_recovery"') < body.index('PEHaltRestart(kPERestartCPU);')
leaf_start = body.index('\t\t\tregister uint64_t x0')
leaf_end = body.index('\n\t\t\t/* Unexpected SMC return', leaf_start)
leaf = body[leaf_start:leaf_end]
assert '0x84000009U' in leaf and '"dsb sy\\n\\tsmc #0"' in leaf
assert re.findall(r'"x([0-9]+)"', leaf) == [str(i) for i in range(18)]
assert '"cc", "memory"' in leaf
# Reject adding storage, locks, allocation, log checkpoint or other callbacks
# to the panic path. The source's comments make no persistence promise.
plain = re.sub(r'/\*.*?\*/', '', body, flags=re.S)
calls = set(re.findall(r'\b([A-Za-z_][A-Za-z0-9_]*)\s*\(', plain))
assert calls <= {'halt_all_cpus', 'if', 'defined', 'printf', 'PE_parse_boot_argn',
                 'sizeof', '__asm__', 'volatile', 'PEHaltRestart', 'while'}, calls
body = body[:leaf_start] + '\t\t\tuint64_t x0 = 0x84000009U;\n\t\t\tprobe_barrier(); probe_smc(&x0);' + body[leaf_end:]

prefix = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
typedef int boolean_t;
enum {kPERestartCPU=1,kPEHaltCPU=2};
static jmp_buf destination;
static int present,value,reset_returns,parses,resets,pe_calls,pe_kind,prints;
static uint64_t reset_id;
static int events[8],used;
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line %d: %s\n",__LINE__,#x);exit(1);}}while(0)
static void record(int event){CHECK(used<8);events[used++]=event;}
static int probe_printf(const char *text){++prints;record(!strcmp(text,"MACH Reboot\n")?1:0);return 0;}
#define printf probe_printf
static __attribute__((unused)) int PE_parse_boot_argn(const char *name,void *out,int bytes){CHECK(!strcmp(name,"houji_panic_recovery") && bytes==sizeof(int));++parses;record(2);if(present)*(int*)out=value;return present;}
static __attribute__((unused)) void probe_barrier(void){record(3);}
static __attribute__((unused)) void probe_smc(uint64_t *x0){++resets;reset_id=*x0;record(4);if(!reset_returns)longjmp(destination,3);*x0=UINT64_C(0xffffffffffffffff);}
static __attribute__((noreturn)) void PEHaltRestart(int kind){++pe_calls;pe_kind=kind;record(5);longjmp(destination,2);}
'''
main = r'''
#undef printf
int main(void){unsigned cases=0;
 for(int reboot=0;reboot<2;++reboot)for(int found=0;found<2;++found)
 for(int argument=-1;argument<=2;++argument)for(int returned=0;returned<2;++returned){
  present=found;value=argument;reset_returns=returned;parses=resets=pe_calls=pe_kind=prints=used=0;reset_id=0;
  int result=setjmp(destination);if(!result)halt_all_cpus(reboot);
  const int expected_reset=TEST_SWEET && reboot && found && argument==1;
  CHECK(prints==1 && events[0]==(reboot?1:0));
  CHECK(parses==(TEST_SWEET && reboot?1:0));
  CHECK(resets==expected_reset);
  if(expected_reset){CHECK(reset_id==UINT64_C(0x84000009));CHECK(events[1]==2 && events[2]==3 && events[3]==4);}
  if(expected_reset && !returned){CHECK(result==3 && !pe_calls && used==4);}
  else {CHECK(result==2 && pe_calls==1 && pe_kind==(reboot?kPERestartCPU:kPEHaltCPU));CHECK(events[used-1]==5);}
  ++cases;
 }
 fprintf(stdout,"PASS: SWEET=%d %u actual panic reset board/bootarg/reboot/SMC-return cases; no storage or reboot\n",TEST_SWEET,cases);
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='houji-panic-recovery-host-') as directory:
    tmp = Path(directory)
    code = tmp / 'test.c'
    code.write_text(prefix + body + main)
    for name, macros in [('sweet', ['-DSWEET=1', '-DTEST_SWEET=1']),
                         ('zero', ['-DSWEET=0', '-DTEST_SWEET=0']),
                         ('other', ['-DTEST_SWEET=0'])]:
        exe = tmp / name
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', *macros, str(code), '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
