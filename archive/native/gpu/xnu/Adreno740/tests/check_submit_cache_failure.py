#!/usr/bin/env python3
"""Actual Submit/VM/Memory/Ring failure propagation over bounded host peers.

The CPU reassert API is the injection boundary; its actual pmap behavior is
covered by check_page_geometry.py. No GPU, kernel or device is exercised.
"""
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESEARCH = Path('${HOUJI_ARTIFACTS}/native-research')
SMMU = RESEARCH / 'armsmmu4k-reference'
PM4 = RESEARCH / 'adrenopm4-reference-445f8fe6'


def replace_once(source, old, new):
    assert source.count(old) == 1, old
    return source.replace(old, new)


peer = (HERE / 'test_submit.cpp').read_text()
main_begin = peer.index('int main()')
main_brace = peer.index('{', main_begin)
end, depth = main_brace + 1, 1
while depth:
    depth += (peer[end] == '{') - (peer[end] == '}')
    end += 1
peer = peer[:main_begin] + r'''
extern unsigned candidate_publish_calls,candidate_tlb_calls,candidate_sample_calls;
static uint64_t fail_physical;
static IOReturn reassert_failure;
static unsigned reset_before_failure,reassert_calls;
static void discardHostOnly(){
    // Fixture-only disposal never authorizes a production quarantine release.
    while(!fixture.live.empty())fixture.live.back()->release();
    while(!fixture.metadata.empty())fixtureMetadataFree(fixture.metadata.back());
}
int main(){
    unsigned cases=0;
    for(unsigned other_target=0;other_target<2;++other_target)
    for(IOReturn failure:{kIOReturnUnsupported,kIOReturnIOError,kIOReturnNotReady}) {
        fixture.cpu_page_bytes=TEST_CPU_PAGE;
        Path p;CHECK(exposed(p,true)==kIOReturnSuccess);
        NativeAdrenoMemory other;uint64_t other_handle=0;
        CHECK(!other.allocate(4096,40,false,NativeAdrenoMemory::backingBudget(4096)));
        CHECK(!other.makeWriteCombined());
        CHECK(!p.vm.map(&other,0,0x804000,3,0,2,&other_handle));
        fail_physical=(other_target?other:p.object).ownedSpans()[0].physical;
        reassert_failure=failure;reset_before_failure=other_target?1:0;reassert_calls=0;
        const auto refs=p.object.deviceReferences(),other_refs=other.deviceReferences();
        const auto retired=p.submit.stats().references_retired;
        const auto writes=cp.writes.size();const auto ring_publish=cp.publish,mmio_calls=mf.calls;
        const auto publications=candidate_publish_calls,tlbs=candidate_tlb_calls,samples=candidate_sample_calls;
        const auto resets=native_adreno_wc_audit[5];
        NativeAdrenoSubmitBuffer buffer{p.handle,0x800000,4096};uint32_t fence=99;
        CHECK(p.submit.submit(&buffer,1,3,&fence)==failure && !fence);
        CHECK(p.submit.poisoned() && p.submit.outstanding()==1 && p.submit.queueOutstanding(3));
        CHECK(p.submit.stats().poisoned_jobs==1 && !p.submit.stats().submissions);
        CHECK(p.submit.stats().references_held==1 && p.submit.stats().references_retired==retired);
        CHECK(p.object.deviceReferences()==refs+1 && other.deviceReferences()==other_refs);
        CHECK((other_target?other:p.object).quarantined());
        if(other_target)CHECK(!p.object.quarantined() && reassert_calls==2);
        else CHECK(!other.quarantined() && reassert_calls==1);
        CHECK(candidate_publish_calls==publications && candidate_tlb_calls==tlbs && candidate_sample_calls==samples);
        CHECK(cp.writes.size()==writes && cp.publish==ring_publish && mf.calls==mmio_calls);
        CHECK(native_adreno_wc_audit[4]==(uint32_t)failure && !p.vm.writeCombinedTrusted());
        CHECK(native_adreno_wc_audit[5]==resets+(other_target?1:0));
        CHECK(p.submit.detach()==kIOReturnBusy && p.object.release()==kIOReturnBusy);
        fence=99;CHECK(p.submit.submit(&buffer,1,3,&fence)==kIOReturnNotReady && !fence);
        CHECK(p.submit.stats().references_retired==retired && p.object.deviceReferences()==refs+1);
        CHECK(cp.writes.size()==writes && cp.publish==ring_publish && mf.calls==mmio_calls);
        discardHostOnly();++cases;
    }
    // Unsupported from the absent OPTIONAL line-audit hook remains harmless
    // only after every mandatory pmap reassertion returned success.
    fixture.cpu_page_bytes=TEST_CPU_PAGE;
    fail_physical=0;reassert_failure=kIOReturnSuccess;reset_before_failure=0;reassert_calls=0;
    Path p;CHECK(!exposed(p,true));native_adreno_line_audit=nullptr;
    const auto writes=cp.writes.size();const auto publications=candidate_publish_calls;
    NativeAdrenoSubmitBuffer buffer{p.handle,0x800000,4096};uint32_t fence=0;
    CHECK(!p.submit.submit(&buffer,1,0,&fence) && fence==1 && !p.submit.poisoned());
    CHECK(!p.object.quarantined() && p.vm.writeCombinedTrusted() && reassert_calls==1);
    CHECK(cp.writes.size()>writes && candidate_publish_calls==publications+1);
    fencemem[1]=1;CHECK(!p.submit.wait(1,&ringclock,1000));CHECK(!p.submit.detach());
    discardHostOnly();++cases;
    printf("PASS: CPU%uK %u actual Submit/VM mandatory-reassert quarantine/retention and optional-audit boundary cases (ASAN/UBSAN); no device\n",TEST_CPU_PAGE/1024,cases);
}
''' + peer[end:]
peer = replace_once(peer, 'p.object.allocate(8192,40,false,8192)',
                    'p.object.allocate(8192,40,false,NativeAdrenoMemory::backingBudget(8192))')
