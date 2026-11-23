#!/usr/bin/env python3
"""Exercise the actual portable core; optionally inspect native COFF disassembly.

--disassembly accepts llvm-objdump -dr output from the actual compiled module.
The native check follows the recorder's direct call graph and refuses service
calls, indirect branches, barriers, translation/cache operations and system
register access other than CNTPCT_EL0. It does not claim physical display or
cross-reset persistence verification.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def check_wrappers(directory):
    """Compile actual native lifecycle/report bodies with CPU-only test sinks."""
    root = Path(__file__).resolve().parents[1]
    native = (root / 'native/gpu/uefi/GpuCallTrace.c').read_text()
    names = ['HoujiGpuCallTraceStart', 'HoujiGpuCallTraceStop',
             'HoujiGpuCallTraceResume', 'HoujiGpuCallTraceRamOnly',
             'HoujiGpuCallTraceConsoleSuppressed',
             'HoujiGpuCallTraceFreezeFirstFailure', 'HoujiGpuCallTraceReport']
    bodies = []
    for name in names:
        match = re.search(r'^(?:void|unsigned) ' + name + r'\(void\) \{', native, re.M)
        assert match, name
        end = native.index('\n}', match.start()) + 2
        bodies.append(native[match.start():end])
    source = Path(directory) / 'check-native-call-trace-wrappers.c'
    source.write_text(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <wchar.h>
#include "GpuCallTrace.h"
#define TRUE true
#define FALSE false
typedef bool BOOLEAN;
static struct hct_ring mCallTrace;
static struct hct_failure mCallTraceFirstFailure;
static struct hct_screen mCallTraceScreen;
static uint64_t mCallTraceReported;
static BOOLEAN mCallTraceFirstFailureReported,mCallTraceNormalScreenSuppressed;
static uint64_t mCallTraceGopStatus;
static unsigned mCallTraceInitReason;
static struct hct_record output[8192];
static unsigned output_count,frozen_headers,frozen_mode,frozen_count;
static size_t frozen_text_bytes;
static unsigned ProbePrint(const wchar_t *format,...) {
  if (wcsstr(format,L"TRACE FIRST FAILURE: ")) {
    frozen_headers++;frozen_mode=1;
  } else if (wcsstr(format,L"TRACE FIRST FAILURE END:")) frozen_mode=0;
  return 0;
}
static void ProbeTraceAppendRecord(uint64_t seq,uint32_t step,uint64_t counter,
                                   uint64_t address,uint64_t value) {
  assert(output_count<sizeof(output)/sizeof(output[0]));
  output[output_count++]=(struct hct_record){seq,counter,address,value,step,0};
  if (frozen_mode) {
    char line[256];
    int n=snprintf(line,sizeof(line),"HOUJI GPU CALL: seq=%llu step=%u counter=%llu address=%016llX value=%016llX\n",
      (unsigned long long)seq,step,(unsigned long long)counter,
      (unsigned long long)address,(unsigned long long)value);
    assert(n>0 && (size_t)n<sizeof(line));frozen_text_bytes+=(size_t)n;frozen_count++;
  }
}
''' + '\n\n'.join(bodies) + r'''
static void push(unsigned count,uint32_t step) {
  for (unsigned i=0;i<count;i++) assert(hct_push(&mCallTrace,step,i,UINT64_MAX,UINT64_MAX));
}
int main(void) {
  HoujiGpuCallTraceRamOnly();HoujiGpuCallTraceStart();
  assert(HoujiGpuCallTraceConsoleSuppressed());
  push(1537,0x6005);HoujiGpuCallTraceFreezeFirstFailure();
  assert(mCallTrace.enabled && mCallTraceFirstFailure.first==1026);
  push(2*HCT_CAPACITY,0xdead);HoujiGpuCallTraceFreezeFirstFailure();
  HoujiGpuCallTraceReport();assert(!output_count && !frozen_headers);
  HoujiGpuCallTraceStop();assert(!HoujiGpuCallTraceConsoleSuppressed());
  HoujiGpuCallTraceReport();
  assert(output_count==HCT_CAPACITY+HCT_FAILURE_CAPACITY && frozen_headers==1);
  assert(frozen_count==HCT_FAILURE_CAPACITY && frozen_text_bytes<62*1024);
  char maximum[192];
  int maximum_length=snprintf(maximum,sizeof(maximum),"HOUJI GPU CALL: seq=%llu step=%u counter=%llu address=%016llX value=%016llX\n",
    (unsigned long long)UINT64_MAX,UINT32_MAX,(unsigned long long)UINT64_MAX,
    (unsigned long long)UINT64_MAX,(unsigned long long)UINT64_MAX);
  assert(maximum_length>0 && maximum_length*HCT_FAILURE_CAPACITY<68*1024);
  for (unsigned i=0;i<HCT_CAPACITY;i++)
    assert(output[i].sequence==2562+i && output[i].step==0xdead);
  for (unsigned i=0;i<HCT_FAILURE_CAPACITY;i++)
    assert(output[HCT_CAPACITY+i].sequence==1026+i && output[HCT_CAPACITY+i].step==0x6005);
  HoujiGpuCallTraceReport();assert(output_count==1536 && frozen_headers==1);
  HoujiGpuCallTraceResume();assert(HoujiGpuCallTraceConsoleSuppressed());
  assert(mCallTraceFirstFailure.first==1026);push(1,0xbeef);
  HoujiGpuCallTraceStop();HoujiGpuCallTraceReport();
  assert(output_count==1537 && output[1536].step==0xbeef && frozen_headers==1);
  /* Even if the normal incremental report has nothing new, an unreported
   * first-failure window is still emitted exactly once. */
  HoujiGpuCallTraceStart();assert(!mCallTraceFirstFailure.state);
  assert(HoujiGpuCallTraceConsoleSuppressed());push(512,0x5005);
  HoujiGpuCallTraceStop();HoujiGpuCallTraceReport();unsigned before=output_count;
  HoujiGpuCallTraceFreezeFirstFailure();HoujiGpuCallTraceReport();
  assert(output_count==before+512 && frozen_headers==2);
  HoujiGpuCallTraceReport();assert(output_count==before+512 && frozen_headers==2);
  puts("Actual native call-trace lifecycle/report: first window retained, no duplicate, RAM-only preserved PASS");
}
''')
    executable = Path(directory) / 'check-native-call-trace-wrappers'
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
                    '-fsanitize=address,undefined', '-I', str(root / 'native/gpu/uefi'),
                    str(source), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)


def check_native(path):
    functions = {}
    current = None
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'[0-9a-f]+ <([^>]+)>:', line)
        if match:
            current = match[1]
            functions[current] = []
        elif current:
            functions[current].append(line)
    pending = ['HoujiGpuCallTrace']
    visited = set()
    counter_reads = 0
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        assert name in functions, f'Missing native function: {name}'
        visited.add(name)
        text = '\n'.join(functions[name])
        instructions = re.findall(r'^\s*[0-9a-f]+:\s+[0-9a-f]{8}\s+(\S+)(.*)$', text, re.M)
        assert instructions, f'No native instructions: {name}'
        for mnemonic, operands in instructions:
            assert mnemonic not in {'dsb', 'dmb', 'isb', 'dc', 'ic', 'at', 'tlbi',
                                    'blr', 'br', 'smc', 'hvc', 'svc', 'msr'}, (name, mnemonic)
            if mnemonic == 'mrs':
                assert re.search(r',\s*CNTPCT_EL0\s*$', operands, re.I), (name, operands)
                counter_reads += 1
        edges = re.findall(r'IMAGE_REL_ARM64_BRANCH26\s+(\S+)', text)
        for edge in edges:
            assert edge.startswith('hct_'), f'Non-core call in critical path: {name} -> {edge}'
            pending.append(edge)
    assert counter_reads == 1, f'Unexpected counter read count: {counter_reads}'
    print(f'Native recorder: {len(visited)} reachable functions PASS; '
          'no service call, indirect branch, device read helper, cache maintenance or barrier')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disassembly', type=Path)
    args = parser.parse_args()
    source = Path(__file__).with_suffix('.c')
    with tempfile.TemporaryDirectory(prefix='houji-call-trace-') as directory:
        executable = Path(directory) / 'check-gpu-call-trace'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
                        '-fsanitize=address,undefined', str(source), '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)
        check_wrappers(directory)
    if args.disassembly:
        check_native(args.disassembly)


if __name__ == '__main__':
    main()
