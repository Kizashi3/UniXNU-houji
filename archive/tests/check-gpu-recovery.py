#!/usr/bin/env python3
"""Exercise actual host arming bytes and native reset guard; never access a phone."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile
p=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('boot',p/'scripts/try-native-userland-boot.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
original=bytes(864)+bytes((i*17+9)&255 for i in range(4194304-864));armed=m.recovery_request(original)
assert len(armed)==len(original) and armed[864:]==original[864:]
assert armed[:14]==b'boot-recovery\0' and armed[64:74]==b'recovery\n\0'
assert m.recovery_request(armed)==armed
for n in (0,864,4096,4194303,4194305):
 try:m.recovery_request(bytes(n))
 except ValueError:pass
 else:raise AssertionError('wrong geometry accepted')
for offset in range(864):
 bad=bytearray(original);bad[offset]=1
 try:m.recovery_request(bad)
 except ValueError:pass
 else:raise AssertionError('foreign request accepted')
u=Path('${HOUJI_UEFI_ROOT}/Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe')
s=(u/'HoujiStorageProbe.c').read_text();start=s.index('STATIC BOOLEAN\nGpuBatchReturnRecovery');end=s.index('\nSTATIC EFI_STATUS\nBootNativeUfsProbe',start);body=s[start:end].strip()
program=r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "GpuRecoveryRequest.h"
#define STATIC static
#define BOOLEAN int
#define VOID void
#define UINT8 uint8_t
#define EFI_STATUS int
#define FALSE 0
#define EFI_SUCCESS 0
#define EFI_ERROR(s) ((s)!=0)
#define EfiResetCold 0
#define Print(...) ((void)0)
#define CompareMem memcmp
struct media {unsigned MediaPresent,BlockSize,IoAlign;uint64_t LastBlock;unsigned MediaId;};
struct io {struct media*Media;int(*ReadBlocks)(struct io*,unsigned,uint64_t,unsigned,void*);};
struct runtime {void(*ResetSystem)(unsigned,int,unsigned,void*);};
static struct io*mGpuCheckpointParent;
static unsigned mode,reads,checkpoints,resets;
static int read_blocks(struct io*io,unsigned id,uint64_t lba,unsigned bytes,void*buf) {
 assert(io==mGpuCheckpointParent && id==io->Media->MediaId && lba==1024 && bytes==4096 && !((uintptr_t)buf&4095));reads++;
 memset(buf,0xff,bytes);assert(hgr_record(buf,864));if(mode==2)((uint8_t*)buf)[64]=0;return mode==1;
}
static int ProbeCheckpoint(const char*s){assert(!strcmp(s,"gpu-batch-recovery-request-verified"));checkpoints++;return mode==3;}
static void reset(unsigned kind,int status,unsigned bytes,void*arg){assert(kind==0 && status==0 && !bytes && !arg);resets++;}
static struct runtime runtime={reset};static struct runtime*gRT=&runtime;
'''+body+r'''
int main(void) {
 struct media media={1,4096,4096,0x100000,77};struct io io={&media,read_blocks};mGpuCheckpointParent=&io;
 for(mode=0;mode<4;mode++) {reads=checkpoints=resets=0;assert(!GpuBatchReturnRecovery());assert(reads==1);assert(resets==(!mode));assert(checkpoints==(mode==0 || mode==3));}
 for(unsigned bad=0;bad<5;bad++) {
  reads=resets=checkpoints=0;struct media good=media;
  if(bad==0)media.MediaPresent=0;if(bad==1)media.BlockSize=512;if(bad==2)media.IoAlign=8192;if(bad==3)media.LastBlock=1023;if(bad==4)io.Media=0;
  assert(!GpuBatchReturnRecovery() && !reads && !checkpoints && !resets);media=good;io.Media=&media;
 }
 mGpuCheckpointParent=0;assert(!GpuBatchReturnRecovery());
 puts("PASS: actual firmware reset guard; exact no-wipe request, aligned bounded read, valid snapshot required, no misc writes, all failed prerequisites refuse reset");
}
'''
with tempfile.TemporaryDirectory() as folder:
 d=Path(folder);(d/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),str(d/'test.c'),'-o',str(d/'test')],check=True)
 subprocess.run([str(d/'test')],check=True)
print('PASS: host BCB builder preserves all 4193440 reserved bytes; every foreign first-864-byte request and wrong geometry refused')
