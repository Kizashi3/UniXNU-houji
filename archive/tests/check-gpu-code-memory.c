// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "GpuScratchContext.h"
#include "vendor/ArmSmmu4K/ArmSmmu4KAudit.h"
static uint8_t *file(const char*path,size_t bytes){FILE*f=fopen(path,"rb");assert(f);uint8_t*p=malloc(bytes);assert(p && fread(p,1,bytes,f)==bytes && fgetc(f)==EOF);fclose(f);return p;}
struct audit {uint64_t *cpu,physical;};
static int descriptor(void*c,uint64_t pa,uint64_t*v){struct audit*m=c;if((pa&7)||pa<m->physical||pa-m->physical>=HSC_GPU_TABLE_PAGES*4096)return 1;*v=m->cpu[(pa-m->physical)/8];return 0;}
int main(int argc,char**argv){assert(argc==3);uint8_t*sqe=file(argv[1],HCC_SQE_BYTES),*aqe=file(argv[2],HCC_AQE_BYTES);void*arena;assert(!posix_memalign(&arena,4096,HCC_BYTES));unsigned cases=0;
 assert(!hcc_firmware(sqe,HCC_SQE_BYTES,0) && !hcc_firmware(aqe,HCC_AQE_BYTES,1) && !hcc_copy(arena,HCC_BYTES,sqe,HCC_SQE_BYTES,aqe,HCC_AQE_BYTES));cases++;
 assert(!memcmp((uint8_t*)arena+HCC_SQE_OFFSET,sqe+4,HCC_SQE_BYTES-4) && !memcmp((uint8_t*)arena+HCC_AQE_OFFSET,aqe+4,HCC_AQE_BYTES-4));cases++;
 for(unsigned type=0;type<2;type++){uint8_t*data=type?aqe:sqe;unsigned n=type?HCC_AQE_BYTES:HCC_SQE_BYTES;
  for(unsigned length=0;length<n;length++){assert(hcc_firmware(data,length,type));cases++;}
  for(unsigned at=0;at<n;at+=997){data[at]^=1;memset(arena,0xaa,HCC_BYTES);assert(hcc_copy(arena,HCC_BYTES,sqe,HCC_SQE_BYTES,aqe,HCC_AQE_BYTES));for(unsigned i=0;i<HCC_BYTES;i++)assert(((uint8_t*)arena)[i]==0xaa);data[at]^=1;cases++;}
 }
 memcpy(arena,sqe,HCC_SQE_BYTES);assert(hcc_copy(arena,HCC_BYTES,arena,HCC_SQE_BYTES,aqe,HCC_AQE_BYTES));cases++;
 uint64_t*t=calloc(HSC_GPU_TABLE_PAGES,4096);assert(t);ArmSmmu4KRange ranges[HSC_GPU_RANGES];
 assert(!hsc_pool_ranges(0x81000000,ranges) && !hsc_large_range(0x82000000,&ranges[4]) && !hsc_gpu_only_ranges(0x83000000,&ranges[5]) && !hcc_ranges(0x84000000,&ranges[HSC_DATA_RANGES]));
 ArmSmmu4KConfig cfg={32,36,0x80000000,HSC_GPU_LEAF_PAGES};ArmSmmu4KResult built;
 assert(!ArmSmmu4KBuild(&cfg,ranges,HSC_GPU_RANGES,t,HSC_GPU_TABLE_PAGES,&built) && built.table_pages==7 && built.leaf_pages==1567);cases++;
 struct audit m={t,cfg.table_physical};ArmSmmu4KTableIo io={&m,descriptor};unsigned char seen[7]={0};ArmSmmu4KAuditRegion region={ranges,HSC_GPU_RANGES,7,7*512,seen,7};ArmSmmu4KTableAuditResult result;
 assert(!ArmSmmu4KAuditTables(&io,&cfg,&built,&region,cfg.table_physical,&result) && result.complete);cases++;
 for(unsigned page=0;page<HCC_PAGES;page++){
  uint64_t address=HCC_IOVA+4096*page,table=cfg.table_physical,entry=0;unsigned present=0;
  for(unsigned level=1;level<=3;level++){unsigned index=(address>>(39-9*level))&(level==1?3u:511u);entry=t[(table-cfg.table_physical)/8+index];if(!(entry&1))break;table=entry&UINT64_C(0x0000fffffffff000);if(level==3)present=1;}
  unsigned code=(page>=1 && page<22)||(page>=33 && page<42),record=page==63;
  assert(present==(code||record));if(present){assert(table==0x84000000+4096*page && ((entry>>6)&3)==(code?3:0) && ((entry>>53)&3)==(code?0:3) && ((entry>>2)&7)==0);}cases++;
 }
 assert(hcc_ranges(UINT64_C(1)<<36,&ranges[9]) && hcc_ranges(0x84000001,&ranges[9]));cases++;
 free(t);free(arena);free(sqe);free(aqe);printf("PASS: %u actual own SQE/AQE cases; strict CRC/length, skip4 and full payload/padding readback, invalid input leaves arena intact, source alias rejected, full actual7table1567leaf audit, sparse ROX code and RW/NX record with guards unmapped\n",cases);
}
