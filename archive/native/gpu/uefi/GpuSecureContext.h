/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Fixed captured secure context, bank3/ASID753/SID2. No CPU secure-data access,
 * global writes, fault clearing, IRQ, CP, PAS or cleanup. Retain until reset.
 */
#ifndef HOUJI_GPU_SECURE_CONTEXT_H
#define HOUJI_GPU_SECURE_CONTEXT_H
#include "GpuScratchContext.h"
#include "GpuSecureMemory.h"
#define HSE_IOVA UINT32_C(0xf0000000)
enum { HSE_BYTES=0x37d000,HSE_PAGES=HSE_BYTES/4096,HSE_TABLE_PAGES=4 };
static inline int hse_request(const uint32_t *q,unsigned n) {
 return q && n==11 && (q[0]&0xfffffu)==0xb14 && q[1]==1 && !q[2] && !q[3] && q[4]==0x1007 &&
  q[5]==5 && !q[6] && q[7]==5 && !q[8] && q[9]==HSE_BYTES && !q[10];
}
static inline int hse_table_frame(const struct hsm_memory *memory,uint64_t table,struct ggs_regs *frame) {
 if(!hsm_valid_memory(memory) || !table || (table&16383) || table>=(UINT64_C(1)<<36) ||
  HSE_TABLE_PAGES*4096>(UINT64_C(1)<<36)-table ||
  (table<memory->data+HSM_BYTES && memory->data<table+HSE_TABLE_PAGES*4096) ||
  (table<memory->control+HSM_CONTROL_BYTES && memory->control<table+HSE_TABLE_PAGES*4096) ||
  hsm_assign_frame(memory,frame))return 1;
 uint64_t *c=memory->control_cpu;c[16]=table;c[17]=HSE_TABLE_PAGES*4096;c[2]=48;
 uint32_t *v=(uint32_t*)c;v[64]=3;v[65]=6;v[70]=10;v[71]=4;return 0;
}
static inline uint32_t hse_address(unsigned i) {
 const uint32_t a[]={0x3dc3000,0x3da180c,0x3da100c,0x3dc3010,0x3dc3030,
  0x3dc3020,0x3dc3028,0x3dc3038,0x3dc303c};return i<9?a[i]:0;
}
static inline int hse_survey(const struct hgp_io *io,struct hsc_result *r,unsigned active) {
 uint32_t v;if(io->power_guard(io->cookie))return 0;
 const uint32_t a[]={0x3da0020,0x3da0024,0x3da0028,0x3da0048},expected[]={0x4c017e18,0x40000016,0x5511,0};
 for(unsigned i=0;i<4;i++)if(!hsc_read(io,r,a[i],&v) || v!=expected[i])return 0;
 for(unsigned i=0;i<24;i++) {
  uint32_t smr=i==0?0x80000005u:i==1?0x80000000u:(active && i==2?0x80000002u:0);
  uint32_t route=i==0?2:i==1?0:(active && i==2?3:0x20000u);
  if(!hsc_read(io,r,0x3da0800+4*i,&v) || v!=smr || !hsc_read(io,r,0x3da0c00+4*i,&v) || v!=route)return 0;
 }
 for(unsigned i=0;i<22;i++) {
  if(!hsc_read(io,r,0x3dc0000+4096*i,&v))return 0;
  if(i==0 || i==2 || (active && i==3)){if((v&~0x1000u)!=0x27)return 0;}else if(v&1)return 0;
 }
 return hsc_read(io,r,0x3dc3058,&r->fsr) && !(r->fsr&0xc00001feu);
}
static inline unsigned hse_run(const struct hgp_io *io,const ArmSmmu4KConfig *cfg,const ArmSmmu4KResult *built,struct hsc_result *r) {
 if(!r)return HSC_ARGUMENT;*r=(struct hsc_result){.retained=1};
 if(!io || !io->read32 || !io->read64 || !io->write32 || !io->write64 || !io->delay || !io->power_guard ||
  !cfg || !built || cfg->input_bits!=32 || cfg->output_bits!=36 || built->root_physical!=cfg->table_physical ||
  built->table_pages!=HSE_TABLE_PAGES || built->leaf_pages!=HSE_PAGES)return r->code=HSC_ARGUMENT;
 ArmSmmu4KContextConfig c={cfg,0,built,0,0x4c017e18,0x5511,0x753,0,0,0};ArmSmmu4KContextImage image;
 if(ArmSmmu4KEncodeContext(&c,&image))return r->code=HSC_ARGUMENT;
#define HSE_REQUIRE(test,error) do {if(!(test))return r->code=(error);} while(0)
 uint32_t v;uint64_t wide;r->phase=1;HSE_REQUIRE(hse_survey(io,r,0),HSC_GUARD);
 HSE_REQUIRE(hsc_read(io,r,0x3dc3000,&v) && !(v&0x41) && hsc_read(io,r,0x3dc3004,&v) && v==3,HSC_GUARD);
 const uint64_t fields[]={0,image.cba2r,image.cbar,image.tcr2,image.tcr,image.ttbr0,image.ttbr1,image.mair0,image.mair1};
 r->phase=2;r->attempted=1;
 for(unsigned i=0;i<9;i++)HSE_REQUIRE(hsc_write(io,r,hse_address(i),fields[i],i==5 || i==6),HSC_IO);
 HSE_REQUIRE(hsc_write(io,r,0x3dc3004,0x32b,0) && hsc_write(io,r,0x3dc3618,0,0) && hsc_write(io,r,0x3dc37f0,0xffffffffu,0),HSC_IO);
 for(unsigned i=0;i<100;i++) {HSE_REQUIRE(hsc_read(io,r,0x3dc37f4,&v),HSC_IO);if(!(v&1))break;r->polls++;HSE_REQUIRE(i<99,HSC_TIMEOUT);HSE_REQUIRE(!io->delay(io->cookie,10),HSC_IO);}
 r->phase=3;
 for(unsigned i=0;i<9;i++) {
  if(i==5 || i==6) {
   r->last_address=hse_address(i);r->last_operation=1;r->observed_valid=0;r->reads++;
   HSE_REQUIRE(!io->read64(io->cookie,hse_address(i),&wide),HSC_IO);r->last_wide=wide;r->observed_valid=1;HSE_REQUIRE(wide==fields[i],HSC_VERIFY);
  } else HSE_REQUIRE(hsc_read(io,r,hse_address(i),&v) && (i==3?((v^(uint32_t)fields[i])&~0x60u)==0:v==fields[i]),HSC_VERIFY);
 }
 HSE_REQUIRE(hsc_read(io,r,0x3dc3004,&v) && v==0x32b && hse_survey(io,r,0),HSC_VERIFY);
 r->phase=4;HSE_REQUIRE(hsc_write(io,r,0x3dc3000,0x1027,0) && hsc_read(io,r,0x3dc3000,&v) && (v&~0x1000u)==0x27,HSC_VERIFY);r->enabled=1;
 HSE_REQUIRE(hsc_write(io,r,0x3da0c08,3,0) && hsc_write(io,r,0x3da0808,0x80000002u,0),HSC_IO);r->attached=1;
 r->phase=5;HSE_REQUIRE(hse_survey(io,r,1) && hsc_read(io,r,0x3dc3004,&v) && v==0x32b,HSC_VERIFY);return r->code;
#undef HSE_REQUIRE
}
#endif
