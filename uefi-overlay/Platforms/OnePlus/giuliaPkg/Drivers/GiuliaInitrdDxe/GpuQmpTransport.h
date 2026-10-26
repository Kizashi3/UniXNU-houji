/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Ace 5 APSS -> AOP QMP v1, using the observed already-UP link handoff.
 * Register/transaction provenance: OnePlus kernel d763ed47deec55451366c1187f813f2f309d88a7,
 * drivers/soc/qcom/qcom_aoss.c and drivers/mailbox/qcom-ipcc.c.
 * The captured board maps MSGRAM at 0x0c300000/0x400 and APSS IPCC at
 * 0x00406000/0x1000. Only the APSS client0/signal0 SEND_ID doorbell is used.
 * All MMIO callbacks must use aligned 32-bit accesses. The caller serializes
 * operations and supplies one persistent software lease shared by every APSS
 * QMP client. Empty storage alone is not an ownership grant. Cold links and
 * already-open host channels and unexplained remote transitions are rejected;
 * uncertain published data is retained. Only the APSS channel state and its
 * ACK of the AOP channel are changed; shared link fields are never written.
 */
#ifndef GIULIA_GPU_QMP_TRANSPORT_H
#define GIULIA_GPU_QMP_TRANSPORT_H
/* Identical qpt algorithm to ios16/platform/giulia_platform_qmp.h; only firmware type
 * aliases and this include guard differ. Host tests exercise the original. */
typedef UINT32 uint32_t;
typedef UINT64 uint64_t;
typedef UINTN uintptr_t;
typedef UINTN size_t;
#define UINT32_C(n) n##U
#define UINT64_C(n) n##ULL
#define UINT32_MAX MAX_UINT32

#define QPT_MSGRAM_PA UINT32_C(0x0c300000)
#define QPT_MSGRAM_BYTES UINT32_C(0x400)
#define QPT_DOORBELL_PA UINT32_C(0x0040600c)
#define QPT_DOORBELL_VALUE UINT32_C(0) /* AOP client 0, signal 0 */
#define QPT_UP UINT32_C(0x0000ffff)
#define QPT_DOWN UINT32_C(0xffff0000)
#define QPT_TIMEOUT_US UINT64_C(1000000)

enum qpt_error { QPT_OK, QPT_ARGUMENT, QPT_BUSY, QPT_DESCRIPTOR,
    QPT_NOT_READY, QPT_OWNER_LOST, QPT_IO, QPT_TIMEOUT, QPT_PUBLICATION };
enum qpt_phase { QPT_CLOSED, QPT_OPENING, QPT_READY, QPT_SENDING,
    QPT_CLOSING, QPT_UNCERTAIN };
