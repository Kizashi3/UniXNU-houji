/* SPDX-License-Identifier: MIT */
/* Actual VM/UserClient policy and maintenance callbacks; no GPU simulation. */
for(unsigned mode:{0u,1u,2u,3u})for(unsigned wb:{0u,1u})for(unsigned share:{2u,3u}) {
    Path p;CHECK(!exposed(p));NativeAdrenoMemory imported;
    CHECK(!imported.importTask(reinterpret_cast<void *>(2),0x100000,fixture.cpu_page_bytes,36,fixture.cpu_page_bytes));
    native_adreno_io_coherent=mode;
    const bool skip=(mode==1 || mode==2) && wb==1 && share==3;
    uint64_t handle=0;unsigned calls=fixture.physical_calls;
    CHECK(!p.vm.map(&imported,0,0x804000,3,wb,share,&handle));
    CHECK(fixture.physical_calls==calls+(skip?0:1));
    calls=fixture.physical_calls;CHECK(!p.vm.publishMapped());
    CHECK(fixture.physical_calls==calls+(skip?0:1));
    calls=fixture.physical_calls;CHECK(!p.vm.acquireImported());
    CHECK(fixture.physical_calls==calls+(skip?0:1));
    CHECK(imported.deviceReferences()==1 && imported.release()==kIOReturnBusy);
    calls=fixture.physical_calls;CHECK(!p.vm.unmap(handle));
    CHECK(fixture.physical_calls==calls+(skip?0:1));
    CHECK(!imported.deviceReferences() && !imported.release());
    native_adreno_io_coherent=0;CHECK(!p.submit.detach());
}
for(unsigned mode:{0u,1u,2u,3u})for(unsigned permissions:{1u,3u}) {
    Path p;CHECK(!exposed(p));NativeAdrenoUserClient client;
    CHECK(!client.open(NativeAdrenoAbiVersion,&p.vm,&p.submit,&p.ring,32,36,true));
    NativeAdrenoAbiBoImport request{0x100000,fixture.cpu_page_bytes};NativeAdrenoAbiBoAllocReply allocated{};
    CHECK(!client.importBo(&request,reinterpret_cast<void *>(2),&allocated));
    native_adreno_io_coherent=mode;
    NativeAdrenoAbiBoMap map{allocated.handle,0x804000,permissions,0,2,0};NativeAdrenoAbiBoMapReply reply{};
    const bool skip=mode==2 || (mode==1 && permissions==1);
    unsigned calls=fixture.physical_calls;
    CHECK(!client.mapBo(&map,&reply) && reply.iova==map.iova);
    CHECK(fixture.physical_calls==calls+(skip?0:1));
    calls=fixture.physical_calls;CHECK(!p.vm.publishMapped());
    CHECK(fixture.physical_calls==calls+(skip?0:1));
    CHECK(client.memoryOf(allocated.handle)->deviceReferences()==1);
    CHECK(!client.unmapRetainedForTrial(allocated.handle));
    NativeAdrenoAbiBoFree release{allocated.handle};CHECK(!client.freeBo(&release));
    CHECK(!client.close() && !p.submit.detach());native_adreno_io_coherent=0;
}
{
    Path p;CHECK(!exposed(p));NativeAdrenoUserClient client;
    CHECK(!client.open(NativeAdrenoAbiVersion,&p.vm,&p.submit,&p.ring,32,36,true));
    // Import aliases an already mapped NC BO. The WB preflight must reject;
    // the validated fallback keeps the original NC class and maintenance.
    fixture.next_physical=p.object.spans()[0].physical;
    NativeAdrenoAbiBoImport request{0x100000,fixture.cpu_page_bytes};NativeAdrenoAbiBoAllocReply allocated{};
    CHECK(!client.importBo(&request,reinterpret_cast<void *>(2),&allocated));
    native_adreno_io_coherent=2;
    NativeAdrenoAbiBoMap map{allocated.handle,0x804000,3,0,2,0};NativeAdrenoAbiBoMapReply reply{};
    unsigned calls=fixture.physical_calls;CHECK(!client.mapBo(&map,&reply));
    CHECK(fixture.physical_calls==calls+1);
    calls=fixture.physical_calls;CHECK(!p.vm.publishMapped());CHECK(fixture.physical_calls==calls+1);
    CHECK(!client.unmapRetainedForTrial(allocated.handle));
    NativeAdrenoAbiBoFree release{allocated.handle};CHECK(!client.freeBo(&release));
    CHECK(!client.close() && !p.submit.detach());native_adreno_io_coherent=0;
}
std::puts("PASS: qualified WB/inner-shareable mappings alone skip maintenance; NC imports/aliases and outer-shareable mappings retain it; read-only vs read-write modes, unknown modes, mapping refs and unmap lifetime (host only)");
