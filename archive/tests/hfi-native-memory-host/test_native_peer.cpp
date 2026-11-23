/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Host boundaries and assertions. Production business code is included above
 * by the runner and the actual adapter .inc is compiled below unchanged. */
#include <array>
#include <cstdarg>
#include <string>
#include "ArmSmmu4KAudit.h"
static bool host_enabled=true;
static bool gRootEnabled=true,gLogEnabled=true,gReturnRecovery=true;
static std::vector<std::string> host_logs;
static unsigned host_at_calls,host_alias_at_calls,host_fail_at,host_bad_par_at;
static unsigned host_publish_fail_slot=99,host_publish_barriers,host_damage_kind,host_damage_slot=99;
static uint64_t host_damage_offset;
static bool host_damage_done,host_alias_wb;
static unsigned host_alias_fault;
struct HostAt {uint64_t va,pa;unsigned write,attr,slot,row,phase;bool alias;};
static std::vector<HostAt> host_at;
struct HostCache {uint64_t va;unsigned op,slot,phase;bool publishing;};
static std::vector<HostCache> host_cache;
static void IOLog(const char *format,...) {
    char line[4096];va_list ap;va_start(ap,format);int n=vsnprintf(line,sizeof line,format,ap);va_end(ap);
    CHECK(n>=0 && (size_t)n<sizeof line);host_logs.emplace_back(line);
}
static bool PE_parse_boot_argn(const char *name,void *value,size_t bytes) {
    CHECK(!strcmp(name,"houji_gpu_fw_mem_probe") && bytes==sizeof(int));*(int*)value=host_enabled?1:0;return true;
}
#define HOUJI_GPU_FIRMWARE_MEMORY_HOST_TEST 1
#include "HoujiGpuFirmwareMemoryProbe.inc"

