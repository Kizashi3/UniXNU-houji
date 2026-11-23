#!/usr/bin/env python3
"""Host-test actual ProbePrint and trace console gating; no firmware/device I/O."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--probe-log', type=Path, default=p.parent / 'uefi-houji' /
                    'Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe/ProbeLog.h')
args = parser.parse_args()
log = args.probe_log.read_text()
trace = (p / 'native/gpu/uefi/GpuCallTrace.c').read_text()


def function(source, name):
    match = re.search(r'^(?:STATIC\s+)?(?:VOID|UINTN|unsigned|void)\s+'
                      r'(?:EFIAPI\s+)?' + re.escape(name) + r'\s*\(', source, re.M)
    if match is None:
        raise ValueError(f'missing actual function {name}')
    end = source.index('{', match.start()) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


query = function(trace, 'HoujiGpuCallTraceConsoleSuppressed')
# Keep this query callable from ProbePrint at any point: no service/instruction
# shim is provided for it. Its actual body must remain CPU-RAM reads only.
query_body = query[query.index('{') + 1:-1]
assert not re.search(r'\b\w+\s*\(', query_body) and '__asm__' not in query_body
trace_functions = '\n'.join(function(trace, name) for name in (
    'HoujiGpuCallTraceStart', 'HoujiGpuCallTraceStop', 'HoujiGpuCallTraceResume',
    'HoujiGpuCallTraceRamOnly', 'HoujiGpuCallTraceFatal'))
counter_read = '__asm__ volatile("mrs %0,cntpct_el0":"=r"(Counter)::"memory");'
assert trace_functions.count(counter_read) == 1
trace_functions = trace_functions.replace(counter_read, 'Counter=++mTestCounter;')
assert '__asm__' not in trace_functions
globals_start = log.index('STATIC CHAR8 mProbeLog[')
globals_end = log.index('STATIC VOID', globals_start)
actual_log = log[globals_start:globals_end] + '\n' + function(log, 'ProbeLogAppend') + '\n' + function(log, 'ProbePrint')
prefix = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "GpuCallTrace.h"
#define STATIC static
#define VOID void
#define CONST const
#define EFIAPI
#define TRUE 1
#define FALSE 0
#define VA_LIST va_list
#define VA_START va_start
#define VA_END va_end
#define CopyMem memcpy
typedef uint8_t UINT8;
typedef uint16_t CHAR16;
typedef char CHAR8;
typedef uintptr_t UINTN;
typedef uint64_t UINT64;
typedef unsigned BOOLEAN;
typedef struct CONSOLE CONSOLE;
struct CONSOLE {unsigned (*OutputString)(CONSOLE *, CONST CHAR16 *);};
static unsigned ConsoleOutput(CONSOLE *, CONST CHAR16 *);
static CONSOLE console={ConsoleOutput};
static struct {CONSOLE *ConOut;} system_table={&console},*gST=&system_table;
static struct hct_ring mCallTrace;
static struct hct_screen mCallTraceScreen;
static uint64_t mCallTraceReported,mTestCounter;
static BOOLEAN mCallTraceNormalScreenSuppressed;
static unsigned format_calls,console_calls,cases;
static char console_text[512*1024],expected_text[512*1024];
static size_t console_length,expected_length;
static const CHAR16 format_ascii[]={ '%','a',0 };
static UINTN UnicodeVSPrint(CHAR16 *out,UINTN bytes,CONST CHAR16 *format,VA_LIST args) {
 assert(format==format_ascii && bytes==2048*sizeof(CHAR16));format_calls++;
 const char *message=va_arg(args,const char *);size_t length=strlen(message);
 if(length>=bytes/sizeof(*out))length=bytes/sizeof(*out)-1;
 for(size_t i=0;i<length;i++){assert((unsigned char)message[i]<=0x7f);out[i]=(UINT8)message[i];}
 out[length]=0;return length;
}
'''
suffix = r'''
static unsigned ConsoleOutput(CONSOLE *self,CONST CHAR16 *text) {
 assert(self==&console);console_calls++;size_t length=0;
 while(text[length]){assert(text[length]<=0x7f);length++;}
 assert(length<=mProbeLogLength && console_length+length<sizeof console_text);
 // Actual ProbePrint must append the entire message before the console call.
 for(size_t i=0;i<length;i++)assert((UINT8)mProbeLog[mProbeLogLength-length+i]==text[i]);
 for(size_t i=0;i<length;i++)console_text[console_length++]=(char)text[i];
 console_text[console_length]=0;return 0;
}
static void reset(void) {
 memset(mProbeLog,0,sizeof mProbeLog);mProbeLogLength=0;
 mProbeLogFrozen=mProbeLogTruncated=FALSE;
 hct_reset(&mCallTrace);memset(&mCallTraceScreen,0,sizeof mCallTraceScreen);
 mCallTraceNormalScreenSuppressed=FALSE;mCallTraceReported=mTestCounter=0;
 console_calls=format_calls=0;console_length=expected_length=0;
 console_text[0]=expected_text[0]=0;gST->ConOut=&console;
}
static void message(const char *text,unsigned output) {
 size_t length=strlen(text);unsigned before_console=console_calls,before_format=format_calls;
 size_t before_console_length=console_length;
 assert(length<2048 && expected_length+length<sizeof expected_text);
 memcpy(expected_text+expected_length,text,length);expected_length+=length;
 assert(ProbePrint(format_ascii,text)==length);
 assert(format_calls==before_format+1 && console_calls==before_console+output);
 assert(mProbeLogLength==expected_length && !memcmp(mProbeLog,expected_text,expected_length));
 assert(!mProbeLogTruncated && !mProbeLogFrozen);
 if(output)assert(console_length==before_console_length+length && !memcmp(console_text+before_console_length,text,length));
 else assert(console_length==before_console_length);
 cases++;
}
int main(void) {
 for(unsigned mode=0;mode<2;mode++)for(unsigned enabled=0;enabled<2;enabled++) {
  reset();mCallTraceNormalScreenSuppressed=mode;mCallTrace.enabled=enabled;
  assert(HoujiGpuCallTraceConsoleSuppressed()==(mode&&enabled));
  message("first diagnostic line\n",!(mode&&enabled));
  message("second line is still retained\n",!(mode&&enabled));
  reset();mCallTraceNormalScreenSuppressed=mode;mCallTrace.enabled=enabled;gST->ConOut=NULL;
  message("no console is safe\n",0);
 }
 reset();HoujiGpuCallTraceRamOnly();HoujiGpuCallTraceStart();
 assert(HoujiGpuCallTraceConsoleSuppressed());
 for(unsigned i=0;i<256;i++) {
  char text[256];int length=snprintf(text,sizeof text,"retained message %03u: CPU diagnostics before SQE; complete ordered text survives suppressed console.\n",i);
  assert(length>0 && (size_t)length<sizeof text);message(text,0);
 }
 assert(console_calls==0 && mProbeLogLength>24000);
 HoujiGpuCallTraceStop();assert(!HoujiGpuCallTraceConsoleSuppressed());message("stopped recorder displays\n",1);
 HoujiGpuCallTraceResume();assert(HoujiGpuCallTraceConsoleSuppressed());message("resumed recorder suppresses again\n",0);
 // Execute the actual fatal path, replacing only its AArch64 counter read.
 // Its screen is disabled, so this test performs no framebuffer writes.
 HoujiGpuCallTraceFatal(0x1234,0x5678,0x9abc,0xdef0);
 assert(!mCallTrace.enabled && mCallTrace.sequence==2 && !HoujiGpuCallTraceConsoleSuppressed());
 message("fatal stopped recorder displays\n",1);
 HoujiGpuCallTraceFatal(0x1234,0x5678,0x9abc,0xdef0);
 assert(!HoujiGpuCallTraceConsoleSuppressed());message("repeated fatal still displays\n",1);
 gST->ConOut=NULL;message("fatal with no console is safe\n",0);
 printf("PASS: %u actual ProbePrint/trace-console cases; all four mode/recorder states append, only RAM-only active suppresses ConOut, NULL console safe, ordered multi-message buffer intact, stop/fatal restore console\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='houji-trace-console-') as directory:
    folder = Path(directory)
    (folder / 'test.c').write_text(prefix + query + '\n' + trace_functions + '\n' + actual_log + '\n' + suffix)
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I', str(p / 'native/gpu/uefi'),
                    str(folder / 'test.c'), '-o', str(folder / 'test')], check=True)
    subprocess.run([str(folder / 'test')], check=True)
