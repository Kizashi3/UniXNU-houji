/* Host-only secure-CX state-machine tests. Never executes an SMC. */
#define GG_HOST_TEST 1
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "vendor/Ace5Gmu/giulia_gpu_scm.h"

struct fixture {
    struct ggs_regs input[160],output[160];
    unsigned count,next,delays,checks;
    int transport,delay_error,prerequisite,fail_second_check;
};
static int call(void *cookie,struct ggs_regs *r)
{
    struct fixture *f=cookie;
    assert(f->next<f->count);f->input[f->next]=*r;
    *r=f->output[f->next++];return f->transport;
}
static int delay_ms(void *cookie,unsigned delay)
{
    struct fixture *f=cookie;
    assert(delay==30);++f->delays;return f->delay_error;
}
static int prerequisites(void *cookie,unsigned operation)
{
    struct fixture *f=cookie;
    assert(operation==GGS_PROBE || operation==GGS_INIT);
    if(++f->checks==2 && f->fail_second_check)return 0;
    return f->prerequisite;
}
static struct ggs_ops ops(struct fixture *f)
{
    struct ggs_ops o={f,call,delay_ms,prerequisites};return o;
}
static void reset(struct fixture *f,struct ggs_state *s)
{memset(f,0,sizeof(*f));memset(s,0,sizeof(*s));f->prerequisite=1;}
static void reply(struct fixture *f,int64_t status,uint64_t value,uint64_t cookie)
{
    struct ggs_regs r={{(uint64_t)status,value,0xfeed,0xbeef,0x44,0x55,cookie,0x77}};
    assert(f->count<160);f->output[f->count++]=r;
}
static void available(struct fixture *f)
{reply(f,0,1,0);reply(f,0,1,0);}
static void input(const struct fixture *f,unsigned index,uint64_t fn,uint64_t arg,uint64_t cookie)
{
    const struct ggs_regs expected={{fn,1,arg,0,0,0,cookie,0}};
    assert(memcmp(&f->input[index],&expected,sizeof(expected))==0);
}
int main(void)
{
    struct fixture f;struct ggs_state s;struct ggs_ops o=ops(&f);
    reset(&f,&s);available(&f);
    assert(ggs_run(&o,&s,GGS_PROBE)==GGS_OK && f.next==2 && !s.init_succeeded);
    input(&f,0,0xc2000601u,0x02000601u,0);input(&f,1,0x42000601u,0x02002801u,0);
    assert(s.convention_verified && s.available && s.last_output.x[7]==0x77);
    reply(&f,0,1,0);reply(&f,0,0xdeadbeef,0);
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_OK && s.init_succeeded);
    input(&f,2,0x42000601u,0x02002801u,0);input(&f,3,0x42002801u,0xb,0);
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_ALREADY_INITIALIZED && f.next==4);

    reset(&f,&s);f.prerequisite=0;
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_PREREQUISITE && f.next==0);
    assert(ggs_run(&o,&s,2)==GGS_ARGUMENT && f.next==0);
    assert(ggs_run(NULL,&s,GGS_PROBE)==GGS_ARGUMENT);
    assert(ggs_run(&o,NULL,GGS_PROBE)==GGS_ARGUMENT);
    reset(&f,&s);available(&f);f.fail_second_check=1;
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_PREREQUISITE && f.next==2 && !s.init_succeeded);

    reset(&f,&s);reply(&f,0,2,0);
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_CONVENTION && f.next==1);
    reset(&f,&s);reply(&f,0,1,0);reply(&f,0,0,0);
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_UNAVAILABLE && f.next==2 && !s.available);
    reset(&f,&s);available(&f);reply(&f,-4,0,0);
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_SECURE_ERROR && !s.init_succeeded);
    assert((int64_t)s.last_output.x[0]==-4);
    /* Unknown upper bits must not turn a nonzero raw a0 into success/resume. */
    for(unsigned low=0;low<=3;low++) {
        reset(&f,&s);available(&f);reply(&f,(int64_t)(UINT64_C(0x100000000)+low),0,0);
        assert(ggs_run(&o,&s,GGS_INIT)==GGS_SECURE_ERROR && !s.init_succeeded);
        assert(f.next==3 && s.interrupt_resumes==0);
    }

    /* Returned a1..a5 are not resume arguments; only a6 is carried. */
    reset(&f,&s);available(&f);reply(&f,1,0xbad,0x123456789abcdef0ull);
    reply(&f,1,0xbad2,0xfedcba9876543210ull);reply(&f,0,9,0);
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_OK && s.interrupt_resumes==2);
    input(&f,3,1,0xb,0x123456789abcdef0ull);input(&f,4,1,0xb,0xfedcba9876543210ull);

    /* BUSY after interruption retries the original function with cookie zero. */
    reset(&f,&s);available(&f);reply(&f,1,0,0xabcd);reply(&f,-12,0,0xcafe);reply(&f,0,0,0);
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_OK && f.delays==1 && s.busy_retries==1);
    input(&f,3,1,0xb,0xabcd);input(&f,4,0x42002801u,0xb,0);
    reset(&f,&s);available(&f);reply(&f,0xfffffff4u,0,0);reply(&f,0,0,0);
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_OK && f.delays==1);

    for(int64_t status=2;status<=3;status++) {
        reset(&f,&s);available(&f);reply(&f,status,0x1234,0x5678);
        assert(ggs_run(&o,&s,GGS_INIT)==GGS_WAITQ && s.quarantined && f.next==3);
        assert(s.last_output.x[1]==0x1234 && s.last_output.x[6]==0x5678);
        assert(ggs_run(&o,&s,GGS_INIT)==GGS_QUARANTINED && f.next==3);
    }
    reset(&f,&s);available(&f);
    for(unsigned i=0;i<=GGS_INTERRUPT_RESUMES;i++)reply(&f,1,0,i);
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_RETRY_LIMIT && s.quarantined);
    assert(f.next==3+GGS_INTERRUPT_RESUMES && s.interrupt_resumes==GGS_INTERRUPT_RESUMES);
    reset(&f,&s);available(&f);
    for(unsigned i=0;i<=GGS_BUSY_RETRIES;i++)reply(&f,-12,0,0);
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_RETRY_LIMIT && s.quarantined);
    assert(f.next==3+GGS_BUSY_RETRIES && f.delays==GGS_BUSY_RETRIES);
    reset(&f,&s);reply(&f,0,1,0);f.transport=1;
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_TRANSPORT && s.quarantined && f.next==1);
    reset(&f,&s);available(&f);reply(&f,-12,0,0);f.delay_error=1;
    assert(ggs_run(&o,&s,GGS_INIT)==GGS_TRANSPORT && s.quarantined && f.next==3);
    puts("GPU secure-CX fixed ABI, retries, raw results and quarantine: passed (host only)");
    return 0;
}
