// SPDX-License-Identifier: MIT
// Adapted from AdrenoMetal 77e6694 / 63e0f0a's render-thread/gap sampler.
// Diagnostic builds only. Sampling perturbs scheduling; it is not an FPS test.
#pragma once
#include <atomic>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <fcntl.h>
#include <mach/mach.h>
#include <pthread.h>
#include <string>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <unordered_set>

#ifndef HOUJI_GPU_CPU_PROFILE
#define HOUJI_GPU_CPU_PROFILE 0
#endif

namespace houji_cpu_profile {
enum Phase : uint32_t { Gap=0, Encoding=1, Pass=2, Draw=3, End=4, Bind=5, Commit=6, Wait=7 };
static constexpr uint64_t kPeriodUs=10000, kDurationUs=90000000, kBytes=4*1024*1024;
static std::atomic<bool> enabled{false}, started{false};
static std::atomic<mach_port_t> target{MACH_PORT_NULL};
static std::atomic<uint32_t> phase{Gap};
static std::atomic<uint64_t> stackLow{0},stackTop{0};
static thread_local bool selected=false;
static uint64_t micros() {return clock_gettime_nsec_np(CLOCK_UPTIME_RAW)/1000;}

struct Sample {
 uint64_t when=0, pauseUs=0, frames[8]={};
 uint32_t phase=Gap, state=0;
 kern_return_t suspend=KERN_FAILURE, registers=KERN_FAILURE, resume=KERN_FAILURE;
};

// No allocations, user locks, symbol lookup, direct stack dereference, or IO
// while the target is suspended. Every successful suspend has a resume, also
// after register/stack read failure. A retained send right prevents port reuse.
static Sample capture(mach_port_t port,uint64_t low,uint64_t top) {
 Sample out;out.when=micros();
 thread_basic_info_data_t info={};mach_msg_type_number_t count=THREAD_BASIC_INFO_COUNT;
 if(thread_info(port,THREAD_BASIC_INFO,(thread_info_t)&info,&count)==KERN_SUCCESS)out.state=info.run_state;
 out.suspend=thread_suspend(port);
 if(out.suspend!=KERN_SUCCESS)return out;
 const uint64_t began=micros();
 out.phase=phase.load(std::memory_order_relaxed);
 arm_thread_state64_t state={};count=ARM_THREAD_STATE64_COUNT;
 out.registers=thread_get_state(port,ARM_THREAD_STATE64,(thread_state_t)&state,&count);
 if(out.registers==KERN_SUCCESS) {
  // Target Darwin 22 user VA is 39 bits. Strip PAC/tag bits before recording.
  constexpr uint64_t mask=0x0000007fffffffffull;
  const uint64_t sp=arm_thread_state64_get_sp(state)&mask;
  uint64_t fp=arm_thread_state64_get_fp(state)&mask;
  out.frames[0]=arm_thread_state64_get_pc(state)&mask;
  out.frames[1]=arm_thread_state64_get_lr(state)&mask;
  for(unsigned n=2;n<8 && micros()-began<2000;n++) {
   if(low>=top || fp<low || fp<sp || fp>top || top-fp<16 || (fp&15))break;
   static_assert(sizeof(vm_address_t)==8,"the sampler requires arm64 VM addresses");
   uint64_t record[2]={};vm_size_t copied=0;
   if(vm_read_overwrite(mach_task_self(),fp,sizeof record,(vm_address_t)record,&copied)!=KERN_SUCCESS || copied!=sizeof record)break;
   out.frames[n]=record[1]&mask;
   const uint64_t next=record[0]&mask;if(next<=fp)break;fp=next;
  }
 }
 out.resume=thread_resume(port);
 out.pauseUs=micros()-began;
 return out;
}

static bool writeAll(int fd,const char *data,size_t count) {
 while(count) {
  const ssize_t n=write(fd,data,count);
  if(n<0 && errno==EINTR)continue;
  if(n<=0)return false;data+=n;count-=static_cast<size_t>(n);
 }
 return true;
}
// A bounded, tab-separated diagnostic file. Definitions precede their samples.
// Lookup/writes occur only after resume; raw addresses remain available even
// when private framework or stripped Rust symbols cannot be resolved here.
static void clean(char *text) {for(char *p=text;*p;++p)if((unsigned char)*p<32)*p=' ';}
static void *writer(void *context) {
 std::string path=*static_cast<std::string *>(context);delete static_cast<std::string *>(context);
 pthread_setname_np("houji-cpu-profile");
 const int fd=open(path.c_str(),O_WRONLY|O_CREAT|O_TRUNC|O_CLOEXEC|O_NOFOLLOW,0600);
 struct stat st={};
 if(fd<0 || fstat(fd,&st) || !S_ISREG(st.st_mode)) {
  if(fd>=0)close(fd);enabled.store(false,std::memory_order_release);return nullptr;
 }
 uint64_t written=0;bool ok=true;
 auto emit=[&](const char *line) {
  const size_t n=strlen(line);
  if(!ok || n>kBytes-written){ok=false;return;}
  ok=writeAll(fd,line,n);if(ok)written+=n;
 };
 emit("HOUJI_CPU_PROFILE_V1\tperiod-us=10000\tduration-us=90000000\tclock=CLOCK_UPTIME_RAW\n");
 std::unordered_set<uint64_t> addresses;
 const uint64_t opened=micros();uint64_t began=0,sequence=0;
 while(ok && micros()-opened<360000000 && (!began || micros()-began<kDurationUs)) {
  usleep(kPeriodUs);
  const mach_port_t port=target.load(std::memory_order_acquire);if(port==MACH_PORT_NULL)continue;
  if(!began)began=micros();
  Sample s=capture(port,stackLow.load(),stackTop.load());
  if(s.suspend==KERN_SUCCESS && s.resume!=KERN_SUCCESS) {
   // Do not enter dladdr/allocator code if resumption was not confirmed.
   // A terminated thread may reject resume; retry the owned suspension once.
   if(thread_resume(port)!=KERN_SUCCESS){
    static const char failure[]="E\tresume-failed\n";
    (void)writeAll(fd,failure,sizeof failure-1);break;
   }
  }
  // The target is now running again. The failure values below remain evidence.
  for(uint64_t address:s.frames)if(address && addresses.size()<4096 && addresses.insert(address).second) {
   Dl_info info={};dladdr(reinterpret_cast<const void *>(address),&info);
   char image[160]={},symbol[256]={},line[560];
   const char *base=info.dli_fname?strrchr(info.dli_fname,'/'):nullptr;
   strlcpy(image,base?base+1:(info.dli_fname?:"?"),sizeof image);
   strlcpy(symbol,info.dli_sname?:"?",sizeof symbol);clean(image);clean(symbol);
   snprintf(line,sizeof line,"A\t%llx\t%llx\t%s\t%s\n",(unsigned long long)address,
    (unsigned long long)(info.dli_fbase?address-(uintptr_t)info.dli_fbase:0),image,symbol);emit(line);
  }
  char line[512];
  snprintf(line,sizeof line,"S\t%llu\t%llu\t%llu\t%u\t%u\t%d\t%d\t%d\t%llx\t%llx\t%llx\t%llx\t%llx\t%llx\t%llx\t%llx\n",
   (unsigned long long)++sequence,(unsigned long long)s.when,(unsigned long long)s.pauseUs,
   s.phase,s.state,s.suspend,s.registers,s.resume,
   (unsigned long long)s.frames[0],(unsigned long long)s.frames[1],(unsigned long long)s.frames[2],(unsigned long long)s.frames[3],
   (unsigned long long)s.frames[4],(unsigned long long)s.frames[5],(unsigned long long)s.frames[6],(unsigned long long)s.frames[7]);emit(line);
  if(s.suspend!=KERN_SUCCESS || s.resume!=KERN_SUCCESS)break;
 }
 enabled.store(false,std::memory_order_release);
 // Stop enrolment before taking the owned send right. A late enrolment handles
 // this race itself; the writer never suspends after releasing the right.
 const mach_port_t port=target.exchange(MACH_PORT_NULL,std::memory_order_acq_rel);
 if(port!=MACH_PORT_NULL)mach_port_deallocate(mach_task_self(),port);
 close(fd);return nullptr;
}
static void start(const char *cache) {
#if HOUJI_GPU_CPU_PROFILE
 if(!cache || strcmp(getprogname(),"backboardd") || started.exchange(true))return;
 enabled.store(true,std::memory_order_release);
 auto *path=new std::string(std::string(cache)+"/cpu-profile.log");
 pthread_t thread;
 if(pthread_create(&thread,nullptr,writer,path)){delete path;enabled.store(false);return;}
 pthread_detach(thread);
#else
 (void)cache;
#endif
}
static void windowOpen() {
#if HOUJI_GPU_CPU_PROFILE
 if(!enabled.load(std::memory_order_acquire))return;
 if(selected){phase.store(Encoding,std::memory_order_relaxed);return;}
 if(target.load(std::memory_order_acquire)!=MACH_PORT_NULL)return;
 char name[64]={};pthread_getname_np(pthread_self(),name,sizeof name);
 if(strncmp(name,"com.apple.coreanimation",23))return;
 const uint64_t top=(uintptr_t)pthread_get_stackaddr_np(pthread_self());
 const uint64_t bytes=pthread_get_stacksize_np(pthread_self());
 if(!bytes || top<bytes)return;
 // Only the first matching render thread is sampled; do not silently switch
 // stacks while the profiler is reading a suspended thread.
 static std::atomic_flag enrolment=ATOMIC_FLAG_INIT;
 if(enrolment.test_and_set(std::memory_order_acquire))return;
 if(enabled.load(std::memory_order_acquire) && target.load()==MACH_PORT_NULL) {
  const mach_port_t port=mach_thread_self();
  stackTop.store(top);stackLow.store(top-bytes);phase.store(Encoding);
  target.store(port,std::memory_order_release);selected=true;
  if(!enabled.load(std::memory_order_acquire)) {
   const mach_port_t late=target.exchange(MACH_PORT_NULL);
   if(late!=MACH_PORT_NULL)mach_port_deallocate(mach_task_self(),late);
  }
 }
 enrolment.clear(std::memory_order_release);
#endif
}
static void windowClose() {
#if HOUJI_GPU_CPU_PROFILE
 if(selected)phase.store(Gap,std::memory_order_relaxed);
#endif
}
struct Scope {
 uint32_t previous=Gap;bool active=false;
 explicit Scope(Phase value) {
#if HOUJI_GPU_CPU_PROFILE
  active=selected && enabled.load(std::memory_order_relaxed);
  if(active)previous=phase.exchange(value,std::memory_order_relaxed);
#else
  (void)value;
#endif
 }
 ~Scope(){if(active)phase.store(previous,std::memory_order_relaxed);}
};
}
