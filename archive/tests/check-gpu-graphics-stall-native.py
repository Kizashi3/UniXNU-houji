#!/usr/bin/env python3
"""Actual combined native capture; mock only owner/read/console boundaries."""
from pathlib import Path
import re
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
header = p / "native/gpu/uefi/GpuGraphicsStallNative.h"
text = header.read_text()
assert not re.search(r"\b(?:MmioWrite|Allocate|Free|Stall|SetMemorySpace|ProbeCheckpoint|ggs_|__asm__)[A-Za-z0-9_]*\s*\(", text)
assert "gBS" not in text and "gDS" not in text
assert text.count("GpuTryRead32(Address,Value)") == 1
assert "return GraphicsRuntimeCheck(0);" in text
source = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#define STATIC static
#define VOID void
#define CONST const
typedef char CHAR8;
static unsigned mHostRingUnsafe,mGpuSaveAllowed,prints;
static unsigned reads,owners,fail_owner,fail_read;
static int owner_error,read_error;
static uint32_t raw[20];
static const uint32_t expected[20]={0x03d00840,0x03d0084c,0x03d0208c,0x03d02084,
 0x03d02090,0x03d02094,0x03d024a0,0x03d024a4,0x03d024a8,0x03d024ac,
 0x03d024b0,0x03d024b4,0x03d02990,0x03d02984,
 0x03d990a8,0x03d990c8,0x03d990c0,0x03d9914c,0x03d99474,0x03d99478};
