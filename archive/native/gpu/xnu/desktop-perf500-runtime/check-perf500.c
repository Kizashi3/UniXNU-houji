#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "GpuDesktopPerfProfile.h"
int main(void){uint32_t a[HHP_PERF_WORDS],b[HHP_PERF_WORDS];assert(HHP_PERF_WORDS==58);assert(hup_perf(NULL));assert(!hhp_perf(a));assert(!hup_perf(b));for(unsigned i=0;i<HHP_PERF_WORDS;i++){uint32_t expected=i==0?3:i==8?0x00500305u:i==9?0xffffffffu:i==10?500000u:a[i];assert(b[i]==expected);}puts("PASS: actual 58-word PERF profile; only level-count and new500MHz GPU triplet differ; original GPU, GMU and padding preserved");}
