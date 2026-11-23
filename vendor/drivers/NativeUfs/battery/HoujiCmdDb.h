/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Sparse cmd-db reader. Only reads aligned words in directory records, names,
 * and the requested resource. No whole carveout copy or foreign aux payload. */
#ifndef HOUJI_CMD_DB_H
#define HOUJI_CMD_DB_H
#include "QcomRpmh.h"
typedef struct {
    int (*read32)(void *,uint32_t,uint32_t *);
    void *context;
    uint32_t size,reads,last;
} HoujiCmdDb;
static int houji_cmd_word(HoujiCmdDb *r,uint32_t at,uint32_t *value) {
    if(!r || !r->read32 || (at&3) || r->size<4 || at>r->size-4 || r->reads>=8192)return 0;
    ++r->reads;r->last=at;return r->read32(r->context,at,value);
}
static int houji_cmd_bytes(HoujiCmdDb *r,uint32_t at,uint8_t *to,uint32_t bytes) {
    if(at>r->size || bytes>r->size-at)return 0;
    while(bytes) {
        uint32_t word=0,shift=at&3;
        if(!houji_cmd_word(r,at&~3u,&word))return 0;
        uint32_t n=4-shift;if(n>bytes)n=bytes;
        for(uint32_t i=0;i<n;i++)to[i]=(uint8_t)(word>>(8*(shift+i)));
        at+=n;to+=n;bytes-=n;
    }
    return 1;
}
static uint16_t houji_cmd_u16(const uint8_t *p) {return (uint16_t)(p[0]|(uint16_t)p[1]<<8);}
static uint32_t houji_cmd_u32(const uint8_t *p) {return houji_cmd_u16(p)|(uint32_t)houji_cmd_u16(p+2)<<16;}
static int houji_cmd_find(HoujiCmdDb *r,const char *name,QcomRpmhResource *out) {
    if(!r || !name || !out || r->size<144)return QcomRpmhArgument;
    uint32_t magic=0;uint8_t id[8]={0};
    if(!houji_cmd_word(r,4,&magic) || magic!=QCOM_CMD_DB_MAGIC)return QcomRpmhNoDb;
    unsigned namesize=0;while(namesize<8 && name[namesize]){id[namesize]=(uint8_t)name[namesize];++namesize;}
    if(!namesize || name[namesize])return QcomRpmhArgument;
    for(unsigned s=0;s<8;s++) {
        uint8_t slave[8];if(!houji_cmd_bytes(r,8+s*16,slave,8))return QcomRpmhCorrupt;
        if(!houji_cmd_u16(slave))break;
        uint32_t heads=144u+houji_cmd_u16(slave+2),data=144u+houji_cmd_u16(slave+4),count=houji_cmd_u16(slave+6);
        if((heads&3) || heads>r->size || count>(r->size-heads)/24 || data>r->size)return QcomRpmhCorrupt;
        for(unsigned e=0;e<count;e++) {
            uint8_t entry[24];uint32_t at=heads+24*e;
            if(!houji_cmd_bytes(r,at,entry,8))return QcomRpmhCorrupt;
            unsigned same=1;for(unsigned i=0;i<8;i++)if(entry[i]!=id[i])same=0;
            if(!same)continue;
            if(!houji_cmd_bytes(r,at+16,entry+16,8))return QcomRpmhCorrupt;
            uint32_t length=houji_cmd_u16(entry+20),aux=data+houji_cmd_u16(entry+22);
            if(length>32 || (length&1) || aux>r->size || length>r->size-aux)return QcomRpmhCorrupt;
            QcomRpmhResource value={0};value.address=houji_cmd_u32(entry+16);
            if(!value.address)return QcomRpmhCorrupt;
            uint8_t levels[32];if(!houji_cmd_bytes(r,aux,levels,length))return QcomRpmhCorrupt;
            for(unsigned i=0;i<length/2;i++) {
                uint16_t level=houji_cmd_u16(levels+i*2);
                if(i && !level)break;
                if(i && level<value.levels[i-1])return QcomRpmhCorrupt;
                value.levels[value.level_count++]=level;
            }
            *out=value;return QcomRpmhOk;
        }
    }
    return QcomRpmhMissing;
}
#endif
