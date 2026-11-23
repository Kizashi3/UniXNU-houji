/* SPDX-License-Identifier: MIT */
/* Actual VM/live updater and register peer: no GPU or timing simulation. */
for(bool perPage:{false,true})for(unsigned pages:{4u,16u,128u,512u,513u}) {
    Path p;CHECK(!exposed(p,false,true,perPage));
    CHECK(p.vm.perPageTlbInvalidation()==perPage);
    NativeAdrenoMemory object;size_t bytes=pages*4096ull;
    CHECK(!object.allocate(bytes,36,true,NativeAdrenoMemory::backingBudget(bytes)));
    uint64_t handle=0;CHECK(!p.vm.map(&object,0,0x2000000,3,0,2,&handle));
    unsigned pageBefore=mf.page_tlbi,asidBefore=mf.asid_tlbi,allBefore=mf.all_tlbi,syncBefore=mf.sync;
    CHECK(!p.vm.unmap(handle));
    const bool byPage=perPage && pages<=ArmSmmu4KTlbPageLimit;
    CHECK(mf.page_tlbi-pageBefore==(byPage?pages:0));
    CHECK(mf.asid_tlbi-asidBefore==(byPage?0:1));
    CHECK(mf.all_tlbi==allBefore && mf.sync==syncBefore+1);
    CHECK(p.vm.lastResult().complete && !object.deviceReferences());
    CHECK(!p.vm.auditLive() && !object.release() && !p.submit.detach());
}
{
    Path p;CHECK(!exposed(p,false,false,false));
    unsigned references=p.object.deviceReferences(),pages=mf.page_tlbi,asid=mf.asid_tlbi;
    mf.fail_sync=true;
    CHECK(p.vm.unmap(p.handle)==kIOReturnIOError);
    CHECK(mf.page_tlbi==pages && mf.asid_tlbi==asid+1);
    CHECK(p.vm.poisoned() && p.object.quarantined() && p.tables.quarantined());
    CHECK(p.object.deviceReferences()==references && !p.vm.lastResult().complete);
    CHECK(p.object.release()!=kIOReturnSuccess);
    mf.fail_sync=false;
}
std::puts("PASS: board-selected ASID unmap retains one TLBSYNC, full table verification and failed-sync quarantine; default page/large-ASID paths preserved across 4..513 pages (host only)");
{
    // The 64th operation still detects a foreign stream routed over an owned
    // stream, before publishing the new mapping or taking its device ref.
    Path p;CHECK(!exposed(p,false,false,false));NativeAdrenoMemory object;
    CHECK(!object.allocate(4096,36,true,NativeAdrenoMemory::backingBudget(4096)));
    uint64_t handle=0;
    for(unsigned i=0;i<31;i++) {
        CHECK(!p.vm.map(&object,0,0x804000,3,0,2,&handle));CHECK(!p.vm.unmap(handle));
    }
    mmio[(0x800+7*4)/4]=(1u<<31)|routes[0].sid;mmio[(0xc00+7*4)/4]=3;
    const uint64_t generation=p.state.generation;
    CHECK(p.vm.map(&object,0,0x804000,3,0,2,&handle)==kIOReturnIOError);
    CHECK(!handle && !object.deviceReferences() && p.state.generation==generation);
    CHECK(p.vm.poisoned() && p.tables.quarantined() && p.object.quarantined());
    CHECK(!object.release());
}
{
    // Changed leaves are checked on every transaction, not just operation 64.
    Path p;CHECK(!exposed(p,false,false,false));
    auto *words=static_cast<uint64_t *>(p.tables.mapping());bool changed=false;
    for(size_t i=0;i<p.tables.bytes()/8;i++)if((words[i]&0x0000fffffffff000ull)==p.object.spans()[0].physical) {
        words[i]^=1u<<7;changed=true;break;
    }
    CHECK(changed);unsigned references=p.object.deviceReferences();
    CHECK(p.vm.unmap(p.handle)==kIOReturnIOError);
    CHECK(p.vm.poisoned() && p.object.quarantined() && p.object.deviceReferences()==references);
}
std::puts("PASS: upstream periodic route check rejects a conflicting stream before map; per-transaction leaf tampering still poisons and retains resources (host only)");
