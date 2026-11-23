#!/usr/bin/env python3
"""Exercise actual trial/reset helpers and inspect their four real callers.

Only boundary services are mocked. This test never opens ADB or phone storage.
The source defaults to the application's UEFI worktree, as do the existing
native recovery tests; --main can instead qualify a frozen application source.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


p = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--main', type=Path, default=Path(
    '${HOUJI_UEFI_ROOT}/Platforms/Xiaomi/houjiPkg/'
    'Application/HoujiStorageProbe/HoujiStorageProbe.c'))
args = parser.parse_args()
source = args.main.read_text()


def code_mask(text):
    """Preserve token positions while hiding braces in strings/comments."""
    pattern = r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\''
    return re.sub(pattern, lambda m: ''.join(
        '\n' if c == '\n' else ' ' for c in m.group()), text)


def closing(mask, start, left='{', right='}'):
    assert mask[start] == left
    depth = 1
    for at in range(start + 1, len(mask)):
        depth += (mask[at] == left) - (mask[at] == right)
        if not depth:
            return at + 1
    raise AssertionError('unclosed source block')


def function(name, result):
    mask = code_mask(source)
    found = re.search(r'STATIC\s+' + result + r'\s+' + name +
                      r'\s*\([^;{}]*\)\s*\{', mask)
    assert found, name
    end = closing(mask, found.end() - 1)
    return source[found.start():end]


batch = function('GpuBatchReturnRecovery', 'BOOLEAN')
trial = function('GpuTrialReturnRecovery', 'BOOLEAN')
run = function('RunUfsReadonly', 'EFI_STATUS')
run_mask = code_mask(run)


def if_scopes(text):
    mask = code_mask(text)
    for match in re.finditer(r'\bif\s*\(', mask):
        opening = mask.index('(', match.start())
        condition_end = closing(mask, opening, '(', ')')
        start = condition_end
        while mask[start].isspace():
            start += 1
        end = (closing(mask, start) if mask[start] == '{'
               else mask.index(';', start) + 1)
        yield (re.sub(r'\s+', '', mask[opening + 1:condition_end - 1]),
               start, end)


scopes = list(if_scopes(run))
calls = {m.group(1): m.start() for m in re.finditer(
    r'\bGpuTrialReturnRecovery\s*\(\s*"([^"\\]+)"\s*\)', run)}
expected = {'gpu-retained-stop-before-XNU', 'gpu-batch-complete',
            'native-loader-returned', 'storage-test-returned-error'}
assert set(calls) == expected
assert len(re.findall(r'\bGpuTrialReturnRecovery\s*\(', run_mask)) == 4
assert not re.search(r'\b(?:GpuBatchReturnRecovery|ResetSystem)\s*\(', run_mask)


def scope_for(reason, condition):
    matching = [(a, b) for cond, a, b in scopes
                if cond == condition and a <= calls[reason] < b]
    assert len(matching) == 1, (reason, condition, matching)
    return run[matching[0][0]:matching[0][1]]


retained = scope_for('gpu-retained-stop-before-XNU', '!HoujiGpuMayBoot()')
complete = scope_for('gpu-batch-complete', 'HOUJI_GPU_BATCH_UEFI_ONLY')
loader = scope_for('native-loader-returned', 'mXnuUfsRun&&!EFI_ERROR(Status)')
storage = scope_for('storage-test-returned-error', 'mXnuUfsRun&&EFI_ERROR(Status)')
assert re.search(r'for\s*\(\s*;\s*;\s*\)\s*gBS->Stall', retained)
assert re.search(r'for\s*\(\s*;\s*;\s*\)\s*gBS->Stall', complete)
assert not re.search(r'\b(?:ProbeCheckpoint|GpuBatchReturnRecovery)\s*\(', retained + complete)
assert re.search(r'Status\s*=\s*BootNativeUfsProbe\s*\(\s*ImageHandle\s*\)', loader)
assert loader.index('BootNativeUfsProbe') < loader.index('GpuTrialReturnRecovery')
assert calls['storage-test-returned-error'] > calls['native-loader-returned']
assert 'return Status;' in run[run.index(storage) + len(storage):]
# The storage tail covers errors reaching Finished; early missing BlockIO or
# an unavailable exception handler may return before it. Do not claim otherwise.
assert run.index('Finished:') < calls['storage-test-returned-error']
assert re.search(r'STATIC\s+BOOLEAN\s+mTrialRecoveryAttempted\s*;', source)

program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "GpuRecoveryRequest.h"
#define STATIC static
#define BOOLEAN int
#define VOID void
#define CONST const
#define CHAR8 char
#define UINT8 uint8_t
#define EFI_STATUS uint64_t
#define TRUE 1
#define FALSE 0
#define EFI_SUCCESS 0ULL
#define EFI_DEVICE_ERROR 0x8000000000000007ULL
#define EFI_ERROR(s) (((uint64_t)(s) >> 63) != 0)
#define EfiResetCold 0
#define Print(...) ((void)0)
#define CompareMem memcmp
struct media {unsigned MediaPresent,BlockSize,IoAlign;uint64_t LastBlock;unsigned MediaId;};
struct io {struct media*Media;EFI_STATUS(*ReadBlocks)(struct io*,unsigned,uint64_t,unsigned,void*);};
struct runtime {void(*ResetSystem)(unsigned,EFI_STATUS,unsigned,void*);};
static struct io *mGpuCheckpointParent;
static BOOLEAN mXnuUfsRun,mTrialRecoveryAttempted;
static unsigned unsafe,owner_calls,reads,checkpoints,resets,cases;
static unsigned fail_save,fail_verify,fail_read,reentrant_at,nested_calls;
static unsigned warning_read,warning_save;
static int corrupt_byte,corrupt_bit;
static char events[32];static unsigned event_bytes;
static BOOLEAN GpuTrialReturnRecovery(CONST CHAR8*);
static void event(char c){assert(event_bytes+1<sizeof events);events[event_bytes++]=c;events[event_bytes]=0;}
static BOOLEAN HoujiGpuMaySave(void){owner_calls++;event('M');return !unsafe;}
static EFI_STATUS ProbeCheckpoint(const char*reason){
 assert(reason);checkpoints++;
 if(checkpoints==1){assert(!strcmp(reason,"test-trial"));event('C');}
 else{assert(checkpoints==2 && !strcmp(reason,"gpu-batch-recovery-request-verified"));event('V');}
 if(reentrant_at==checkpoints){nested_calls++;assert(!GpuTrialReturnRecovery("reentrant"));}
 if((checkpoints==1 && fail_save)||(checkpoints==2 && fail_verify))return EFI_DEVICE_ERROR;
 return warning_save?1:EFI_SUCCESS;
}
static EFI_STATUS read_blocks(struct io*io,unsigned id,uint64_t lba,unsigned bytes,void*buf){
 assert(io==mGpuCheckpointParent && id==io->Media->MediaId && lba==1024 && bytes==4096);
 assert(!((uintptr_t)buf&4095));reads++;event('B');
 memset(buf,0x5a,bytes);assert(hgr_record(buf,864));
 if(corrupt_byte>=0)((uint8_t*)buf)[corrupt_byte]^=(uint8_t)(1u<<corrupt_bit);
 if(reentrant_at==3){nested_calls++;assert(!GpuTrialReturnRecovery("reentrant"));}
 if(fail_read)return EFI_DEVICE_ERROR;
 return warning_read?1:EFI_SUCCESS;
}
static void reset(unsigned kind,EFI_STATUS status,unsigned bytes,void*arg){
 assert(kind==EfiResetCold && status==EFI_SUCCESS && !bytes && !arg);
 assert(checkpoints==2 && reads==1 && mTrialRecoveryAttempted);
 resets++;event('R');
 // Returning from this mock must not make either actual helper report success.
}
static struct runtime runtime={reset};static struct runtime*gRT=&runtime;
'''
program += '\n' + batch + '\n' + trial + '\n'
program += r'''
static struct media media;
static struct io io;
static void fresh(void){
 media=(struct media){1,4096,4096,0x100000,77};io=(struct io){&media,read_blocks};mGpuCheckpointParent=&io;
 mXnuUfsRun=1;mTrialRecoveryAttempted=0;unsafe=0;
 owner_calls=reads=checkpoints=resets=event_bytes=0;events[0]=0;
 fail_save=fail_verify=fail_read=reentrant_at=nested_calls=warning_read=warning_save=0;
 corrupt_byte=-1;corrupt_bit=0;
}
static void twice(const char*expected){
 assert(!GpuTrialReturnRecovery("test-trial"));assert(!strcmp(events,expected));
 unsigned old_owner=owner_calls,old_reads=reads,old_saves=checkpoints,old_reset=resets;
 assert(!GpuTrialReturnRecovery("test-trial"));
 assert(owner_calls==old_owner && reads==old_reads && checkpoints==old_saves && resets==old_reset);
 cases++;
}
int main(void){
 fresh();twice("MCBVR");assert(resets==1 && mTrialRecoveryAttempted);
 for(unsigned n=0;n<5;n++){
  fresh();if(n==0)mXnuUfsRun=0;else if(n==1)mGpuCheckpointParent=0;
  else if(n==2)unsafe=1;else if(n==3)mTrialRecoveryAttempted=1;
  const char*reason=n==4?0:"test-trial";
  assert(!GpuTrialReturnRecovery(reason) && !reads && !checkpoints && !resets);
  assert(owner_calls==(n==2));assert(mTrialRecoveryAttempted==(n==3));cases++;
 }
 // Unready/unsafe eligibility does not consume the one attempt. It may become
 // eligible after the real parent or ownership proof is established.
 fresh();mGpuCheckpointParent=0;assert(!GpuTrialReturnRecovery("test-trial"));mGpuCheckpointParent=&io;
 twice("MCBVR");assert(resets==1);
 fresh();unsafe=1;assert(!GpuTrialReturnRecovery("test-trial"));unsafe=0;events[0]=0;event_bytes=0;
 twice("MCBVR");assert(resets==1);
 fresh();fail_save=1;twice("MC");assert(!reads && !resets);
 fresh();fail_read=1;twice("MCB");assert(checkpoints==1 && !resets);
 fresh();fail_verify=1;twice("MCBV");assert(!resets);
 for(unsigned at=0;at<864;at++)for(unsigned bit=0;bit<8;bit++){
  fresh();corrupt_byte=(int)at;corrupt_bit=(int)bit;twice("MCB");assert(!resets && checkpoints==1);
 }
 // Bytes beyond the exact command/recovery structure are neither modified nor
 // interpreted by these helpers. The read remains one full aligned block.
 for(unsigned at=864;at<4096;at+=127){fresh();corrupt_byte=(int)at;twice("MCBVR");assert(resets==1);}
 for(unsigned bad=0;bad<5;bad++){
  fresh();if(bad==0)media.MediaPresent=0;else if(bad==1)media.BlockSize=512;
  else if(bad==2)media.IoAlign=8192;else if(bad==3)media.LastBlock=1023;else io.Media=0;
  twice("MC");assert(!reads && checkpoints==1 && !resets);
 }
 for(unsigned align=0;align<=4096;align=align?4096:1){
  fresh();media.IoAlign=align;media.LastBlock=1024;twice("MCBVR");assert(resets==1);if(align==4096)break;
 }
 for(unsigned n=1;n<=3;n++){fresh();reentrant_at=n;twice("MCBVR");assert(nested_calls==1 && resets==1);}
 for(unsigned n=0;n<3;n++){fresh();warning_save=n!=1;warning_read=n!=0;twice("MCBVR");assert(resets==1);}
 printf("trial return: %u actual helper cases PASS (ASAN/UBSAN); four actual control paths qualified, no phone accessed.\n",cases);
 return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='houji-trial-return-') as td:
    folder = Path(td)
    c = folder / 'test.c'
    c.write_text(program)
    exe = folder / 'test'
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-I', str(p / 'native/gpu/uefi'), str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
