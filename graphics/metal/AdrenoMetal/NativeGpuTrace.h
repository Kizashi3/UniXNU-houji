// SPDX-License-Identifier: MIT
// Disk output runs only on this thread, never on a render/completion thread.
// Records come from AdrenoMetal's stage trace with houji's nonblocking slot guard.
#pragma once
#include "bridge/NativeMetalObjects.h"
#include <atomic>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <pthread.h>
#include <string>
#include <time.h>
#include <unistd.h>

namespace houji_gpu_trace {
static_assert(sizeof(NmbStageRecord)==24,"C/Rust stage record ABI");
static constexpr uint64_t kBytes=16*1024*1024;
static constexpr uint64_t kNanos=360ull*1000000000;
static std::atomic<bool> started{false};
static bool writeAll(int fd,const void *data,size_t size) {
 const char *p=static_cast<const char *>(data);
 while(size){
  const ssize_t n=write(fd,p,size);
  if(n<0 && errno==EINTR)continue;
  if(n<=0)return false;
  p+=n;size-=static_cast<size_t>(n);
 }
 return true;
}
static void *writer(void *context) {
 const std::string path=*static_cast<std::string *>(context);
 delete static_cast<std::string *>(context);
 pthread_setname_np("houji-gpu-trace");
 const int fd=open(path.c_str(),O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC|O_NOFOLLOW,0600);
 if(fd<0){nmb_stage_ring_stop();return nullptr;}
 const uint64_t began=clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
 // 32-byte header: magic, start uptime ns, record bytes, file budget. Little endian arm64.
 struct Header {char magic[8];uint64_t began,recordSize,limit;};
 const Header header={{'H','J','G','P','U','0','1','\n'},began,sizeof(NmbStageRecord),kBytes};
 uint64_t bytes=sizeof header,cursor=0;
 bool ok=writeAll(fd,&header,sizeof header);
 NmbStageRecord records[1024];
 while(ok && bytes+sizeof(NmbStageRecord)<=kBytes &&
       clock_gettime_nsec_np(CLOCK_UPTIME_RAW)-began<kNanos) {
  const size_t room=static_cast<size_t>((kBytes-bytes)/sizeof(NmbStageRecord));
  uint64_t next=cursor;
  const size_t n=nmb_stage_ring_read(cursor,records,room<1024?room:1024,&next);
  cursor=next;
  if(n){ok=writeAll(fd,records,n*sizeof(NmbStageRecord));bytes+=n*sizeof(NmbStageRecord);}
  // Drain a backlog without sleeping; idle polls stay off the rendering threads.
  if(n<1024)usleep(250000);
 }
 nmb_stage_ring_stop();
 close(fd);
 return nullptr;
}
static void start(const char *cache) {
 const char *env=getenv("HOUJI_GPU_TRACE");
 if(!cache || !env || strcmp(env,"1") || strcmp(getprogname(),"backboardd"))return;
 if(started.exchange(true))return;
 auto *path=new std::string(std::string(cache)+"/stages.bin");
 pthread_t thread;
 if(pthread_create(&thread,nullptr,writer,path)){
  delete path;nmb_stage_ring_stop();return;
 }
 pthread_detach(thread);
}
}
