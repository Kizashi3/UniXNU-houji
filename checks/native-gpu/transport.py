#!/usr/bin/env python3
"""Exercise the active Turnip batching and tunnel transport with an IOKit peer."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'graphics/turnip/overlay/src/freedreno/vulkan/tu_knl_darwin.cc').read_text()


def section(first, last):
    start = source.index(first)
    return source[start:source.index(last, start)]


unit = r'''
#include "NativeAdrenoABI.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <pthread.h>
#include <unistd.h>
#include <vector>
using kern_return_t=int;
using VkResult=int;
constexpr int KERN_SUCCESS=0,kIOReturnBadArgument=1,kIOReturnBusy=2,VK_SUCCESS=0;
constexpr uint32_t DW_TUNNEL_MAGIC=0x4e544e4c;
struct tu_device {int vk;};
struct tu_queue {tu_device *device;};
struct {
    int conn=1;bool tunnel=false;unsigned selector=23;NativeAdrenoAbiParams params{};
    pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
    unsigned inflight_count=0;uint32_t inflight[8]{};
} dw;
struct Request {uint32_t method;std::vector<NativeAdrenoAbiSubmitBuffer> buffers;};
static std::vector<Request> calls;
static unsigned busy=0;static bool fail=false;static uint32_t next_fence=1,last_noted=0;
static int IOConnectCallStructMethod(int connection,uint32_t selector,const void *input,size_t bytes,void *out,size_t *out_bytes){
    assert(connection==1 && out && out_bytes && *out_bytes==sizeof(NativeAdrenoAbiSubmitReply));
    uint32_t method=selector;const auto *payload=static_cast<const unsigned char*>(input);
    if(dw.tunnel){
        assert(selector==23 && bytes>=8);uint32_t header[2];memcpy(header,payload,8);
        assert(header[0]==DW_TUNNEL_MAGIC);method=header[1];payload+=8;bytes-=8;
    }
    assert(method==NativeAdrenoMethodSubmit || method==NativeAdrenoMethodSubmitBatch);
    assert(bytes==(method==NativeAdrenoMethodSubmit?416:3104));
    NativeAdrenoAbiSubmitBatch wire{};memcpy(&wire,payload,bytes);
    assert(wire.buffer_count && wire.buffer_count<=(method==NativeAdrenoMethodSubmit?16:128));
    assert(!wire.reserved && !wire.queue && !wire.wait_fence && !wire.wait_timeout_ns);
    calls.push_back({method,{wire.buffers,wire.buffers+wire.buffer_count}});
    if(fail)return 99;
    if(busy){--busy;return kIOReturnBusy;}
    static_cast<NativeAdrenoAbiSubmitReply*>(out)->fence=next_fence++;
    return KERN_SUCCESS;
}
static int vk_device_set_lost(int*,const char*,...){return -1;}
static uint64_t os_time_get_nano(){return 0;}
static int dw_wait_fence_locked_free(tu_device*,uint32_t,uint64_t){return VK_SUCCESS;}
static void darwin_note_fence(uint32_t fence){last_noted=fence;}
'''
unit += section('static kern_return_t\ndw_call(', '/* Finds an admitted selector:')
unit += section('static unsigned\ndarwin_submit_limit(', 'static VkResult\ndarwin_queue_submit(')
unit += r'''
#define MIN2(a,b) ((a)<(b)?(a):(b))
static VkResult submit_all(tu_queue *queue,const NativeAdrenoAbiSubmitBuffer *all,unsigned total){
    uint32_t fence=0;
'''
unit += section('      const unsigned limit = darwin_submit_limit();', '      p_atomic_set(&queue->fence, fence);')
unit += r'''
    assert(fence==last_noted);return VK_SUCCESS;
}
int main(){
    tu_device device{};tu_queue queue{&device};
    NativeAdrenoAbiSubmitBuffer buffers[259];
    for(unsigned i=0;i<259;++i)buffers[i]={i+1,0x80000000ull+4096*i,4096};
    for(bool tunnel:{false,true})for(bool batch:{false,true}){
        dw.tunnel=tunnel;dw.params.flags=batch?NativeAdrenoParamsSubmitBatch:0;
        const unsigned limit=batch?128:16;
        assert(darwin_submit_limit()==limit);calls.clear();
        assert(!submit_all(&queue,buffers,259));
        assert(calls.size()==(batch?3:17));unsigned seen=0;
        for(const auto &call:calls){
            assert(call.method==(batch?17u:5u));
            for(const auto &b:call.buffers){
                assert(!memcmp(&b,&buffers[seen],sizeof(b)));++seen;
            }
        }
        assert(seen==259 && calls.back().buffers.size()==3);
        const auto count=calls.size();uint32_t fence=0;
        assert(darwin_submit_chunk(&queue,buffers,0,&fence)==-1);
        assert(darwin_submit_chunk(&queue,buffers,limit+1,&fence)==-1 && calls.size()==count);
        busy=1;assert(!darwin_submit_chunk(&queue,buffers,limit,&fence));
        assert(calls.size()==count+2);
        fail=true;const auto before=calls.size();
        assert(darwin_submit_chunk(&queue,buffers,limit,&fence)==-1 && calls.size()==before+1);
        fail=false; // errors cannot fall back and accidentally submit work twice
    }
    puts("PASS: active Turnip 128/16 negotiation, exact direct/tunnel payloads, ordered chunking and no replay on failure (IOKit peer)");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-batch-transport-') as directory:
    tmp = Path(directory)
    (tmp / 'transport.cpp').write_text(unit)
    subprocess.run(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I' + str(ROOT / 'graphics/include'),
                    str(tmp / 'transport.cpp'), '-o', str(tmp / 'transport')], check=True)
    subprocess.run([str(tmp / 'transport')], check=True, timeout=10)