static unsigned fixture_slot(const IOBufferMemoryDescriptor *d) {
    const auto at=std::find(fixture.live.begin(),fixture.live.end(),d);CHECK(at!=fixture.live.end());return (unsigned)(at-fixture.live.begin());
}
static bool houjiFirmwareAt(uint64_t va,bool write,uint64_t *par) {
    CHECK(par);const bool alias=(va>>48)==0xffff;
    if(alias)++host_alias_at_calls;++host_at_calls;
    for(auto*d:fixture.live) {
        const uint64_t begin=alias?(UINT64_C(0xffff000000000000)|d->physical_base):(uint64_t)(uintptr_t)d->raw;
        if(va<begin || va-begin>=d->bytes)continue;
        const uint64_t offset=va-begin,pa=d->physical_base+offset;
        unsigned attr=(alias && host_alias_wb)?0xff:attributes[(ppnum_t)(pa>>14)]==VM_WIMG_WCOMB?0x44:attributes[(ppnum_t)(pa>>14)]==VM_WIMG_DEFAULT?0xff:0;
        if(alias && host_alias_fault==1)attr=0; // Device
        if(alias && host_alias_fault==2)attr=0x55; // unsupported Normal encoding
        if(alias && host_alias_fault==4 && write)attr=attr==0xff?0x44:0xff;
        const unsigned slot=fixture_slot(d),row=(unsigned)(offset/4096);
        host_at.push_back({va,pa,write,attr,slot,row,gHoujiFirmwareMemory.phase,alias});
        *par=((uint64_t)attr<<56)|(pa&UINT64_C(0x0000fffffffff000))|0xb00;
        if(host_at_calls==host_fail_at)return false;
        if(host_at_calls==host_bad_par_at)*par^=UINT64_C(1)<<56;
        if(alias && host_alias_fault==3)*par^=UINT64_C(1)<<12;
        const auto&p=gHoujiFirmwareMemory;
        if(!alias && p.phase==3 && p.validated==0x1ff && slot==host_publish_fail_slot && write && row+1==d->bytes/4096)
            cpu_ctr=UINT64_C(11)<<16; /* next real maintenance call rejects unsupported CTR */
        return true;
    }
    CHECK(false);return false;
}
static void native_cache_hook(uintptr_t address,unsigned op) {
    for(auto*d:fixture.live)if(address>=(uintptr_t)d->raw && address-(uintptr_t)d->raw<d->bytes) {
        const auto&p=gHoujiFirmwareMemory;
        host_cache.push_back({address,op,fixture_slot(d),p.phase,p.phase==3 && p.validated==0x1ff && p.next==9});return;
    }
    CHECK(false);
}
static void houjiFirmwareBarrier(void) {
    ++barriers;++host_publish_barriers;auto&p=gHoujiFirmwareMemory;
    CHECK(p.phase==3 && p.validated==0x1ff && p.next==9);
    if(host_damage_kind && !host_damage_done && host_publish_barriers==9) {
        CHECK(host_damage_slot<9 && host_damage_offset<p.info[host_damage_slot].owned);
        auto *bytes=(unsigned char*)(uintptr_t)p.info[host_damage_slot].va;
        bytes[host_damage_offset]^=1;host_damage_done=true;
    }
}
static void discard_host_fixture_only() {
    /* Host test disposal only. No production release/reset authorization. */
    while(!fixture.live.empty())fixture.live.back()->release();
    while(!fixture.metadata.empty())fixtureMetadataFree(fixture.metadata.back());
}
static void reset() {
    discard_host_fixture_only();memset((void*)&gHoujiFirmwareMemory,0,sizeof gHoujiFirmwareMemory);gHoujiFirmwareMemoryOnce=0;
    fixture=MemoryFixture{};fixture.cpu_page_bytes=16384;fixture.next_physical=UINT64_C(0x8c5d10000);
    gPhysBase=UINT64_C(0x800000000);gPhysSize=UINT64_C(0x800000000);
    page_size=map_page_bytes=PAGE_SIZE;cpu_tcr=(UINT64_C(2)<<14)|(UINT64_C(1)<<30);cpu_ttbr0=0x30000000;cpu_ttbr1=0x30004000;cpu_sctlr=1;cpu_ctr=UINT64_C(4)<<16;
    attributes.clear();pmap_writes.clear();cache_lines.clear();host_cache.clear();host_at.clear();host_logs.clear();
    host_at_calls=host_alias_at_calls=host_fail_at=host_bad_par_at=host_alloc_attempts=host_fail_alloc=host_publish_barriers=0;
    host_publish_fail_slot=host_damage_slot=99;host_damage_offset=host_damage_kind=host_alias_fault=0;host_damage_done=host_alias_wb=false;
    attribute_write_fail=barriers=now=0;host_enabled=gRootEnabled=gLogEnabled=gReturnRecovery=true;preemption_depth=0;
    memset((void*)native_adreno_cache_stats,0,sizeof native_adreno_cache_stats);
}
static void retained_failure() {
    const auto&p=gHoujiFirmwareMemory;CHECK(!p.complete && p.code && !p.active && p.phase==5 && !fixture.released);
    if(!p.content_attempted)CHECK(p.content_code==UINT32_MAX);
    for(unsigned i=0;i<9;++i)if(p.bo[i].backed())CHECK(p.bo[i].quarantined() && !p.bo[i].deviceReferences());
    const unsigned a=host_alloc_attempts,at=host_at_calls,b=barriers,r=fixture.released;
    CHECK(!houjiGpuFirmwareMemoryProbeOnce() && host_alloc_attempts==a && host_at_calls==at && barriers==b && fixture.released==r);
}
static void verify_profile() {
    const auto&p=gHoujiFirmwareMemory;const auto&s=p.summary;
    CHECK(p.complete && !p.code && p.firmware_valid && p.next==9 && !p.active && p.phase==5 && !fixture.released);
    CHECK(p.content_attempted && !p.content_status && !p.content_code);
    CHECK(p.validated==0x1ff && p.published==0x1ff && s.allocated==0x1ff && s.validated==0x1ff && s.retained==0x1ff && !s.released);
    CHECK(s.count==8 && s.records==15 && s.reservations==5 && s.bytes_loaded==77808 && s.tcm_bytes_deferred==540);
    CHECK(s.built_table_pages==6 && s.built_leaf_pages==139 && s.audit_complete && s.audit_descriptor_reads==3072);
    CHECK(p.audit.complete && p.audit.table_pages==6 && p.audit.leaf_pages==139 && p.audit.descriptor_reads==3072 && p.physical_reads==3072);
    static const unsigned pages[]={19,27,19,37,2,18,16,1,10};size_t logical=0,owned=0;
    for(unsigned i=0;i<9;++i) {
        const auto&b=p.info[i];CHECK(b.allocated && b.logical==pages[i]*4096u && b.owned==((b.logical+16383)&~UINT64_C(16383)) && b.rows==b.owned/4096);
        CHECK(b.pa>UINT32_MAX && b.pa+b.owned<=(UINT64_C(1)<<36) && !p.bo[i].quarantined() && !p.bo[i].deviceReferences());
        CHECK(p.bo[i].cpuPageBytes()==16384 && p.bo[i].ownedSpanCount()==1 && p.bo[i].spanCount()==1);
        CHECK(b.nc==(i>=5 && i<=7) && p.bo[i].writeCombined()==bool(b.nc));logical+=b.logical;owned+=b.owned;
        const auto*bytes=(const unsigned char*)(uintptr_t)b.va;for(uint64_t at=b.logical;at<b.owned;++at)CHECK(!bytes[at]);
        for(unsigned row=0;row<b.rows;++row) {
            bool rd=false,wr=false;
            for(const auto&a:host_at)if(!a.alias && a.phase==4 && a.slot==i && a.row==row && a.attr==(b.nc?0x44u:0xffu)){if(a.write)wr=true;else rd=true;}
            CHECK(rd && wr);
        }
        CHECK(b.alias_rows==b.rows && b.alias_wb+b.alias_nc==b.rows && b.alias_nc==(b.nc&&!host_alias_wb?b.rows:0));
        size_t published_lines=0;for(const auto&c:host_cache)if(c.slot==i && c.publishing && c.op==0)++published_lines;
        CHECK(published_lines==(b.nc?0:b.owned/64));
    }
    CHECK(logical==610304 && owned==671744 && owned/16384==41 && host_publish_barriers==9 && pmap_writes.size()==10);
    const auto*h=(const uint32_t*)(uintptr_t)p.info[5].va;CHECK(h[0]==0 && h[1]==210 && h[2]==6 && h[3]==12 && h[4]==17 && h[5]==17);
    for(unsigned q=0;q<17;++q){const auto*head=h+6+q*12;const unsigned priority=q<7?0:q<11?1:q<14?2:q<16?3:4;
        CHECK(head[0]==1 && head[1]==0x60010000+848+q*4096 && head[2]==(q|(priority<<8)) && head[3]==1024);
        for(unsigned i=4;i<12;++i)CHECK(!head[i]);const auto*ring=h+848/4+q*1024;for(unsigned i=0;i<1024;++i)CHECK(!ring[i]);}
    const auto*bytes=(const unsigned char*)h;for(unsigned i=840;i<848;++i)CHECK(!bytes[i]);for(unsigned i=848+17*4096;i<73728;++i)CHECK(!bytes[i]);
    CHECK(!memcmp((void*)(uintptr_t)p.info[0].va,gHoujiGmuFirmwareImage+684,77808));
    const unsigned allocations=host_alloc_attempts,ats=host_at_calls,lines=(unsigned)host_cache.size(),d=barriers;
    CHECK(houjiGpuFirmwareMemoryProbeOnce() && host_alloc_attempts==allocations && host_at_calls==ats && host_cache.size()==lines && barriers==d && !fixture.released);
}
static bool damage_case(unsigned slot,uint64_t offset,unsigned kind) {
    reset();host_damage_slot=slot;host_damage_offset=offset;host_damage_kind=kind;
    const bool accepted=houjiGpuFirmwareMemoryProbeOnce();CHECK(host_damage_done);
    if(!accepted)retained_failure();return !accepted;
}
static void verify_content_api_guards() {
    auto&p=gHoujiFirmwareMemory;CHECK(p.complete);
    const unsigned a=host_alloc_attempts,at=host_at_calls,b=barriers,r=fixture.released;
    std::array<unsigned char,HHI_STORAGE_BYTES> state_before{};memcpy(state_before.data(),&p.storage,sizeof p.storage);
    std::array<std::vector<unsigned char>,9> before;
    for(unsigned i=0;i<9;++i){const auto*start=(const unsigned char*)(uintptr_t)p.info[i].va;before[i].assign(start,start+p.info[i].owned);}
    uint32_t out=0x12345678;
    CHECK(hhi_verify_contents(&p.storage,sizeof(p.storage)-1,gHoujiGmuFirmwareImage,sizeof gHoujiGmuFirmwareImage,&out)!=HHI_OK && out==0x12345678);
    CHECK(hhi_verify_contents((unsigned char*)&p.storage+1,sizeof(p.storage),gHoujiGmuFirmwareImage,sizeof gHoujiGmuFirmwareImage,&out)!=HHI_OK && out==0x12345678);
    CHECK(hhi_verify_contents(&p.storage,sizeof(p.storage),gHoujiGmuFirmwareImage,sizeof(gHoujiGmuFirmwareImage)-1,&out)!=HHI_OK && out==0x12345678);
    CHECK(hhi_verify_contents(&p.storage,sizeof(p.storage),gHoujiGmuFirmwareImage,sizeof gHoujiGmuFirmwareImage,nullptr)!=HHI_OK);
    CHECK(hhi_verify_contents(&p.storage,sizeof(p.storage),gHoujiGmuFirmwareImage,sizeof gHoujiGmuFirmwareImage,(uint32_t*)(uintptr_t)p.info[6].va)!=HHI_OK);
    HhiStorage copy{};memcpy(&copy,&p.storage,sizeof copy);
    CHECK(hhi_verify_contents(&copy,sizeof copy,gHoujiGmuFirmwareImage,sizeof gHoujiGmuFirmwareImage,&out)!=HHI_OK && out==0x12345678);
    HhiStorage empty{};CHECK(hhi_verify_contents(&empty,sizeof empty,gHoujiGmuFirmwareImage,sizeof gHoujiGmuFirmwareImage,&out)!=HHI_OK && out==0x12345678);
    const HhiCallbacks callbacks={HHI_ABI_VERSION,0,&p,houjiFirmwareAllocate,houjiFirmwareValidate,houjiFirmwarePublish,houjiFirmwareRetain};
    CHECK(hhi_init(&empty,sizeof empty,&callbacks,sizeof callbacks)==HHI_OK);
    CHECK(hhi_verify_contents(&empty,sizeof empty,gHoujiGmuFirmwareImage,sizeof gHoujiGmuFirmwareImage,&out)==HHI_NOT_PREPARED && out==0x12345678);
    CHECK(hhi_verify_contents(&p.storage,sizeof p.storage,gHoujiGmuFirmwareImage,sizeof gHoujiGmuFirmwareImage,&out)==HHI_OK && !out);
    CHECK(!memcmp(state_before.data(),&p.storage,sizeof p.storage));
    for(unsigned i=0;i<9;++i)CHECK(!memcmp(before[i].data(),(void*)(uintptr_t)p.info[i].va,before[i].size()));
    CHECK(host_alloc_attempts==a && host_at_calls==at && barriers==b && fixture.released==r);
}
int main(int argc,char**argv) {
    const bool allow_gaps=argc==2 && !strcmp(argv[1],"--record-known-gaps");unsigned cases=0,gaps=0;
    reset();host_enabled=false;CHECK(houjiGpuFirmwareMemoryProbeOnce() && !gHoujiFirmwareMemoryOnce && !host_alloc_attempts);++cases;
    for(unsigned gate=0;gate<3;++gate){reset();if(!gate)gRootEnabled=false;else if(gate==1)gLogEnabled=false;else gReturnRecovery=false;
        CHECK(!houjiGpuFirmwareMemoryProbeOnce() && gHoujiFirmwareMemory.code==16 && !host_alloc_attempts && !host_at_calls);retained_failure();++cases;}
    reset();CHECK(houjiGpuFirmwareMemoryProbeOnce());verify_profile();verify_content_api_guards();const unsigned all_ats=host_at_calls;cases+=2;
    printf("BASELINE: CPU16K highPA9BO logical610304 backing671744 AT=%u aliasAT=%u 6tables139leaves3072reads HFI17; retained, refs0\n",all_ats,host_alias_at_calls);
    for(unsigned n=1;n<=9;++n){reset();host_fail_alloc=n;CHECK(!houjiGpuFirmwareMemoryProbeOnce());retained_failure();CHECK(fixture.created==n-1);++cases;}
    for(unsigned n=1;n<=10;++n){reset();attribute_write_fail=n;CHECK(!houjiGpuFirmwareMemoryProbeOnce());retained_failure();++cases;}
    for(unsigned n=1;n<=all_ats;++n){reset();host_fail_at=n;CHECK(!houjiGpuFirmwareMemoryProbeOnce());retained_failure();++cases;}
    for(unsigned n:{1u,2u,39u,40u,327u,328u,all_ats-1,all_ats}){reset();host_bad_par_at=n;CHECK(!houjiGpuFirmwareMemoryProbeOnce());retained_failure();++cases;}
    for(unsigned slot:{0u,1u,2u,3u,4u,8u}){reset();host_publish_fail_slot=slot;CHECK(!houjiGpuFirmwareMemoryProbeOnce());retained_failure();CHECK(gHoujiFirmwareMemory.first_code==10);++cases;}
    for(unsigned slot=0;slot<9;++slot)if(slot!=6){const uint64_t logical[]={77824,110592,77824,151552,8192,73728,65536,4096,40960};CHECK(damage_case(slot,logical[slot],1));++cases;}
    CHECK(damage_case(8,0,2));++cases;CHECK(damage_case(8,6*4096,3));++cases;
    // Inject only at the architecture publication boundary. The final audit
    // must independently verify retained RAM rather than trust a prior flag.
    const auto contents_damage=[&](unsigned slot,uint64_t offset,const char*name) {
        if(!damage_case(slot,offset,4)){++gaps;printf("GAP: Native complete accepted corrupt %s byte slot=%u offset=%llu after CPU publication\n",name,slot,(unsigned long long)offset);}
        else {const unsigned code=slot==5?4:slot==6?5:slot==7?6:!strcmp(name,"FW payload")?2:3;
            CHECK(gHoujiFirmwareMemory.content_attempted && !gHoujiFirmwareMemory.content_status && gHoujiFirmwareMemory.content_code==code && gHoujiFirmwareMemory.code==15);}
        ++cases;
    };
    for(uint64_t offset:{UINT64_C(0),UINT64_C(77807)})contents_damage(0,offset,"FW payload");
    for(uint64_t offset:{UINT64_C(77808),UINT64_C(77823)})contents_damage(0,offset,"FW holes");
    const uint64_t firmware_logical[]={77824,110592,77824,151552,8192};
    for(unsigned slot=1;slot<5;++slot){contents_damage(slot,0,"FW holes");contents_damage(slot,firmware_logical[slot]-1,"FW holes");}
    for(unsigned word=0;word<6;++word)contents_damage(5,word*4,"HFI table header");
    for(unsigned q=0;q<17;++q){contents_damage(5,24+q*48+(q%12)*4,"HFI queue header");contents_damage(5,848+q*4096+(q&1?4095:0),"HFI ring");}
    for(uint64_t offset:{UINT64_C(24+10*4),UINT64_C(840),UINT64_C(847),UINT64_C(848+17*4096),UINT64_C(73727)})contents_damage(5,offset,"HFI cursor/padding");
    for(uint64_t offset:{UINT64_C(0),UINT64_C(65535)})contents_damage(6,offset,"log");
    for(uint64_t offset:{UINT64_C(0),UINT64_C(4095)})contents_damage(7,offset,"VRB");
    reset();host_alias_wb=true;CHECK(houjiGpuFirmwareMemoryProbeOnce() && host_alias_at_calls);verify_profile();
    for(unsigned slot=0;slot<9;++slot)CHECK(gHoujiFirmwareMemory.info[slot].alias_wb==gHoujiFirmwareMemory.info[slot].rows && !gHoujiFirmwareMemory.info[slot].alias_nc);
    for(const auto&line:host_logs)if(line.find("HOUJI FW MEMORY BO:")==0)CHECK(line.find("DMA-eligible=0")!=std::string::npos);++cases;
    for(unsigned fault=1;fault<=4;++fault){reset();host_alias_fault=fault;CHECK(!houjiGpuFirmwareMemoryProbeOnce());retained_failure();++cases;}
    // All owned bytes must be within the known aperture before phystokv/AT.
    for(unsigned mode=0;mode<3;++mode){reset();if(!mode)gPhysBase=fixture.next_physical+16384;else if(mode==1)gPhysSize=1;else gPhysSize=fixture.next_physical-gPhysBase+81919;
        CHECK(!houjiGpuFirmwareMemoryProbeOnce() && !host_alias_at_calls);retained_failure();++cases;}
    // Firmware identity really uses the linked production SHA/validate path.
    NativeAdrenoFirmwareRules rules{78588,{0x96,0x85,0xf6,0x2c,0x42,0x54,0x3b,0xef,0xca,0xee,0x68,0xd2,0x53,0x55,0xe1,0x6b,0xf5,0x5c,0xdb,0x0d,0x57,0x3b,0xdd,0xcc,0x9f,0x66,0x33,0xf5,0x9e,0xec,0x3f,0x72}};
    std::vector<uint8_t> changed(gHoujiGmuFirmwareImage,gHoujiGmuFirmwareImage+sizeof gHoujiGmuFirmwareImage);changed[1000]^=1;NativeAdrenoFirmwareView view{};
    CHECK(NativeAdrenoFirmware::validate(changed.data(),changed.size(),&rules,&view) && !view.bytes);
    CHECK(NativeAdrenoFirmware::validate(gHoujiGmuFirmwareImage,78587,&rules,&view) && !view.bytes);++cases;
    reset();discard_host_fixture_only();printf("RESULT: %u boundary/failure profiles; known-gaps=%u ASan/UBSan; no GPU/SMC/MMIO/firmware execution\n",cases,gaps);
    return gaps && !allow_gaps?2:0;
}