struct qpt_state {
    uint32_t offset,size,pending_bytes,last_offset,last_value;
    uint32_t remote_offset,remote_size,remote_ack;
    /* Verified proof is retained after success for diagnostics, then cleared
     * by the next submission/open/close. It is required for every pending ACK. */
    unsigned leased,owned,pending,publication_verified,phase,error;
    uint64_t wait_elapsed_us;
};
struct qpt_io {
    void *context;
    uint32_t bytes;
    uint32_t (*read32)(void *,uint32_t); /* MSGRAM offsets only */
    void (*write32)(void *,uint32_t,uint32_t); /* MSGRAM offsets only */
    void (*barrier)(void *); /* platform full device-write ordering barrier */
    void (*kick)(void *); /* only write 0 to APSS IPCC_SEND_ID 0x0040600c */
    uint64_t (*now_us)(void *);
    void (*delay_us)(void *,unsigned);
    int (*claim)(void *,const void *); /* global QMP lease, not a per-Wi-Fi lock */
    int (*owns)(void *,const void *);
    void (*release)(void *,const void *);
};
static inline int qpt_valid(const struct qpt_io *b)
{
    return b && b->bytes==QPT_MSGRAM_BYTES && b->read32 && b->write32 &&
        b->barrier && b->kick && b->now_us && b->delay_us &&
        b->claim && b->owns && b->release;
}
static inline uint32_t qpt_read(const struct qpt_io *b,struct qpt_state *s,uint32_t o)
{
    s->last_offset=o;s->last_value=b->read32(b->context,o);return s->last_value;
}
static inline int qpt_fail(struct qpt_state *s,unsigned error)
{
    s->error=error;
    if(s->owned)s->phase=QPT_UNCERTAIN;
    return (int)error;
}
static inline int qpt_geometry(const struct qpt_io *b,struct qpt_state *s,int fresh)
{
    if(qpt_read(b,s,0)!=UINT32_C(0x4d41494c) || qpt_read(b,s,4)!=1)return 0;
    uint32_t size=qpt_read(b,s,0x34),offset=qpt_read(b,s,0x38);
    uint32_t remote_size=qpt_read(b,s,0x1c),remote_offset=qpt_read(b,s,0x20);
    /* Reserve the descriptor and the AOP mailbox. A bounded HLOS mailbox
     * alone does not establish ownership of an overlapping remote buffer. */
    if(offset<0x3c || (offset&3) || (size&3) || size<8 ||
       offset>b->bytes || size>b->bytes-offset)return 0;
    if(remote_offset<0x3c || (remote_offset&3) || (remote_size&3) || remote_size<8 ||
       remote_offset>b->bytes || remote_size>b->bytes-remote_offset)return 0;
    if(offset<remote_offset+remote_size && remote_offset<offset+size)return 0;
    if(fresh) {
        s->offset=offset;s->size=size;s->remote_offset=remote_offset;s->remote_size=remote_size;return 1;
    }
    return offset==s->offset && size==s->size &&
        remote_offset==s->remote_offset && remote_size==s->remote_size;
}
static inline int qpt_links_up(const struct qpt_io *b,struct qpt_state *s)
{
    /* These are inherited, shared link fields: this transport never writes them. */
    static const uint32_t fields[]={0x0c,0x10,0x24,0x28};
    for(unsigned i=0;i<sizeof(fields)/sizeof(fields[0]);i++)
        if(qpt_read(b,s,fields[i])!=QPT_UP)return 0;
    return 1;
}
static inline int qpt_link_up(const struct qpt_io *b,struct qpt_state *s)
{
    return qpt_links_up(b,s) && qpt_read(b,s,0x14)==QPT_UP && qpt_read(b,s,0x18)==QPT_UP;
}
static inline int qpt_owns(const struct qpt_io *b,struct qpt_state *s)
{ return s->leased && b->owns(b->context,s); }
static inline int qpt_live(const struct qpt_io *b,struct qpt_state *s)
{
    return qpt_owns(b,s) && qpt_geometry(b,s,0) && qpt_link_up(b,s) &&
        qpt_read(b,s,0x2c)==QPT_UP && qpt_read(b,s,0x30)==QPT_UP;
}
static inline int qpt_wait_channel(const struct qpt_io *b,struct qpt_state *s,uint32_t expected)
{
    uint64_t start=b->now_us(b->context);
    for(unsigned polls=0;;polls++) {
        if(!qpt_owns(b,s))return qpt_fail(s,QPT_OWNER_LOST);
        if(!qpt_geometry(b,s,0) || !qpt_links_up(b,s) ||
           qpt_read(b,s,0x2c)!=expected)return qpt_fail(s,QPT_IO);
        uint32_t remote=qpt_read(b,s,0x14),remote_ack=qpt_read(b,s,0x18);
        if(remote_ack!=s->remote_ack || qpt_read(b,s,s->offset)!=0)return qpt_fail(s,QPT_OWNER_LOST);
        if(remote!=QPT_UP && remote!=QPT_DOWN)return qpt_fail(s,QPT_IO);
        uint32_t ack=qpt_read(b,s,0x30);
        if(ack!=QPT_UP && ack!=QPT_DOWN)return qpt_fail(s,QPT_IO);
        /* APSS owns UCORE_CH_STATE_ACK. AOP drops its own channel after our
         * close request; acknowledge that change rather than demanding UP.
         * On reopen, this is vendor qmp_open's remote-UP -> ACK-UP step.
         * Never acknowledge an unobserved remote transition or write links. */
        if(remote==expected && remote_ack!=expected) {
            s->remote_ack=expected;
            b->write32(b->context,0x18,expected);b->barrier(b->context);
            if(qpt_read(b,s,0x18)!=expected)return qpt_fail(s,QPT_IO);
            b->kick(b->context);continue;
        }
        s->wait_elapsed_us=b->now_us(b->context)-start;
        if(ack==expected && remote==expected && remote_ack==expected)return QPT_OK;
        /* Both elapsed time and a poll bound protect against a stalled clock. */
        if(s->wait_elapsed_us>=QPT_TIMEOUT_US || polls>=1000)return qpt_fail(s,QPT_TIMEOUT);
        b->delay_us(b->context,1000);
    }
}
static inline int qpt_open(const struct qpt_io *b,struct qpt_state *s)
{
    if(!qpt_valid(b) || !s)return QPT_ARGUMENT;
    if(s->leased || s->owned || s->pending)return QPT_BUSY;
    if(!b->claim(b->context,s))return QPT_BUSY;
    s->leased=1;s->phase=QPT_CLOSED;s->error=0;s->publication_verified=0;
    unsigned error=QPT_DESCRIPTOR;uint32_t remote=0;
    if(!qpt_geometry(b,s,1))goto before_claim;
    error=QPT_NOT_READY;if(!qpt_links_up(b,s))goto before_claim;
    error=QPT_BUSY;
    s->remote_ack=qpt_read(b,s,0x18);
    remote=qpt_read(b,s,0x14);
    if((s->remote_ack!=QPT_UP && s->remote_ack!=QPT_DOWN) ||
       (remote!=s->remote_ack && !(remote==QPT_UP && s->remote_ack==QPT_DOWN)))goto before_claim;
    /* AOP may reopen after a completed firmware/UEFI close while APSS's ACK
     * is still DOWN. The vendor qmp_open writes host UP, observes remote UP,
     * then acknowledges remote UP. This is a fresh open request, only when
     * both host state/ACK are DOWN and BOTH mailboxes are empty. Never clear
     * inherited payload or appropriate an already-open host channel. */
    /* Recheck just before changing the HLOS channel. No inherited message,
     * open channel, transitional handshake or geometry is appropriated. */
    for(unsigned i=0;i<2;i++) {
        if(!qpt_owns(b,s) || !qpt_geometry(b,s,0) || !qpt_links_up(b,s) ||
           qpt_read(b,s,0x14)!=remote || qpt_read(b,s,0x18)!=s->remote_ack ||
           qpt_read(b,s,0x2c)!=QPT_DOWN || qpt_read(b,s,0x30)!=QPT_DOWN ||
           qpt_read(b,s,s->offset)!=0 ||
           (remote!=s->remote_ack && qpt_read(b,s,s->remote_offset)!=0))goto before_claim;
    }
    s->owned=1;s->phase=QPT_OPENING;
    b->write32(b->context,0x2c,QPT_UP);b->barrier(b->context);
    if(qpt_read(b,s,0x2c)!=QPT_UP)return qpt_fail(s,QPT_IO);
    b->kick(b->context);
    if(qpt_wait_channel(b,s,QPT_UP))return (int)s->error;
    if(qpt_read(b,s,s->offset)!=0)return qpt_fail(s,QPT_OWNER_LOST);
    s->phase=QPT_READY;return QPT_OK;
before_claim:
    if(b->owns(b->context,s))b->release(b->context,s);
    s->leased=0;return qpt_fail(s,error);
}
/* A timed-out send keeps its lease, channel and nonzero payload length. This
 * function may be called later to observe consumption; it performs no stores. */
