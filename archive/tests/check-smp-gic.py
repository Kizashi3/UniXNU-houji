#!/usr/bin/env python3
"""Compile actual CPU-interface snapshot with sysreg mocks; prohibit MMIO."""
from pathlib import Path
import subprocess,tempfile
P=Path(__file__).resolve().parents[1]
source=(P/'native/smp/HoujiSmpGic.inc').read_text()
for forbidden in ('gicr_read','gicd_read','_gic_read','find_gicr_pe_base','__builtin_arm_wsr','IOLog(', 'printf('):
    assert forbidden not in source, forbidden
program=r"""
#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
static unsigned mock_cpu, reads;
static unsigned ml_get_cpu_number_local(void) { return mock_cpu; }
static uint64_t mock_read(const char *reg) {
 const char *names[]={"ICC_IGRPEN1_EL1","ICC_PMR_EL1","ICC_SRE_EL1","DAIF","VBAR_EL1","CNTV_CTL_EL0","ICC_CTLR_EL1","ICC_HPPIR1_EL1"};
 for(unsigned i=0;i<8;i++)if(!strcmp(reg,names[i])) { reads++;return 0x100+i; }
 assert(!"unexpected system register read");return 0;
}
#define SWEET 1
#define __builtin_arm_rsr64(reg) mock_read(reg)
#include "HoujiSmpGic.inc"
int main(void) {
 for(mock_cpu=0;mock_cpu<8;mock_cpu++) {
  houji_smp_capture_gic();assert(houji_gic_snapshot_ready[mock_cpu]);
  const uint64_t *fields=(const uint64_t *)&houji_gic_snapshot[mock_cpu];
  for(unsigned i=0;i<8;i++)assert(fields[i]==0x100+i);
 }
 assert(reads==64);
 for(mock_cpu=8;mock_cpu<100;mock_cpu++)houji_smp_capture_gic();
 mock_cpu=UINT32_MAX;houji_smp_capture_gic();assert(reads==64);
 puts("PASS: actual snapshot captures 8 permitted sysregs on all 8 CPUs; rejects invalid IDs; no MMIO or register writes");
}
"""
with tempfile.TemporaryDirectory() as directory:
 d=Path(directory);(d/'check.c').write_text(program)
 subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(P/'native/smp'),str(d/'check.c'),'-o',str(d/'check')],check=True)
 subprocess.run([str(d/'check')],check=True)
