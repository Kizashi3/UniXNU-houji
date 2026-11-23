/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Fixed device-page policy: real recursive audit and descriptor transforms,
 * with only the physical table-view/CPU mapping boundary substituted.
 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../native/gpu/uefi/HoujiCpDeviceNgNrePolicy.h"

#define PAGES 1030u
static uint64_t tables[PAGES][512];
static uint64_t addresses[PAGES];
static unsigned count,views,deny_page,cases;
static const uint64_t flags=(UINT64_C(3)<<53)|(UINT64_C(3)<<8)|(UINT64_C(1)<<10)|
  (UINT64_C(1)<<11)|(UINT64_C(1)<<6)|(UINT64_C(1)<<5);
static const uint64_t tcr=UINT64_C(0x280803518);

static const uint64_t *view(void *cookie,uint64_t p) {
  (void)cookie;views++;
  for(unsigned i=0;i<count;i++)if(addresses[i]==p)return i==deny_page?NULL:tables[i];
  return NULL;
}
static void fresh(void) {
  memset(tables,0,sizeof tables);count=4;views=0;deny_page=UINT32_MAX;
  addresses[0]=UINT64_C(0xa7602000);addresses[1]=UINT64_C(0xa7603000);
  addresses[2]=UINT64_C(0xb8000000);addresses[3]=UINT64_C(0xb8001000);
  tables[0][0]=addresses[1]|3;
  tables[1][0]=flags|1;
}
static void split(void) {
  tables[1][0]=addresses[2]|3;
  for(unsigned i=0;i<512;i++)tables[2][i]=((uint64_t)i<<21)|flags|1;
  unsigned cp=(unsigned)(HCN_CP>>21);
  tables[2][cp]=addresses[3]|3;
  for(unsigned i=0;i<512;i++)tables[3][i]=((HCN_CP&~UINT64_C(0x1fffff))+4096*i)|flags|3;
  tables[3][(HCN_CP>>12)&511]|=HCN_INDEX4;
}
static unsigned audit(struct hcn_audit *a,unsigned after) {
  a->cookie=NULL;a->table=view;
  return hcn_audit_root(a,addresses[0],tcr,after);
}
static void regime_tests(void) {
  const uint64_t known[]={UINT64_C(0x80803520),UINT64_C(0x18080351c),
    UINT64_C(0x280803518),UINT64_C(0x380803516),UINT64_C(0x480803514),UINT64_C(0x580803510)};
  for(unsigned k=0;k<sizeof known/sizeof known[0];k++) {
    assert(hcn_known_regime(4,known[k],UINT64_C(0xa7602000),HCN_MAIR_BEFORE,0));
    assert(hcn_known_regime(4,known[k],UINT64_C(0xa7602000),HCN_MAIR_AFTER,1));cases++;
    for(unsigned bit=0;bit<64;bit++) {
      assert(!hcn_known_regime(4,known[k]^(UINT64_C(1)<<bit),UINT64_C(0xa7602000),HCN_MAIR_BEFORE,0));
      assert(!hcn_known_regime(4,known[k],UINT64_C(0xa7602000),HCN_MAIR_BEFORE^(UINT64_C(1)<<bit),0));
      cases++;
    }
  }
  for(unsigned el=0;el<16;el++)if(el!=4) {
    assert(!hcn_known_regime(el,tcr,UINT64_C(0xa7602000),HCN_MAIR_BEFORE,0));cases++;
  }
  const uint64_t roots[]={0,UINT64_C(0xa7602001),UINT64_C(0xa7602100),
    UINT64_C(0xa7000000),UINT64_C(0xa7100000),UINT64_C(0x10000a7602000),
    UINT64_C(0x10000000a7602000),UINT64_C(0xa7605000),UINT64_C(0xd3a00000)};
  for(unsigned i=0;i<sizeof roots/sizeof roots[0];i++) {
    assert(!hcn_known_regime(4,tcr,roots[i],HCN_MAIR_BEFORE,0));cases++;
  }
  const uint64_t owned[]={UINT64_C(0xa7602000),UINT64_C(0xa7604000),
    UINT64_C(0xa764d000),UINT64_C(0xa76d8000),UINT64_C(0xb8000000),UINT64_C(0xd39ff000)};
  for(unsigned i=0;i<sizeof owned/sizeof owned[0];i++) {
    assert(hcn_owned_table(owned[i]));assert(!hcn_owned_table(owned[i]+1));cases++;
  }
}
static void graph_tests(void) {
  struct hcn_audit *a=calloc(1,sizeof *a);assert(a);
  fresh();assert(!audit(a,0) && a->tables==2 && a->leaves==1 && a->target_level==1);
  uint64_t before=a->target_descriptor,n0=a->neighbor_descriptor[0],n1=a->neighbor_descriptor[1];
  split();assert(!audit(a,1) && a->tables==4 && a->leaves==1023 && a->target_level==3);
  assert(a->target_descriptor==hcn_cp_leaf(before));
  assert(hcn_normalized_leaf(n0,HCN_CP-4096)==hcn_normalized_leaf(a->neighbor_descriptor[0],HCN_CP-4096));
  assert(hcn_normalized_leaf(n1,HCN_CP+4096)==hcn_normalized_leaf(a->neighbor_descriptor[1],HCN_CP+4096));cases++;
  for(unsigned bit=0;bit<64;bit++) {
    uint64_t mask=UINT64_C(1)<<bit;
    if(mask&(HCN_ADDRESS|HCN_INDEX_MASK|3))continue;
    uint64_t changed=before^mask,after=hcn_cp_leaf(changed);
    assert((after&~(HCN_ADDRESS|HCN_INDEX_MASK|3))==(changed&~(HCN_ADDRESS|HCN_INDEX_MASK|3)));
    assert((after&HCN_ADDRESS)==HCN_CP && (after&HCN_INDEX_MASK)==HCN_INDEX4 && (after&3)==3);cases++;
  }
  fresh();tables[0][0]|=UINT64_C(1)<<4;assert(audit(a,0)==HCN_DESCRIPTOR);cases++;
  fresh();tables[0][0]=flags|1;assert(audit(a,0)==HCN_DESCRIPTOR);cases++;
  fresh();tables[0][0]=addresses[0]|3;assert(audit(a,0)==HCN_DUPLICATE);cases++;
  fresh();tables[0][1]=addresses[1]|3;assert(audit(a,0)==HCN_DUPLICATE);cases++;
  fresh();tables[0][0]=UINT64_C(0xa7100000)|3;assert(audit(a,0)==HCN_OWNER);cases++;
  fresh();deny_page=1;assert(audit(a,0)==HCN_OWNER && a->tables==1);cases++;
  fresh();tables[1][0]|=HCN_INDEX4;assert(audit(a,0)==HCN_INDEX_CONFLICT);cases++;
  fresh();tables[1][0]|=UINT64_C(1)<<52;assert(audit(a,0)==HCN_TARGET);cases++;
  fresh();tables[1][0]|=UINT64_C(1)<<51;assert(audit(a,0)==HCN_DESCRIPTOR);cases++;
  fresh();tables[1][0]|=4;assert(audit(a,0)==HCN_TARGET);cases++;
  fresh();tables[1][0]=UINT64_C(0x40000000)|flags|1;assert(audit(a,0)==HCN_DESCRIPTOR);cases++;
  fresh();tables[1][0]=0;assert(audit(a,0)==HCN_TARGET);cases++;
  fresh();split();assert(audit(a,0)==HCN_INDEX_CONFLICT);cases++;
  fresh();split();tables[3][(HCN_CP>>12)&511]&=~HCN_INDEX_MASK;assert(audit(a,1)==HCN_TARGET);cases++;
  fresh();split();tables[3][0]|=HCN_INDEX4;assert(audit(a,1)==HCN_INDEX_CONFLICT);cases++;
  fresh();split();tables[3][1]=(tables[3][1]&~UINT64_C(3))|1;assert(audit(a,1)==HCN_DESCRIPTOR);cases++;
  fresh();split();tables[3][0]=HCN_CP+flags+3;assert(audit(a,1)==HCN_DESCRIPTOR);cases++;
  // The entire active root, not just the CP path, must be checked. A second
  // root branch with an identity leaf using index4 must fail before MAIR.
  fresh();count=5;addresses[4]=UINT64_C(0xb8002000);tables[0][1]=addresses[4]|3;
  tables[4][0]=(UINT64_C(1)<<39)|flags|HCN_INDEX4|1;
  assert(audit(a,0)==HCN_INDEX_CONFLICT);cases++;
  // Root table has exactly two active entries at this TCR. Garbage in its
  // architecturally unused tail must neither be dereferenced nor reserved.
  fresh();tables[0][511]=UINT64_C(0xa7000000)|3;assert(!audit(a,0));cases++;
  // Bounded traversal refuses a hostile tree instead of looping or escaping
  // its preallocated visited storage, even if the CP target is not reached.
  fresh();count=PAGES;
  for(unsigned i=2;i<PAGES;i++)addresses[i]=UINT64_C(0xb8000000)+4096*(i-2);
  for(unsigned i=0;i<512;i++) {
    tables[1][i]=addresses[2+i]|3;
    tables[2+i][0]=addresses[514+i]|3;
  }
  assert(audit(a,0)==HCN_LIMIT && a->tables==HCN_MAX_TABLES);cases++;
  assert(hcn_audit_root(NULL,0,0,0)==HCN_ARGUMENT);
  a->table=NULL;assert(hcn_audit_root(a,0,0,0)==HCN_ARGUMENT);cases++;
  free(a);
}
int main(void) {
  regime_tests();graph_tests();
  printf("Fixed CP nGnRE policy: %u cases PASS; physical table/AT boundary substituted, no phone execution\n",cases);
  return 0;
}