static inline int qpt_complete(const struct qpt_io *b,struct qpt_state *s)
{
    if(!qpt_valid(b) || !s || !s->owned || !s->pending)return QPT_ARGUMENT;
    /* Zero is only a consumption ACK after this host has observed the exact
     * published length. A dropped store or early zero before that proof must
     * retain the buffer/lease; subsequent zero reads cannot invent the proof. */
    if(!s->publication_verified)return qpt_fail(s,QPT_PUBLICATION);
    uint64_t start=b->now_us(b->context);
    for(unsigned polls=0;;polls++) {
        if(!qpt_live(b,s))return qpt_fail(s,QPT_OWNER_LOST);
        uint32_t length=qpt_read(b,s,s->offset);
        s->wait_elapsed_us=b->now_us(b->context)-start;
        if(!length) {
            s->pending=0;s->pending_bytes=0;s->phase=QPT_READY;s->error=0;return QPT_OK;
        }
        if(length!=s->pending_bytes)return qpt_fail(s,QPT_OWNER_LOST);
        if(s->wait_elapsed_us>=QPT_TIMEOUT_US || polls>=1000)return qpt_fail(s,QPT_TIMEOUT);
        b->delay_us(b->context,1000);
    }
}
static inline int qpt_send(const struct qpt_io *b,struct qpt_state *s,
                           const uint32_t *words,size_t bytes)
{
    if(!qpt_valid(b) || !s || !words || ((uintptr_t)words&3) || !bytes || (bytes&3))return QPT_ARGUMENT;
    if(!s->owned || s->pending || s->phase!=QPT_READY)return QPT_BUSY;
    if(s->size<8 || bytes>s->size-4u)return QPT_ARGUMENT;
    if(!qpt_live(b,s))return qpt_fail(s,QPT_OWNER_LOST);
    if(qpt_read(b,s,s->offset)!=0)return qpt_fail(s,QPT_OWNER_LOST);
    s->publication_verified=0;
    for(size_t i=0;i<bytes/4;i++)b->write32(b->context,s->offset+4+(uint32_t)i*4,words[i]);
    b->barrier(b->context);
    /* Verify the complete, still-unpublished payload with 32-bit reads. A
     * dropped data store must not become an acknowledged truncated command. */
    for(size_t i=0;i<bytes/4;i++)
        if(qpt_read(b,s,s->offset+4+(uint32_t)i*4)!=words[i])return qpt_fail(s,QPT_IO);
    if(!qpt_live(b,s) || qpt_read(b,s,s->offset)!=0)return qpt_fail(s,QPT_OWNER_LOST);
    /* Publication transfers buffer ownership to AOP. There is no cancellation
     * store: even a timeout or an unexpected descriptor must retain the data. */
    s->pending=1;s->pending_bytes=(uint32_t)bytes;s->phase=QPT_SENDING;
    b->write32(b->context,s->offset,(uint32_t)bytes);b->barrier(b->context);
    /* Unlike a mere posted-write flush, this proves publication. If AOP
     * consumed before the readback, fail conservatively instead of calling an
     * indistinguishable dropped length store a successful transfer. */
    if(qpt_read(b,s,s->offset)!=(uint32_t)bytes)return qpt_fail(s,QPT_PUBLICATION);
    s->publication_verified=1;
    b->kick(b->context);
    /* Zero length confirms transport consumption, never a regulator readback. */
    return qpt_complete(b,s);
}
static inline int qpt_close(const struct qpt_io *b,struct qpt_state *s)
{
    if(!qpt_valid(b) || !s)return QPT_ARGUMENT;
    if(!s->owned || s->pending || s->phase!=QPT_READY)return QPT_BUSY;
    if(!qpt_live(b,s) || qpt_read(b,s,s->offset)!=0)return qpt_fail(s,QPT_OWNER_LOST);
    s->phase=QPT_CLOSING;
    b->write32(b->context,0x2c,QPT_DOWN);b->barrier(b->context);
    if(qpt_read(b,s,0x2c)!=QPT_DOWN)return qpt_fail(s,QPT_IO);
    b->kick(b->context);
    if(qpt_wait_channel(b,s,QPT_DOWN))return (int)s->error;
    s->owned=0;s->leased=0;s->phase=QPT_CLOSED;s->error=0;s->publication_verified=0;
    b->release(b->context,s);return QPT_OK;
}
#endif
