#!/usr/bin/env python3
"""Exercise the real new native checkpoint adapter against TPL refusal."""
from pathlib import Path
import re,subprocess,tempfile
p=Path(__file__).resolve().parents[1]
s=(p/'native/gpu/uefi/GpuSecureMemoryNative.h').read_text()
a=s.index('STATIC EFI_STATUS SecureMemorySave(');start=s.index('{',a);b=start+1;depth=1
while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
body=s[a:b]
program=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
using EFI_STATUS=uint64_t;using EFI_TPL=unsigned;using CHAR8=char;
#define STATIC static
#define CONST const
using VOID=void;
static constexpr unsigned TPL_APPLICATION=4,TPL_NOTIFY=16,TPL_HIGH_LEVEL=31,EFI_UNSUPPORTED=3,GGS_INIT=1;
static unsigned current_tpl,calls,guards,status;
static bool good;
static EFI_TPL raise(EFI_TPL t){assert(t>=current_tpl);auto old=current_tpl;current_tpl=t;return old;}
static void restore(EFI_TPL t){assert(t<=current_tpl);current_tpl=t;}
struct BS {EFI_TPL(*RaiseTPL)(EFI_TPL);void(*RestoreTPL)(EFI_TPL);};static BS bs={raise,restore},*gBS=&bs;
static int SecureCxPrerequisites(VOID*,unsigned op){assert(op==GGS_INIT && current_tpl==TPL_NOTIFY);guards++;return good;}
static EFI_STATUS ProbeCheckpoint(CONST CHAR8*){assert(current_tpl==TPL_APPLICATION && good);calls++;return status;}
template<class...T>static void Print(const wchar_t*,T...){assert(current_tpl==TPL_NOTIFY);}
'''+body+r'''
int main(){unsigned cases=0;
 for(unsigned failure=0;failure<20;failure++){
  current_tpl=TPL_NOTIFY;calls=guards=0;status=failure;good=true;
  assert(SecureMemorySave("owner")==failure && current_tpl==TPL_NOTIFY && calls==1 && guards==1);cases++;
 }
 for(unsigned t=0;t<=TPL_HIGH_LEVEL;t++)if(t!=TPL_NOTIFY){current_tpl=t;calls=guards=0;good=true;assert(SecureMemorySave("owner")==EFI_UNSUPPORTED && !calls && !guards && current_tpl==t);cases++;}
 current_tpl=TPL_NOTIFY;calls=guards=0;good=false;assert(SecureMemorySave("owner")==EFI_UNSUPPORTED && !calls && guards==1 && current_tpl==TPL_NOTIFY);cases++;
 printf("PASS: %u actual secure checkpoint adapter cases; revalidate reset/ownership, application TPL for I/O, restore notify TPL on every returned status, refuse foreign TPL/guard\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.cpp').write_text(program)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(f/'test.cpp'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
