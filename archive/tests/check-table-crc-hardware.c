#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/auxv.h>
#include <time.h>
#define HOUJI_CRC_TEST_AVAILABLE ((getauxval(AT_HWCAP)&(1ul<<7))!=0)
#include "../native/gpu/xnu/hardware-crc-runtime/HoujiTableCrc32.h"
static uint64_t now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000ull+t.tv_nsec;}
int main(void){
 if(!HOUJI_CRC_TEST_AVAILABLE){puts("CRC hardware unavailable; no instruction executed");return 2;}
 const size_t size=4*1024*1024;unsigned char *p=malloc(size+128);if(!p)return 3;
 uint32_t seed=12345;for(size_t i=0;i<size+128;i++){seed=seed*1664525u+1013904223u;p[i]=(unsigned char)(seed>>24);}
 unsigned cases=0;for(size_t off=0;off<64;off++)for(size_t n=0;n<257;n++){
  if(houji_table_crc32(p+off,n)!=houji_table_crc32_software(p+off,n))return 4;cases++;
 }
 uint64_t hw=0,soft=0;volatile uint32_t sink=0;
 for(unsigned i=0;i<24;i++){
  p[(i*17011)%size]^=(unsigned char)(i+1);uint64_t t=now();uint32_t a=houji_table_crc32(p,size);hw+=now()-t;
  t=now();uint32_t b=houji_table_crc32_software(p,size);soft+=now()-t;if(a!=b)return 5;sink^=a;
 }
 printf("PASS cases=%u full_4MiB=24 hw-ns=%llu soft-ns=%llu ratio=%.3f checksum=%08x hwcap=%lx\n",cases,(unsigned long long)hw,(unsigned long long)soft,(double)soft/(double)hw,sink,getauxval(AT_HWCAP));free(p);return 0;
}