peer = replace_once(peer,
    '{return spans && count && reset?kIOReturnSuccess:kIOReturnBadArgument;}',
    '''{if(!spans || !count || !reset)return kIOReturnBadArgument;
       ++reassert_calls;
       if(spans[0].physical==fail_physical)return reassert_failure;
       *reset+=reset_before_failure;return kIOReturnSuccess;}''')

submit = (ROOT / 'NativeAdrenoSubmit.cpp').read_text()
submit = replace_once(submit, '__asm__ volatile("dsb sy":::"memory");', '(void)0; /* host architectural barrier peer */')
vm = (ROOT / 'NativeAdrenoVm.cpp').read_text()
vm = 'unsigned candidate_publish_calls=0,candidate_tlb_calls=0,candidate_sample_calls=0;\n' + vm
for signature, counter in [('IOReturn NativeAdrenoVm::publishMapped()', 'candidate_publish_calls'),
                           ('IOReturn NativeAdrenoVm::invalidateTlb()', 'candidate_tlb_calls'),
                           ('IOReturn NativeAdrenoVm::sampleWord(uint64_t iova,uint32_t *cached,uint32_t *dram) const', 'candidate_sample_calls')]:
    vm = replace_once(vm, signature + '\n{', signature + '\n{\n    ++' + counter + '; /* host observer only */')

with tempfile.TemporaryDirectory(prefix='native-adreno-submit-cache-failure-') as temporary:
    tmp = Path(temporary)
    for name in ['IOKit/IOTypes.h', 'IOKit/IOBufferMemoryDescriptor.h', 'IOKit/IOLib.h', 'kern/task.h']:
        h = tmp / name
        h.parent.mkdir(parents=True, exist_ok=True)
        h.write_text('#include "XnuMemoryFixture.h"\n')
    (tmp / 'submit.cpp').write_text(submit)
    (tmp / 'vm.cpp').write_text(vm)
    (tmp / 'peer.cpp').write_text(peer)
    common = ['-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
              '-I' + str(tmp), '-I' + str(HERE), '-I' + str(ROOT), '-I' + str(SMMU), '-I' + str(PM4)]
    objects = []
    for source in sorted(SMMU.glob('ArmSmmu4K*.c')) + [PM4 / 'AdrenoPM4.c']:
        obj = tmp / (source.stem + '.o')
        subprocess.run(['clang', '-std=c11', *common, '-c', str(source), '-o', str(obj)], check=True)
        objects.append(str(obj))
    for page in (4096, 16384):
        exe = tmp / ('test-' + str(page))
        sources = [ROOT / 'NativeAdrenoMemory.cpp', ROOT / 'NativeAdrenoSmmuMemory.cpp',
                   ROOT / 'NativeAdrenoRing.cpp', tmp / 'vm.cpp', tmp / 'submit.cpp', tmp / 'peer.cpp']
        subprocess.run(['clang++', '-std=c++17', '-Wno-c99-designator', *common,
                        '-DTEST_CPU_PAGE=' + str(page), *map(str, sources), *objects, '-o', str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
