#!/usr/bin/env python3
"""Execute the actual ring under lapping, collisions and concurrent readers; no GPU."""
from pathlib import Path
import os
import importlib.util
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'graphics/runtime/overlay/crates/metal2vulkan-runtime/src/stage_trace.rs'
source = path.read_text()
# Substitute only the platform clock so rustc can exercise the ring without a libc crate.
start = source.index('pub fn now_nanos()')
end = source.index('\n/// Whether the host', start)
source = source[:start] + '''pub fn now_nanos() -> u64 {
    static CLOCK: AtomicU64 = AtomicU64::new(1);
    CLOCK.fetch_add(1, Ordering::Relaxed)
}
''' + source[end:]
source += r'''
fn main() {
    use std::thread;
    if std::env::args().nth(1).as_deref() == Some("off") {
        mark(1, Stage::CommitCall, 0);
        assert_eq!(statistics(), [0, 1]);
        return;
    }
    assert_eq!(std::mem::size_of::<StageRecord>(), 24);
    // A busy slot must not block a producer or reader.
    SLOTS[1].busy.store(true, Ordering::Release);
    mark(111, Stage::CommitCall, 111);
    assert_eq!(statistics(), [1, 2]);
    let mut out = [StageRecord::default(); 256];
    assert_eq!(read(1, &mut out), (0, 2));
    SLOTS[1].busy.store(false, Ordering::Release);
    // An older producer must not overwrite a newer lap.
    SLOTS[2].sequence.store(2 + RING as u64, Ordering::Relaxed);
    mark(112, Stage::CommitCall, 112);
    assert_eq!(statistics(), [2, 3]);
    for i in 0..RING * 2 { mark(i % 60000 + 1, Stage::CommitCall, (i % 60000 + 1) as u32); }
    let (n, mut cursor) = read(0, &mut out);
    assert!(n > 0 && out[0].sequence as usize > RING);
    let mut last = 0;
    let check = |records: &[StageRecord], last: &mut u32| {
        for r in records {
            assert!(r.when > 0 && r.sequence > *last);
            assert_eq!(r.stage, Stage::CommitCall as u16);
            assert_eq!(r.id, r.arg as u64); // mixed fields would violate this invariant
            *last = r.sequence;
        }
    };
    check(&out[..n], &mut last);
    let live = std::sync::Arc::new(AtomicU64::new(4));
    let writers: Vec<_> = (0..4).map(|k| {
        let live = live.clone();
        thread::spawn(move || {
            for i in 0..120000 {
                let id = ((k * 120000 + i) % 60000 + 1) as usize;
                mark(id, Stage::CommitCall, id as u32);
                if i % 317 == 0 { thread::yield_now(); }
            }
            live.fetch_sub(1, Ordering::Release);
        })
    }).collect();
    while live.load(Ordering::Acquire) != 0 || cursor < NEXT.load(Ordering::Acquire) {
        let (n, next) = read(cursor, &mut out);
        assert!(next >= cursor);
        check(&out[..n], &mut last);
        cursor = next;
    }
    for t in writers { t.join().unwrap(); }
    frontend(7, 65535, 0); // unknown kind ignored
    frontend(7, 39, 999999);
    let (n, _) = read(cursor, &mut out);
    assert_eq!(n, 1);
    assert_eq!((out[0].id, out[0].stage, out[0].arg), (7, 39, 65535));
    let before = statistics();
    stop(); mark(1, Stage::CommitCall, 1);
    assert_eq!(statistics(), before);
}
'''
with tempfile.TemporaryDirectory(prefix='houji-stage-ring-') as directory:
    tmp = Path(directory)
    rust = tmp / 'ring.rs'
    rust.write_text(source)
    binary = tmp / 'ring'
    subprocess.run(['rustc', '--edition=2024', '-O', '-Adead_code', str(rust), '-o', str(binary)], check=True)
    env = dict(os.environ)
    env.pop('HOUJI_GPU_TRACE', None)
    subprocess.run([str(binary), 'off'], env=env, check=True, timeout=30)
    for value in ['0', 'yes']:
        subprocess.run([str(binary), 'off'], env=dict(env, HOUJI_GPU_TRACE=value), check=True, timeout=30)
    subprocess.run([str(binary)], env=dict(env, HOUJI_GPU_TRACE='1'), check=True, timeout=60)
    # Exercise the actual disk writer with synthetic records: byte cap and failed open.
    cpp = tmp / 'writer.cpp'
    cpp.write_text(r'''
#include "NativeGpuTrace.h"
#include <cassert>
#include <sys/stat.h>
static unsigned stopped;
extern "C" size_t nmb_stage_ring_read(uint64_t from,NmbStageRecord *out,size_t n,uint64_t *next) {
 for(size_t i=0;i<n;i++)out[i]={from+i+1,123,(uint32_t)(from+i+1),1,0};
 *next=from+n;return n;
}
extern "C" void nmb_stage_ring_stop(){++stopped;}
int main(int argc,char **argv){
 assert(argc==2);
 const std::string path=std::string(argv[1])+"/stages.bin";
 houji_gpu_trace::writer(new std::string(path));
 struct stat st{};assert(stat(path.c_str(),&st)==0);
 assert(st.st_size<=houji_gpu_trace::kBytes && st.st_size>houji_gpu_trace::kBytes-24);
 assert((st.st_size-32)%24==0 && (st.st_mode&0777)==0600 && stopped==1);
 houji_gpu_trace::writer(new std::string(path+"/nonexistent"));
 assert(stopped==2);
}
''')
    executable = tmp / 'writer'
    subprocess.run(['clang++', '-std=c++17', '-O2', '-I',
                    str(ROOT/'graphics/metal/AdrenoMetal'), str(cpp), '-o', str(executable)], check=True)
    subprocess.run([str(executable), str(tmp)], check=True, timeout=30)
