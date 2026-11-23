#!/usr/bin/env python3
"""Compile the actual Mu FindFreePages with high/low bins and promotion paths."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uefi', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / 'native/high-memory/manifest.json').read_text())
    raw = (args.uefi / manifest['page_source']).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest['after_sha256']
    text = raw.decode().replace('\r\n', '\n')
    begin = text.index('UINT64\nFindFreePages (')
    end = text.index('\n/**', begin)
    function = text[begin:end]
    assert text.count('CoreFindFreePagesI (') == 4  # definition + three calls
    allocation = text[text.index('CoreInternalAllocatePages ('):]
    assert 'if (Type != AllocateAddress)' in allocation
    # The real search function sees the same bins as production. The stub
    # models availability at low/high physical addresses and records requests.
    harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define IN
typedef uint64_t UINT64;
typedef uint32_t UINT32;
typedef unsigned long UINTN;
typedef unsigned EFI_MEMORY_TYPE;
typedef int BOOLEAN;
#define EfiMaxMemoryType 16
#define EFI_PAGE_SIZE 4096
static struct {UINT64 MaximumAddress, BaseAddress;} mMemoryTypeStatistics[16];
static UINT64 mDefaultMaximumAddress, mDefaultBaseAddress;
static unsigned calls, promoted, allow_promote, has_low, has_high;
static UINT64 highest;
static UINT64 CoreFindFreePagesI(UINT64 max, UINT64 min, UINT64 pages,
    EFI_MEMORY_TYPE type, UINTN align, BOOLEAN guard) {
  (void)pages; (void)type; (void)align; (void)guard;
  ++calls;
  if (max > highest) highest = max;
  if (has_high && max >= 0x8c000ffffULL && min <= 0x8c0000000ULL)
    return 0x8c0000000ULL;
  if (has_low && max >= 0xc000ffffULL && min <= 0xc0000000ULL)
    return 0xc0000000ULL;
  return 0;
}
static int PromoteMemoryResource(void) {
  if (allow_promote && !promoted++) {has_low = 1; return 1;}
  return 0;
}
FUNCTION
static void reset(void) {
  for (int i=0;i<16;++i) {mMemoryTypeStatistics[i].MaximumAddress=UINT64_MAX;
    mMemoryTypeStatistics[i].BaseAddress=0;}
  mDefaultMaximumAddress=UINT64_MAX; mDefaultBaseAddress=0;
  calls=promoted=allow_promote=has_low=has_high=0; highest=0;
}
int main(void) {
  reset();has_low=has_high=1;
#ifdef HOUJI_LOW_UEFI_ALLOCS
  assert(FindFreePages(UINT64_MAX,1,4,4096,0)==0xc0000000ULL);
  assert(highest<=UINT32_MAX);
  reset();has_high=1;
  assert(FindFreePages(UINT64_MAX,1,4,4096,0)==0);
  assert(highest<=UINT32_MAX);
  reset();has_low=has_high=1;
  mMemoryTypeStatistics[4].MaximumAddress=0x8c000ffffULL;
  mMemoryTypeStatistics[4].BaseAddress=0x8c0000000ULL;
  mDefaultMaximumAddress=0x8c000ffffULL;
  assert(FindFreePages(UINT64_MAX,1,4,4096,0)==0xc0000000ULL);
  assert(calls==1 && highest==UINT32_MAX);
  reset();has_low=has_high=1;
  assert(FindFreePages(0xbfffffffULL,1,4,4096,1)==0);
  assert(highest==0xbfffffffULL);
  reset();has_high=1;allow_promote=1;
  assert(FindFreePages(UINT64_MAX,1,4,4096,0)==0xc0000000ULL);
  assert(promoted==1 && calls==2 && highest==UINT32_MAX);
  reset();has_low=1;mMemoryTypeStatistics[4].MaximumAddress=0xc000ffffULL;
  assert(FindFreePages(UINT64_MAX,1,4,4096,0)==0xc0000000ULL);
  assert(calls==1 && highest==0xc000ffffULL);
  reset();has_low=1;mDefaultMaximumAddress=0xc000ffffULL;
  mDefaultBaseAddress=0xc1000000ULL;
  assert(FindFreePages(UINT64_MAX,1,4,4096,1)==0xc0000000ULL);
  assert(mDefaultBaseAddress==0xbffff000ULL);
#else
  assert(FindFreePages(UINT64_MAX,1,4,4096,0)==0x8c0000000ULL);
  assert(highest==UINT64_MAX);
#endif
  puts("actual FindFreePages PASS");
}
'''.replace('FUNCTION', function)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / 'check.c'
        source.write_text(harness)
        for enabled in (False, True):
            binary = Path(directory) / ('high' if enabled else 'default')
            command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror']
            if enabled:
                command += ['-DHOUJI_LOW_UEFI_ALLOCS=1']
            subprocess.run(command + [str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
    print('7 houji allocation cases and unchanged default profile passed')


if __name__ == '__main__':
    main()
