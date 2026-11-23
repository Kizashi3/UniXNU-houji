/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Fixed secure-context backing ownership diagnostic. INFO queries plus one
 * HLOS -> CP_PIXEL assignment of a private 4MiB allocation; no GPU mapping,
 * firmware ACK, data access after revocation, PAS or command submission.
 */
#ifndef HOUJI_GPU_SECURE_MEMORY_H
#define HOUJI_GPU_SECURE_MEMORY_H
#include "vendor/Ace5Gmu/giulia_gpu_scm.h"
enum { HSM_BYTES=0x400000,HSM_CONTROL_BYTES=0x4000,HSM_QUERY_COUNT=6 };
enum { HSM_OK,HSM_ARGUMENT,HSM_GUARD,HSM_QUERY,HSM_PREPARE,HSM_REVOKE,HSM_ASSIGN,HSM_CHECKPOINT };
struct hsm_memory {uint64_t data,control;void *control_cpu;};
struct hsm_result {
 unsigned code,phase,queried,available,prepared,revoked,attempted,owned,retained;
 unsigned calls,result_valid;uint64_t status_a0,status_a1;struct hsm_memory memory;
};
struct hsm_io {
 struct ggs_ops scm;
 int (*prepare)(void *,struct hsm_memory *);
 int (*revoke)(void *,const struct hsm_memory *);
 int (*publish)(void *,const struct hsm_memory *);
 int (*checkpoint)(void *,const struct hsm_result *);
};
static inline uint32_t hsm_query_id(unsigned index) {
 const uint32_t ids[]={0x02000c16,0x02000c1b,0x02000201,0x02000202,0x02000205,0x02000206};
 return index<HSM_QUERY_COUNT?ids[index]:0;
}
static inline int hsm_valid_memory(const struct hsm_memory *m) {
 if(!m || !m->data || !m->control || !m->control_cpu || (m->data&65535) || (m->control&16383) ||
    ((uintptr_t)m->control_cpu&16383) || (uintptr_t)m->control_cpu>UINTPTR_MAX-HSM_CONTROL_BYTES || m->data>=(UINT64_C(1)<<36) || HSM_BYTES>(UINT64_C(1)<<36)-m->data ||
    m->control>=(UINT64_C(1)<<36) || HSM_CONTROL_BYTES>(UINT64_C(1)<<36)-m->control)return 0;
 return !(m->data<m->control+HSM_CONTROL_BYTES && m->control<m->data+HSM_BYTES);
}
/* Independent fixed little-endian ABI: 7 arguments; 3 read-only descriptor
 * buffers. Extended args[3..9] at control+0, region+128, source+192, dest+256.
 * No CPU data pointer is accepted or dereferenced by this encoder. */
static inline int hsm_assign_frame(const struct hsm_memory *m,struct ggs_regs *frame) {
 if(!frame || !hsm_valid_memory(m))return 1;
 uint64_t *control=m->control_cpu;for(unsigned i=0;i<HSM_CONTROL_BYTES/8;i++)control[i]=0;
 control[16]=m->data;control[17]=HSM_BYTES;((uint32_t *)control)[48]=3;
 ((uint32_t *)control)[64]=10;((uint32_t *)control)[65]=6;
 control[0]=4;control[1]=m->control+256;control[2]=24;
 *frame=(struct ggs_regs){{0x42000c16,0x1117,m->control+128,16,m->control+192,m->control,0,0}};return 0;
}
static inline unsigned hsm_run(const struct hsm_io *io,struct ggs_state *scm,struct hsm_result *r) {
 if(!r)return HSM_ARGUMENT;*r=(struct hsm_result){0};r->retained=1;
 if(!io || !scm || !io->scm.call || !io->scm.delay_ms || !io->scm.prerequisites || !io->prepare ||
    !io->revoke || !io->publish || !io->checkpoint)return r->code=HSM_ARGUMENT;
#define HSM_REQUIRE(test,error) do {if(!(test))return r->code=(error);} while(0)
 HSM_REQUIRE(scm->convention_verified && scm->init_succeeded && !scm->quarantined &&
  io->scm.prerequisites(io->scm.cookie,GGS_INIT)==1,HSM_GUARD);
 unsigned start_calls=scm->calls;r->phase=1;
 for(unsigned i=0;i<HSM_QUERY_COUNT;i++) {
  HSM_REQUIRE(io->scm.prerequisites(io->scm.cookie,GGS_INIT)==1,HSM_GUARD);
  int code=ggs_exchange(&io->scm,scm,0x42000601,hsm_query_id(i));r->calls=scm->calls-start_calls;
  r->status_a0=scm->last_output.x[0];r->status_a1=scm->last_output.x[1];r->result_valid=code!=GGS_TRANSPORT && code!=GGS_QUARANTINED;HSM_REQUIRE(!code,HSM_QUERY);
  r->queried|=1u<<i;if(scm->last_output.x[1])r->available|=1u<<i;
 }
 // PAS/aperture results are diagnostic only. Assignment itself must exist.
 HSM_REQUIRE(r->available&1,HSM_QUERY);r->phase=2;
 HSM_REQUIRE(!io->prepare(io->scm.cookie,&r->memory) && hsm_valid_memory(&r->memory),HSM_PREPARE);r->prepared=1;
 struct ggs_regs frame;HSM_REQUIRE(!hsm_assign_frame(&r->memory,&frame) && !io->publish(io->scm.cookie,&r->memory),HSM_PREPARE);
 r->phase=3;HSM_REQUIRE(!io->revoke(io->scm.cookie,&r->memory),HSM_REVOKE);r->revoked=1;
 HSM_REQUIRE(io->scm.prerequisites(io->scm.cookie,GGS_INIT)==1,HSM_GUARD);
 HSM_REQUIRE(!io->checkpoint(io->scm.cookie,r),HSM_CHECKPOINT);
 r->phase=4;r->attempted=1;
 int code=ggs_exchange_frame(&io->scm,scm,&frame);r->calls=scm->calls-start_calls;r->status_a0=scm->last_output.x[0];r->status_a1=scm->last_output.x[1];r->result_valid=code!=GGS_TRANSPORT && code!=GGS_QUARANTINED;
 HSM_REQUIRE(!code && !scm->last_output.x[1],HSM_ASSIGN);r->owned=1;r->phase=5;
 HSM_REQUIRE(!io->checkpoint(io->scm.cookie,r),HSM_CHECKPOINT);return HSM_OK;
#undef HSM_REQUIRE
}
#endif
