/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef HOUJI_DVFS_POLICY_H
#define HOUJI_DVFS_POLICY_H
#include <stdint.h>
/* Immediate rise; four genuinely low windows before falling. Holding the
 * current level must not clear the low-window count (ishtar fix 2033). */
static inline unsigned houjiDvfsChoose(const uint32_t *khz,unsigned n,unsigned cur,
 unsigned busy,unsigned floor,unsigned *low) {
 if(!n)return 0;
 if(cur>=n)cur=n-1;if(floor>=n)floor=n-1;if(busy>1000)busy=1000;
 unsigned want=n-1;
 if(busy<900){uint64_t need=(uint64_t)khz[cur]*busy*125/100000;
  want=floor;while(want+1<n && khz[want]<need)++want;}
 if(want>cur){*low=0;return want;}
 if(want==cur){*low=0;return cur;}
 if(++*low<4)return cur;
 *low=0;return want;
}
#endif
