#!/usr/bin/env python3
"""Actual portable power-only candidate and callback fault matrix; no device."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
power_source = (root / "native/gpu/uefi/GpuPower.c").read_text()
start = power_source.index("STATIC EFI_STATUS EFIAPI Prepare (")
brace = power_source.index("{", start)
depth = 1
end = brace + 1
while depth:
    depth += (power_source[end] == "{") - (power_source[end] == "}")
    end += 1
prepare = power_source[start:end]

native_fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "GpuPowerOnlyHandoff.h"
#define STATIC static
#define CONST const
#define EFIAPI
#define NULLPTR ((void *)0)
#define Print(...) ((void)0)
#define CopyMem memcpy
typedef uint64_t EFI_STATUS;
typedef uint64_t UINTN;
typedef uint64_t UINT64;
#define TRUE 1
#define EFI_INVALID_PARAMETER UINT64_C(0x8000000000000002)
#define EFI_ALREADY_STARTED UINT64_C(0x8000000000000014)
#define EFI_DEVICE_ERROR UINT64_C(0x8000000000000007)
#define EFI_SUCCESS 0
static int mAttempted,mQmpTouched,mQmpUncertain;
static struct gpp_report mReport;
static struct {unsigned phase,error,pending,publication_verified,last_offset;} mQmp;
static uint32_t values[GPP_REGISTER_COUNT];
static GPP_U64 Resolve(void *c) {(void)c;return 0;}
static GPP_U64 Acd(void *c) {(void)c;return 0;}
static GPP_U64 Resource(void *c,unsigned id,unsigned op,uint32_t request,uint32_t *actual) {
 (void)c;(void)actual;assert(id==GPP_CX && op==GPP_ENABLE && request==1);
 values[GPP_REG_CX]=0;values[GPP_REG_CX_HW]=0x80000000;return 0;
}
static GPP_U64 Read(void *c,unsigned reg,uint32_t *v) {(void)c;*v=values[reg];return 0;}
static GPP_U64 Delay(void *c,unsigned us) {(void)c;(void)us;assert(0);return 1;}
/* ACTUAL_PREPARE */
int main(void) {
 for(unsigned scenario=0;scenario<8;scenario++) {
  mAttempted=0;mQmpTouched=1;mQmpUncertain=0;memset(values,0,sizeof(values));
  memset(&mQmp,0,sizeof(mQmp));mQmp.publication_verified=1;mQmp.last_offset=0x2c;
  values[GPP_REG_CFG]=1;values[GPP_REG_CX]=1;values[GPP_REG_GMU]=0x2001;
  if(scenario==1)mQmpTouched=0;
  if(scenario==2)mQmpUncertain=1;
  if(scenario==3)mQmp.phase=1;
  if(scenario==4)mQmp.error=1;
  if(scenario==5)mQmp.pending=1;
  if(scenario==6)mQmp.last_offset=0x400;
  if(scenario==7)mQmp.last_offset=0x2d;
  struct gpp_report p;gpp_report_init(&p);
  EFI_STATUS status=Prepare(&p,sizeof(p));
  assert(status==EFI_DEVICE_ERROR && gpp_report_valid(&p));
  assert(hph_power_qualified(&p,status)==(scenario==0));
  assert(Prepare(&p,sizeof(p))==EFI_ALREADY_STARTED);
 }
 puts("actual GpuPower.c Prepare compatibility: 8 cases PASS");return 0;
}
'''.replace("/* ACTUAL_PREPARE */", prepare)
with tempfile.TemporaryDirectory(prefix="houji-power-only-") as tmp:
    common = ["clang", "-std=c11", "-Wall", "-Wextra", "-Werror", "-g",
              "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
              "-I", str(root / "native/gpu/uefi")]
    for profile in ([], ["-DHPH_TEST_FIRMWARE_TYPES=1"]):
        binary = Path(tmp) / ("power-only-firmware" if profile else "power-only")
        subprocess.run(common + profile + [str(root / "tests/check-gpu-power-only-handoff.c"),
                                          "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    # Shared XNU consumer parsing: compile the actual complete header as C++14,
    # without relaxing warnings or substituting copies of any policy function.
    cxx = Path(tmp) / "consumer.cpp"
    cxx.write_text('#include "GpuPowerOnlyHandoff.h"\n'
                   'int main() { hph_record r; hph_zero(&r,sizeof(r));\n'
                   ' return hph_decode(0,0,&r) || hph_recheck(&r,0,0)!=HPH_RECORD; }\n')
    binary = Path(tmp) / "consumer"
    subprocess.run(["clang++", "-std=gnu++14"] + common[2:4] +
                   ["-Werror", "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
                    "-I", str(root / "native/gpu/uefi"), str(cxx), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    native = Path(tmp) / "native-prepare.c"
    native.write_text(native_fixture)
    binary = Path(tmp) / "native-prepare"
    subprocess.run(common + [str(native), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
