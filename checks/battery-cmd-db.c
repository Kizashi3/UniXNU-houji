/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/battery/HoujiCmdDb.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint8_t memory[0x20000],allowed[0x20000];
static unsigned forbidden;
static int read_word(void *context,uint32_t at,uint32_t *out) {
    (void)context;assert(!(at&3) && at+4<=sizeof(memory));
    for(unsigned i=0;i<4;i++)if(!allowed[at+i]){++forbidden;return 0;}
    memcpy(out,memory+at,4);return 1;
}
static void word(unsigned at,uint32_t value) {memcpy(memory+at,&value,4);}
static void permit(unsigned at,unsigned n) {memset(allowed+at,1,n);}
static void fixture(void) {
    memset(memory,0,sizeof memory);memset(allowed,0,sizeof allowed);forbidden=0;
    word(4,QCOM_CMD_DB_MAGIC);permit(4,4);
    word(8,3);word(12,200u|(2u<<16));permit(8,8);permit(24,8);
    memcpy(memory+144,"foreign",7);permit(144,8);
    memcpy(memory+168,"lcx.lvl",7);permit(168,8);permit(184,8);
    word(184,0x30040);word(188,8);word(344,64u<<16);word(348,192u|(384u<<16));permit(344,8);
}
int main(void) {
    fixture();HoujiCmdDb db={read_word,0,sizeof memory,0,0};QcomRpmhResource r={0};
    assert(!houji_cmd_find(&db,"lcx.lvl",&r));assert(!forbidden && db.reads<30);
    assert(r.address==0x30040 && r.level_count==4 && r.levels[3]==384);
    uint32_t index=0;assert(!qcom_rpmh_level_index(&r,0xffffffffu,&index) && index==3);
    assert(houji_cmd_find(&db,"absent",&r)==QcomRpmhMissing && !forbidden);
    fixture();db.reads=0;word(188,33);assert(houji_cmd_find(&db,"lcx.lvl",&r)==QcomRpmhCorrupt && !forbidden);
    fixture();db.reads=0;word(188,8u|(0xffffu<<16));assert(houji_cmd_find(&db,"lcx.lvl",&r)==QcomRpmhCorrupt);
    fixture();db.reads=8192;assert(houji_cmd_find(&db,"lcx.lvl",&r)==QcomRpmhNoDb && !forbidden);
    fixture();db.reads=0;word(4,0);assert(houji_cmd_find(&db,"lcx.lvl",&r)==QcomRpmhNoDb);
    fixture();db.reads=0;word(348,32u|(384u<<16));assert(houji_cmd_find(&db,"lcx.lvl",&r)==QcomRpmhCorrupt);
    fixture();db.reads=0;db.size=350;assert(houji_cmd_find(&db,"lcx.lvl",&r)==QcomRpmhCorrupt);
    puts("battery sparse cmd-db: selected-resource reads, bounds, levels and budget PASS");
}
