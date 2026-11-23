/* SPDX-License-Identifier: MIT */
/* Real VM preflight + live SMMU transaction: indexed and fallback paths must
 * make the same alias decisions. No GPU or host timing qualification. */
{
    Path p;CHECK(!exposed(p,false,true));
    CHECK(!p.vm.unmap(p.handle) && !p.submit.detach() && !p.vm.detach());
    NativeAdrenoVmRegion lower{&p.tables,&p.arena,&p.state};
    CHECK(!p.vm.attachSeeded(&smmuio,&context,&streams,&lower,nullptr,8192,1000,
        nullptr,0,nullptr,0,false,false));
    houji_test_seal_arena(&p.arena);
    CHECK(houji_test_check_sealed_arena(&p.arena));
    CHECK(!p.vm.enableAliasWorkspace());
    // r280: replacing these CPU scratch fields broke the retained GMU graph
    // seal. The next DVFS request was rejected before a firmware transaction.
    CHECK(houji_test_check_sealed_arena(&p.arena));
    uint64_t handle=0;
    CHECK(!p.vm.map(&p.object,0,0x10000000,3,0,2,&handle));
    CHECK(houji_test_check_sealed_arena(&p.arena));
    CHECK(!p.vm.unmap(handle) && !p.vm.detach() && !p.object.release());
    CHECK(houji_test_check_sealed_arena(&p.arena));
    // Real changes to the original arena must still fail and stay failed.
    const auto original=p.arena;
    p.arena.alias_scratch_entries=1;
    CHECK(!houji_test_check_sealed_arena(&p.arena) && houji_test_seal_failure());
    p.arena=original;
    CHECK(!houji_test_check_sealed_arena(&p.arena));
    std::puts("PASS: retained-owner graph seal survives VM workspace/map/unmap; genuine metadata mutation remains sticky-fatal; no GPU");
}
{
    Path p;CHECK(exposed(p,false,true)==kIOReturnSuccess);
    CHECK(!p.arena.alias_scratch && !p.arena.alias_scratch_entries);
    CHECK(!p.vm.unmap(p.handle) && !p.submit.detach() && !p.vm.detach());
    CHECK(!p.arena.alias_scratch && !p.arena.alias_scratch_entries);
    NativeAdrenoVmRegion lower{&p.tables,&p.arena,&p.state};
    uint32_t borrowed[2]={};p.arena.alias_scratch=borrowed;p.arena.alias_scratch_entries=2;
    const size_t metadata=fixture.metadata.size();
    for(unsigned fail=1;fail<=3;++fail) {
        fixture.metadata_fail_call=fixture.metadata_calls+fail;
        CHECK(p.vm.attach(&smmuio,&context,&streams,&lower,nullptr,8192,1000)==kIOReturnNoMemory);
        CHECK(fixture.metadata.size()==metadata);
        CHECK(p.arena.alias_scratch==borrowed && p.arena.alias_scratch_entries==2);
        fixture.metadata_fail_call=0;
    }
    CHECK(!p.vm.attach(&smmuio,&context,&streams,&lower,nullptr,8192,1000));
    CHECK(p.arena.alias_scratch==borrowed && p.arena.alias_scratch_entries==2);
    CHECK(!p.vm.detach());
    for(unsigned mode=0;mode<3;++mode) {
        // Absent and insufficient borrowed scratch exercise the fallback.
        // Owned scratch must not replace either field in the caller's arena.
        p.arena.alias_scratch=mode?borrowed:nullptr;
        p.arena.alias_scratch_entries=mode?1:0;
        const auto original=p.arena;
        CHECK(!p.vm.attachSeeded(&smmuio,&context,&streams,&lower,nullptr,8192,1000,
            nullptr,0,nullptr,0,true,mode==2));
        houji_test_seal_arena(&p.arena);
        const uint64_t indexed=native_adreno_vm_alias_paths[0],pairwise=native_adreno_vm_alias_paths[1];
        NativeAdrenoMemory first,same,many,separate;
        fixture.mode=Scattered;
        CHECK(!first.allocate(4*TEST_CPU_PAGE,40,false,4*TEST_CPU_PAGE));
        fixture.next_physical=first.spans()[0].physical;
        CHECK(!same.allocate(4*TEST_CPU_PAGE,40,false,4*TEST_CPU_PAGE));
        fixture.next_physical=first.spans()[0].physical;
        CHECK(!many.allocate(8*TEST_CPU_PAGE,40,false,8*TEST_CPU_PAGE));
        CHECK(!separate.allocate(4*TEST_CPU_PAGE,40,false,4*TEST_CPU_PAGE));
        fixture.mode=Contiguous;
        uint64_t a=0,b=0,c=0;CHECK(!p.vm.map(&first,0,0x10000000,3,0,2,&a));
        CHECK(!p.vm.map(&same,0,0x11000000,1,0,2,&b) && !p.vm.unmap(b));
        // Reject differing cache, shareability and privilege before MMIO or
        // taking ownership. Test both smaller-side choices in the index.
        for(auto *object:{&same,&many})for(unsigned attribute=0;attribute<3;++attribute) {
            const unsigned calls=mf.calls;const auto generation=p.state.generation;
            const unsigned permissions=3|(attribute==2?ArmSmmu4KPrivileged:0);
            CHECK(p.vm.map(object,0,0x11000000,permissions,attribute==0,attribute==1?3:2,&b)==kIOReturnBadArgument);
            CHECK(!b && !object->deviceReferences() && calls==mf.calls && generation==p.state.generation);
        }
        CHECK(!p.vm.map(&separate,0,0x12000000,3,1,3,&c));
        CHECK(!p.vm.auditLive());
        CHECK(!p.vm.unmap(c) && !p.vm.unmap(a));
        CHECK(!first.release() && !same.release() && !many.release() && !separate.release());
        CHECK(mode==2 ? native_adreno_vm_alias_paths[0]>indexed && native_adreno_vm_alias_paths[1]==pairwise
                      : native_adreno_vm_alias_paths[1]>pairwise && native_adreno_vm_alias_paths[0]==indexed);
        CHECK(houji_test_check_sealed_arena(&p.arena) && !std::memcmp(&original,&p.arena,sizeof(original)));
        CHECK(!p.vm.detach());
        CHECK(!std::memcmp(&original,&p.arena,sizeof(original)));
    }
    p.arena.alias_scratch=borrowed;p.arena.alias_scratch_entries=2;
    CHECK(!p.vm.attach(&smmuio,&context,&streams,&lower,nullptr,8192,1000));
    houji_test_seal_arena(&p.arena);
    // A genuinely scattered map takes the existing index, with no exclusive
    // alias bypass. This catches accidentally leaving the arena unwired.
    constexpr size_t pages=2048;
    NativeAdrenoMemory a,b;fixture.mode=Scattered;
    CHECK(!a.allocate(pages*TEST_CPU_PAGE,40,false,pages*TEST_CPU_PAGE));
    CHECK(!b.allocate(pages*TEST_CPU_PAGE,40,false,pages*TEST_CPU_PAGE));
    fixture.mode=Contiguous;CHECK(a.spanCount()==pages && b.spanCount()==pages);
    uint64_t ah=0,bh=0;CHECK(!p.vm.map(&a,0,0x20000000,3,0,2,&ah));
    const uint64_t indexed=native_adreno_vm_alias_paths[0],pairwise=native_adreno_vm_alias_paths[1];
    CHECK(!p.vm.map(&b,0,0x30000000,3,1,3,&bh));
    CHECK(native_adreno_vm_alias_paths[0]==indexed+1 && native_adreno_vm_alias_paths[1]==pairwise);
    CHECK(p.vm.spanCount()==2*pages && !p.vm.auditLive());
    CHECK(!p.vm.unmap(bh) && !p.vm.unmap(ah) && !a.release() && !b.release());
    CHECK(houji_test_check_sealed_arena(&p.arena));
    CHECK(!p.vm.detach() && fixture.metadata.size()==metadata);
    CHECK(p.arena.alias_scratch==borrowed && p.arena.alias_scratch_entries==2);
    // Board comparison can omit this allocation without replacing a caller's
    // workspace or dropping any alias validation. Only two metadata blocks.
    const unsigned allocations=fixture.metadata_calls;
    CHECK(!p.vm.attachSeeded(&smmuio,&context,&streams,&lower,nullptr,8192,1000,
        nullptr,0,nullptr,0,false,false));
    CHECK(fixture.metadata_calls==allocations+2);
    CHECK(p.arena.alias_scratch==borrowed && p.arena.alias_scratch_entries==2);
    uint64_t active=0;
    CHECK(!p.vm.map(&p.object,0,0x10000000,3,0,2,&active));
    const unsigned busyAllocations=fixture.metadata_calls;
    CHECK(p.vm.enableAliasWorkspace()==kIOReturnBusy && fixture.metadata_calls==busyAllocations);
    CHECK(!p.vm.unmap(active));
    fixture.metadata_fail_call=fixture.metadata_calls+1;
    CHECK(p.vm.enableAliasWorkspace()==kIOReturnNoMemory);
    CHECK(p.arena.alias_scratch==borrowed && p.arena.alias_scratch_entries==2 && !p.vm.auditLive());
    fixture.metadata_fail_call=0;
    CHECK(!p.vm.enableAliasWorkspace());
    CHECK(p.arena.alias_scratch==borrowed && p.arena.alias_scratch_entries==2);
    const unsigned enabledAllocations=fixture.metadata_calls;
    CHECK(!p.vm.enableAliasWorkspace() && fixture.metadata_calls==enabledAllocations);
    NativeAdrenoMemory deferredA,deferredB;fixture.mode=Scattered;
    CHECK(!deferredA.allocate(4*TEST_CPU_PAGE,40,false,4*TEST_CPU_PAGE));
    CHECK(!deferredB.allocate(4*TEST_CPU_PAGE,40,false,4*TEST_CPU_PAGE));
    fixture.mode=Contiguous;uint64_t da=0,db=0;
    CHECK(!p.vm.map(&deferredA,0,0x10000000,3,0,2,&da));
    const uint64_t deferredIndexed=native_adreno_vm_alias_paths[0],deferredPairwise=native_adreno_vm_alias_paths[1];
    CHECK(!p.vm.map(&deferredB,0,0x11000000,3,1,3,&db));
    CHECK(native_adreno_vm_alias_paths[0]==deferredIndexed+1 && native_adreno_vm_alias_paths[1]==deferredPairwise);
    CHECK(!p.vm.auditLive() && !p.vm.unmap(db) && !p.vm.unmap(da));
    CHECK(!deferredB.release() && !deferredA.release());
    CHECK(!p.vm.detach() && fixture.metadata.size()==metadata);
    CHECK(p.arena.alias_scratch==borrowed && p.arena.alias_scratch_entries==2);
    p.arena.alias_scratch=nullptr;p.arena.alias_scratch_entries=0;
    CHECK(!p.object.release());
    std::puts("PASS: VM alias workspace ownership/failure cleanup, unchanged caller arenas, deferred activation/idempotence/busy guard, index/fallback equivalence, 2048-span mixed-class map/unmap; no GPU");
}
