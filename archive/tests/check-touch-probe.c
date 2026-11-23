// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdio.h>
#include "../native/touch/HoujiTouchProbe.h"
struct model {unsigned calls,se_reads,halted,fail_at;};
static int read32(void *context,uint32_t address,uint32_t *value) {
    struct model *m=context;assert(ht_probe_address_allowed(address));
    if(++m->calls==m->fail_at)return 0;
    if(address>=0xa90000 && address<0xa94000)m->se_reads++;
    *value=address==0x1183bc && m->halted?0x80000000:0;
    return 1;
}
int main(void) {
    struct ht_probe snapshot;struct model m={0};struct ht_probe_ops ops={&m,read32};
    assert(!ht_probe_address_allowed(0));assert(!ht_probe_address_allowed(0xf16c000)); // Ace 5 power GPIO108 is excluded.
    assert(!ht_probe_address_allowed(0xa00000)); // No GPI or SMMU access.
    assert(ht_probe_capture(&ops,&snapshot)==0 && m.calls==23 && m.se_reads==7);
    m=(struct model){.halted=1};assert(ht_probe_capture(&ops,&snapshot)==1 && m.se_reads==0 && m.calls==16);
    for(unsigned fail=1;fail<=23;fail++) {
        m=(struct model){.fail_at=fail};assert(ht_probe_capture(&ops,&snapshot)==2);
        assert(m.calls==fail && snapshot.completed_reads==fail-1);
    }
    assert(ht_probe_capture(NULL,&snapshot)==2);
    assert(ht_probe_capture(&ops,NULL)==2);
    puts("PASS: touch read whitelist, halted-clock SE exclusion, exact read count and all callback failures; no writes exist in probe API");
}
