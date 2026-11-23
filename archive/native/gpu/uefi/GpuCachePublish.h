/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Publish only the owned inactive native4K tables and diagnostic data to PoC.
 * This is CPU cache maintenance, not proof of a device DMA transaction.
 */
#ifndef HOUJI_GPU_CACHE_PUBLISH_H
#define HOUJI_GPU_CACHE_PUBLISH_H
#include "GpuSmmuPrepare.h"
enum { HGC_OK,HGC_ARGUMENT,HGC_VALIDATE,HGC_CONTENT,HGC_CLEAN,HGC_BARRIER };
struct hgc_io {
  void *cookie;
  int (*validate)(void *,uint64_t,void *,unsigned);
  int (*clean_line)(void *,uintptr_t);
  int (*barrier)(void *);
};
struct hgc_result {
  unsigned code,line_bytes,validated,cleaned_lines,barriers,audits;
  size_t descriptor_reads;
};
static inline int hgc_content(const struct hgt_owned *o,struct hgc_result *r) {
  unsigned char visited[3]={0};
  struct hgt_tables actual={o->tables,o->table_physical};
  ArmSmmu4KTableIo physical={&actual,hgt_read_descriptor};
  ArmSmmu4KAuditRegion region={&o->range,1,3,3*512,visited,sizeof(visited)};
  ArmSmmu4KTableAuditResult audit={0};
  unsigned status=ArmSmmu4KAuditTables(&physical,&o->config,&o->built,&region,
    o->built.root_physical,&audit);
  r->audits++;r->descriptor_reads+=audit.descriptor_reads;
  if(status || !audit.complete || audit.table_pages!=3 || audit.leaf_pages!=1)return 0;
  const volatile uint32_t *data=o->data;
  for(unsigned i=0;i<1024;i++) {
    uint32_t wanted=i==0?0x7504cafeu:(i==1?0x86500071u:0);
    if(data[i]!=wanted)return 0;
  }
  return 1;
}
static inline unsigned hgc_publish(const struct hgc_io *io,const struct hgt_owned *o,
    uint64_t ctr,struct hgc_result *r) {
  if(!r)return HGC_ARGUMENT;*r=(struct hgc_result){0};
  unsigned line=4u<<((ctr>>16)&15);r->line_bytes=line;
  if(!io || !io->validate || !io->clean_line || !io->barrier || !o ||
     !o->tables || !o->data || line<16 || line>4096 ||
     ((uintptr_t)o->tables&4095) || ((uintptr_t)o->data&4095) ||
     (uintptr_t)o->tables>UINTPTR_MAX-12288 || (uintptr_t)o->data>UINTPTR_MAX-4096 ||
     (o->table_physical&4095) || (o->data_physical&4095) ||
     o->table_physical>=(UINT64_C(1)<<36)-12288 ||
     o->data_physical>=(UINT64_C(1)<<36)-4096 ||
     (o->table_physical<o->data_physical+4096 && o->data_physical<o->table_physical+12288) ||
     ((uintptr_t)o->tables<(uintptr_t)o->data+4096 && (uintptr_t)o->data<(uintptr_t)o->tables+12288) ||
     o->config.input_bits!=32 || o->config.output_bits!=36 ||
     o->config.table_physical!=o->table_physical || o->config.leaf_budget!=1 ||
     o->built.table_pages!=3 || o->built.leaf_pages!=1 || o->built.start_level!=1 ||
     o->built.root_physical!=o->table_physical || o->built.upper_region || o->built.mair!=0xff44 ||
     o->range.iova!=UINT64_C(0x60000000) || o->range.physical!=o->data_physical ||
     o->range.bytes!=4096 || o->range.permissions!=(ArmSmmu4KRead|ArmSmmu4KWrite) ||
     o->range.writeback!=1 || o->range.shareability!=3)return r->code=HGC_ARGUMENT;
  if(io->validate(io->cookie,o->table_physical,o->tables,3) ||
     io->validate(io->cookie,o->data_physical,o->data,1))return r->code=HGC_VALIDATE;
  r->validated=3;
  if(!hgc_content(o,r))return r->code=HGC_CONTENT;
  for(unsigned range=0;range<2;range++) {
    uintptr_t start=(uintptr_t)(range?o->data:o->tables);
    unsigned bytes=range?4096:12288;
    // Page alignment and a checked power-of-two line size ensure that no
    // operation touches cache lines belonging to any other allocation.
    for(unsigned offset=0;offset<bytes;offset+=line) {
      if(io->clean_line(io->cookie,start+offset))return r->code=HGC_CLEAN;
      r->cleaned_lines++;
    }
  }
  if(io->barrier(io->cookie))return r->code=HGC_BARRIER;
  r->barriers=1;
  if(!hgc_content(o,r))return r->code=HGC_CONTENT;
  return HGC_OK;
}
#endif
