#!/usr/bin/env python3
"""Check pinned PE patch plus actual SCM value/handler/registration code.

The native handler and wrapper are extracted from the real UEFI app; only the
normal-context SP sample and naked self-test invocation get host substitutes.
This does not execute firmware, SMC, GPU, or the real exception-entry assembly.
"""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import re
import struct
import subprocess
import tempfile


def extract(text, name, next_name, result):
    begin = text.index(f'STATIC {result}\n{name} (')
    end = text.index(f'\nSTATIC ', begin + 1)
    block = text[begin:end]
    assert next_name in text[end:end + 120], (name, next_name)
    return block


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--uefi', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('patch_scm', root / 'scripts/patch-scm-trace.py')
    patch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patch)
    raw = args.source.read_bytes()
    diagnostic, sites, header = patch.create(raw)
    board = args.uefi / 'Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe'
    assert header == (board / 'ScmTraceSites.inc').read_text()
    assert len(sites) == 9
    restored = bytearray(diagnostic)
    for site in sites:
        assert struct.unpack_from('<I', diagnostic, site['rva'])[0] == patch.BRK_OPCODE
        struct.pack_into('<I', restored, site['rva'], site['opcode'])
    assert bytes(restored) == raw
    for offset, opcode in patch.CALLS.items():
        assert struct.unpack_from('<I', diagnostic, offset)[0] == opcode
    # Exact byte preservation also covers every SMC, load/store and failure branch.
    for n in range(0, len(raw) - 3, 4):
        if struct.unpack_from('<I', raw, n)[0] == 0xD4000003:
            assert diagnostic[n:n + 4] == raw[n:n + 4]
    wrong = bytearray(raw)
    wrong[0x150C] ^= 1
    try:
        patch.create(wrong)
    except ValueError:
        pass
    else:
        raise AssertionError('Wrong raw PE accepted')
    app = (board / 'HoujiStorageProbe.c').read_text()
    assert 'HOUJI LOGFS r128:' in app
    assert app.count('HoujiGpuCallTraceInit (') == 1
    assert 'HoujiGpuCallTraceInit();' not in app
    assert app.index('if (HandleScmTrace (Type, C))') < app.index('HOUJI_CALL_TRACE(0x7000')
    handler = extract(app, 'HandleScmTrace', 'HandleClockTrace', 'BOOLEAN')
    readable = extract(app, 'ScmTraceReadable', 'ValidateScmTraceCode', 'BOOLEAN')
    validator = extract(app, 'ValidateScmTraceCode', 'RunScmTrace', 'BOOLEAN')
    wrapper = extract(app, 'RunScmTrace', 'StartFoundationRange', 'EFI_STATUS')
    for forbidden in ('Print (', 'gBS->', 'SerialPortWrite', 'Allocate', 'Mmio', 'ProbeCheckpoint'):
        assert forbidden not in handler, forbidden
    assert wrapper.count('__asm__ volatile ("mov %0, sp" : "=r" (mScmTraceEntrySp));') == 1
    wrapper = wrapper.replace('__asm__ volatile ("mov %0, sp" : "=r" (mScmTraceEntrySp));',
                              'mScmTraceEntrySp = 0xA764C000;')
    assert wrapper.count('ClockTraceSelfTest ();') == 1
    wrapper = wrapper.replace('ClockTraceSelfTest ();', 'test_selftest ();')
    substitutions = {
        '__asm__ volatile ("mrs %0,CurrentEL" : "=r" (El));': 'El = test_el;',
        '__asm__ volatile ("mrs %0,par_el1" : "=r" (SavedPar));': 'SavedPar = test_par_register;',
        '__asm__ volatile ("at s1e1r,%1; isb; mrs %0,par_el1" : "=r" (Par) : "r" (Page) : "memory");': 'Par = test_read_par (Page);',
        '__asm__ volatile ("msr par_el1,%0; isb" :: "r" (SavedPar) : "memory");': 'test_par_register = SavedPar;',
    }
    for instruction, replacement in substitutions.items():
        assert readable.count(instruction) == 1
        readable = readable.replace(instruction, replacement)
    trace_p = (root / 'native/gpu/uefi/GpuCallTrace.c').read_bytes()
    assert trace_p == (board / 'GpuCallTrace.c').read_bytes()
    assert b'(Step>=0x8000 && Step<=0x8008)' in trace_p
    assert b'!mCallTraceNormalScreenSuppressed && Sequence' in trace_p
    declarations = app[app.index('STATIC BOOLEAN mScmTraceActive,'):app.index('\nSTATIC VOID\nUfsRetryReport')]
    preamble = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#include <setjmp.h>
