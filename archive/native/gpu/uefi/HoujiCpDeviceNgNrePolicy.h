/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Fixed houji CPU CP-page comparison. This policy audits the firmware-
 * controlled active identity table, not provenance of each allocation.
 */
#ifndef HOUJI_CP_DEVICE_NGNRE_POLICY_H
#define HOUJI_CP_DEVICE_NGNRE_POLICY_H
#include <stdint.h>
#include <stddef.h>
#define HCN_CP UINT64_C(0x03d02000)
#define HCN_BYTES UINT64_C(4096)
#define HCN_INDEX_MASK UINT64_C(0x1c)
#define HCN_INDEX4 UINT64_C(0x10)
#define HCN_ADDRESS UINT64_C(0x0000fffffffff000)
#define HCN_ATTRIBUTES ((UINT64_C(0xfff)<<52)|(UINT64_C(0x3ff)<<2))
#define HCN_MAIR_BEFORE UINT64_C(0x00000000ffbb4400)
#define HCN_MAIR_AFTER UINT64_C(0x00000004ffbb4400)
#define HCN_MAX_TABLES 1024u
enum {HCN_OK,HCN_ARGUMENT,HCN_REGIME,HCN_OWNER,HCN_DUPLICATE,HCN_DESCRIPTOR,
      HCN_INDEX_CONFLICT,HCN_TARGET,HCN_LIMIT};
struct hcn_audit {
  void *cookie;
  const uint64_t *(*table)(void *,uint64_t);
  uint64_t visited[HCN_MAX_TABLES];
  uint64_t target_descriptor;
  uint64_t neighbor_descriptor[2];
  unsigned neighbor_count[2];
  unsigned tables,leaves,target_level,target_count,allow_index4,code;
};
static inline int hcn_owned_table(uint64_t p) {
  if(p&4095)return 0;
  return (p>=UINT64_C(0xa7602000) && p<=UINT64_C(0xa7604000)) ||
    (p>=UINT64_C(0xa764d000) && p<=UINT64_C(0xa76d8000)) ||
    (p>=UINT64_C(0xb8000000) && p<=UINT64_C(0xd39ff000));
}
static inline int hcn_known_regime(uint64_t el,uint64_t tcr,uint64_t ttbr,
                                  uint64_t mair,unsigned after) {
  static const uint64_t known[]={UINT64_C(0x80803520),UINT64_C(0x18080351c),
    UINT64_C(0x280803518),UINT64_C(0x380803516),UINT64_C(0x480803514),
    UINT64_C(0x580803510)};
  if(el!=4 || (ttbr&~HCN_ADDRESS) || !hcn_owned_table(ttbr) ||
    mair!=(after?HCN_MAIR_AFTER:HCN_MAIR_BEFORE))return 0;
  for(unsigned i=0;i<sizeof(known)/sizeof(known[0]);i++)if(tcr==known[i])return 1;
  return 0;
}
static inline uint64_t hcn_cp_leaf(uint64_t before) {
  return (before&~(HCN_ADDRESS|HCN_INDEX_MASK|UINT64_C(3)))|HCN_CP|HCN_INDEX4|3;
}
static inline uint64_t hcn_normalized_leaf(uint64_t d,uint64_t address) {
  return (d&~(HCN_ADDRESS|UINT64_C(3)))|(address&HCN_ADDRESS)|3;
}
static inline unsigned hcn_walk(struct hcn_audit *a,uint64_t pa,uint64_t va,
                                unsigned level,unsigned entries) {
  if(!a || !a->table || level>3 || !entries || entries>512)return HCN_ARGUMENT;
  if(!hcn_owned_table(pa))return HCN_OWNER;
  if(a->tables==HCN_MAX_TABLES)return HCN_LIMIT;
  for(unsigned i=0;i<a->tables;i++)if(a->visited[i]==pa)return HCN_DUPLICATE;
  const uint64_t *p=a->table(a->cookie,pa);
  if(!p)return HCN_OWNER;
  a->visited[a->tables++]=pa;
  uint64_t span=UINT64_C(1)<<(12+9*(3-level));
  for(unsigned i=0;i<entries;i++) {
    uint64_t d=p[i],v=va+(uint64_t)i*span;
    if(!(d&1))continue;
    if(level<3 && (d&3)==3) {
      const uint64_t allowed_table=HCN_ADDRESS|UINT64_C(3)|(UINT64_C(0x1f)<<59);
      if(d&~allowed_table)return HCN_DESCRIPTOR;
      unsigned code=hcn_walk(a,d&HCN_ADDRESS,v,level+1,512);
      if(code)return code;
      continue;
    }
    if(level==0 || (level==3?(d&3)!=3:(d&3)!=1) ||
      (d&~(HCN_ADDRESS|HCN_ATTRIBUTES|UINT64_C(3))) ||
      ((d&HCN_ADDRESS)&(span-1)) || (d&HCN_ADDRESS)!=v)return HCN_DESCRIPTOR;
    unsigned index=(unsigned)((d&HCN_INDEX_MASK)>>2);
    if(index>3 && !(a->allow_index4 && index==4 && level==3 && v==HCN_CP))
      return HCN_INDEX_CONFLICT;
    a->leaves++;
    if(HCN_CP>=v && HCN_CP-v<span) {
      if(++a->target_count!=1 || (d&(UINT64_C(1)<<52)) ||
        (!a->allow_index4 && index!=0) || (a->allow_index4 && index!=4))return HCN_TARGET;
      a->target_descriptor=d;a->target_level=level;
    }
    for(unsigned n=0;n<2;n++) {
      uint64_t address=n?HCN_CP+4096:HCN_CP-4096;
      if(address>=v && address-v<span) {
        if(++a->neighbor_count[n]!=1)return HCN_TARGET;
        a->neighbor_descriptor[n]=d;
      }
    }
  }
  return HCN_OK;
}
static inline unsigned hcn_audit_root(struct hcn_audit *a,uint64_t root,uint64_t tcr,
                                      unsigned after) {
  if(!a || !a->table)return HCN_ARGUMENT;
  unsigned t0sz=(unsigned)(tcr&63);
  if(t0sz<16 || t0sz>32)return HCN_REGIME;
  a->tables=a->leaves=a->target_level=a->target_count=0;
  a->neighbor_count[0]=a->neighbor_count[1]=0;
  a->neighbor_descriptor[0]=a->neighbor_descriptor[1]=0;
  a->target_descriptor=0;a->allow_index4=after;
  a->code=hcn_walk(a,root,0,(t0sz-16)/9,512u>>((t0sz-16)%9));
  if(!a->code && (a->target_count!=1 || a->neighbor_count[0]!=1 || a->neighbor_count[1]!=1))
    a->code=HCN_TARGET;
  return a->code;
}
#endif
