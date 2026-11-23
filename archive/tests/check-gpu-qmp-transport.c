// SPDX-License-Identifier: BSD-2-Clause-Patent
// Ace 5 transport model against the actual firmware header.
/* Host-only model. Only the model's AOP side clears published lengths. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stddef.h>
typedef uint32_t UINT32;typedef uint64_t UINT64;typedef uintptr_t UINTN;
#define MAX_UINT32 0xffffffffU
#undef UINT32_C
#undef UINT64_C
#undef UINT32_MAX
#include "../native/gpu/uefi/GpuQmpTransport.h"

struct model {
    uint32_t ram[QPT_MSGRAM_BYTES/4],before[QPT_MSGRAM_BYTES/4];
    uint32_t received[QPT_MSGRAM_BYTES/4];
    const void *owner;
    uint64_t now;
    unsigned reads,writes,kicks,barriers,claims,releases,delays;
    unsigned ack_open,ack_close,consume,freeze_clock,drop_channel,change_geometry,change_remote_geometry;
    unsigned payload_writes,barrier_after_payload,published,received_bytes;
    unsigned drop_payload,publication_mode;
    unsigned remote_ack_writes,drop_remote_ack,remote_stays_up,close_link_loss;
    unsigned corrupt_remote_ack,close_pending_bytes;
    unsigned remote_state_reads,change_remote_on_read;
} h;

static uint32_t read32(void *context,uint32_t offset)
{
    struct model *m=context;assert(!(offset&3) && offset<QPT_MSGRAM_BYTES);
    if(offset==0x14 && ++m->remote_state_reads==m->change_remote_on_read)m->ram[offset/4]=QPT_DOWN;
    m->reads++;return m->ram[offset/4];
}
static void write32(void *context,uint32_t offset,uint32_t value)
{
    struct model *m=context;assert(m->owner && !(offset&3) && offset<QPT_MSGRAM_BYTES);
    m->writes++;
    if(offset==0x2c) {
        assert(value==QPT_UP || value==QPT_DOWN);
        if(!m->drop_channel)m->ram[offset/4]=value;
        return;
    }
    if(offset==0x18) {
        assert(value==QPT_UP || value==QPT_DOWN);
        assert(m->ram[0x14/4]==value); /* ACK only an observed AOP state. */
        m->remote_ack_writes++;
        if(!m->drop_remote_ack)m->ram[offset/4]=value;
        return;
    }
    /* This also proves no link fields, AOP ACKs, IPCC receive registers, or
     * unrelated SRAM words are changed by the transport. */
    uint32_t base=m->ram[0x38/4],size=m->ram[0x34/4];
    assert(offset>=base && offset<base+size);
    assert(m->ram[base/4]==0); /* AOP owns every published buffer until consume. */
    if(offset==base) {
        assert(value && !(value&3) && value<=size-4); /* Host never cancels with zero. */
        assert(m->payload_writes==value/4 && m->barrier_after_payload);
        m->published=value;
        if(m->publication_mode==1)return; /* Dropped length store: remains zero. */
        if(m->publication_mode==2) { /* AOP consumes before the first readback. */
            memcpy(m->received,m->ram+base/4+1,value);m->received_bytes=value;
            m->ram[base/4]=0;m->payload_writes=0;m->published=0;return;
        }
        if(m->publication_mode==3) {m->ram[base/4]=value+4;return;}
        if(m->publication_mode==4) {m->ram[base/4]=UINT32_MAX;return;}
    } else {
        m->payload_writes++;m->barrier_after_payload=0;
        if(m->payload_writes==m->drop_payload)return;
    }
    m->ram[offset/4]=value;
}
static void barrier(void *context)
{ struct model *m=context;m->barriers++;if(m->payload_writes)m->barrier_after_payload=1; }
static void aop_consume(struct model *m)
{
    unsigned base=m->ram[0x38/4],bytes=m->ram[base/4];
    assert(bytes && bytes<=m->ram[0x34/4]-4);
    memcpy(m->received,m->ram+base/4+1,bytes);m->received_bytes=bytes;
    m->ram[base/4]=0;m->payload_writes=0;m->published=0;
}
static void kick(void *context)
{
    struct model *m=context;assert(m->owner);m->kicks++;
    /* The real adapter has exactly this one IPCC operation. */
    assert(QPT_DOORBELL_PA==0x0040600c && QPT_DOORBELL_VALUE==0);
    if(m->ram[0x2c/4]==QPT_UP && m->ack_open) {
        m->ram[0x14/4]=QPT_UP;
        if(m->ram[0x18/4]==QPT_UP)m->ram[0x30/4]=QPT_UP;
    }
    if(m->ram[0x2c/4]==QPT_DOWN && m->ack_close) {
        if(!m->remote_stays_up)m->ram[0x14/4]=QPT_DOWN;
        m->ram[0x30/4]=QPT_DOWN;
        if(m->close_link_loss)m->ram[0x0c/4]=QPT_DOWN;
        if(m->corrupt_remote_ack)m->ram[0x18/4]=0x12345678;
        if(m->close_pending_bytes)m->ram[m->ram[0x38/4]/4]=m->close_pending_bytes;
    }
    if(m->consume && m->published)aop_consume(m);
}
static uint64_t now_us(void *context){return ((struct model *)context)->now;}
static void delay_us(void *context,unsigned us)
{
    struct model *m=context;assert(us==1000);m->delays++;
    if(!m->freeze_clock)m->now+=us;
    if(m->change_geometry)m->ram[0x34/4]-=4;
    if(m->change_remote_geometry)m->ram[0x20/4]-=4;
}
static int claim(void *context,const void *owner)
{
    struct model *m=context;m->claims++;
    if(m->owner)return 0;m->owner=owner;return 1;
}
static int owns(void *context,const void *owner)
{return ((struct model *)context)->owner==owner;}
static void release(void *context,const void *owner)
{struct model *m=context;assert(m->owner==owner);m->owner=NULL;m->releases++;}
static struct qpt_io io={&h,QPT_MSGRAM_BYTES,read32,write32,barrier,kick,now_us,delay_us,claim,owns,release};
static void init(struct qpt_state *s)
{
    memset(&h,0,sizeof(h));memset(s,0,sizeof(*s));
    for(unsigned i=0;i<QPT_MSGRAM_BYTES/4;i++)h.ram[i]=0xa5a5a5a5;
    h.ram[0]=0x4d41494c;h.ram[1]=1;h.ram[2]=0;
    const unsigned up[]={0x0c,0x10,0x14,0x18,0x24,0x28};
    for(unsigned i=0;i<sizeof(up)/sizeof(up[0]);i++)h.ram[up[i]/4]=QPT_UP;
    h.ram[0x1c/4]=0x68;h.ram[0x20/4]=0xc0;
    h.ram[0x2c/4]=h.ram[0x30/4]=QPT_DOWN;
    h.ram[0x34/4]=0x2d8;h.ram[0x38/4]=0x128;h.ram[0x128/4]=0;
    h.ack_open=h.ack_close=h.consume=1;
    memcpy(h.before,h.ram,sizeof(h.ram));
}
static void unchanged(void){assert(!h.writes && !memcmp(h.before,h.ram,sizeof(h.ram)));}
static void unrelated_unchanged(void)
{
    for(unsigned i=0;i<0x128/4;i++)
        if(i!=0x14/4 && i!=0x18/4 && i!=0x2c/4 && i!=0x30/4)assert(h.ram[i]==h.before[i]);
}
int main(void)
{
    struct qpt_state s;unsigned cases=0;
    uint32_t packet[QPT_MSGRAM_BYTES/4];
    for(unsigned i=0;i<QPT_MSGRAM_BYTES/4;i++)packet[i]=0x12340000+i;
    init(&s);assert(qpt_open(&io,&s)==QPT_OK && s.phase==QPT_READY && h.owner==&s);
    assert(h.writes==1 && h.ram[0x24/4]==QPT_UP);cases++;
    assert(qpt_send(&io,&s,packet,64)==QPT_OK && !s.pending && s.publication_verified);
    assert(h.received_bytes==64 && !memcmp(h.received,packet,64));
    assert(!memcmp(h.ram+0x12c/4,packet,64));unrelated_unchanged();cases++;
    assert(qpt_send(&io,&s,packet,0x2d4)==QPT_OK && h.received_bytes==0x2d4);cases++;
    assert(qpt_close(&io,&s)==QPT_OK && !h.owner && h.ram[0x2c/4]==QPT_DOWN && !s.publication_verified);
    assert(h.ram[0x14/4]==QPT_DOWN && h.ram[0x18/4]==QPT_DOWN && h.remote_ack_writes==1);
    assert(h.ram[0x24/4]==QPT_UP);unrelated_unchanged();cases++;
    /* Complete the observed close handshake, then reopen the same channel:
     * host UP -> remote UP -> host ACK UP -> remote ACK UP, preserving links. */
    unsigned reopen_kicks=h.kicks;
    assert(qpt_open(&io,&s)==QPT_OK && h.kicks==reopen_kicks+2 && h.remote_ack_writes==2);
    assert(qpt_send(&io,&s,packet,64)==QPT_OK && qpt_close(&io,&s)==QPT_OK);
    unrelated_unchanged();cases++;
    /* Geometry/identity failures never write the shared region. */
    static const uint32_t invalid[][2]={{0,0},{4,2},{0x38,0x129},{0x38,0x38},
        {0x38,0xfffffffc},{0x34,0},{0x34,4},{0x34,0x2dc},{0x34,0xffffffff},
        {0x1c,0},{0x1c,4},{0x1c,0x69},{0x1c,0x6c},{0x1c,0xffffffff},
        {0x20,0},{0x20,0x38},{0x20,0xc1},{0x20,0xfffffffc},
        {0x38,0xc0},{0x38,0x124}};
    for(unsigned i=0;i<sizeof(invalid)/sizeof(invalid[0]);i++) {
        init(&s);h.ram[invalid[i][0]/4]=invalid[i][1];memcpy(h.before,h.ram,sizeof(h.ram));
        assert(qpt_open(&io,&s)==QPT_DESCRIPTOR && !s.leased && !h.owner);unchanged();cases++;
    }
    static const unsigned links[]={0x0c,0x10,0x24,0x28};
    for(unsigned i=0;i<sizeof(links)/sizeof(links[0]);i++) {
        init(&s);h.ram[links[i]/4]=QPT_DOWN;memcpy(h.before,h.ram,sizeof(h.ram));
        assert(qpt_open(&io,&s)==QPT_NOT_READY && !s.leased);unchanged();cases++;
    }
    for(unsigned i=0;i<4;i++) {
        init(&s);
        h.ram[(i&1?0x18:0x14)/4]=i<2?QPT_DOWN:0x12345678;
        memcpy(h.before,h.ram,sizeof(h.ram));
        assert(qpt_open(&io,&s)==QPT_BUSY && !s.leased);unchanged();cases++;
    }
    init(&s);h.ram[0x14/4]=h.ram[0x18/4]=QPT_DOWN;
    assert(qpt_open(&io,&s)==QPT_OK && h.remote_ack_writes==1 && h.kicks==2);
    assert(qpt_close(&io,&s)==QPT_OK && h.remote_ack_writes==2);unrelated_unchanged();cases++;
    /* Observed after UEFI: remote UP / remote ACK DOWN, host DOWN/DOWN,
     * both lengths zero. Follow the vendor open handshake; never reset a
     * mailbox or steal an inherited open APSS channel to make it work. */
    init(&s);h.ram[0x18/4]=QPT_DOWN;h.ram[0xc0/4]=0;
    memcpy(h.before,h.ram,sizeof(h.ram));
    assert(qpt_open(&io,&s)==QPT_OK && s.owned && s.leased);
    assert(h.remote_ack_writes==1 && h.kicks==2 && h.ram[0x18/4]==QPT_UP);
    assert(qpt_send(&io,&s,packet,64)==QPT_OK && qpt_close(&io,&s)==QPT_OK);
    unrelated_unchanged();cases++;
    for(unsigned fault=0;fault<6;fault++) {
        init(&s);h.ram[0x18/4]=QPT_DOWN;h.ram[0xc0/4]=0;
        if(fault==0)h.ram[0xc0/4]=64;
        if(fault==1)h.ram[0x128/4]=64;
        if(fault==2)h.ram[0x2c/4]=QPT_UP;
        if(fault==3)h.ram[0x30/4]=QPT_UP;
        if(fault==4)h.ram[0x18/4]=0x12345678;
        if(fault==5)h.change_remote_on_read=3;
        memcpy(h.before,h.ram,sizeof(h.ram));
        assert(qpt_open(&io,&s)==QPT_BUSY && !s.leased && !s.owned && !h.owner && !h.writes);
        if(fault!=5)unchanged();cases++;
    }
    init(&s);h.ram[0x18/4]=QPT_DOWN;h.ram[0xc0/4]=0;h.drop_remote_ack=1;
    assert(qpt_open(&io,&s)==QPT_IO && s.owned && s.leased && s.phase==QPT_UNCERTAIN);
    assert(h.remote_ack_writes==1 && !h.received_bytes && h.ram[0x128/4]==0);cases++;
    for(unsigned i=0;i<3;i++) {
        init(&s);
        if(i==0)h.ram[0x2c/4]=h.ram[0x30/4]=QPT_UP;
        if(i==1)h.ram[0x30/4]=QPT_UP;
        if(i==2)h.ram[0x128/4]=64;
        memcpy(h.before,h.ram,sizeof(h.ram));
        assert(qpt_open(&io,&s)==QPT_BUSY && !s.leased);unchanged();cases++;
    }
    init(&s);h.owner=&packet;assert(qpt_open(&io,&s)==QPT_BUSY && !h.reads);unchanged();cases++;
    init(&s);h.ack_open=0;
    assert(qpt_open(&io,&s)==QPT_TIMEOUT && s.owned && s.leased && s.phase==QPT_UNCERTAIN);
    assert(h.now==QPT_TIMEOUT_US && h.delays==1000 && h.ram[0x128/4]==0 && h.ram[0x2c/4]==QPT_UP);
    unsigned writes=h.writes;
    assert(qpt_open(&io,&s)==QPT_BUSY && qpt_close(&io,&s)==QPT_BUSY && h.writes==writes);cases++;
    init(&s);h.drop_channel=1;assert(qpt_open(&io,&s)==QPT_IO && s.owned && !h.kicks);cases++;
    for(unsigned drop=1;drop<=16;drop++) {
        init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.drop_payload=drop;
        unsigned kicks=h.kicks;
        assert(qpt_send(&io,&s,packet,64)==QPT_IO && !s.pending && !s.publication_verified && s.phase==QPT_UNCERTAIN);
        assert(h.ram[0x128/4]==0 && h.kicks==kicks && !h.received_bytes && h.owner==&s);cases++;
    }
    /* A zero length alone cannot distinguish a consumed packet from a dropped
     * publication store. No doorbell, clear, overwrite, lease release or later
     * "completion" is permitted without first observing exactly 64. */
    for(unsigned mode=1;mode<=4;mode++) {
        init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.publication_mode=mode;
        unsigned kicks=h.kicks;
        assert(qpt_send(&io,&s,packet,64)==QPT_PUBLICATION);
        assert(s.pending && s.pending_bytes==64 && !s.publication_verified && s.phase==QPT_UNCERTAIN);
        assert(s.leased && s.owned && h.owner==&s && h.kicks==kicks);
        assert(h.received_bytes==(mode==2?64u:0u));
        unsigned length=mode<=2?0u:mode==3?68u:UINT32_MAX;
        assert(h.ram[0x128/4]==length && !memcmp(h.ram+0x12c/4,packet,64));
        unsigned writes=h.writes,reads=h.reads;
        assert(qpt_complete(&io,&s)==QPT_PUBLICATION);
        assert(qpt_send(&io,&s,packet,64)==QPT_BUSY && qpt_close(&io,&s)==QPT_BUSY && qpt_open(&io,&s)==QPT_BUSY);
        assert(h.writes==writes && h.reads==reads && h.kicks==kicks && h.ram[0x128/4]==length);
        /* Even a later AOP zero cannot retroactively prove the original store. */
        h.ram[0x128/4]=0;
        assert(qpt_complete(&io,&s)==QPT_PUBLICATION && s.pending && !s.publication_verified);
        assert(h.writes==writes && h.reads==reads && h.kicks==kicks && h.owner==&s);cases++;
    }
    /* A completed earlier transfer must not lend its proof to a new one. */
    init(&s);assert(qpt_open(&io,&s)==QPT_OK && qpt_send(&io,&s,packet,64)==QPT_OK && s.publication_verified);
    h.publication_mode=1;
    assert(qpt_send(&io,&s,packet,64)==QPT_PUBLICATION && !s.publication_verified && s.pending);
    assert(qpt_complete(&io,&s)==QPT_PUBLICATION && s.pending && h.owner==&s);cases++;
    /* Timeout cannot erase an unconsumed packet or permit reuse/freeing. */
    init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.consume=0;
    assert(qpt_send(&io,&s,packet,64)==QPT_TIMEOUT && s.pending && s.publication_verified && h.owner==&s);
    assert(h.ram[0x128/4]==64 && !memcmp(h.ram+0x12c/4,packet,64));
    assert(h.now==QPT_TIMEOUT_US && h.delays==1000);writes=h.writes;unsigned kicks=h.kicks;
    assert(qpt_send(&io,&s,packet,64)==QPT_BUSY && qpt_close(&io,&s)==QPT_BUSY);
    assert(h.writes==writes && h.kicks==kicks);cases++;
    aop_consume(&h);assert(qpt_complete(&io,&s)==QPT_OK && !s.pending && s.publication_verified);
    assert(h.writes==writes && h.kicks==kicks);assert(qpt_close(&io,&s)==QPT_OK);cases++;
    init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.consume=0;h.freeze_clock=1;
    assert(qpt_send(&io,&s,packet,64)==QPT_TIMEOUT && h.delays==1000 && s.pending);cases++;
    init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.consume=0;h.now=UINT64_MAX-500000;
    assert(qpt_send(&io,&s,packet,64)==QPT_TIMEOUT && s.wait_elapsed_us==QPT_TIMEOUT_US);cases++;
    init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.consume=0;h.change_geometry=1;
    assert(qpt_send(&io,&s,packet,64)==QPT_OWNER_LOST && s.pending && h.ram[0x128/4]==64);cases++;
    /* AOP buffer relocation invalidates ownership even when it still fits
     * without overlap; never let an in-flight descriptor change go unnoticed. */
    init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.consume=0;h.change_remote_geometry=1;
    assert(qpt_send(&io,&s,packet,64)==QPT_OWNER_LOST && s.pending && h.ram[0x128/4]==64);cases++;
    init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.ram[0x20/4]-=4;writes=h.writes;
    assert(qpt_send(&io,&s,packet,64)==QPT_OWNER_LOST && !s.pending && h.writes==writes);cases++;
    init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.consume=0;
    assert(qpt_send(&io,&s,packet,64)==QPT_TIMEOUT);h.ram[0x128/4]=68;writes=h.writes;
    assert(qpt_complete(&io,&s)==QPT_OWNER_LOST && h.writes==writes && h.ram[0x128/4]==68);cases++;
    init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.owner=&packet;writes=h.writes;
    assert(qpt_send(&io,&s,packet,64)==QPT_OWNER_LOST && h.writes==writes);cases++;
    init(&s);assert(qpt_open(&io,&s)==QPT_OK);h.ack_close=0;
    assert(qpt_close(&io,&s)==QPT_TIMEOUT && s.leased && s.owned && h.ram[0x24/4]==QPT_UP);cases++;
    /* AOP's DOWN response is expected. Unchanged remote UP, a lost link,
     * an unexplained ACK change or a newly occupied mailbox are not closure. */
    for(unsigned mode=0;mode<5;mode++) {
        init(&s);assert(qpt_open(&io,&s)==QPT_OK);
        if(mode==0)h.remote_stays_up=1;
        if(mode==1)h.drop_remote_ack=1;
        if(mode==2)h.close_link_loss=1;
        if(mode==3)h.corrupt_remote_ack=1;
        if(mode==4)h.close_pending_bytes=64;
        unsigned releases=h.releases;
        int error=qpt_close(&io,&s);
        assert(error==(mode==0?QPT_TIMEOUT:mode<=2?QPT_IO:QPT_OWNER_LOST));
        assert(s.phase==QPT_UNCERTAIN && s.owned && s.leased && h.owner==&s && h.releases==releases);
        assert(h.ram[0x24/4]==QPT_UP);cases++;
    }
    /* Reopening a stable DOWN/DOWN channel cannot succeed if the new
     * APSS ACK write is dropped; retain ownership instead of publishing data. */
    init(&s);h.ram[0x14/4]=h.ram[0x18/4]=QPT_DOWN;h.drop_remote_ack=1;
    assert(qpt_open(&io,&s)==QPT_IO && s.phase==QPT_UNCERTAIN && s.leased && s.owned);
    assert(h.ram[0x128/4]==0 && !h.received_bytes && h.remote_ack_writes==1);cases++;
    init(&s);assert(qpt_open(&io,&s)==QPT_OK);writes=h.writes;
    assert(qpt_send(&io,&s,packet,0)==QPT_ARGUMENT);
    assert(qpt_send(&io,&s,packet,3)==QPT_ARGUMENT);
    assert(qpt_send(&io,&s,packet,0x2d8)==QPT_ARGUMENT);
    assert(qpt_send(&io,&s,packet,SIZE_MAX-3)==QPT_ARGUMENT);
    assert(qpt_send(&io,&s,(const uint32_t *)((const unsigned char *)packet+1),4)==QPT_ARGUMENT);
    assert(qpt_send(&io,&s,NULL,4)==QPT_ARGUMENT && h.writes==writes);cases++;
    printf("Wi-Fi QMP: %u ownership, 32-bit bounds, ordering, timeout, late-consume and retention cases passed\n",cases);
}