typedef uint8_t UINT8; typedef uint32_t UINT32; typedef uint64_t UINT64;
typedef int64_t INT64; typedef uintptr_t UINTN; typedef int BOOLEAN;
typedef wchar_t CHAR16; typedef char CHAR8; typedef void VOID; typedef void *EFI_HANDLE;
typedef UINT64 EFI_STATUS; typedef unsigned EFI_EXCEPTION_TYPE;
typedef UINTN EFI_TPL;
#define TPL_HIGH_LEVEL 31
#define STATIC static
#define CONST const
#define TRUE 1
#define FALSE 0
#define MAX_UINT64 UINT64_MAX
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define EFI_SUCCESS 0
#define EFI_NOT_READY (UINT64_C(0x8000000000000006))
#define EFI_NOT_STARTED (UINT64_C(0x8000000000000013))
#define EFI_ABORTED (UINT64_C(0x8000000000000015))
#define EFI_COMPROMISED_DATA (UINT64_C(0x8000000000000021))
#define EFI_ERROR(s) (((s)>>63)!=0)
#define EXCEPT_AARCH64_SYNCHRONOUS_EXCEPTIONS 0
#define EXCEPT_AARCH64_SERROR 3
#define ZeroMem(p,n) memset(p,0,n)
typedef struct { UINT64 X0,X1,X2,X3,X4,X5,X6,X7,X8,X9,X10,X11,X12,X13,X14,X15,
 X16,X17,X18,X19,X20,X21,X22,X23,X24,X25,X26,X27,X28,X29,LR,SP,ELR,ESR,FAR,NZCV; } EFI_SYSTEM_CONTEXT_AARCH64;
typedef struct { VOID *ImageBase; UINT64 ImageSize; } EFI_LOADED_IMAGE_PROTOCOL;
typedef VOID (*HANDLER)(VOID);
typedef struct CPU CPU;
struct CPU { EFI_STATUS (*RegisterInterruptHandler)(CPU *,unsigned,HANDLER); };
typedef CPU EFI_CPU_ARCH_PROTOCOL;
struct BOOT { EFI_STATUS (*LocateProtocol)(VOID *,VOID *,VOID **);
 EFI_STATUS (*StartImage)(EFI_HANDLE,VOID *,VOID *);
 EFI_TPL (*RaiseTPL)(EFI_TPL); VOID (*RestoreTPL)(EFI_TPL); };
static struct BOOT *gBS;
static unsigned gEfiCpuArchProtocolGuid;
static UINT64 mStorageImageBase=0x11,mStorageImageBytes=0x22;
static const CHAR16 *mStorageDriverName=L"old";
static UINT32 SelfCode[2]={0xD4290960U,0xD65F03C0U};
#define ClockTraceSelfTest SelfCode
static unsigned in_handler,prints,trace_calls,initialized,starts,stops,reports;
static void Print(const CHAR16 *format,...) { (void)format;assert(!in_handler);prints++; }
static void trace(UINT32 step,UINT64 address,UINT64 value) {
 (void)step;(void)address;(void)value;trace_calls++;
}
#define HOUJI_CALL_TRACE(s,a,v) trace((s),(a),(v))
static void HoujiGpuCallTraceInit(void) { assert(!in_handler);initialized++; }
static void HoujiGpuCallTraceStart(void) { assert(!in_handler);starts++; }
static void HoujiGpuCallTraceStop(void) { assert(!in_handler);stops++; }
static void HoujiGpuCallTraceReport(void) { assert(!in_handler);reports++; }
static void StorageException(void) {}
static void test_selftest(void);
static void CpuDeadLoop(void);
static UINT64 test_el=4,test_par_register=0x12345678,test_bad_page=UINT64_MAX;
static unsigned at_calls,current_tpl=4;
static UINT64 test_read_par(UINT64 page) {
 assert(!in_handler && current_tpl==TPL_HIGH_LEVEL);at_calls++;
 test_par_register=page==test_bad_page?1:(UINT64_C(0xff)<<56)|page;return test_par_register;
}
'''
    tests = r'''
