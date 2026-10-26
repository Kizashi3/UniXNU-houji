/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef GIULIA_GPU_GUNYAH_REPORT_H
#define GIULIA_GPU_GUNYAH_REPORT_H
#if !defined(GGR_FIRMWARE_TYPES)
#include <stdint.h>
typedef uint32_t GGR_U32;
typedef uint64_t GGR_U64;
#else
typedef UINT32 GGR_U32;
typedef UINT64 GGR_U64;
#endif
#define GGR_REPORT_MAGIC 0x31524747u
#define GGR_REPORT_VERSION 1u
#define GGR_REPORT_BYTES 256u
#define GGR_REQUEST_CAPTURE 1u
#define GGR_SOURCE_BOOT_FDT 1u
#define GGR_MAX_FDT_BYTES (16u*1024u*1024u)
#define GGR_PROTOCOL_VERSION 1u
#define GGR_PROTOCOL_GUID {0x327e4dc8,0xfef7,0x4aeb,{0x90,0x5b,0x67,0x75,0x6e,0x79,0x61,0x68}}
enum { GGR_OK=0,GGR_ERR_ARGUMENT=1,GGR_ERR_FDT=2,GGR_ERR_RESOURCE=3,
    GGR_ERR_EPOCH=4 };
/* Current-boot FDT provenance only. Capability handles are not MMIO addresses.
 * Raw GIC SPI specifications are not registered interrupts or IRQ leases.
 * The boot-local epoch and CRC detect accidental reuse/corruption; they
 * authenticate neither a hypervisor nor any runtime channel/VM/memory owner.
 * This platform's counter starts at zero and may repeat after a cold boot.
 * No pointer, firmware handle, READY or lease bit crosses this boundary. */
struct ggr_report {
    GGR_U32 magic,version,bytes,request;
    GGR_U32 code,source,fdt_bytes,fdt_crc32;
    GGR_U64 epoch,tx_cap,rx_cap;
    GGR_U32 rm_node,gic_node,interrupt_parent,interrupt_cells;
    GGR_U32 tx_irq[3],rx_irq[3];
    GGR_U32 reserved[39];
    GGR_U32 crc32;
};
typedef char ggr_report_size_check[sizeof(struct ggr_report)==GGR_REPORT_BYTES?1:-1];
static inline GGR_U32 ggr_crc32(const void *data,unsigned bytes)
{
    const unsigned char *p=(const unsigned char *)data;GGR_U32 crc=0xffffffffu;
    for(unsigned i=0;i<bytes;i++) {
        crc^=p[i];for(unsigned j=0;j<8;j++)crc=(crc>>1)^(0xedb88320u&(0u-(crc&1u)));
    }
    return ~crc;
}
static inline void ggr_report_init(struct ggr_report *r)
{
    if(!r)return;
    for(unsigned i=0;i<sizeof(*r);i++)((unsigned char *)r)[i]=0;
    r->magic=GGR_REPORT_MAGIC;r->version=GGR_REPORT_VERSION;
    r->bytes=GGR_REPORT_BYTES;r->request=GGR_REQUEST_CAPTURE;
}
static inline void ggr_report_seal(struct ggr_report *r)
{if(r)r->crc32=ggr_crc32(r,GGR_REPORT_BYTES-4);}
static inline int ggr_report_requested(const struct ggr_report *r)
{
    if(!r)return 0;
    struct ggr_report expected;ggr_report_init(&expected);
    for(unsigned i=0;i<sizeof(expected);i++)
        if(((const unsigned char *)r)[i]!=((const unsigned char *)&expected)[i])return 0;
    return 1;
}
static inline int ggr_irq_valid(const GGR_U32 irq[3])
{return irq[0]==0 && irq[1]<988 && (irq[2]==1 || irq[2]==4);}
/* The actual EmbeddedMonotonicCounter returns its postincrement value, so
 * its first successful result is legitimately zero. Read at most twice to
 * obtain a nonzero local generation; never invent a fallback generation.
 * read returns exactly 1 on service success. Failed calls may change their
 * private output, but *out remains unchanged on every failed acquisition. */
static inline int ggr_boot_epoch(int (*read)(void *,GGR_U64 *),void *cookie,GGR_U64 *out)
{
    if(!read || !out)return 0;
    for(unsigned attempt=0;attempt<2;attempt++) {
        GGR_U64 value=0;
        if(read(cookie,&value)!=1)return 0;
        if(value){*out=value;return 1;}
    }
    return 0;
}
static inline int ggr_report_valid(const struct ggr_report *r)
{
    if(!r || r->magic!=GGR_REPORT_MAGIC || r->version!=GGR_REPORT_VERSION ||
       r->bytes!=GGR_REPORT_BYTES || r->request!=GGR_REQUEST_CAPTURE || r->code!=GGR_OK ||
       r->source!=GGR_SOURCE_BOOT_FDT || !r->epoch || r->fdt_bytes<72 ||
       r->fdt_bytes>GGR_MAX_FDT_BYTES || r->tx_cap==(GGR_U64)-1 ||
       r->rx_cap==(GGR_U64)-1 || r->tx_cap==r->rx_cap ||
       !r->interrupt_parent || r->interrupt_parent==0xffffffffu || r->interrupt_cells!=3 ||
       r->rm_node>=r->fdt_bytes || r->gic_node>=r->fdt_bytes ||
       r->rm_node==r->gic_node || (r->rm_node&3) || (r->gic_node&3) ||
       !ggr_irq_valid(r->tx_irq) || !ggr_irq_valid(r->rx_irq) ||
       r->tx_irq[1]==r->rx_irq[1] || r->crc32!=ggr_crc32(r,GGR_REPORT_BYTES-4))return 0;
    for(unsigned i=0;i<39;i++)if(r->reserved[i])return 0;
    return 1;
}
/* Implemented by GpuGunyah.c using the actual FdtLib property/node APIs.
 * Caller supplies an accessible immutable complete FDT and a fresh local boot
 * epoch. Failure never changes out. This function executes no HVC or IRQ I/O. */
#ifdef __cplusplus
extern "C" {
#endif
int ggr_fdt_capture(const void *,GGR_U32,GGR_U64,struct ggr_report *);
/* Validate ordinary, non-read-protected UEFI memory-map coverage only. This
 * does not create a CPU mapping, reserve storage or grant an RM/IRQ lease. */
int ggr_fdt_memory_covered(const void *,GGR_U32,GGR_U32,GGR_U64,GGR_U32);
#ifdef __cplusplus
}
#endif
#endif
