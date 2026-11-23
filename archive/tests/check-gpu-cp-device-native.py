#!/usr/bin/env python3
"""Compile the actual CP-page adapter against the real ArmMmuLib API typedef.

Only the low-level API, owner guard and console sink are mocked. The application
header is included unchanged; this test does not run MMIO or page-table code.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--api-header', type=Path, default=p.parent / 'uefi-houji' /
                    'Mu_Basecore/UefiCpuPkg/Include/Library/ArmMmuLib.h')
args = parser.parse_args()
api = args.api_header.read_text()
report = re.search(r'typedef\s+struct\s*\{[^{}]*\}\s*ARM_HOUJI_CP_DEVICE_REPORT\s*;', api)
declaration = re.search(r'EFI_STATUS\s+EFIAPI\s+ArmSetHoujiCpDeviceNgNre\s*\([^;]*\);', api)
if report is None or declaration is None:
    parser.error('--api-header must contain the real CP-device report and API declaration')
source = (p / 'native/gpu/uefi/GpuCpDeviceNative.h').read_text()
has_audit_log = 'mCpDeviceReport.AuditCode' in source
shim = '#ifndef TEST_ARM_MMU_LIB_H\n#define TEST_ARM_MMU_LIB_H\n' + report[0] + '\n' + declaration[0] + '\n#endif\n'
program = r'''
#include <assert.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#define STATIC static
#define VOID void
#define EFIAPI
#define OUT
#define OPTIONAL
typedef uint32_t UINT32;
typedef uint64_t UINT64;
typedef uint64_t EFI_STATUS;
#define EFI_ERROR(status) (((EFI_STATUS)(status) >> 63) != 0)
#define EFI_SUCCESS UINT64_C(0)
#define EFIERR(code) (UINT64_C(0x8000000000000000) | (code))
#include <Library/ArmMmuLib.h>
static EFI_STATUS api_status;
static ARM_HOUJI_CP_DEVICE_REPORT api_report;
static unsigned guards, api_calls, prints, fail_guard, cases;
static unsigned events[16], event_count;
static void event(unsigned kind) {assert(event_count < 16); events[event_count++] = kind;}
static int HostPreparationGuard(void *cookie) {
 assert(cookie == NULL); event(1); return ++guards == fail_guard;
}
static void CapturePrint(const wchar_t *format, ...);
#define Print CapturePrint
#include "GpuCpDeviceNative.h"
_Static_assert(sizeof(mCpDeviceReport.Version) == 4, "Print %u requires 32-bit report counters");
_Static_assert(sizeof(mCpDeviceReport.AuditCode) == 4, "real API audit field retained");
_Static_assert(sizeof(mCpDeviceReport.Root) == 8, "Print %lx requires 64-bit report addresses");
_Static_assert(sizeof(mCpDeviceReport.Status) == sizeof(EFI_STATUS), "report/API status width");
static EFI_STATUS (EFIAPI *const api_signature)(ARM_HOUJI_CP_DEVICE_REPORT *) = ArmSetHoujiCpDeviceNgNre;
EFI_STATUS EFIAPI ArmSetHoujiCpDeviceNgNre(ARM_HOUJI_CP_DEVICE_REPORT *report) {
 assert(report == &mCpDeviceReport && mCpDeviceAttempted == 1 && guards == 1 && !api_calls && !prints);
 event(2); api_calls++; *report = api_report; return api_status;
}
static void CapturePrint(const wchar_t *format, ...) {
 assert(api_calls == 1 && guards == 1 && mCpDeviceAttempted == 1 && prints < 4);
 event(3); va_list args; va_start(args, format);
#define U32(field) assert(va_arg(args, UINT32) == api_report.field)
#define U64(field) assert(va_arg(args, UINT64) == api_report.field)
 switch (prints++) {
  case 0:
   assert(wcsstr(format, L"HOUJI GPU CPU CP TYPE:") && wcsstr(format, L"fixed CP 03d02000/1000 only"));
   assert(va_arg(args, UINT64) == api_status);
   U32(Version); U32(Stage); U32(Failed);
#if TEST_AUDIT_LOG
   assert(wcsstr(format, L"failed=%u audit=%u tables=%u"));
   U32(AuditCode);
#endif
   U32(Tables); U32(Leaves); U32(SplitsNeeded); U32(SpareUsed);
   break;
  case 1:
   assert(wcsstr(format, L"HOUJI GPU CPU CP REGIME:") && wcsstr(format, L"CPU page tables, not GPU SMMU"));
   U64(Root); U64(Tcr); U64(MairBefore); U64(MairAfter); break;
  case 2:
   assert(wcsstr(format, L"HOUJI GPU CPU CP PTE:") && wcsstr(format, L"only AttrIndx changes"));
   U32(BeforeLevel); U32(AfterLevel); U64(BeforeDescriptor); U64(AfterDescriptor); break;
  case 3:
   assert(wcsstr(format, L"HOUJI GPU CPU CP PAR:") && wcsstr(format, L"require identity Device04 and neighbors unchanged"));
   assert(!wcsstr(format, L"actual identity Device04"));
   U64(ParBeforeRead); U64(ParBeforeWrite); U64(ParAfterRead); U64(ParAfterWrite);
   U64(NeighborBefore[0]); U64(NeighborBefore[1]); U64(NeighborAfter[0]); U64(NeighborAfter[1]); break;
  default: assert(0);
 }
#undef U32
#undef U64
 va_end(args);
}
static void reset(void) {
 memset(&mCpDeviceReport, 0, sizeof mCpDeviceReport);
 mCpDeviceAttempted = guards = api_calls = prints = fail_guard = event_count = 0;
 memset(events, 0, sizeof events); api_status = EFI_SUCCESS;
 api_report = (ARM_HOUJI_CP_DEVICE_REPORT){
  .Version=1, .Stage=8, .Tables=19, .Leaves=337, .SplitsNeeded=2, .SpareUsed=1,
  .BeforeLevel=1, .AfterLevel=3, .AuditCode=0,
  .Root=UINT64_C(0xb8011000), .Tcr=UINT64_C(0x80803520),
  .MairBefore=UINT64_C(0xffbb4400), .MairAfter=UINT64_C(0x4ffbb4400),
  .BeforeDescriptor=UINT64_C(0x60000002000401), .AfterDescriptor=UINT64_C(0x60000003d02413),
  .ParBeforeRead=UINT64_C(0x03d02b80), .ParBeforeWrite=UINT64_C(0x03d02d80),
  .ParAfterRead=UINT64_C(0x0400000003d02b80), .ParAfterWrite=UINT64_C(0x0400000003d02d80),
  .NeighborBefore={UINT64_C(0x03d01b80),UINT64_C(0x03d03b80)},
  .NeighborAfter={UINT64_C(0x03d01b80),UINT64_C(0x03d03b80)}, .Status=EFI_SUCCESS
 };
}
static void check_api_attempt(int expected, unsigned expected_guards) {
 assert(CpDeviceNgNrePrepare() == expected);
 assert(api_calls == 1 && prints == 4 && guards == expected_guards && mCpDeviceAttempted == 1);
 assert(event_count == 6 + (expected_guards == 2));
 assert(events[0] == 1 && events[1] == 2);
 for(unsigned i=2;i<6;i++)assert(events[i] == 3);
 if(expected_guards == 2)assert(events[6] == 1);
 cases++;
 // A failed, partial or successful API attempt is consumed exactly once.
 for(unsigned i=0;i<3;i++) {
  assert(CpDeviceNgNrePrepare() == 1);
  assert(api_calls == 1 && prints == 4 && guards == expected_guards && event_count == 6 + (expected_guards == 2));
  cases++;
 }
}
int main(void) {
 assert(api_signature != NULL);
 reset(); fail_guard=1; memset(&mCpDeviceReport, 0xa5, sizeof mCpDeviceReport);
 unsigned char before[sizeof mCpDeviceReport]; memcpy(before, &mCpDeviceReport, sizeof before);
 assert(CpDeviceNgNrePrepare() == 1 && guards == 1 && !api_calls && !prints && !mCpDeviceAttempted);
 assert(!memcmp(before, &mCpDeviceReport, sizeof before) && event_count == 1 && events[0] == 1); cases++;
 reset(); mCpDeviceAttempted=1;
 assert(CpDeviceNgNrePrepare() == 1 && !guards && !api_calls && !prints && !event_count); cases++;
 for(unsigned code=1;code<=4;code++) {
  reset(); api_status=EFIERR(code); api_report.Status=api_status; check_api_attempt(1,1);
 }
 for(unsigned stage=0;stage<=9;stage++)if(stage!=8) {
  reset(); api_report.Stage=stage; api_report.AuditCode=7; check_api_attempt(1,1);
 }
 const UINT32 bad_failed[]={1,UINT32_MAX};
 for(unsigned i=0;i<2;i++){reset();api_report.Failed=bad_failed[i];check_api_attempt(1,1);}
 const UINT32 bad_versions[]={0,2,UINT32_MAX};
 for(unsigned i=0;i<3;i++){reset();api_report.Version=bad_versions[i];check_api_attempt(1,1);}
 reset(); api_report.Status=EFIERR(1); check_api_attempt(1,1);
 reset(); api_report.Status=1; check_api_attempt(1,1);
 reset(); fail_guard=2; check_api_attempt(1,2);
 reset(); check_api_attempt(0,2);
 printf("PASS: %u actual CP-device native adapter cases; real API typedef/signature and printed fields checked, pre/post guards, version/status/stage/failure refusal, one API attempt only\n", cases);
}
'''
with tempfile.TemporaryDirectory(prefix='houji-cp-device-native-') as directory:
    folder = Path(directory)
    (folder / 'Library').mkdir()
    (folder / 'Library/ArmMmuLib.h').write_text(shim)
    (folder / 'test.c').write_text(program)
    command = ['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', f'-DTEST_AUDIT_LOG={int(has_audit_log)}',
               '-I', str(folder), '-I', str(p / 'native/gpu/uefi'),
               str(folder / 'test.c'), '-o', str(folder / 'test')]
    subprocess.run(command, check=True)
    subprocess.run([str(folder / 'test')], check=True)