static unsigned cases;
static UINT8 *image;
static EFI_LOADED_IMAGE_PROTOCOL info;
static unsigned locate_calls,register_calls,unregister_calls,start_calls;
static unsigned fail_locate,fail_sync,fail_serror,fail_unreg_sync,fail_unreg_serror,fail_self;
static EFI_STATUS driver_status;
static HANDLER installed[4];
static jmp_buf retained_stop;
static unsigned retained_stops;
static void CpuDeadLoop(void) {assert(!in_handler);retained_stops++;longjmp(retained_stop,1);}
static EFI_SYSTEM_CONTEXT_AARCH64 context(UINTN index) {
 EFI_SYSTEM_CONTEXT_AARCH64 c;
 UINT64 *p=(UINT64 *)&c;
 for(unsigned i=0;i<sizeof(c)/8;i++)p[i]=UINT64_C(0x8020304050607000)+i*0x101;
 c.ELR=(UINTN)image+mScmTraceSites[index].Rva;c.ESR=(UINT64_C(0x3c)<<26)|HOUJI_SCM_TRACE_ISS;
 c.SP=0;c.X8=8192;c.X0=UINT64_C(0x8000000000000007);return c;
}
static void invoke(EFI_SYSTEM_CONTEXT_AARCH64 *c,unsigned expected) {
 in_handler=1;unsigned before=prints;
 assert(HandleScmTrace(0,c)==(int)expected);
 assert(prints==before);in_handler=0;
}
static void reset_trace(void) {
 mScmTraceActive=1;mScmTraceSelfTestPassed=1;mScmTraceImageBase=(UINTN)image;
 mScmTraceModuleVerified=1;mScmTraceStackVerified=0;
 mScmTraceImageBytes=HOUJI_SCM_TRACE_BYTES;mScmTraceEntrySp=0xA764C000;
 memset(mScmTraceSnapshots,0,sizeof(mScmTraceSnapshots));trace_calls=0;
}
static EFI_STATUS registration(CPU *cpu,unsigned type,HANDLER h) {
 (void)cpu;assert(!in_handler);assert(type==0 || type==3);
 if(h){register_calls++;if((type==0 && fail_sync)||(type==3 && fail_serror))return EFI_NOT_READY;
  assert(!installed[type]);installed[type]=h;return 0;}
 unregister_calls++;assert(installed[type]==StorageException);
 if((type==0 && fail_unreg_sync)||(type==3 && fail_unreg_serror))return EFI_NOT_READY;
 installed[type]=0;return 0;
}
static CPU cpu={registration};
static EFI_STATUS locate(VOID *guid,VOID *registration_key,VOID **out) {
 (void)guid;(void)registration_key;assert(!in_handler);locate_calls++;
 *out=fail_locate?0:&cpu;return fail_locate?EFI_NOT_READY:0;
}
static void test_selftest(void) {
 if(fail_self)return;
 EFI_SYSTEM_CONTEXT_AARCH64 c={0};c.ELR=(UINTN)SelfCode;c.ESR=(UINT64_C(0x3c)<<26)|0x484b;
 invoke(&c,1);assert(c.ELR==(UINTN)SelfCode+4 && mScmTraceSelfTestPassed);
}
static EFI_STATUS driver(EFI_HANDLE handle,VOID *a,VOID *b) {
 (void)handle;(void)a;(void)b;assert(!in_handler);start_calls++;
 assert(installed[0]==StorageException && installed[3]==StorageException);
 assert(mScmTraceActive && mScmTraceSelfTestPassed && starts==1);
 for(UINTN i=0;i<ARRAY_SIZE(mScmTraceSites);i++) {
  EFI_SYSTEM_CONTEXT_AARCH64 c=context(i);invoke(&c,1);
 }
 return driver_status;
}
static EFI_TPL raise_tpl(EFI_TPL tpl) {assert(!in_handler);EFI_TPL old=current_tpl;current_tpl=(unsigned)tpl;return old;}
static VOID restore_tpl(EFI_TPL tpl) {assert(!in_handler);current_tpl=(unsigned)tpl;}
static struct BOOT boot={locate,driver,raise_tpl,restore_tpl};
static void reset_wrapper(void) {
 memset(installed,0,sizeof(installed));mScmTraceActive=0;mScmTraceSelfTestPassed=0;
 locate_calls=register_calls=unregister_calls=start_calls=0;
 fail_locate=fail_sync=fail_serror=fail_unreg_sync=fail_unreg_serror=fail_self=0;
 initialized=starts=stops=reports=prints=0;driver_status=0;
 mStorageImageBase=0x11;mStorageImageBytes=0x22;mStorageDriverName=L"old";
 SelfCode[0]=0xD4290960U;SelfCode[1]=0xD65F03C0U;gBS=&boot;
 test_el=4;test_par_register=0x12345678;test_bad_page=UINT64_MAX;at_calls=0;current_tpl=4;retained_stops=0;
}
int main(int argc,char **argv) {
 assert(argc==2);FILE *f=fopen(argv[1],"rb");assert(f);
 image=aligned_alloc(4096,HOUJI_SCM_TRACE_BYTES);assert(image);
 assert(fread(image,1,HOUJI_SCM_TRACE_BYTES,f)==HOUJI_SCM_TRACE_BYTES);fclose(f);
 info=(EFI_LOADED_IMAGE_PROTOCOL){image,HOUJI_SCM_TRACE_BYTES};
 gBS=&boot;
 assert(ValidateScmTraceCode(&info));cases++;
 *(UINT64 *)(image+0xB270)=0x81234000;*(UINT64 *)(image+0xB278)=0x81235000;
 for(UINTN i=0;i<ARRAY_SIZE(mScmTraceSites);i++)for(unsigned n=0;n<64;n++)for(unsigned stack=0;stack<2;stack++) {
  reset_trace();EFI_SYSTEM_CONTEXT_AARCH64 c=context(i),before=c,want=c;
  if(stack) {
   c.SP=want.SP=(UINTN)image+0xC000;*(UINT64 *)(UINTN)(c.SP+8)=0x12345;
   mScmTraceStackVerified=1;mScmTraceStackLow=c.SP;mScmTraceStackHigh=c.SP+4096;mScmTraceEntrySp=c.SP+128;
  }
  c.X0=want.X0=(UINT64)n<<58|n;UINT64 value=0;
  assert(ScmTraceOriginalValue(i,(UINTN)image,c.ELR,c.X0,&value));
  switch(mScmTraceSites[i].Register) {
   case 2:want.X2=2;break;case 9:want.X9=56;break;
   case 8:want.X8=(UINTN)image+0xB000;break;
   case 22:want.X22=(UINTN)image+0xB000;break;
   case 19:want.X19=mScmTraceSites[i].Kind==2?c.X0:(UINTN)image+0xB000;break;
   default:assert(0);
  }
  before=c;want.ELR+=4;invoke(&c,1);
  assert(!memcmp(&c,&want,sizeof(c)) && trace_calls==4 && mScmTraceSnapshots[i].Seen);
  assert(mScmTraceSnapshots[i].Result==before.X0 && mScmTraceSnapshots[i].Pointer56==0x81234000);
  assert(mScmTraceSnapshots[i].Pointer8192==0x81235000);
  if(mScmTraceSites[i].Sample==0)assert(mScmTraceSnapshots[i].Requested==56);
  if(mScmTraceSites[i].Sample==3)assert(mScmTraceSnapshots[i].Requested==8192);
  if(stack && mScmTraceSites[i].Sample!=0 && mScmTraceSites[i].Sample!=3 && mScmTraceSites[i].Sample!=6)
   assert(mScmTraceSnapshots[i].Requested==0x12345 && (mScmTraceSnapshots[i].Flags&1));
  cases++;
 }
 for(UINTN i=0;i<ARRAY_SIZE(mScmTraceSites);i++)for(unsigned fault=0;fault<9;fault++) {
  reset_trace();EFI_SYSTEM_CONTEXT_AARCH64 c=context(i),before;
  UINT32 *word=(UINT32 *)(image+mScmTraceSites[i].Rva),saved=*word;
  if(fault==0)mScmTraceActive=0;if(fault==1)mScmTraceSelfTestPassed=0;
  if(fault==2)c.ESR^=1;if(fault==3)c.ESR=0;
  if(fault==4)c.ELR=(UINTN)image-4;if(fault==5)*word^=0x20;
  if(fault==6)mScmTraceSnapshots[i].Seen=1;if(fault==7)mScmTraceImageBytes--;
  if(fault==8)mScmTraceModuleVerified=0;
  before=c;invoke(&c,0);assert(!memcmp(&c,&before,sizeof(c)) && !trace_calls);
  *word=saved;cases++;
 }
 for(UINTN i=0;i<ARRAY_SIZE(mScmTraceSites);i++) {
  UINT64 out=0xBAD;UINT64 base=0xD29CE000;
  assert(ScmTraceOriginalValue(i,base,base+mScmTraceSites[i].Rva,0x1234,&out));
  if(mScmTraceSites[i].Kind==1)assert(out==base+0xB000);
  out=0xBAD;assert(!ScmTraceOriginalValue(i,base+1,base+1+mScmTraceSites[i].Rva,0,&out)&&out==0xBAD);
  assert(!ScmTraceOriginalValue(i,base,base+mScmTraceSites[i].Rva+4,0,&out)&&out==0xBAD);cases+=3;
 }
 {UINT64 out=0xBAD;assert(!ScmTraceOriginalValue(9,0,0,0,&out)&&out==0xBAD);
  assert(!ScmTraceOriginalValue(0,UINT64_C(0xfffffffffffff000),0,0,&out)&&out==0xBAD);
  assert(!ScmTraceOriginalValue(0,0,0,0,0));cases+=3;}
 reset_trace();assert(!HandleScmTrace(0,0));EFI_SYSTEM_CONTEXT_AARCH64 c=context(0),before=c;
 assert(!HandleScmTrace(3,&c)&&!memcmp(&c,&before,sizeof(c)));cases+=2;
 for(unsigned mode=0;mode<7;mode++) {
  reset_wrapper();if(mode==1)fail_locate=1;if(mode==2)fail_sync=1;if(mode==3)fail_serror=1;
  if(mode==4)SelfCode[1]=0;if(mode==5)fail_self=1;
  if(mode==6)driver_status=EFI_NOT_READY;
  EFI_STATUS result=RunScmTrace((VOID *)1,&info);
  if(mode==0 || mode==6)assert(result==driver_status);
  else assert(EFI_ERROR(result));
  assert(!mScmTraceActive && mStorageImageBase==0x11 && mStorageImageBytes==0x22);
  if(mode==0 || mode>=6)assert(start_calls==1 && initialized==1 && starts==1 && stops==1 && reports==1 && unregister_calls==2);
  else assert(!start_calls);
  if(mode==1)assert(!register_calls && !unregister_calls);
  if(mode==2)assert(register_calls==1 && !unregister_calls);
  if(mode==3)assert(register_calls==2 && unregister_calls==1);
  if(mode==4)assert(!initialized && !starts && unregister_calls==2);
  if(mode==5)assert(initialized==1 && starts==1 && stops==1 && reports==1 && unregister_calls==2);
  cases++;
 }
 for(unsigned mode=0;mode<2;mode++) {
  reset_wrapper();fail_unreg_sync=mode==0;fail_unreg_serror=mode==1;
  if(setjmp(retained_stop)==0) {(void)RunScmTrace((VOID *)1,&info);assert(!"retained STOP returned");}
  assert(retained_stops==1 && !mScmTraceActive && unregister_calls==2 && start_calls==1);cases++;
 }
 for(UINTN i=0;i<ARRAY_SIZE(mScmTraceSites);i++) {
  reset_wrapper();UINT32 *word=(UINT32 *)(image+mScmTraceSites[i].Rva),saved=*word;*word^=0x20;
  assert(RunScmTrace((VOID *)1,&info)==EFI_COMPROMISED_DATA && !locate_calls && !start_calls);*word=saved;cases++;
 }
 reset_wrapper();EFI_LOADED_IMAGE_PROTOCOL bad=info;bad.ImageSize--;
 assert(RunScmTrace((VOID *)1,&bad)==EFI_COMPROMISED_DATA && !locate_calls);cases++;
 for(unsigned mode=0;mode<5;mode++) {
  reset_wrapper();test_bad_page=mode<3?(UINTN)image+(mode==0?0x1000:mode==1?0x4000:0xB000):
    mode==3?((UINTN)SelfCode&~4095ULL):0xA763C000;
  EFI_STATUS status=RunScmTrace((VOID *)1,&info);
  if(mode<3)assert(status==EFI_COMPROMISED_DATA && !locate_calls && !start_calls);
  if(mode==3)assert(status==EFI_ABORTED && !start_calls && !initialized && unregister_calls==2);
  if(mode==4)assert(status==0 && start_calls==1 && !mScmTraceStackVerified);
  assert(test_par_register==0x12345678 && current_tpl==4);cases++;
 }
 reset_wrapper();test_el=8;assert(!ScmTraceReadable((UINTN)image,4096)&&!at_calls);cases++;
 assert(!ScmTraceReadable(0,0)&&!at_calls);cases++;
 assert(!ScmTraceReadable(UINT64_MAX,2)&&!at_calls);cases++;
 reset_wrapper();assert(ScmTraceReadable((UINTN)image+7,4096) && at_calls==2 && test_par_register==0x12345678 && current_tpl==4);cases++;
 free(image);printf("SCM exact trace: %u cases PASS; ASAN/UBSAN, no firmware/device execution\n",cases);return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='houji-scm-trace-') as directory:
        temp = Path(directory)
        source = temp / 'test.c'
        source.write_text(preamble + header + declarations + handler + readable + validator + wrapper + tests)
        pe = temp / 'diagnostic.efi'
        pe.write_bytes(diagnostic)
        exe = temp / 'test'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
                        '-fsanitize=address,undefined', str(source), '-o', str(exe)], check=True)
        subprocess.run([str(exe), str(pe)], check=True)
    print(f'Pinned 9-site patch restores SHA256 {hashlib.sha256(restored).hexdigest()}; real BL/BLR/SMC preserved')


if __name__ == '__main__':
    main()
