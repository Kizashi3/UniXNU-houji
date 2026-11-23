/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_GPU_DMA_MEMORY_H
#define HOUJI_GPU_DMA_MEMORY_H
#include "GpuSmmuPrepare.h"
struct hga_cpu_io {
  void *cookie;unsigned line_bytes;
  int (*invalidate_line)(void *,uintptr_t);
  int (*clean_line)(void *,uintptr_t);
  int (*barrier)(void *);
};
struct hga_cpu_result {unsigned invalidated,cleaned,barriers,verified,restored;uint32_t observed;};
/* Caller has reset the only master, detached its stream, disabled/synchronized
 * its bank, and owns these full cache lines. CPU has not written the data
 * since its initial clean. IVAC must discard stale CPU data, not write it
 * back over the device's marker. No reads occur until invalidation completes. */
static inline int hga_cpu_finish(const struct hga_cpu_io *io,const struct hgt_owned *o,
    struct hga_cpu_result *r) {
  if(!r)return 1;*r=(struct hga_cpu_result){0};
  if(!io || !io->invalidate_line || !io->clean_line || !io->barrier || !o || !o->data ||
     ((uintptr_t)o->data&4095) || (uintptr_t)o->data>UINTPTR_MAX-4096 ||
     io->line_bytes<16 || io->line_bytes>4096 || (io->line_bytes&(io->line_bytes-1)))return 1;
  if(io->barrier(io->cookie))return 1;r->barriers++;
  for(unsigned off=0;off<4096;off+=io->line_bytes) {
    if(io->invalidate_line(io->cookie,(uintptr_t)o->data+off))return 1;r->invalidated++;
  }
  if(io->barrier(io->cookie))return 1;r->barriers++;
  volatile uint32_t *data=o->data;r->observed=data[2];
  for(unsigned i=0;i<1024;i++) {
    uint32_t expected=i==0?0x7504cafeu:(i==1?0x86500071u:(i==2?0xa750cafeu:0));
    if(data[i]!=expected)return 1;
  }
  r->verified=1;data[2]=0;
  for(unsigned off=0;off<4096;off+=io->line_bytes) {
    if(io->clean_line(io->cookie,(uintptr_t)o->data+off))return 1;r->cleaned++;
  }
  if(io->barrier(io->cookie))return 1;r->barriers++;
  for(unsigned i=0;i<1024;i++) {
    uint32_t expected=i==0?0x7504cafeu:(i==1?0x86500071u:0);
    if(data[i]!=expected)return 1;
  }
  r->restored=1;return 0;
}
#endif
