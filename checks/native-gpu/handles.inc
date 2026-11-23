/* SPDX-License-Identifier: MIT */
/* Included inside the shared host fixture's main(), for both CPU page sizes. */
{
    NativeAdrenoHandleIndex<8> index;
    CHECK(index.allocate());
    // Deliberately form a collision chain across the end of the hash table.
    uint64_t keys[8]{};unsigned count=0;
    for(uint64_t key=1;count<8;++key)
        if(((key*UINT64_C(0x9e3779b97f4a7c15))>>40&15)==15)keys[count++]=key;
    for(unsigned i=0;i<8;++i)index.insert(keys[i],100+i);
    for(unsigned remove:{0u,4u,7u,1u,6u,3u,2u,5u}) {
        index.erase(keys[remove]);keys[remove]=0;
        for(unsigned i=0;i<8;++i)CHECK(index.find(keys[i])==(keys[i]?100+i:UINT32_MAX));
    }
    CHECK(index.find(UINT64_MAX)==UINT32_MAX);index.release();
}
{
    NativeAdrenoHandleIndex<4096> index;CHECK(index.allocate());
    uint64_t keys[4096]{};
    for(unsigned i=0;i<4096;++i){keys[i]=UINT64_MAX-i;index.insert(keys[i],i);}
    uint64_t state=17;
    for(unsigned step=0;step<16384;++step) {
        state=state*UINT64_C(6364136223846793005)+1;
        const unsigned slot=(state>>32)&4095;
        CHECK(index.find(keys[slot])==slot);
        const uint64_t stale=keys[slot];index.erase(stale);CHECK(index.find(stale)==UINT32_MAX);
        keys[slot]=1+step;index.insert(keys[slot],slot);
        for(unsigned i=step%32;i<4096;i+=32)CHECK(index.find(keys[i])==i);
    }
    index.release();CHECK(index.find(1)==UINT32_MAX);
}
{
    Path p;CHECK(!exposed(p,false,true));NativeAdrenoUserClient client;
    // The second metadata allocation is the index. Failed open releases the
    // entry table and may be retried on the same client.
    const size_t metadata_before=fixture.metadata.size();
    fixture.metadata_fail_call=fixture.metadata_calls+2;
    CHECK(client.open(NativeAdrenoAbiVersion,&p.vm,&p.submit,&p.ring,32,36,true)==kIOReturnNoMemory);
    CHECK(fixture.metadata.size()==metadata_before && !client.liveObjects());
    fixture.metadata_fail_call=0;
    CHECK(!client.open(NativeAdrenoAbiVersion,&p.vm,&p.submit,&p.ring,32,36,true));
    NativeAdrenoAbiBoAlloc alloc{4096,12,0};NativeAdrenoAbiBoAllocReply reply{};
    fixture.allocation_fail=true;
    CHECK(client.allocBo(&alloc,&reply)==kIOReturnNoMemory && !reply.handle && !client.liveObjects());
    fixture.allocation_fail=false;
    std::vector<uint64_t> handles(NativeAdrenoClientMaxObjects);
    for(size_t i=0;i<handles.size();++i) {
        CHECK(!client.allocBo(&alloc,&reply));handles[i]=reply.handle;
        CHECK(reply.handle && client.memoryOf(reply.handle) && client.liveObjects()==i+1);
    }
    CHECK(client.allocBo(&alloc,&reply)==kIOReturnNoResources && !reply.handle);
    for(size_t i=0;i<handles.size();i+=2) {
        NativeAdrenoAbiBoFree request{handles[i]};CHECK(!client.freeBo(&request));
        CHECK(!client.memoryOf(handles[i]) && client.freeBo(&request)==kIOReturnBadArgument);
    }
    CHECK(client.liveObjects()==handles.size()/2);
    for(size_t i=0;i<handles.size();i+=2) {
        const uint64_t stale=handles[i];CHECK(!client.allocBo(&alloc,&reply));handles[i]=reply.handle;
        CHECK(reply.handle!=stale && !client.memoryOf(stale));
        NativeAdrenoAbiBoCpuMap map{reply.handle};NativeAdrenoAbiBoCpuMapReply mapped{};
        CHECK(!client.cpuMap(&map,&mapped) && mapped.token==i+1);
        CHECK(client.memoryForToken(mapped.token)==client.memoryOf(reply.handle));
        NativeAdrenoAbiBoFree release{reply.handle};CHECK(client.freeBo(&release)==kIOReturnBusy);
        NativeAdrenoAbiBoCpuUnmap unmap{stale,mapped.token,0};
        CHECK(client.cpuUnmap(&unmap)==kIOReturnBadArgument && client.mappingLeases(mapped.token)==1);
        unmap.handle=reply.handle;CHECK(!client.cpuUnmap(&unmap));
    }
    for(uint64_t handle:handles)CHECK(client.memoryOf(handle));
    CHECK(!client.releaseAll(&ringclock,100) && !client.liveObjects());
    CHECK(!client.memoryOf(handles[0]) && fixture.metadata.size()==metadata_before);
    // Import and owned allocation use the same index and live count.
    CHECK(!client.open(NativeAdrenoAbiVersion,&p.vm,&p.submit,&p.ring,32,36,true));
    NativeAdrenoAbiBoImport imported{0x100000,fixture.cpu_page_bytes};
    CHECK(!client.importBo(&imported,reinterpret_cast<void *>(2),&reply));
    CHECK(client.liveObjects()==1 && client.memoryOf(reply.handle)->imported());
    NativeAdrenoAbiBoFree release{reply.handle};CHECK(!client.freeBo(&release));
    CHECK(!client.liveObjects() && !client.close() && !p.submit.detach());
}
{
    Path p;CHECK(!exposed(p,false,true));NativeAdrenoUserClient client;
    CHECK(!client.open(NativeAdrenoAbiVersion,&p.vm,&p.submit,&p.ring,32,36,true));
    NativeAdrenoAbiBoAlloc alloc{4096,12,0};NativeAdrenoAbiBoAllocReply reply{};
    fixture.null_mapping=true;fixture.complete_fail=true;
    CHECK(client.allocBo(&alloc,&reply) && !reply.handle && client.liveObjects()==1);
    fixture.null_mapping=false;fixture.complete_fail=false;
    // A failed release is still occupied and blocks close, without publishing
    // handle zero or offering its quarantined backing to a new allocation.
    CHECK(!client.memoryOf(0) && client.close()==kIOReturnBusy);
    CHECK(!client.allocBo(&alloc,&reply) && client.liveObjects()==2);
    NativeAdrenoAbiBoCpuMap map{reply.handle};NativeAdrenoAbiBoCpuMapReply mapped{};
    CHECK(!client.cpuMap(&map,&mapped) && mapped.token==2);
    NativeAdrenoAbiBoCpuUnmap unmap{reply.handle,mapped.token,0};CHECK(!client.cpuUnmap(&unmap));
    NativeAdrenoAbiBoFree release{reply.handle};CHECK(!client.freeBo(&release));
    CHECK(client.liveObjects()==1 && client.close()==kIOReturnBusy);
}
std::puts("PASS: indexed BO handles, collision deletion, 4096-object exhaustion/reuse, stale CPU tokens, failed open, imports and quarantined-slot ownership; no GPU");
