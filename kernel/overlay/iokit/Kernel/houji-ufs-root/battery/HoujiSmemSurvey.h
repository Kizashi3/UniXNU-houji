/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Read-only SMEM metadata walker. Layout follows pinned QcomSmem.c; unrelated
 * partition bodies and item payloads are never read. No allocation or writes. */
#ifndef HOUJI_SMEM_SURVEY_H
#define HOUJI_SMEM_SURVEY_H
#include <stdint.h>

enum {HoujiSmemOk=0, HoujiSmemNoTable=-1, HoujiSmemMissing=-2,
      HoujiSmemInvalid=-3, HoujiSmemReadFailed=-4, HoujiSmemChanged=-5,
      HoujiSmemBudget=-6};
typedef int (*HoujiSmemRead32)(void *, uint32_t, uint32_t *);
typedef struct {
    HoujiSmemRead32 read;
    void *context;
    uint32_t size, reads, limit, last_offset;
    int error;
} HoujiSmemReader;
typedef struct {
    uint32_t offset, size, hosts, cacheline, uncached, cached;
} HoujiSmemPart;

static int houji_smem_read(HoujiSmemReader *r,uint32_t offset,uint32_t *value) {
    if(r->error)return 0;
    if(!r->read || !value || (offset&3) || r->size<4 || offset>r->size-4) {
        r->error=HoujiSmemInvalid;return 0;
    }
    if(r->reads>=r->limit){r->error=HoujiSmemBudget;return 0;}
    r->reads++;r->last_offset=offset;
    if(!r->read(r->context,offset,value)){r->error=HoujiSmemReadFailed;return 0;}
    return 1;
}
static int houji_smem_part_header(HoujiSmemReader *r,HoujiSmemPart *p) {
    uint32_t magic,hosts,size,uncached,cached;
    if(!houji_smem_read(r,p->offset,&magic) || !houji_smem_read(r,p->offset+4,&hosts) ||
       !houji_smem_read(r,p->offset+8,&size) || !houji_smem_read(r,p->offset+12,&uncached) ||
       !houji_smem_read(r,p->offset+16,&cached))return r->error;
    if(magic!=0x54525024u || hosts!=p->hosts || size!=p->size ||
       uncached<32 || uncached>cached || cached>size || (uncached&7) || (cached&3))
        return HoujiSmemInvalid;
    p->uncached=uncached;p->cached=cached;return HoujiSmemOk;
}
static int houji_smem_partition_ro(HoujiSmemReader *r,uint16_t host,uint16_t remote,HoujiSmemPart *out) {
    if(!r||!out||r->size<0x2000||(r->size&0xfff))return HoujiSmemNoTable;
    uint32_t toc=r->size-0x1000,magic,version,count;
    if(!houji_smem_read(r,toc,&magic)||!houji_smem_read(r,toc+4,&version)||
       !houji_smem_read(r,toc+8,&count))return r->error;
    if(magic!=0x434f5424u||version!=1||count>(0x1000u-32)/48)return HoujiSmemNoTable;
    for(uint32_t i=0;i<count;i++) {
        uint32_t e=toc+32+i*48,hosts,offset,size,line;
        if(!houji_smem_read(r,e+12,&hosts))return r->error;
        uint16_t h0=(uint16_t)hosts,h1=(uint16_t)(hosts>>16);
        if(!((h0==host&&h1==remote)||(h1==host&&h0==remote)))continue;
        if(!houji_smem_read(r,e,&offset)||!houji_smem_read(r,e+4,&size)||
           !houji_smem_read(r,e+16,&line))return r->error;
        if(!offset||!size)continue;
        if(offset>toc||size>toc-offset||size<64||(offset&7)||(size&3))return HoujiSmemInvalid;
        if(!line)line=8;
        if(line<8||line>size||(line&(line-1)))return HoujiSmemInvalid;
        HoujiSmemPart p={offset,size,hosts,line,0,0};
        int rc=houji_smem_part_header(r,&p);if(rc)return rc;
        uint32_t again;
        if(!houji_smem_read(r,toc+8,&again))return r->error;
        if(again!=count)return HoujiSmemChanged;
        *out=p;return HoujiSmemOk;
    }
    return HoujiSmemMissing;
}
static int houji_smem_same_header(HoujiSmemReader *r,const HoujiSmemPart *p) {
    HoujiSmemPart now=*p;int rc=houji_smem_part_header(r,&now);
    if(rc)return rc;
    return now.uncached==p->uncached&&now.cached==p->cached?HoujiSmemOk:HoujiSmemChanged;
}
static int houji_smem_item_ro(HoujiSmemReader *r,const HoujiSmemPart *p,uint16_t item,
                              uint32_t *offset,uint32_t *size) {
    if(!r||!p||!offset||!size||r->size<0x1000||p->offset>r->size-0x1000||
       p->size>r->size-0x1000-p->offset||p->size<64||(p->offset&7)||
       p->uncached<32||p->uncached>p->cached||p->cached>p->size||
       p->cacheline<8||p->cacheline>p->size||(p->cacheline&(p->cacheline-1)))return HoujiSmemInvalid;
    int rc=houji_smem_same_header(r,p);if(rc)return rc;
    uint32_t at=32;
    while(at<p->uncached) {
        uint32_t tag,bytes,pads;
        if((at&7)||p->uncached-at<16)return HoujiSmemInvalid;
        if(!houji_smem_read(r,p->offset+at,&tag)||!houji_smem_read(r,p->offset+at+4,&bytes)||
           !houji_smem_read(r,p->offset+at+8,&pads))return r->error;
        uint32_t pad_header=pads>>16,pad_data=pads&0xffff;
        uint64_t end=(uint64_t)at+16+pad_header+bytes;
        if((tag&0xffff)!=0xa5a5||pad_data>bytes||end>p->uncached||(end&7))return HoujiSmemInvalid;
        if((tag>>16)==item) {
            uint32_t data=p->offset+at+16+pad_header;
            if(data&3)return HoujiSmemInvalid;
            rc=houji_smem_same_header(r,p);if(rc)return rc;
            *offset=data;*size=bytes-pad_data;return HoujiSmemOk;
        }
        at=(uint32_t)end;
    }
    uint32_t header=(16+p->cacheline-1)&~(p->cacheline-1);
    if(header>p->size)return HoujiSmemInvalid;
    at=p->size-header;
    while(at>p->cached) {
        uint32_t tag,bytes,pads;
        if((at&3)||p->size-at<16)return HoujiSmemInvalid;
        if(!houji_smem_read(r,p->offset+at,&tag)||!houji_smem_read(r,p->offset+at+4,&bytes)||
           !houji_smem_read(r,p->offset+at+8,&pads))return r->error;
        if((tag&0xffff)!=0xa5a5||bytes>at-p->cached||(pads&0xffff)>bytes)return HoujiSmemInvalid;
        if((tag>>16)==item) {
            if((at-bytes)&3)return HoujiSmemInvalid;
            rc=houji_smem_same_header(r,p);if(rc)return rc;
            *offset=p->offset+at-bytes;*size=bytes-(pads&0xffff);return HoujiSmemOk;
        }
        if((uint64_t)bytes+header>at)return HoujiSmemInvalid;
        at-=bytes+header;
    }
    return HoujiSmemMissing;
}
#endif
