// SPDX-License-Identifier: BSD-2-Clause-Patent
// Pinned Ace 5 policy cases, compiled against the actual houji firmware policy.
#include <assert.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "../native/gpu/uefi/GpuPowerPolicy.h"

#define FW_FAILURE UINT64_C(0x8000000000000042)
struct model {
    uint32_t regs[GPP_REGISTER_COUNT],rates[2];
    unsigned resolved,acd,resource_calls,read_calls,delay_calls,events;
    unsigned fail_resolve,fail_acd,fail_resource,fail_read,fail_delay;
    unsigned dropped_resource,bad_set,bad_get,unknown_get,all_ones;
    unsigned cx_after_delay,lose_cx_at_final,cx_reads;
    unsigned cfg_reads,lose_cfg_at_final,drop_final_reg;
    unsigned reset_reads,release_reset_read,reset_proven,inherit_gmu_after_bus;
    unsigned enabled_reads[GPP_REGISTER_COUNT];
    unsigned reg_reads[GPP_REGISTER_COUNT];
    unsigned resources[64],operations[64];
};
static unsigned cases;
static void reset_model(struct model *m)
{
    unsigned i;
    memset(m,0,sizeof(*m));m->regs[GPP_REG_CX]=1;
    for(i=GPP_REG_GMU;i<=GPP_REG_SMMU;i++)m->regs[i]=0x80000000u;
    m->regs[GPP_REG_SYSRESET]=1;m->all_ones=m->drop_final_reg=~0u;
}
static unsigned reg_for(unsigned resource)
{
    static const unsigned reg[]={GPP_REG_CFG,GPP_REG_CX,~0u,~0u,
        GPP_REG_GMU,GPP_REG_CXO,GPP_REG_AXI,GPP_REG_MEMNOC,GPP_REG_DVM,
        GPP_REG_AHB,GPP_REG_HUB,GPP_REG_SMMU};
    assert(resource<sizeof(reg)/sizeof(reg[0]));return reg[resource];
}
static uint64_t resolve(void *cookie)
{
    struct model *m=cookie;m->events++;
    if(m->fail_resolve)return FW_FAILURE;
    m->resolved=1;return 0;
}
static uint64_t acd(void *cookie)
{
    struct model *m=cookie;
    assert(m->resolved && !m->acd && !m->rates[0] && !m->rates[1]);
    assert((m->regs[GPP_REG_CX]&1) && !(m->regs[GPP_REG_CX_HW]&0x80000000u));
    m->acd++;m->events++;return m->fail_acd?FW_FAILURE:0;
}
static uint64_t resource(void *cookie,unsigned id,unsigned op,uint32_t requested,uint32_t *actual)
{
    struct model *m=cookie;unsigned call=m->resource_calls++;
    assert(call<64 && id<GPP_RESOURCE_COUNT && actual && m->resolved);
    m->resources[call]=id;m->operations[call]=op;m->events++;
    if(id!=GPP_CFG)assert(m->acd==1);
    if(id!=GPP_CFG && id!=GPP_CX) {
        assert(!(m->regs[GPP_REG_CX]&1));
        assert(m->regs[GPP_REG_CX_HW]&0x80000000u);
    }
    if(id==GPP_GMU_RATE || id==GPP_GMU_CLK) {
        assert(m->reset_proven && (m->regs[GPP_REG_SYSRESET]&1));
        if(op!=GPP_GET_RATE)assert(!(m->regs[GPP_REG_GMU]&1));
    }
    if(m->fail_resource==call+1)return FW_FAILURE;
    if(m->dropped_resource==id+1)return 0;
    if(op==GPP_ENABLE) {
        unsigned reg=reg_for(id);assert(requested==1);
        if(id==GPP_CX) {
            m->regs[reg]&=~1u;
            if(!m->cx_after_delay)m->regs[GPP_REG_CX_HW]|=0x80000000u;
        } else if(id==GPP_AXI_CLK)m->regs[reg]|=1u; /* HALT_SKIP need not toggle */
        else m->regs[reg]=(m->regs[reg]&~0x80000000u)|1u;
    } else {
        unsigned index=id==GPP_GMU_RATE?0:1;
        assert(id==GPP_GMU_RATE || id==GPP_HUB_RATE);
        if(op==GPP_SET_RATE) {
            assert(requested==(index?200000000u:625000000u));
            m->rates[index]=requested;*actual=m->bad_set==id+1?requested-1:requested;
        } else {
            assert(op==GPP_GET_RATE && !requested);
            *actual=m->unknown_get==id+1?0:m->rates[index]-(m->bad_get==id+1);
        }
    }
    return 0;
}
static uint64_t read_reg(void *cookie,unsigned reg,uint32_t *value)
{
    struct model *m=cookie;
    assert(m->resolved && reg<GPP_REGISTER_COUNT);
    if(reg!=GPP_REG_CFG)assert(m->regs[GPP_REG_CFG]&1);
    if(reg>=GPP_REG_GMU) {
        assert(!(m->regs[GPP_REG_CX]&1));
        assert(m->regs[GPP_REG_CX_HW]&0x80000000u);
    }
    if(reg==GPP_REG_SYSRESET) {
        unsigned i;assert(m->rates[1]==200000000u);
        for(i=GPP_REG_CXO;i<=GPP_REG_SMMU;i++)assert(m->regs[i]&1);
        if(!m->reset_reads)assert(!m->rates[0] && !(m->regs[GPP_REG_GMU]&1));
    }
    m->read_calls++;m->events++;
    m->reg_reads[reg]++;
    if(reg==GPP_REG_CFG && ++m->cfg_reads==3 && m->lose_cfg_at_final)
        m->regs[GPP_REG_CFG]&=~1u;
    if((m->regs[reg]&1) && reg>=GPP_REG_GMU && reg<=GPP_REG_SMMU)
        m->enabled_reads[reg]++;
    if(m->drop_final_reg==reg && m->enabled_reads[reg]==2)
        m->regs[reg]=(m->regs[reg]&~1u)|0x80000000u;
    if(reg==GPP_REG_CX && ++m->cx_reads==3 && m->lose_cx_at_final)
        m->regs[GPP_REG_CX]|=1;
    if(reg==GPP_REG_GMU && m->inherit_gmu_after_bus && m->rates[1])
        m->regs[GPP_REG_GMU]|=1;
    if(reg==GPP_REG_SYSRESET && ++m->reset_reads==m->release_reset_read)
        m->regs[GPP_REG_SYSRESET]=0;
    if(m->fail_read==m->read_calls)return FW_FAILURE;
    *value=m->all_ones==reg?0xffffffffu:m->regs[reg];
    if(reg==GPP_REG_SYSRESET && *value!=0xffffffffu && (*value&1))m->reset_proven=1;
    return 0;
}
static uint64_t delay_us(void *cookie,unsigned us)
{
    struct model *m=cookie;assert(us==10);m->delay_calls++;m->events++;
    if(m->fail_delay==m->delay_calls)return FW_FAILURE;
    if(m->cx_after_delay && m->delay_calls==m->cx_after_delay)
        m->regs[GPP_REG_CX_HW]|=0x80000000u;
    return 0;
}
static struct gpp_io ops(struct model *m)
{struct gpp_io io={m,resolve,acd,resource,read_reg,delay_us};return io;}
static unsigned run(struct model *m,struct gpp_report *r)
{
    struct gpp_io io=ops(m);unsigned code;
    gpp_report_init(r);assert(gpp_report_requested(r) && !gpp_report_valid(r));
    code=gpp_prepare(&io,r);assert(gpp_report_valid(r));
    assert(r->code==code && r->retained==!!r->attempted);
    assert(!(r->confirmed&~r->attempted));cases++;return code;
}
static void no_late_resources(const struct model *m)
{
    unsigned i;
    for(i=0;i<m->resource_calls;i++)assert(m->resources[i]==GPP_CFG || m->resources[i]==GPP_CX);
    assert(!m->rates[0] && !m->rates[1]);
}
static void no_gmu_mutation(const struct model *m)
{
    unsigned i;
    for(i=0;i<m->resource_calls;i++)
        assert(m->resources[i]!=GPP_GMU_RATE && m->resources[i]!=GPP_GMU_CLK);
    assert(!m->rates[0]);
}
int main(void)
{
    struct model m;struct gpp_report r;unsigned i,calls,reads;
    reset_model(&m);assert(run(&m,&r)==GPP_OK);
    assert(sizeof(r)==256 && offsetof(struct gpp_report,crc32)==252);
    assert((r.flags&(GPP_READY|GPP_ACD_CONSUMED))==(GPP_READY|GPP_ACD_CONSUMED));
    assert(r.attempted==(1u<<GPP_RESOURCE_COUNT)-1 && r.confirmed==r.attempted);
    assert(r.valid_reads==0x3fffu);
    assert(r.values[GPP_VALUE_GMU_RATE]==625000000u && r.values[GPP_VALUE_HUB_RATE]==200000000u);
    calls=m.resource_calls;reads=m.read_calls;
    reset_model(&m);m.regs[GPP_REG_CFG]=1;assert(run(&m,&r)==GPP_OK);
    assert(r.flags&GPP_CFG_INHERITED);assert(!(r.attempted&(1u<<GPP_CFG)));
    for(i=0;i<m.resource_calls;i++)assert(m.resources[i]!=GPP_CFG);

    reset_model(&m);m.fail_resolve=1;assert(run(&m,&r)==GPP_ERR_RESOLVE);
    assert(!m.resource_calls && !m.read_calls && !r.attempted && r.firmware_status==FW_FAILURE);
    for(i=0;i<4;i++) {
        reset_model(&m);m.regs[GPP_REG_CFG]=1;
        if(i&1)m.regs[GPP_REG_CX]=0;
        if(i&2)m.regs[GPP_REG_CX_HW]=0x80000000u;
        if(!i)continue;
        assert(run(&m,&r)==GPP_ERR_INITIAL);
        assert(!m.resource_calls && !m.acd && !r.attempted);
    }
    reset_model(&m);m.regs[GPP_REG_CX_HW]=0x80000000u;
    assert(run(&m,&r)==GPP_ERR_INITIAL);assert(r.attempted==(1u<<GPP_CFG) && r.retained);
    reset_model(&m);m.fail_acd=1;assert(run(&m,&r)==GPP_ERR_ACD);
    assert(r.attempted&1u<<GPP_ACD);assert(!(r.confirmed&1u<<GPP_ACD));no_late_resources(&m);

    /* Every native resource failure retains all possibly modified resources,
     * never executes a later action, and preserves the full 64-bit status. */
    for(i=1;i<=calls;i++) {
        reset_model(&m);m.fail_resource=i;assert(run(&m,&r)==GPP_ERR_RESOURCE);
        assert(m.resource_calls==i && r.firmware_status==FW_FAILURE && r.retained);
        assert(r.failure_resource==m.resources[i-1]);
    }
    for(i=1;i<=reads;i++) {
        reset_model(&m);m.fail_read=i;assert(run(&m,&r)==GPP_ERR_READ);
        assert(m.read_calls==i && r.firmware_status==FW_FAILURE);
        assert(!(r.valid_reads&(1u<<r.failed_read)));
        assert(!(r.flags&GPP_OBSERVED_VALID));
    }
    for(i=0;i<GPP_REGISTER_COUNT;i++) {
        reset_model(&m);m.all_ones=i;assert(run(&m,&r)==GPP_ERR_READ);
        assert(!(r.valid_reads&(1u<<i)) && !r.firmware_status);
    }
    for(i=GPP_CFG;i<=GPP_SMMU_CLK;i++) {
        if(i==GPP_GMU_RATE || i==GPP_HUB_RATE)continue;
        reset_model(&m);m.dropped_resource=i+1;assert(run(&m,&r)==GPP_ERR_TIMEOUT);
        assert(r.attempted&(1u<<i));assert(!(r.confirmed&(1u<<i)));
        assert(m.delay_calls==GPP_POLL_LIMIT-1 && r.polls==GPP_POLL_LIMIT);
        if(i==GPP_CX || i==GPP_CFG)no_late_resources(&m);
    }
    reset_model(&m);m.cx_after_delay=4;assert(run(&m,&r)==GPP_OK);
    assert(m.delay_calls==4 && r.polls==4);
    reset_model(&m);m.cx_after_delay=4;m.fail_delay=2;
    assert(run(&m,&r)==GPP_ERR_RESOURCE);assert(r.failure_operation==GPP_OP_DELAY);
    no_late_resources(&m);
    for(i=GPP_GMU_RATE;i<=GPP_HUB_RATE;i++) {
        reset_model(&m);m.bad_set=i+1;assert(run(&m,&r)==GPP_ERR_RATE);
        assert(r.failure_operation==GPP_OP_SET_RATE && !(r.confirmed&(1u<<i)));
        reset_model(&m);m.bad_get=i+1;assert(run(&m,&r)==GPP_ERR_RATE);
        assert(r.failure_operation==GPP_OP_GET_RATE && !(r.confirmed&(1u<<i)));
        reset_model(&m);m.unknown_get=i+1;assert(run(&m,&r)==GPP_ERR_RATE);
        assert(r.values[i==GPP_GMU_RATE?GPP_VALUE_GMU_RATE:GPP_VALUE_HUB_RATE]==0);
        assert(!(r.valid_reads&(1u<<(i==GPP_GMU_RATE?GPP_VALUE_GMU_RATE:GPP_VALUE_HUB_RATE))));
        assert(!(r.flags&GPP_OBSERVED_VALID));
    }
    reset_model(&m);m.regs[GPP_REG_SYSRESET]=0;
    assert(run(&m,&r)==GPP_ERR_RESET);assert(!(r.flags&GPP_READY) && r.retained);
    no_gmu_mutation(&m);
    reset_model(&m);m.regs[GPP_REG_GMU]=1;
    assert(run(&m,&r)==GPP_ERR_INITIAL);no_gmu_mutation(&m);
    assert(!m.rates[1]);
    reset_model(&m);m.inherit_gmu_after_bus=1;
    assert(run(&m,&r)==GPP_ERR_INITIAL);no_gmu_mutation(&m);
    reset_model(&m);m.all_ones=GPP_REG_SYSRESET;
    assert(run(&m,&r)==GPP_ERR_READ);no_gmu_mutation(&m);
    reset_model(&m);m.release_reset_read=2;
    assert(run(&m,&r)==GPP_ERR_RESET);
    assert(m.rates[0]==625000000u && !(r.attempted&(1u<<GPP_GMU_CLK)));
    reset_model(&m);m.release_reset_read=3;
    assert(run(&m,&r)==GPP_ERR_RESET);
    reset_model(&m);m.lose_cx_at_final=1;assert(run(&m,&r)==GPP_ERR_INITIAL);
    assert(m.reset_reads==2);
    reset_model(&m);m.lose_cfg_at_final=1;assert(run(&m,&r)==GPP_ERR_INITIAL);
    assert(m.reset_reads==2);
    for(i=GPP_REG_GMU;i<=GPP_REG_SMMU;i++) {
        reset_model(&m);m.drop_final_reg=i;assert(run(&m,&r)==GPP_ERR_TIMEOUT);
        assert(r.failure_phase==GPP_PHASE_READY && !(r.flags&GPP_READY));
        assert(m.reset_reads==2);
    }

    /* Missing callbacks and reused requests never invoke firmware. CRC and
     * reserved-byte corruption cannot be mistaken for a returned result. */
    reset_model(&m);
    {struct gpp_io io=ops(&m);io.acd=0;gpp_report_init(&r);
     assert(gpp_prepare(&io,&r)==GPP_ERR_ARGUMENT && !m.events && gpp_report_valid(&r));cases++;}
    reset_model(&m);assert(run(&m,&r)==GPP_OK);
    {struct gpp_io io=ops(&m);unsigned events=m.events;
     assert(gpp_prepare(&io,&r)==GPP_ERR_REUSED && m.events==events);cases++;}
    r.protocol_status=FW_FAILURE;gpp_report_seal(&r);assert(gpp_report_valid(&r));
    r.values[0]^=1;assert(!gpp_report_valid(&r));r.values[0]^=1;
    r.reserved[3]=1;gpp_report_seal(&r);assert(!gpp_report_valid(&r));cases++;
    printf("GPU power preparation: %u bounded, ownership, failure-retention, rate, read-validity and ABI cases passed\n",cases);
    return 0;
}
