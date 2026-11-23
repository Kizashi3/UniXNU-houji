#!/usr/bin/env python3
"""Compile the actual TCC compatibility callback with checked user-copy fixtures."""
from pathlib import Path
import subprocess, tempfile
ROOT = Path(__file__).resolve().parents[1]
header = ROOT / 'kernel/overlay/bsd/kern/HoujiTccCompatibility.h'
source = (ROOT / 'kernel/overlay/bsd/kern/sweet_amfi.c').read_text()
assert 'return houji_tcc_extension_issue(p, arg);' in source
unit = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define MAXPATHLEN 1024
#if !defined(__APPLE__)
typedef uintptr_t user_addr_t;
#endif
struct proc {int platform,setugid,path_error,no_terminator;const char *path;};
static uint64_t request[7];
static char output[16];
static const char *class_name,*resource,*allowed_class="com.apple.tcc.kTCCServiceMediaLibrary";
static unsigned reads,writes;
static int input_error,output_error,string_error,resource_error;
static int proc_issetugid(struct proc*p){return p->setugid;}
static int csproc_get_platform_binary(struct proc*p){return p->platform;}
static int proc_pidpathinfo_internal(struct proc*p,uint64_t a,char *out,uint32_t n,int32_t *ret){
 assert(a==0&&n==1024&&ret);if(p->path_error)return p->path_error;
 if(p->no_terminator)memset(out,'x',n);else snprintf(out,n,"%s",p->path);return 0;
}
static int copyin(user_addr_t a,void *out,size_t n){
 ++reads;assert(a==0x111&&n==56);if(input_error)return input_error;memcpy(out,request,n);return 0;
}
static int copyinstr(user_addr_t a,void *out,size_t n,size_t *copied){
 assert(a==0x222||a==0x444);const char *s=a==0x222?class_name:resource;
 int error=a==0x222?string_error:resource_error;if(error)return error;size_t len=strlen(s)+1;
 if(len>n)return ENAMETOOLONG;memcpy(out,s,len);*copied=len;return 0;
}
static int copyout(const void *in,user_addr_t a,size_t n){
 ++writes;assert(a==0x333&&n==8);if(output_error)return output_error;memcpy(output,in,n);return 0;
}
'''
unit += '\n#include "' + str(header) + '"\n' + r'''
static void reset(void){
 const uint64_t valid[]={0x222,0,0x444,0,0x333,0,0};memcpy(request,valid,sizeof(valid));
 memset(output,0x5a,sizeof(output));class_name=allowed_class;
 resource="/";reads=writes=0;input_error=output_error=string_error=resource_error=0;
 houji_tcc_media_issued=houji_tcc_photos_issued=0;
}
int main(void){
 struct proc p={1,0,0,0,"/System/Library/PrivateFrameworks/TCC.framework/Support/tccd"};
 const char *allowed[]={"com.apple.tcc.kTCCServiceMediaLibrary","com.apple.tcc.kTCCServicePhotos"};
 for(unsigned service=0;service<2;++service){
 allowed_class=allowed[service];
 reset();assert(houji_tcc_extension_issue(&p,0x111)==0&&writes==1);
 assert(houji_tcc_media_issued==(service==0)&&houji_tcc_photos_issued==(service==1));
 assert(strcmp(output,"invalid")==0);for(unsigned i=8;i<sizeof(output);++i)assert(output[i]==0x5a);
 // The target library consumes this native sentinel locally, with handle 0.
 assert(!strcmp(output,"invalid"));
 for(unsigned bit=0;bit<64;++bit){reset();request[3]=1ull<<bit;assert(houji_tcc_extension_issue(&p,0x111)==ENOENT&&writes==0);}
 for(unsigned i=1;i<7;++i){if(i==3)continue;reset();request[i]=(i==2||i==4)?0:1;assert(houji_tcc_extension_issue(&p,0x111)==ENOENT&&writes==0);}
 reset();request[1]=3;request[2]=0;assert(houji_tcc_extension_issue(&p,0x111)==ENOENT&&writes==0);
 const char *bad_resources[]={"", ".", "//", "/private/var/mobile/Media"};
 for(unsigned i=0;i<sizeof(bad_resources)/sizeof(bad_resources[0]);++i){reset();resource=bad_resources[i];assert(houji_tcc_extension_issue(&p,0x111)!=0&&writes==0);}
 const char *bad[]={"", "com.apple.tcc.kTCCServiceMediaLibrar", "com.apple.tcc.kTCCServiceCamera", "com.apple.app-sandbox.read", "com.apple.tcc.kTCCServiceMediaLibrary/extra", "com.apple.tcc.kTCCServicePhoto", "com.apple.tcc.kTCCServicePhotosAdd", "com.apple.tcc.kTCCServicePhotos/extra", "com.apple.tcc.kTCCServicePhotosX"};
 for(unsigned i=0;i<sizeof(bad)/sizeof(bad[0]);++i){reset();class_name=bad[i];assert(houji_tcc_extension_issue(&p,0x111)!=0&&writes==0);}
 reset();input_error=EFAULT;assert(houji_tcc_extension_issue(&p,0x111)==EFAULT&&writes==0);
 reset();string_error=EFAULT;assert(houji_tcc_extension_issue(&p,0x111)==EFAULT&&writes==0);
 reset();resource_error=EFAULT;assert(houji_tcc_extension_issue(&p,0x111)==EFAULT&&writes==0);
 reset();output_error=EFAULT;assert(houji_tcc_extension_issue(&p,0x111)==EFAULT&&houji_tcc_media_issued==0&&houji_tcc_photos_issued==0&&output[0]==0x5a);
 }
 reset();p.platform=0;assert(houji_tcc_extension_issue(&p,0x111)==ENOENT&&reads==0);p.platform=1;
 reset();p.setugid=1;assert(houji_tcc_extension_issue(&p,0x111)==ENOENT&&reads==0);p.setugid=0;
 reset();p.path_error=ESRCH;assert(houji_tcc_extension_issue(&p,0x111)==ENOENT&&reads==0);p.path_error=0;
 reset();p.no_terminator=1;assert(houji_tcc_extension_issue(&p,0x111)==ENOENT&&reads==0);p.no_terminator=0;
 const char *paths[]={"/Applications/Music.app/Music","/usr/libexec/tccd","/System/Library/PrivateFrameworks/TCC.framework/Support/tccd/extra","/System/Library/PrivateFrameworks/TCC.framework/Support/../Support/tccd"};
 for(unsigned i=0;i<sizeof(paths)/sizeof(paths[0]);++i){reset();p.path=paths[i];assert(houji_tcc_extension_issue(&p,0x111)==ENOENT&&reads==0);}
 p.path="/System/Library/PrivateFrameworks/TCC.framework/Support/tccd";
 char log[192];reset();assert(houji_tcc_extension_snapshot(NULL,0)==0);
 assert(houji_tcc_extension_snapshot(log,1)==0&&log[0]==0);
 unsigned n=houji_tcc_extension_snapshot(log,sizeof(log));assert(n==strlen(log)&&strstr(log,"unconfined-replies=0"));
 assert(houji_tcc_extension_snapshot(log,n)==0&&log[0]==0);
 assert(houji_tcc_extension_snapshot(log,n+1)==n);
 class_name=allowed[0];assert(houji_tcc_extension_issue(&p,0x111)==0);
 class_name=allowed[1];assert(houji_tcc_extension_issue(&p,0x111)==0);
 assert(houji_tcc_extension_issue(&p,0x111)==0);
 assert(houji_tcc_extension_snapshot(log,sizeof(log))>0);
 assert(strstr(log,"unconfined-replies=1 photos-replies=2"));
 houji_tcc_media_issued=houji_tcc_photos_issued=UINT64_MAX;
 assert(houji_tcc_extension_snapshot(log,sizeof(log))>0);return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='houji-tcc-') as tmp:
    c, binary = Path(tmp)/'check.c', Path(tmp)/'check'
    c.write_text(unit)
    subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(c),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
print('PASS: exact iOS 16 ABI, tccd identity, MediaLibrary/Photos-only native unconfined results and separate counters, flags/targets/classes/copy-fault rejection; no device claim')
