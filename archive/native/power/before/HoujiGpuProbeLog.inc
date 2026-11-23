/* SPDX-License-Identifier: MIT
 * Read only the two fixed root-owned probe logs. Never hold the GPU gate
 * during filesystem I/O. Dump only after the real GPU reset/halt boundary.
 */
#ifndef HOUJI_GPU_PROBE_LOG_INC
#define HOUJI_GPU_PROBE_LOG_INC
#include <sys/vnode.h>
#include <sys/uio.h>
static char gHoujiProbeLog[32769];
static int houjiProbeRead(const char*path,unsigned capacity,unsigned*used){
 *used=0;if(!capacity || capacity>sizeof(gHoujiProbeLog)-1)return EINVAL;
 vnode_t vp=nullptr;vfs_context_t ctx=vfs_context_kernel();if(!ctx)return ENXIO;
 int e=vnode_lookup(path,VNODE_LOOKUP_NOFOLLOW,&vp,ctx);if(e)return e;
 struct vnode_attr attr;VATTR_INIT(&attr);VATTR_WANTED(&attr,va_uid);VATTR_WANTED(&attr,va_data_size);
 e=vnode_getattr(vp,&attr,ctx);
 if(!e && (!vnode_isreg(vp) || !VATTR_IS_SUPPORTED(&attr,va_uid) || !VATTR_IS_SUPPORTED(&attr,va_data_size) || attr.va_uid!=0 || attr.va_data_size>65536))e=EINVAL;
 if(!e){unsigned n=attr.va_data_size<capacity?(unsigned)attr.va_data_size:capacity;int residual=0;
  if(n)e=vn_rdwr(UIO_READ,vp,gHoujiProbeLog,n,0,UIO_SYSSPACE,0,vfs_context_ucred(ctx),&residual,vfs_context_proc(ctx));
  if(!e && residual>=0 && (unsigned)residual<=n){*used=n-residual;gHoujiProbeLog[*used]=0;}else if(!e)e=EIO;
 }
 vnode_put(vp);return e;
}
static bool houjiProbeContains(unsigned used,const char*needle){
 size_t n=strlen(needle);if(!n || n>used)return false;
 for(unsigned i=0;i<=used-n;i++)if(!memcmp(gHoujiProbeLog+i,needle,n))return true;
 return false;
}
static unsigned houjiProbeLogState(void){
 unsigned used=0;if(houjiProbeRead("/private/var/ngpu/logs/adrenometalprobe.jsonl",32768,&used) || !used)return 0;
 if(houjiProbeContains(used,"\"pass\":false"))return 2;
 if(houjiProbeContains(used,"\"stage\":\"complete\""))return 1;
 return 0;
}
static void houjiProbeLogDump(void){
 const char*paths[]={"/private/var/ngpu/logs/adrenometalprobe.jsonl","/private/var/ngpu/logs/adrenometalprobe.stderr.log"};
 for(unsigned which=0;which<2;which++){
  unsigned used=0;int e=houjiProbeRead(paths[which],which?8192:32768,&used);
  IOLog("HOUJI PROBE FILE: which=%u read-error=%d bytes=%u; fixed regular root-owned path, no-follow\n",which,e,used);if(e)continue;
  for(unsigned at=0;at<used;){unsigned count=0;while(at+count<used && count<480 && gHoujiProbeLog[at+count]!='\n')++count;
   IOLog("HOUJI PROBE %s: %.*s\n",which?"STDERR":"JSON",count,gHoujiProbeLog+at);at+=count;if(at<used && gHoujiProbeLog[at]=='\n')++at;
  }
 }
}
#endif
