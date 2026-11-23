#!/usr/bin/env python3
"""Exercise the actual narrow AMFI dyld compatibility callback; no kernel emulation."""
from pathlib import Path
import json,re,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
source=(ROOT/'kernel/overlay/bsd/kern/sweet_amfi.c').read_text()
body=source[source.index('static int\nsweet_amfi_syscall('):source.index('static const struct mac_policy_ops sweet_amfi_mac_ops')]
header=ROOT/'kernel/overlay/bsd/kern/HoujiSystemAppPaths.h'
expected=set(json.loads((ROOT/'userland/apps/system-apps.json').read_text())['applications'])
assert set(re.findall(r'"/Applications/([^/]+)/"',header.read_text()))==expected
assert '.mpo_policy_syscall = sweet_amfi_syscall' in source and '.mpc_name = "AMFI"' in source
fixture=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define ENOPOLICY 103
#define MAXPATHLEN 1024
#if !defined(__APPLE__)
typedef uintptr_t user_addr_t;
#endif
struct proc { int setugid,platform,path_error,no_terminator;const char *path; };
static struct {uint64_t input;user_addr_t output;} request;
static uint64_t answer;
static unsigned reads,writes,paths,logs;
static int input_error,output_error;
static int copyin(user_addr_t arg,void *out,size_t bytes){++reads;assert(arg==0x111&&bytes==16);if(input_error)return input_error;memcpy(out,&request,bytes);return 0;}
static int copyout(const void *in,user_addr_t arg,size_t bytes){++writes;assert(arg==0x222&&bytes==8);if(output_error)return output_error;memcpy(&answer,in,bytes);return 0;}
static int proc_issetugid(struct proc*p){return p->setugid;}
static int csproc_get_platform_binary(struct proc*p){return p->platform;}
static int proc_pidpathinfo_internal(struct proc*p,uint64_t arg,char *out,uint32_t bytes,int32_t *retval){++paths;assert(arg==0&&bytes==MAXPATHLEN&&retval);if(p->path_error)return p->path_error;if(p->no_terminator)memset(out,'A',bytes);else snprintf(out,bytes,"%s",p->path);return 0;}
static int proc_pid(struct proc*p){assert(p);return 42;}
static void proc_name(int pid,char *out,size_t bytes){assert(pid==42);snprintf(out,bytes,"fixture");}
#define printf(...) (++logs)
'''
unit=fixture+'\n#include "'+str(header)+'"\n'+body+r'''
static void reset(void){request.input=0;request.output=0x222;answer=~(uint64_t)0;reads=writes=paths=logs=0;input_error=output_error=0;}
int main(void){
 struct proc p={0,1,0,0,"/Applications/Books.app/PlugIns/BooksWidgetExtension.appex/BooksWidgetExtension"};
 reset();assert(sweet_amfi_syscall(&p,0x5a,0x111)==0);assert(answer==1&&writes==1&&logs==1&&paths==1);
 reset();assert(sweet_amfi_syscall(&p,0x60,0)==ENOPOLICY&&reads==0&&writes==0&&paths==0);
 reset();input_error=EFAULT;assert(sweet_amfi_syscall(&p,0x5a,0x111)==EFAULT&&writes==0&&paths==0);
 reset();output_error=EFAULT;assert(sweet_amfi_syscall(&p,0x5a,0x111)==EFAULT&&answer==~(uint64_t)0&&logs==0);
 for(unsigned bit=0;bit<64;++bit){reset();request.input=1ull<<bit;assert(sweet_amfi_syscall(&p,0x5a,0x111)==ENOPOLICY&&writes==0&&paths==0);}
 reset();p.setugid=1;assert(sweet_amfi_syscall(&p,0x5a,0x111)==ENOPOLICY&&writes==0&&paths==0);p.setugid=0;
 reset();p.platform=0;assert(sweet_amfi_syscall(&p,0x5a,0x111)==ENOPOLICY&&writes==0&&paths==0);p.platform=1;
 reset();p.path_error=ESRCH;assert(sweet_amfi_syscall(&p,0x5a,0x111)==ENOPOLICY&&writes==0);p.path_error=0;
 reset();p.no_terminator=1;assert(sweet_amfi_syscall(&p,0x5a,0x111)==ENOPOLICY&&writes==0);p.no_terminator=0;
 const char *bad[]={"","/sbin/launchd","/Applications/Books.app","/Applications/Books.app/","/Applications/Books.app.evil/Main","/Applications/books.app/Main","/private/var/mobile/Books.app/Main","/Applications/Books.app/../Other/Main","/Applications/Books.app/./Main","/Applications//Books.app/Main","/Applications/Books.app/..","/Applications/Books.app/."};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);++i){reset();p.path=bad[i];assert(sweet_amfi_syscall(&p,0x5a,0x111)==ENOPOLICY&&writes==0&&answer==~(uint64_t)0);}
 assert(!houji_system_app_path(NULL));
'''
for name in sorted(expected):
    unit+=' reset();p.path="/Applications/'+name+'/OriginalExecutable";assert(sweet_amfi_syscall(&p,0x5a,0x111)==0&&answer==1&&logs==1);\n'
unit+='return 0;}\n'
with tempfile.TemporaryDirectory(prefix='houji-system-app-dyld-') as tmp:
    c=Path(tmp)/'check.c';binary=Path(tmp)/'check';c.write_text(unit)
    subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(c),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print('PASS: production dyld policy, exact 32 bundle scope, only @-path bit, no env/insertion permissions, restricted/encrypted/setugid rejection, malformed paths and copy faults; no device claim')
