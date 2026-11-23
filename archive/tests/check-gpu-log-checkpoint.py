#!/usr/bin/env python3
"""Compile and fault-inject the actual UEFI durable checkpoint writer."""
from pathlib import Path
import subprocess
import tempfile
p=Path(__file__).resolve().parents[1]
u=p/'native/gpu/uefi/LogFsTest.h'
body=u.read_text().split('EFI_STATUS EFIAPI ProbeCheckpoint',1)[1]
program=r'''
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <vector>
#include <cstdio>
using UINTN=size_t;using UINT32=uint32_t;using UINT64=uint64_t;using EFI_STATUS=uint64_t;
using EFI_TPL=unsigned;using CHAR8=char;using VOID=void;
#define CONST const
#define EFIAPI
#define EFI_ERROR(x) ((x)!=0)
#define TRUE true
#define FALSE false
enum {EFI_NOT_READY=1,EFI_UNSUPPORTED,EFI_BUFFER_TOO_SMALL,EFI_DEVICE_ERROR,EFI_OUT_OF_RESOURCES,EFI_CRC_ERROR};
enum {TPL_APPLICATION=4,TPL_HIGH_LEVEL=31,EFI_FILE_MODE_READ=1,EFI_FILE_MODE_WRITE=2};
static bool mXnuUfsRun=true,mLogFsWritesArmed,mProbeLogFrozen,mProbeLogTruncated;
static unsigned current_tpl=TPL_APPLICATION,operations,fail_at,flushes,closes,corrupt;
static char mProbeLog[131072];static size_t mProbeLogLength;
static std::vector<char> disk;
static unsigned step(){return ++operations==fail_at?EFI_DEVICE_ERROR:0;}
template<class... T>static void Print(const wchar_t*,T...){if(!mProbeLogFrozen){memcpy(mProbeLog+mProbeLogLength,"line\n",5);mProbeLogLength+=5;}}
static int CompareMem(const void*a,const void*b,size_t n){return memcmp(a,b,n);}
static void* AllocatePool(size_t n){return malloc(n);}
static void FreePool(void*p){free(p);}
struct EFI_FILE_PROTOCOL {
 EFI_STATUS(*Open)(EFI_FILE_PROTOCOL*,EFI_FILE_PROTOCOL**,const wchar_t*,uint64_t,uint64_t);
 EFI_STATUS(*SetPosition)(EFI_FILE_PROTOCOL*,uint64_t);
 EFI_STATUS(*Write)(EFI_FILE_PROTOCOL*,size_t*,const void*);
 EFI_STATUS(*Flush)(EFI_FILE_PROTOCOL*);
 EFI_STATUS(*Close)(EFI_FILE_PROTOCOL*);
 EFI_STATUS(*Read)(EFI_FILE_PROTOCOL*,size_t*,void*);
};
static EFI_FILE_PROTOCOL root,file;
static EFI_STATUS open_file(EFI_FILE_PROTOCOL*,EFI_FILE_PROTOCOL**out,const wchar_t*name,uint64_t mode,uint64_t attr){
 assert(mLogFsWritesArmed && mProbeLogFrozen && !wcscmp(name,L"\\UniXNU.log") && !attr);
 assert(mode==1 || mode==3);if(auto s=step())return s;*out=&file;return 0;}
static EFI_STATUS position(EFI_FILE_PROTOCOL*,uint64_t at){assert(!at);return step();}
static EFI_STATUS write(EFI_FILE_PROTOCOL*,size_t*n,const void*b){
 assert(mLogFsWritesArmed && mProbeLogFrozen);if(auto s=step())return s;
 disk.assign(static_cast<const char*>(b),static_cast<const char*>(b)+*n);return 0;}
static EFI_STATUS flush(EFI_FILE_PROTOCOL*){assert(mLogFsWritesArmed);return step();}
static EFI_STATUS close_file(EFI_FILE_PROTOCOL*){assert(mLogFsWritesArmed);closes++;return step();}
static EFI_STATUS read(EFI_FILE_PROTOCOL*,size_t*n,void*out){
 assert(mLogFsWritesArmed);if(auto s=step())return s;
 assert(*n==disk.size()+1);*n=disk.size();memcpy(out,disk.data(),*n);
 if(corrupt && *n)static_cast<char*>(out)[0]^=1;return 0;}
struct EFI_SIMPLE_FILE_SYSTEM_PROTOCOL {EFI_STATUS(*OpenVolume)(EFI_SIMPLE_FILE_SYSTEM_PROTOCOL*,EFI_FILE_PROTOCOL**);};
static EFI_STATUS volume(EFI_SIMPLE_FILE_SYSTEM_PROTOCOL*,EFI_FILE_PROTOCOL**out){assert(mLogFsWritesArmed);if(auto s=step())return s;*out=&root;return 0;}
struct EFI_BLOCK_IO_PROTOCOL {EFI_STATUS(*FlushBlocks)(EFI_BLOCK_IO_PROTOCOL*);};
static EFI_STATUS blocks(EFI_BLOCK_IO_PROTOCOL*){assert(mLogFsWritesArmed);flushes++;return step();}
static EFI_SIMPLE_FILE_SYSTEM_PROTOCOL fs={volume},*mGpuCheckpointFs=&fs;
static EFI_BLOCK_IO_PROTOCOL parent={blocks},*mGpuCheckpointParent=&parent;
static EFI_TPL raise(EFI_TPL t){unsigned old=current_tpl;assert(t>=old);current_tpl=t;return old;}
static void restore(EFI_TPL t){current_tpl=t;}
static EFI_STATUS crc(const void*b,size_t n,uint32_t*out){
 if(auto s=step())return s;uint32_t c=~0u;auto p=static_cast<const unsigned char*>(b);
 for(size_t i=0;i<n;i++){c^=p[i];for(unsigned j=0;j<8;j++)c=(c>>1)^(0xedb88320u&(0u-(c&1)));}*out=~c;return 0;}
struct BS {EFI_TPL(*RaiseTPL)(EFI_TPL);void(*RestoreTPL)(EFI_TPL);EFI_STATUS(*CalculateCrc32)(const void*,size_t,uint32_t*);};
static BS bs={raise,restore,crc},*gBS=&bs;
EFI_STATUS EFIAPI ProbeCheckpoint'''+body+r'''
static void reset(){operations=flushes=closes=fail_at=corrupt=0;mProbeLogLength=5;memcpy(mProbeLog,"hello",5);disk.assign(1,'x');mLogFsWritesArmed=mProbeLogFrozen=mProbeLogTruncated=false;current_tpl=TPL_APPLICATION;}
int main(){root=file={open_file,position,write,flush,close_file,read};
 reset();assert(!ProbeCheckpoint("test"));unsigned count=operations;
 assert(!mLogFsWritesArmed && !mProbeLogFrozen && flushes==2 && closes==3);
 assert(disk.size()>5 && !memcmp(disk.data(),mProbeLog,disk.size()));
 // Repeated snapshots must replace the existing file, keep the same prefix,
 // and grow monotonically without trailing stale bytes.
 size_t previous=disk.size();assert(!ProbeCheckpoint("test2") && disk.size()>previous);
 assert(!memcmp(disk.data(),mProbeLog,disk.size()));
 for(unsigned i=1;i<=count;i++){reset();fail_at=i;assert(ProbeCheckpoint("fault"));assert(!mLogFsWritesArmed && !mProbeLogFrozen);}
 reset();corrupt=1;assert(ProbeCheckpoint("corrupt")==EFI_CRC_ERROR && !mLogFsWritesArmed);
 reset();current_tpl=16;assert(ProbeCheckpoint("tpl")==EFI_UNSUPPORTED && !operations);
 printf("PASS: actual UEFI checkpoint writer; repeated exact snapshots, CRC/readback, every %u I/O failure, corruption/TPL refusal, and closed write gate\n",count);
}
'''
with tempfile.TemporaryDirectory() as directory:
 d=Path(directory);(d/'test.cpp').write_text(program)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(d/'test.cpp'),'-o',str(d/'test')],check=True)
 subprocess.run([str(d/'test')],check=True)
