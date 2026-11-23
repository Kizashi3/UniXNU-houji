#include "ArmSmmu4KLive.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do{if(!(x)){fprintf(stderr,"line%d %s\n",__LINE__,#x);abort();}}while(0)
int main(void){unsigned cases=0;volatile uint64_t*t=aligned_alloc(16384,1028*4096);CHECK(t);ArmSmmu4KLiveArena a={{32,36,0x80000000,524288},0,0x80000000,0,t,1028,0,0};ArmSmmu4KLiveState s={0};ArmSmmu4KLiveResult r;ArmSmmu4KRange ranges[2]={{0x60000000,0x100000000,16384,3,0,3},{0x62000000,0x100008000,16384,3,0,3}};
 CHECK(!ArmSmmu4KLivePrepare(&a,&s));CHECK(s.tables.table_pages==1027 && !s.tables.leaf_pages);CHECK(!ArmSmmu4KLiveAudit(&a,&s,0,0,&r) && r.descriptor_reads==1027*512);++cases;
 ArmSmmu4KRange bad[2];memcpy(bad,ranges,sizeof bad);bad[0].physical=0x80000000;CHECK(ArmSmmu4KLiveSeedInactive(&a,&s,bad,2,&r)==ArmSmmu4KOverlap && !r.descriptor_writes && !s.poisoned);++cases;
 memcpy(bad,ranges,sizeof bad);bad[1].iova=bad[0].iova;CHECK(ArmSmmu4KLiveSeedInactive(&a,&s,bad,2,&r)==ArmSmmu4KOverlap && !r.descriptor_writes);++cases;
 memcpy(bad,ranges,sizeof bad);bad[1].iova=0x80000000;CHECK(ArmSmmu4KLiveSeedInactive(&a,&s,bad,2,&r)!=0 && !r.descriptor_writes);++cases;
 CHECK(!ArmSmmu4KLiveSeedInactive(&a,&s,ranges,2,&r) && r.complete && r.descriptor_writes==8 && s.tables.leaf_pages==8);CHECK(!ArmSmmu4KLiveAudit(&a,&s,ranges,2,&r));++cases;
 CHECK(ArmSmmu4KLiveSeedInactive(&a,&s,ranges,2,&r)!=0 && !r.descriptor_writes);++cases;
 t[0]^=4096;CHECK(ArmSmmu4KLiveAudit(&a,&s,ranges,2,&r)!=0 && !r.complete);++cases;
 free((void*)t);printf("PASS %u new inactive seeded-topology cases; actual 4K descriptors in owned CPU16K pool, no MMIO/GPU emulation\n",cases);return 0;}
