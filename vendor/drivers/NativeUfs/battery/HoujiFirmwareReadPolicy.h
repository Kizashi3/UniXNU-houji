// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef HOUJI_FIRMWARE_READ_POLICY_H
#define HOUJI_FIRMWARE_READ_POLICY_H
#include <stdint.h>
struct HoujiFirmwareReadGrant {unsigned active;uint64_t first,blocks;};
// A grant exists only under the transport lock for one firmware command.
// active 1: primary GPT metadata (LBA 1..5) and TEST UNIT READY on LUN 4.
// active 2: READ(10) wholly inside the already validated modem_a range.
static inline bool houjiUfsFirmwareCommandAllowed(const uint8_t *u,unsigned n,unsigned dir,
    uint32_t bytes,const HoujiFirmwareReadGrant &grant) {
    if(!u || n<32 || !grant.active || grant.active>2 || u[0]!=1 || u[2]!=4 ||
       u[3] || u[4] || u[5] || u[6] || u[7] || u[8] || u[9] || u[10] || u[11] ||
       bytes>131072 || (bytes&4095) || u[1]!=(bytes?0x40:0) || dir!=(bytes?2u:0u))return false;
    uint32_t transfer=(uint32_t(u[12])<<24)|(uint32_t(u[13])<<16)|(uint32_t(u[14])<<8)|u[15];
    if(transfer!=bytes)return false;
    const uint8_t *c=u+16;
    if(!bytes) {
        if(grant.active!=1)return false;
        for(unsigned i=0;i<16;i++)if(c[i])return false;
        return true;
    }
    if(c[0]!=0x28 || c[1] || c[6] || c[9])return false;
    for(unsigned i=10;i<16;i++)if(c[i])return false;
    uint64_t lba=(uint32_t(c[2])<<24)|(uint32_t(c[3])<<16)|(uint32_t(c[4])<<8)|c[5];
    unsigned blocks=(unsigned(c[7])<<8)|c[8];
    if(!blocks || blocks>32 || bytes!=blocks*4096u)return false;
    if(grant.active==1)return (lba==1 && blocks==1) || (lba==2 && blocks<=4);
    return grant.blocks && grant.first<=0xffffffffu && grant.blocks<=0x100000000ULL-grant.first &&
        lba>=grant.first && lba-grant.first<grant.blocks && blocks<=grant.blocks-(lba-grant.first);
}
#endif
