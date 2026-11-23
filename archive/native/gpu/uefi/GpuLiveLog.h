/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Pre-CP canary only: allow one application-TPL file snapshot under an explicit
 * live-GMU/empty-queues/no-CP memory-isolation owner. Always restore worker TPL.
 */
#ifndef HOUJI_GPU_LIVE_LOG_H
#define HOUJI_GPU_LIVE_LOG_H
#include <stdint.h>
#ifndef HOUJI_CALL_TRACE
#define HOUJI_CALL_TRACE(step,address,value) ((void)0)
#endif
enum {HLL_OK,HLL_ARGUMENT,HLL_TPL,HLL_GUARD,HLL_SAVE,HLL_RESTORE};
struct hll_result {unsigned code,phase,lowered,restored,guards,before_tpl,after_tpl;uint64_t status;};
struct hll_io {void *cookie;unsigned (*tpl)(void *);void (*lower)(void *);int (*restore)(void *);int (*guard)(void *);uint64_t (*save)(void *);};
static inline unsigned hll_run(const struct hll_io *io,struct hll_result *r) {
 HOUJI_CALL_TRACE(0x1000,0,0);
 if(!r) {HOUJI_CALL_TRACE(0x1001,0,HLL_ARGUMENT);return HLL_ARGUMENT;}
 *r=(struct hll_result){0};
 if(!io || !io->tpl || !io->lower || !io->restore || !io->guard || !io->save) {
  r->code=HLL_ARGUMENT;HOUJI_CALL_TRACE(0x1001,r->phase,r->code);return r->code;
 }
 r->phase=1;HOUJI_CALL_TRACE(0x1002,0,r->phase);
 r->before_tpl=io->tpl(io->cookie);HOUJI_CALL_TRACE(0x1003,0,r->before_tpl);
 if(r->before_tpl!=16) {r->code=HLL_TPL;HOUJI_CALL_TRACE(0x1001,r->phase,r->code);return r->code;}
 r->guards++;HOUJI_CALL_TRACE(0x1004,0,r->guards);
 int guard=io->guard(io->cookie);HOUJI_CALL_TRACE(0x1005,0,guard);
 if(guard) {r->code=HLL_GUARD;HOUJI_CALL_TRACE(0x1001,r->phase,r->code);return r->code;}
 r->phase=2;HOUJI_CALL_TRACE(0x1006,0,r->phase);
 io->lower(io->cookie);HOUJI_CALL_TRACE(0x1007,0,0);r->lowered=1;
 HOUJI_CALL_TRACE(0x1008,0,r->phase);
 unsigned lowered_tpl=io->tpl(io->cookie);HOUJI_CALL_TRACE(0x1009,0,lowered_tpl);
 if(lowered_tpl!=4)r->code=HLL_TPL;
 else {
  r->guards++;HOUJI_CALL_TRACE(0x100a,0,r->guards);
  guard=io->guard(io->cookie);HOUJI_CALL_TRACE(0x100b,0,guard);
  if(guard)r->code=HLL_GUARD;
  else {
   r->phase=3;HOUJI_CALL_TRACE(0x100c,0,r->phase);
   r->status=io->save(io->cookie);HOUJI_CALL_TRACE(0x100d,0,r->status);
   if(r->status>>63)r->code=HLL_SAVE;
  }
 }
 r->phase=4;HOUJI_CALL_TRACE(0x100e,0,r->phase);
 int restored=io->restore(io->cookie);HOUJI_CALL_TRACE(0x100f,0,restored);
 HOUJI_CALL_TRACE(0x1010,0,r->phase);
 r->after_tpl=io->tpl(io->cookie);HOUJI_CALL_TRACE(0x1011,0,r->after_tpl);
 if(restored || r->after_tpl!=16) {r->code=HLL_RESTORE;HOUJI_CALL_TRACE(0x1001,r->phase,r->code);return r->code;}
 r->restored=1;r->guards++;HOUJI_CALL_TRACE(0x1012,0,r->guards);
 guard=io->guard(io->cookie);HOUJI_CALL_TRACE(0x1013,0,guard);
 if(guard)r->code=HLL_GUARD;
 r->phase=5;HOUJI_CALL_TRACE(0x1001,r->phase,r->code);return r->code;
}
#endif