static void Print(const wchar_t *f,...){assert(f && !mHostRingUnsafe && mGpuSaveAllowed);prints++;}
static int GraphicsRuntimeCheck(unsigned RequireIdle){assert(!RequireIdle && mHostRingUnsafe && !mGpuSaveAllowed);owners++;return owners==fail_owner?owner_error:0;}
static int GpuTryRead32(uint32_t a,uint32_t *v){assert(v && reads<20 && a==expected[reads] && mHostRingUnsafe && !mGpuSaveAllowed);*v=0xdeadbeef;reads++;if(reads==fail_read)return read_error;*v=raw[reads-1];return 0;}
// Match the actual GpuPower include order. This existing platform header
// owns hgs_result; a short-tag collision must not pass an isolated test.
#include "GpuSmmuPlatform.h"
#include "GpuGraphicsStallNative.h"
static void reset(void){memset(mGraphicsStall,0,sizeof mGraphicsStall);mGraphicsStallRunning=mGraphicsStallStage=0;
 mHostRingUnsafe=1;mGpuSaveAllowed=0;prints=reads=owners=fail_owner=fail_read=0;owner_error=17;read_error=23;
 for(unsigned i=0;i<20;i++)raw[i]=0xabcd0000u+i;raw[0]=0x800005;
 raw[14]=0x80000000u;raw[15]=0;raw[16]=1;raw[17]=0x20000000u;
}
static void assert_prefix(const struct houji_graphics_stall_native_result*r,unsigned read_count,unsigned valid_count){
 assert(r->reads==read_count && reads==read_count && r->valid==((1u<<valid_count)-1) && r->attempted==((1u<<read_count)-1));
 for(unsigned i=0;i<14;i++)assert(r->cp.raw[i]==(i<valid_count?raw[i]:0));
 for(unsigned i=0;i<6;i++)assert(r->clock[i]==(14+i<valid_count?raw[14+i]:0));
}
int main(void){unsigned cases=0;
 for(unsigned s=0;s<2;s++){
  reset();assert(!CaptureGraphicsStall(s));const struct houji_graphics_stall_native_result*r=&mGraphicsStall[s];
  assert(r->started && r->stage==s && !r->code && r->phase==4 && r->guards==22 && owners==22 && !r->owner_code && !r->read_code && !r->failed_read_seen && !mGraphicsStallRunning && !prints);
  assert_prefix(r,20,20);struct houji_graphics_stall_native_result saved=*r;
  assert(CaptureGraphicsStall(s)==HCS_REUSED && !memcmp(r,&saved,sizeof saved) && reads==20 && owners==22);
  GraphicsStallReport();assert(!prints && !r->reported);mHostRingUnsafe=0;GraphicsStallReport();assert(!prints && !r->reported);
  mGpuSaveAllowed=1;GraphicsStallReport();assert(prints==21 && r->reported);GraphicsStallReport();assert(prints==21);cases++;
 }
 for(unsigned stage=0;stage<2;stage++)for(unsigned n=1;n<=22;n++)for(unsigned sign=0;sign<2;sign++){
  reset();fail_owner=n;owner_error=sign?-17:17;assert(CaptureGraphicsStall(stage)==HCS_OWNER);
  const struct houji_graphics_stall_native_result*r=&mGraphicsStall[stage];unsigned nr=n<=15?n-1:n-2;
  assert(r->code==HCS_OWNER && r->owner_code==owner_error && r->guards==n && owners==n && !r->failed_read_seen && !r->read_code && !mGraphicsStallRunning && !prints);
  assert_prefix(r,nr,nr);struct houji_graphics_stall_native_result saved=*r;assert(CaptureGraphicsStall(stage)==HCS_REUSED && !memcmp(&saved,r,sizeof saved));cases++;
 }
 for(unsigned stage=0;stage<2;stage++)for(unsigned n=1;n<=20;n++)for(unsigned sign=0;sign<2;sign++){
  reset();fail_read=n;read_error=sign?-23:23;assert(CaptureGraphicsStall(stage)==HCS_READ);const struct houji_graphics_stall_native_result*r=&mGraphicsStall[stage];
  assert(r->code==HCS_READ && r->read_code==read_error && r->failed_read_seen && r->failed_read_address==expected[n-1] && r->failed_read_code==read_error && r->failed_read_returned==0xdeadbeef && !mGraphicsStallRunning && !prints);
  assert(r->guards==(n<=14?n:n+1) && owners==r->guards);assert_prefix(r,n,n-1);
  mHostRingUnsafe=0;mGpuSaveAllowed=1;GraphicsStallReport();assert(prints==22);cases++;
 }
 // A busy CP value is data, not permission to waive or require idle. Both
 // independent snapshots preserve their own actual observations and failures.
 reset();assert(!CaptureGraphicsStall(0));struct houji_graphics_stall_native_result first=mGraphicsStall[0];
 owners=reads=0;for(unsigned i=0;i<20;i++)raw[i]^=0xffffffffu;
 assert(!CaptureGraphicsStall(1) && !memcmp(&first,&mGraphicsStall[0],sizeof first));assert_prefix(&mGraphicsStall[1],20,20);
 mHostRingUnsafe=0;mGpuSaveAllowed=1;GraphicsStallReport();assert(prints==42);cases++;
 for(unsigned field=0;field<2;field++){
  reset();if(!field)mHostRingUnsafe=0;else mGpuSaveAllowed=1;
  assert(CaptureGraphicsStall(0)==HCS_OWNER && !reads && !owners && mGraphicsStall[0].guards==1 && mGraphicsStall[0].owner_code==1);cases++;
 }
 reset();assert(CaptureGraphicsStall(2)==HCS_ARGUMENT && CaptureGraphicsStall(0xffffffffu)==HCS_ARGUMENT && !mGraphicsStall[0].started && !reads && !owners);cases++;
 reset();mGraphicsStallRunning=1;assert(CaptureGraphicsStall(0)==HCS_ARGUMENT && !mGraphicsStall[0].started && !reads && !owners);GraphicsStallReport();assert(!prints);cases++;
 reset();uint32_t v=0xfeedface;assert(GraphicsStallRead(NULL,expected[0],&v)==HCS_ARGUMENT && v==0xfeedface && !reads);assert(GraphicsStallOwned(NULL) && !owners);cases++;
 reset();mGraphicsStallRunning=1;mGraphicsStallStage=2;assert(GraphicsStallRead(NULL,expected[0],&v)==HCS_ARGUMENT && GraphicsStallOwned(NULL) && !reads && !owners);cases++;
 reset();mGraphicsStallRunning=1;assert(GraphicsStallRead(NULL,expected[0],&v)==HCS_ARGUMENT && GraphicsStallOwned(NULL) && !reads && !owners);cases++;
 // Actual native callback denies every nearby unlisted address with no
 // backend access, including the tempting clock-enable/debug selector MMIO.
 reset();mGraphicsStallRunning=1;mGraphicsStall[0].started=1;
 const uint32_t bad[]={0,0x3d02000,0x3d0210c,0x3d990a9,0x3d9947c,0x3d72ff4,0xffffffffu};
 for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++){v=0xfeedface;assert(GraphicsStallRead(NULL,bad[i],&v)==HCS_ARGUMENT && v==0xfeedface && !reads);cases++;}
 assert(GraphicsStallRead(NULL,expected[0],NULL)==HCS_ARGUMENT && !reads);cases++;
 reset();for(unsigned i=0;i<6;i++)assert(GraphicsStallClockAddress(i)==expected[14+i] && strcmp(GraphicsStallClockName(i),"invalid"));
 assert(!GraphicsStallClockAddress(6) && !strcmp(GraphicsStallClockName(6),"invalid"));cases++;
 printf("PASS: %u actual combined graphics stall adapter cases; fixed CP14+GPUCC6, both one-shot stages, every signed owner/read failure, invalid raw/status retained, no unsafe print/BS/FS/write, no idle or frequency waiver\n",cases);
}
'''
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    (folder / "test.c").write_text(source)
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-I", str(header.parent),
                    "-I", str(p / "native/gpu"),
                    str(folder / "test.c"), "-o", str(folder / "test")], check=True)
    subprocess.run([str(folder / "test")], check=True)
