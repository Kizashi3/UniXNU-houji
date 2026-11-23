/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/battery/HoujiSmemSurvey.h"
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/battery/QcomSmem.h"

static uint32_t memory[0x200000/4];
static unsigned char permitted[0x200000/4];
static unsigned denied,modify_at,header_reads;
static void put(uint32_t o,uint32_t v){memory[o/4]=v;}
static void allow(uint32_t o,uint32_t n){assert(!(o&3)&&!(n&3));memset(permitted+o/4,1,n/4);}
static int read32(void *context,uint32_t o,uint32_t *value){
    assert(context==memory);assert(!(o&3)&&o<sizeof memory);
    if(!permitted[o/4]){denied++;return 0;}
    if(o==0x1000c&&modify_at&&++header_reads==modify_at)memory[o/4]+=8;
    *value=memory[o/4];return 1;
}
static HoujiSmemReader reader(void){
    HoujiSmemReader r={read32,memory,sizeof memory,0,8192,0,0};return r;
}
static void fixture(void){
    memset(memory,0,sizeof memory);memset(permitted,0,sizeof permitted);
    denied=modify_at=header_reads=0;
    uint32_t toc=sizeof memory-4096;
    put(toc,0x434f5424);put(toc+4,1);put(toc+8,2);
    put(toc+32,0x10000);put(toc+36,0x10000);put(toc+44,2u<<16);put(toc+48,64);
    /* A foreign partition must not be read. Only its table entry is visible. */
    put(toc+80,0x80000);put(toc+84,0x40000);put(toc+92,3u<<16);put(toc+96,64);
    allow(toc,128);allow(0x10000,32);
    put(0x10000,0x54525024);put(0x10004,2u<<16);put(0x10008,0x10000);
    put(0x1000c,32);put(0x10010,0x10000);
    QcomSmem smem={(volatile uint8_t *)memory,sizeof memory};QcomSmemPartition part;
    assert(!qcom_smem_partition(&smem,0,2,&part));
    assert(!qcom_smem_alloc(&smem,&part,100,0x4000));
    assert(!qcom_smem_alloc(&smem,&part,443,340));
    assert(!qcom_smem_alloc(&smem,&part,478,32));
    allow(0x10020,16);allow(0x14030,16);allow(0x14198,16);
}
int main(void){
    fixture();HoujiSmemReader r=reader();HoujiSmemPart p;
    assert(!houji_smem_partition_ro(&r,0,2,&p));assert(p.offset==0x10000);
    uint32_t offset=0,size=0;
    assert(!houji_smem_item_ro(&r,&p,443,&offset,&size));assert(offset==0x14040&&size==340);
    assert(!houji_smem_item_ro(&r,&p,478,&offset,&size));assert(offset==0x141a8&&size==32);
    assert(houji_smem_item_ro(&r,&p,480,&offset,&size)==HoujiSmemMissing);
    assert(houji_smem_partition_ro(&r,0xfffe,0xfffe,&p)==HoujiSmemMissing);
    assert(denied==0&&r.reads<150);
    fixture();r=reader();put(sizeof memory-4096+8,85);
    assert(houji_smem_partition_ro(&r,0,2,&p)==HoujiSmemNoTable);
    fixture();r=reader();put(sizeof memory-4096+32,0xfffffff8);
    assert(houji_smem_partition_ro(&r,0,2,&p)==HoujiSmemInvalid&&denied==0);
    fixture();r=reader();put(sizeof memory-4096+48,0x80000000);
    assert(houji_smem_partition_ro(&r,0,2,&p)==HoujiSmemInvalid&&denied==0);
    fixture();r=reader();assert(!houji_smem_partition_ro(&r,0,2,&p));put(0x10024,0xfffffffc);
    assert(houji_smem_item_ro(&r,&p,443,&offset,&size)==HoujiSmemInvalid&&denied==0);
    fixture();r=reader();assert(!houji_smem_partition_ro(&r,0,2,&p));put(0x10028,1u<<16);
    assert(houji_smem_item_ro(&r,&p,443,&offset,&size)==HoujiSmemInvalid&&denied==0);
    fixture();r=reader();r.limit=4;
    assert(houji_smem_partition_ro(&r,0,2,&p)==HoujiSmemBudget&&r.reads==4&&denied==0);
    fixture();r=reader();modify_at=2;assert(!houji_smem_partition_ro(&r,0,2,&p));
    assert(houji_smem_item_ro(&r,&p,443,&offset,&size)==HoujiSmemChanged&&denied==0);
    fixture();r=reader();permitted[0x1ff000/4]=0;
    assert(houji_smem_partition_ro(&r,0,2,&p)==HoujiSmemReadFailed&&denied==1);
    /* Cached entry: payload immediately below its cacheline-sized header. */
    fixture();put(0x10010,0xff80);put(0x1ffc0,480u<<16|0xa5a5);put(0x1ffc4,64);put(0x1ffc8,0);
    allow(0x1ffc0,16);r=reader();assert(!houji_smem_partition_ro(&r,0,2,&p));
    assert(!houji_smem_item_ro(&r,&p,480,&offset,&size));assert(offset==0x1ff80&&size==64&&denied==0);
    put(0x1ffc4,0x10000);r=reader();
    assert(houji_smem_item_ro(&r,&p,480,&offset,&size)==HoujiSmemInvalid&&denied==0);
    puts("PASS: sparse SMEM metadata, foreign/payload exclusion, cached/uncached items, changed/corrupt bounds and read budget");
}
