#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "GpuPowerReport.h"
#include "HoujiTableCrc32.h"
static uint64_t rng=0x524185;
static uint32_t random32(void){rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;return (uint32_t)rng;}
int main(void){unsigned char *p=malloc(4*1024*1024+32);assert(p);for(unsigned i=0;i<4*1024*1024+32;i++)p[i]=random32();unsigned n=0;assert(houji_table_crc32(NULL,0)==0);assert(houji_table_crc32("123456789",9)==0xcbf43926);
for(unsigned off=0;off<16;off++)for(unsigned len=0;len<=257;len++){assert(gpp_crc32(p+off,len)==houji_table_crc32(p+off,len));n++;}
for(unsigned i=0;i<24;i++){unsigned len=i<8?(1u<<(i+9)):random32()%(4*1024*1024),off=random32()&15;assert(gpp_crc32(p+off,len)==houji_table_crc32(p+off,len));n++;}
assert(gpp_crc32(p,4*1024*1024)==houji_table_crc32(p,4*1024*1024));n++;free(p);printf("PASS %u CRC comparisons: original gpp_crc32, standard vector, empty/unaligned/boundary/random and actual4MiB length; ASAN/UBSAN; CPU-only check\n",n);}
