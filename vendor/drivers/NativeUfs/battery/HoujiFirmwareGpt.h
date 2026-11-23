/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Validate the primary GPT before granting read access to modem_a. No disk or
 * partition GUID is embedded. The caller supplies a 4 KiB header and bounded
 * entry array; this parser performs no I/O and never grants write access. */
#ifndef HOUJI_FIRMWARE_GPT_H
#define HOUJI_FIRMWARE_GPT_H
#include <stdint.h>
#include <stddef.h>
typedef struct {uint64_t first, blocks;} HoujiFirmwarePartition;
static inline uint32_t houji_fw_le32(const uint8_t *p) {
    return p[0] | (uint32_t)p[1]<<8 | (uint32_t)p[2]<<16 | (uint32_t)p[3]<<24;
}
static inline uint64_t houji_fw_le64(const uint8_t *p) {
    return houji_fw_le32(p) | (uint64_t)houji_fw_le32(p+4)<<32;
}
static inline uint32_t houji_fw_crc32(const uint8_t *p, size_t n, int header) {
    uint32_t c=~0u;
    for(size_t i=0;i<n;i++) {
        c^=header && i>=16 && i<20 ? 0 : p[i];
        for(unsigned b=0;b<8;b++)c=(c>>1)^(0xedb88320u & (0u-(c&1u)));
    }
    return ~c;
}
/* Return the number of bytes needed for the entry array, or zero. Only the
 * primary layout with 128-byte entries at LBA 2 is supported, bounded at 16K. */
static inline uint32_t houji_fw_gpt_bytes(const uint8_t *h, size_t bytes) {
    static const uint8_t magic[8]={'E','F','I',' ','P','A','R','T'};
    if(!h || bytes!=4096)return 0;
    for(unsigned i=0;i<8;i++)if(h[i]!=magic[i])return 0;
    uint32_t count=houji_fw_le32(h+80), size=houji_fw_le32(h+12);
    if(houji_fw_le32(h+8)!=0x10000 || size!=92 || houji_fw_le32(h+20) ||
       houji_fw_le64(h+24)!=1 || houji_fw_le64(h+72)!=2 ||
       !count || count>128 || houji_fw_le32(h+84)!=128 ||
       houji_fw_crc32(h,size,1)!=houji_fw_le32(h+16))return 0;
    uint64_t first=houji_fw_le64(h+40),last=houji_fw_le64(h+48),backup=houji_fw_le64(h+32);
    uint64_t array_blocks=((uint64_t)count*128+4095)/4096;
    if(first<2+array_blocks || first>last || backup>0xffffffffu ||
       last>=backup || backup-last<=array_blocks)return 0;
    return count*128;
}
static inline int houji_fw_gpt_partition(const uint8_t *h, const uint8_t *entries,
                                        size_t bytes, HoujiFirmwarePartition *out) {
    uint32_t need=houji_fw_gpt_bytes(h,4096);
    if(!need || !entries || !out || bytes!=need ||
       houji_fw_crc32(entries,bytes,0)!=houji_fw_le32(h+88))return 0;
    static const char name[]="modem_a";
    HoujiFirmwarePartition found={0,0};uint32_t selected=0;
    for(uint32_t i=0;i<need/128;i++) {
        const uint8_t *e=entries+i*128;
        unsigned used=0;for(unsigned b=0;b<16;b++)used|=e[b];
        if(!used)continue;
        unsigned match=1;
        for(unsigned c=0;c<36;c++)
            if(e[56+c*2]!=(c<sizeof(name)-1?(uint8_t)name[c]:0) || e[57+c*2])match=0;
        if(!match)continue;
        uint64_t first=houji_fw_le64(e+32),last=houji_fw_le64(e+40);
        if(found.blocks || first>last || first<houji_fw_le64(h+40) || last>houji_fw_le64(h+48))return 0;
        found.first=first;found.blocks=last-first+1;selected=i;
    }
    if(!found.blocks)return 0;
    /* A corrupt/overlapping directory cannot broaden the read grant. */
    for(uint32_t i=0;i<need/128;i++) {
        const uint8_t *e=entries+i*128;unsigned used=0;
        for(unsigned b=0;b<16;b++)used|=e[b];
        if(!used)continue;
        uint64_t first=houji_fw_le64(e+32),last=houji_fw_le64(e+40);
        if(first>last || first<houji_fw_le64(h+40) || last>houji_fw_le64(h+48))return 0;
        if(i==selected)continue;
        if(first<found.first+found.blocks && found.first<=last)return 0;
    }
    *out=found;return 1;
}
#endif
