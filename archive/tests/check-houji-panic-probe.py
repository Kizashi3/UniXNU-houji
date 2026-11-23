#!/usr/bin/env python3
"""Test actual checkpoint and BCB functions with host transport/reset peers."""
from pathlib import Path
import json
import subprocess
import tempfile

P = Path(__file__).resolve().parents[1]
S = P / '.cache/ios16-reference/dxb-ios/xnu/iokit/Kernel/houji-ufs-root'
L = P / 'native/smp/panic-checkpoint-probe'


def function(text, signature):
    begin = text.index(signature)
    brace = text.index('{', begin)
    depth = 0
    for at in range(brace, len(text)):
        depth += (text[at] == '{') - (text[at] == '}')
        if depth == 0:
            return text[begin:at + 1], begin, at + 1
    raise AssertionError('Unterminated actual function')


before = (L / 'HoujiUfsRead.before.cpp').read_text()
after = (L / 'HoujiUfsRead.after.cpp').read_text()
actual = (S / 'HoujiUfsRead.cpp').read_text()
signature = 'extern "C" void houji_ufs_checkpoint('
old, lo, hi = function(before, signature)
new, nlo, nhi = function(after, signature)
assert lo == nlo and before[:lo] == after[:nlo] and before[hi:] == after[nhi:]
assert old != new
assert function(actual, signature)[0] == new
recovery, _, _ = function(after, 'static const char *setRecoveryBoot(void) {')
assert function(before, 'static const char *setRecoveryBoot(void) {')[0] == recovery
assert function(actual, 'static const char *setRecoveryBoot(void) {')[0] == recovery
old = old.replace('void houji_ufs_checkpoint(', 'void baseline_checkpoint(', 1)

