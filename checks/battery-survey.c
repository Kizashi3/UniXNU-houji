// SPDX-License-Identifier: BSD-2-Clause-Patent
// Real SMEM parser fixtures; these do not emulate an ADSP or prove battery I/O.
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/battery/QcomSmem.h"
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/battery/QcomSmp2p.h"

static uint32_t words[0x4000/4], saved[0x4000/4];
static void put(unsigned at,uint32_t value){words[at/4]=value;}
int main(void){
  QcomSmem memory={(volatile uint8_t *)words,sizeof words};
  QcomSmemPartition part={};
  assert(qcom_smem_partition(&memory,0,2,&part)==QcomSmemNoTable);
  put(0x3000,0x434f5424);put(0x3004,1);put(0x3008,1);
  put(0x3020,0x1000);put(0x3024,0x1000);put(0x302c,2u<<16);put(0x3030,64);
  put(0x1000,0x54525024);put(0x1004,2u<<16);put(0x1008,0x1000);
  put(0x100c,32);put(0x1010,0x1000);
  assert(qcom_smem_partition(&memory,0,2,&part)==0);
  assert(qcom_smem_partition(&memory,2,0,&part)==0);
  assert(qcom_smem_partition(&memory,0,3,&part)==QcomSmemNoPartition);
  assert(qcom_smem_alloc(&memory,&part,443,QCOM_SMP2P_ITEM_BYTES)==0);
  uint32_t offset=0,size=0;
  assert(qcom_smem_find(&memory,&part,443,&offset,&size)==0);
  assert(size==QCOM_SMP2P_ITEM_BYTES);
  QcomSmp2p remote={0},view={0};
  qcom_smp2p_init_out(&remote,words+offset/4,2,0);
  int index=qcom_smp2p_add_entry(&remote,"slave-kernel");
  assert(index==0);assert(qcom_smp2p_update(&remote,index,7,6)==1);
  view.in=words+offset/4;
  memcpy(saved,words,sizeof words);
  assert(qcom_smp2p_check_in(view.in,0,2)==0);
  assert(qcom_smp2p_check_in(view.in,0,3)!=0);
  assert(qcom_smp2p_find_in(&view,"slave-kernel")==0);
  assert(qcom_smp2p_find_in(&view,"not-present")==-1);
  assert(qcom_smp2p_in_value(&view,0)==6);
  assert(qcom_smem_find(&memory,&part,480,&offset,&size)==QcomSmemMissing);
  assert(memcmp(saved,words,sizeof words)==0); // read paths never mutate the image
  put(0x3008,1000);assert(qcom_smem_partition(&memory,0,2,&part)==QcomSmemNoTable);
  memcpy(words,saved,sizeof words);put(0x3024,0xffffffff);
  assert(qcom_smem_partition(&memory,0,2,&part)==QcomSmemBadPartition);
  memcpy(words,saved,sizeof words);put(0x3030,3);
  assert(qcom_smem_partition(&memory,0,2,&part)==QcomSmemBadPartition);
  memcpy(words,saved,sizeof words);put(0x100c,0x1001);
  assert(qcom_smem_partition(&memory,0,2,&part)==QcomSmemBadPartition);
  memcpy(words,saved,sizeof words);assert(qcom_smem_partition(&memory,0,2,&part)==0);
  put(0x1020,0);assert(qcom_smem_find(&memory,&part,443,&offset,&size)==QcomSmemCorrupt);
  memcpy(words,saved,sizeof words);put(0x1024,0xfffffff0);
  assert(qcom_smem_find(&memory,&part,443,&offset,&size)==QcomSmemCorrupt);
  puts("PASS: SMEM/SMP2P survey fixtures, read-only paths and corrupt bounds; no hardware claim");
}
