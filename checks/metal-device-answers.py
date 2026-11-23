#!/usr/bin/env python3
"""Exercise the actual device-answer cache without a GPU or private framework."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
frontend = (ROOT/'graphics/metal/AdrenoMetal/NativeBridgeMetalFrontend.mm').read_text()
start = frontend.index('static std::atomic<uint64_t> gAnswerHits')
end = frontend.index('static NSUInteger countArgAnswer', start)
actual = frontend[start:end]
source = r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <mutex>
#include <thread>
#include <unordered_map>
#include <vector>
using SEL = const char *;
using NSUInteger = uint64_t;
using id = void *;
using BOOL = bool;
static void *gDevice;
static std::unordered_map<SEL,uint64_t> gAnswers;
static std::atomic<unsigned> calls{0},failures{0};
#define NBLOG(...) ((void)0)
static const char *sel_getName(SEL sel) {return sel;}
static bool nmb_device_answer(void *,const char *selector,uint64_t arg,uint64_t *out) {
 ++calls;
 if(!strcmp(selector,"retry:") && failures.fetch_add(1)==0)return false;
 *out=!strcmp(selector,"zero:")?0:arg^(!strcmp(selector,"other:")?0x55ull:0xaaull);
 return true;
}
''' + actual + r'''
int main() {
 const SEL first="first:",other="other:",zero="zero:",retry="retry:",overflow="overflow:";
 // Zero is a successful answer too; preserve full-width arguments and selector identity.
 for(uint64_t arg:{0ull,1ull,0x100000001ull,0xffffffffffffffffull}) {
  assert(askAnswer(first,arg)==(arg^0xaa));
  assert(askAnswer(other,arg)==(arg^0x55));
 }
 assert(askAnswer(zero,1)==0);
 const unsigned cold=calls;
 for(unsigned i=0;i<10000;i++) {
  assert(askAnswer(first,0x100000001ull)==(0x100000001ull^0xaa));
  assert(askAnswer(zero,1)==0);
 }
 assert(calls==cold);
 assert(askAnswer(retry,42)==0); // failed query is not a cached false capability
 assert(askAnswer(retry,42)==(42^0xaa));
 const unsigned recovered=calls;
 assert(askAnswer(retry,42)==(42^0xaa) && calls==recovered);
 // Cold races may duplicate runtime queries, but must not cross-contaminate keys or deadlock.
 std::vector<std::thread> workers;
 for(unsigned t=0;t<8;t++)workers.emplace_back([=]{
  for(unsigned i=0;i<2000;i++) {
   const uint64_t arg=100+(i%32);
   assert(askAnswer(first,arg)==(arg^0xaa));
   assert(askAnswer(other,arg)==(arg^0x55));
  }
 });
 for(auto &worker:workers)worker.join();
 const unsigned warmed=calls;
 for(unsigned i=100;i<132;i++)assert(askAnswer(first,i)==(i^0xaa));
 assert(calls==warmed);
 // A full cache continues to answer uncached keys correctly and keeps old answers.
 for(unsigned i=0;i<2048;i++)assert(askAnswer(overflow,i)==(i^0xaa));
 assert(gAnswerEntries==1024);
 const unsigned full=calls;
 assert(askAnswer(overflow,4096)==(4096^0xaa));
 assert(askAnswer(overflow,4096)==(4096^0xaa));
 assert(calls==full+2);
 const unsigned before=calls;
 assert(askAnswer(first,1)==(1^0xaa) && calls==before);
 assert(gAnswerHits>20000 && gAnswerMisses==calls);
}
'''
with tempfile.TemporaryDirectory(prefix='houji-device-answers-') as tmp:
    folder = Path(tmp)
    cpp = folder/'check.cpp'
    cpp.write_text(source)
    for sanitizer in ('address,undefined', 'thread'):
        binary = folder/('check-' + sanitizer.replace(',', '-'))
        subprocess.run(['clang++', '-std=c++17', '-O1', '-g', '-pthread',
                        '-fsanitize=' + sanitizer, str(cpp), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30)
print('Device answers: actual cache preserves values, retries failures, bounds storage and passes concurrent sanitizer checks; no GPU/FPS claim')
