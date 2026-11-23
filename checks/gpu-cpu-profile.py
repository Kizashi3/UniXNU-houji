#!/usr/bin/env python3
"""Exercise the actual Mach sampler against a host thread, never a GPU."""
import importlib.util
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
assert platform.system() == 'Darwin' and platform.machine() == 'arm64', 'requires the Apple Silicon build host'
source = r'''
#include "NativeMetalCpuProfile.h"
#include <cassert>
using namespace houji_cpu_profile;
static std::atomic<bool> ready{false},stop{false};
static std::atomic<uint64_t> progress{0};
static uint64_t low,top;
static mach_port_t port;
__attribute__((noinline)) static void busy() {
 while(!stop.load())progress.fetch_add(1);
}
static void *run(void *) {
 top=(uintptr_t)pthread_get_stackaddr_np(pthread_self());
 low=top-pthread_get_stacksize_np(pthread_self());
 port=mach_thread_self();ready.store(true,std::memory_order_release);busy();return nullptr;
}
int main() {
 pthread_t worker;assert(!pthread_create(&worker,nullptr,run,nullptr));
 while(!ready.load(std::memory_order_acquire))usleep(1000);
 for(int i=0;i<30;i++) {
  phase.store(i%8);
  const Sample s=capture(port,i&1?0:low,i&1?0:top);
  assert(s.suspend==0 && s.registers==0 && s.resume==0 && s.frames[0]);
  assert(s.phase==(unsigned)i%8);
  if(i&1)assert(!s.frames[2]); // invalid stack bounds keep PC/LR, still resume
  const uint64_t before=progress.load();usleep(1000);assert(progress.load()>before);
 }
 const Sample bad=capture(MACH_PORT_NULL,low,top);
 assert(bad.suspend!=KERN_SUCCESS && !bad.frames[0]);
 stop.store(true);pthread_join(worker,nullptr);mach_port_deallocate(mach_task_self(),port);
 // Non-render-server executables cannot enable the writer, even in a profile build.
 start("/path-that-must-not-be-created");assert(!enabled.load());
}
'''
with tempfile.TemporaryDirectory(prefix='houji-cpu-profile-') as tmp:
    folder = Path(tmp)
    cpp = folder / 'check.cpp'
    cpp.write_text(source)
    for enabled in (0, 1):
        binary = folder / ('check' + str(enabled))
        subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O1', '-fno-omit-frame-pointer',
                        '-DHOUJI_GPU_CPU_PROFILE=' + str(enabled), '-fsanitize=address,undefined',
                        '-I', str(ROOT/'graphics/metal/AdrenoMetal'), str(cpp), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], timeout=20, check=True)

spec = importlib.util.spec_from_file_location('profile', ROOT/'tools/analyze-cpu-profile.py')
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
header = b'HOUJI_CPU_PROFILE_V1\tclock=CLOCK_UPTIME_RAW\n'
data = header + b'A\t1000\t10\tQuartzCore\t?\n'
data += b'S\t1\t1000000\t20\t0\t3\t0\t0\t0\t1000\t1000\t0\t0\t0\t0\t0\t0\n'
data += b'S\t2\t2000000\t30\t3\t1\t0\t0\t0\t2000\t0\t0\t0\t0\t0\t0\t0\n'
result = parser.analyze(data)
assert result['valid_samples'] == 2 and result['pause_total_us'] == 50
assert result['phases']['gap']['inclusive'] == [('QuartzCore`0x10', 1)]
assert parser.analyze(data.replace(b'QuartzCore\t?', b'QuartzCore\t<redacted>'))['phases']['gap']['inclusive'] == [('QuartzCore`0x10', 1)]
assert parser.analyze(data, 1.5, 2.5)['selected_samples'] == 1
assert parser.analyze(data+b'S\t')['truncated_tail']
for bad in (data.replace(b'S\t2', b'S\t4'), data.replace(b'\t3\t1\t0', b'\t8\t1\t0'), header+b'garbage\n'):
    try:
        parser.analyze(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('malformed profile accepted')
print('CPU sampler: real Mach suspend/read/resume, invalid bounds/port, disabled/gated builds and profile parser passed; no GPU or FPS claim')