spec = importlib.util.spec_from_file_location('gpu_stages', ROOT / 'tools/analyze-gpu-stages.py')
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
header = parser.HEADER.pack(b'HJGPU01\n', 1, 24, parser.MAX_BYTES)
rows = [(1000, 99, 1, 30, 0), (2000, 99, 2, 31, 0), (3000, 99, 4, 33, 0),
        (3100, 99, 5, 34, 65535), (4000, 99, 6, 30, 0), (5000, 99, 7, 31, 0),
        (7000, 99, 8, 33, 0)]
data = header + b''.join(parser.RECORD.pack(*r) for r in rows)
result = parser.analyze(data + b'partial')
assert result['complete_buffers'] == 2 and result['sequence_gaps'] == 1
assert result['incomplete_tail_bytes'] == 7
assert result['timings']['commit_to_completed_callback']['max_us'] == 2
assert result['timings']['gpu_span']['count'] == 1
assert result['single_batch_chain']['count'] == 0
assert result['last_record_uptime_s'] == 7000/1e9
# Adjacent phases must sum to this command's callback latency. A duplicate
# submission, a grouped batch, a missing stage or invalid order must not acquire
# a plausible-looking decomposition from a different batch or command.
def trace(events):
    return header + b''.join(parser.RECORD.pack(at, 77, i+1, stage, arg)
                            for i, (at, stage, arg) in enumerate(events))
chain = [(500, 30, 0)] + [(1000+i*1000, stage, 0) for i, stage in enumerate(parser.CHAIN)]
exact = parser.analyze(trace(chain))
assert exact['single_batch_chain']['count'] == 1
assert sum(exact['slow'][0]['chain_us'].values()) == exact['slow'][0]['callback_us'] == 9
for wrong in [chain+[ (12000,8,0) ],
              [(at,stage,1 if stage==9 else arg) for at,stage,arg in chain],
              [row for row in chain if row[1]!=14],
              [(at+3000 if stage==4 else at,stage,arg) for at,stage,arg in chain]]:
    rejected = parser.analyze(trace(wrong))
    assert rejected['single_batch_chain']['count'] == 0
    assert rejected['slow'][0]['chain_us'] is None
# A completion timestamp before its commit is incomplete, never a sorting
# exception or a negative/zero duration masquerading as a good command.
bad_clock = parser.analyze(trace([(1000,30,0),(3000,31,0),(2000,33,0)]))
assert bad_clock['complete_buffers'] == 0 and bad_clock['incomplete_buffers'] == 1
for invalid in [b'', b'x'*32, header + parser.RECORD.pack(*rows[0])*2]:
    try:
        parser.analyze(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError('invalid trace accepted')
print('PASS: stage trace off by default; nonblocking collisions, lapped producers, concurrent snapshots, stop and parser gaps/reused identities; no GPU')