cpp = r'''
#include <stdint.h>
#include <cstdio>
#include <cstring>
#include <cstdarg>
#include <string>
#include <vector>
#include <array>
#include <climits>
#include "HoujiRecoveryRecord.h"
#include "HoujiLogCommit.h"
static int lockToken;
static int *gCheckpointLock=&lockToken;
static bool gLogEnabled,gRootEnabled,gReturnRecovery,gRecoveryArmed;
struct Terminal {int kind;std::string message;};
enum {SELF=1,DIAGNOSTIC=2,NORMAL=3};
struct Peer {
  bool locked=false,probePresent=false,ensureFail=false;
  int target=0,probe=0,bcbFail=-1,commitFail=-1;
  unsigned bcbStep=0,commitStep=0,probeQueries=0;
  std::vector<std::string> events;
  std::array<uint8_t,4096> misc{};
  std::array<uint8_t,65536> image{},media{};
} p;
static unsigned cases;
#define CHECK(x) do {if(!(x)){fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);__builtin_trap();}} while(0)
static void initializeNativeFlags(){p.events.emplace_back("flags");}
[[noreturn]] static void rootDiagnosticFailure(const char *why){
  p.events.emplace_back("diagnostic");throw Terminal{DIAGNOSTIC,why};
}
static void ensureNative(){p.events.emplace_back("ensure");if(p.ensureFail)rootDiagnosticFailure("ensure");}
static void nativeStage(const char *stage){p.events.emplace_back(std::string("stage:")+stage);}
static void IOLockLock(int *lock){CHECK(lock==gCheckpointLock && !p.locked);p.locked=true;p.events.emplace_back("lock");}
static void IOLockUnlock(int *lock){CHECK(lock==gCheckpointLock && p.locked);p.locked=false;p.events.emplace_back("unlock");}
static bool PE_parse_boot_argn(const char *name,void *out,unsigned bytes){
  CHECK(bytes==sizeof(int));
  if(!strcmp(name,"houji_checkpoint_stop")){*(int *)out=p.target;return true;}
  CHECK(!strcmp(name,"houji_panic_probe"));++p.probeQueries;*(int *)out=p.probe;return p.probePresent;
}
static void IOLog(const char *,...){p.events.emplace_back("BCB-verified");}
using IOReturn=int;
enum {kIOReturnSuccess=0,kIOReturnIOError=1};
static IOReturn hostRead4k(unsigned lun,uint32_t lba,unsigned blocks,uint8_t *out){
  CHECK(lun==0 && lba==1024 && blocks==1 && out);
  p.events.emplace_back("BCB-read");
  unsigned step=p.bcbStep++;
  if(int(step)==p.bcbFail)return kIOReturnIOError;
  memcpy(out,p.misc.data(),4096);
  if(p.bcbFail==4 && step==3)out[1000]^=1;
  return kIOReturnSuccess;
}
static IOReturn writeNativeBlocks(uint32_t lba,unsigned blocks,const uint8_t *in){
  CHECK(gRecoveryArmed && lba==1024 && blocks==1 && in);
  p.events.emplace_back("BCB-write");
  if(int(p.bcbStep++)==p.bcbFail)return kIOReturnIOError;
  memcpy(p.misc.data(),in,4096);return kIOReturnSuccess;
}
static IOReturn flushNative(){
  CHECK(gRecoveryArmed);p.events.emplace_back("BCB-flush");
  return int(p.bcbStep++)==p.bcbFail?kIOReturnIOError:kIOReturnSuccess;
}
static const char *saveNativeLog(){
  p.events.emplace_back("commit-begin");
  const char *why=houjiCommitLog(p.image.data(),p.image.size(),
    [](unsigned index,const uint8_t *data){
      CHECK(index<16);p.events.emplace_back("log-write:"+std::to_string(index));
      if(int(p.commitStep++)==p.commitFail)return false;
      memcpy(p.media.data()+4096*index,data,4096);return true;
    },[](){
      p.events.emplace_back("log-flush");return int(p.commitStep++)!=p.commitFail;
    },[](unsigned index,uint8_t *out){
      CHECK(index<16);p.events.emplace_back("log-read:"+std::to_string(index));
      if(int(p.commitStep++)==p.commitFail)return false;
      memcpy(out,p.media.data()+4096*index,4096);return true;
    });
  if(!why){CHECK(p.media==p.image);p.events.emplace_back("commit-verified");}
  return why;
}
static const char *setRecoveryBoot(void);
static void logTrialReset(){
  p.events.emplace_back("normal-reset");
  if(const char *why=setRecoveryBoot())rootDiagnosticFailure(why);
  throw Terminal{NORMAL,"normal reset peer"};
}
[[noreturn]] static void panic(const char *format,...){
  CHECK(!p.locked);p.events.emplace_back("self-panic");
  CHECK(strstr(format,"HOUJI PANIC RECOVERY SELF-TEST:") && p.commitStep==34);
  CHECK(!gRecoveryArmed);
  throw Terminal{SELF,format};
}
'''
cpp += '\n' + recovery + '\n' + old + '\n' + new + '\n'
cpp += r'''
static void resetPeer(bool log,bool root,bool recovery){
  p=Peer{};gLogEnabled=log;gRootEnabled=root;gReturnRecovery=recovery;gRecoveryArmed=false;
  for(unsigned i=864;i<p.misc.size();i++)p.misc[i]=uint8_t(i*11+1);
  for(unsigned i=0;i<p.image.size();i++)p.image[i]=uint8_t(i*17+3);
}
static int run(bool actual,unsigned stop){
  try {if(actual)houji_ufs_checkpoint("fixture stage",stop);else baseline_checkpoint("fixture stage",stop);return 0;}
  catch(const Terminal &end){return end.kind;}
}
static unsigned eventAt(const char *needle){
  for(unsigned i=0;i<p.events.size();i++)if(p.events[i]==needle)return i;
  return UINT_MAX;
}
static bool intended(){return eventAt("stage:panic recovery self-test armed; verified BCB, panic after successful log commit")!=UINT_MAX;}
int main(){
  const int targets[]={-1,0,1,2,3,4,99};const unsigned stops[]={0,1,2,3,4,99,UINT_MAX};
  const int probes[]={-1,0,1,2,INT_MAX};
  for(bool log:{false,true})for(bool root:{false,true})for(bool recovery:{false,true})
  for(int target:targets)for(unsigned stop:stops)for(bool present:{false,true})for(int probe:probes){
    resetPeer(log,root,recovery);p.target=target;p.probePresent=present;p.probe=probe;
    int oldResult=run(false,stop);Peer oldPeer=p;
    resetPeer(log,root,recovery);p.target=target;p.probePresent=present;p.probe=probe;
    int result=run(true,stop);
    bool selected=stop==3 && target==3 && log && recovery && present && probe==1;
    if(selected){
      CHECK(result==SELF && !p.locked && p.bcbStep==4 && p.commitStep==34);
      CHECK(eventAt("BCB-verified")<eventAt("stage:panic recovery self-test armed; verified BCB, panic after successful log commit"));
      CHECK(intended() && eventAt("commit-verified")<eventAt("self-panic"));
      CHECK(eventAt("unlock")<eventAt("self-panic") && p.events.back()=="self-panic");
      CHECK(eventAt("normal-reset")==UINT_MAX);
      CHECK(!memcmp(p.misc.data()+864,oldPeer.misc.data()+864,4096-864));
    }else{
      CHECK(result==oldResult && p.events==oldPeer.events && p.media==oldPeer.media && p.misc==oldPeer.misc);
      CHECK(!intended() && eventAt("self-panic")==UINT_MAX);
    }
    if(!log && !root)CHECK(p.probeQueries==0 && p.bcbStep==0 && p.commitStep==0);
    if(stop!=3 || target!=3 || !log || !recovery)CHECK(p.probeQueries==0);
    CHECK(!gRecoveryArmed);++cases;
  }
  for(int failure=0;failure<5;failure++){
    resetPeer(true,true,true);p.target=3;p.probePresent=true;p.probe=1;p.bcbFail=failure;
    auto original=p.misc;CHECK(run(true,3)==DIAGNOSTIC);
    CHECK(!intended() && p.commitStep==0 && eventAt("self-panic")==UINT_MAX && eventAt("normal-reset")==UINT_MAX);
    CHECK(!gRecoveryArmed && !memcmp(p.misc.data()+864,original.data()+864,4096-864));++cases;
  }
  // Existing BCB helper normalizes the first864 only; host preflight owns the
  // foreign-request refusal. This layer must not change that existing policy.
  resetPeer(true,true,true);p.target=3;p.probePresent=true;p.probe=1;p.misc[0]='X';
  auto reserved=p.misc;CHECK(run(true,3)==SELF && p.commitStep==34 && intended());
  CHECK(!strcmp((const char *)p.misc.data(),"boot-recovery") &&
        !strcmp((const char *)p.misc.data()+64,"recovery\n") &&
        !memcmp(p.misc.data()+864,reserved.data()+864,4096-864));++cases;
  for(int failure=0;failure<34;failure++){
    resetPeer(true,true,true);p.target=3;p.probePresent=true;p.probe=1;p.commitFail=failure;
    CHECK(run(true,3)==DIAGNOSTIC && intended() && p.bcbStep==4);
    CHECK(p.commitStep==unsigned(failure+1));
    CHECK(eventAt("commit-verified")==UINT_MAX && eventAt("self-panic")==UINT_MAX && eventAt("normal-reset")==UINT_MAX);
    CHECK(p.events.back()=="diagnostic" && !gRecoveryArmed);++cases;
  }
  resetPeer(true,true,true);p.target=3;p.probePresent=true;p.probe=1;p.ensureFail=true;
  CHECK(run(true,3)==DIAGNOSTIC && p.bcbStep==0 && p.commitStep==0 && !intended());++cases;
  printf("PASS: %u actual checkpoint/baseline/BCB/real-commit scenarios; ASAN/UBSAN; no device reset; intent is not panic proof\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='houji-panic-checkpoint-') as temporary:
    folder = Path(temporary)
    source, binary = folder / 'actual-checkpoint.cpp', folder / 'actual-checkpoint'
    source.write_text(cpp)
    command = ['clang++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               '-I', str(S), str(source), '-o', str(binary)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    print(result.stdout, end='')
