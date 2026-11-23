/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <assert.h>
#include <stdio.h>
#include "uefi/GpuLiveLog.h"
static unsigned tpl,guards,saves,lowers,restores,fail_guard,cases,lower_wrong,restore_wrong;
static uint64_t save_status;
static unsigned get_tpl(void*c){(void)c;return tpl;}
static void lower(void*c){(void)c;assert(tpl==16);lowers++;tpl=lower_wrong?8:4;}
static int restore(void*c){(void)c;restores++;tpl=restore_wrong?8:16;return (int)restore_wrong;}
static int guard(void*c){(void)c;guards++;return guards==fail_guard;}
static uint64_t save(void*c){(void)c;assert(tpl==4);saves++;return save_status;}
static void reset(void){tpl=16;guards=saves=lowers=restores=fail_guard=lower_wrong=restore_wrong=0;save_status=0;}
int main(void){const struct hll_io io={0,get_tpl,lower,restore,guard,save};struct hll_result result;
 reset();assert(!hll_run(&io,&result) && tpl==16 && saves==1 && result.restored && result.phase==5);cases++;
 for(unsigned t=0;t<32;t++)if(t!=16){reset();tpl=t;assert(hll_run(&io,&result)==HLL_TPL && !lowers && !saves && !restores);cases++;}
 for(unsigned g=1;g<=3;g++){reset();fail_guard=g;assert(hll_run(&io,&result)==HLL_GUARD && saves==(g==3) && restores==(g!=1) && tpl==16);cases++;}
 for(unsigned error=1;error<40;error++){reset();save_status=(UINT64_C(1)<<63)|error;assert(hll_run(&io,&result)==HLL_SAVE && restores==1 && tpl==16 && result.status==save_status);cases++;}
 reset();lower_wrong=1;assert(hll_run(&io,&result)==HLL_TPL && !saves && restores==1 && tpl==16);cases++;
 reset();restore_wrong=1;assert(hll_run(&io,&result)==HLL_RESTORE && !result.restored && result.after_tpl==8);cases++;
 reset();assert(hll_run(0,&result)==HLL_ARGUMENT && !lowers && !saves);cases++;
 printf("PASS: %u application-TPL-only checkpoint cases; pre/post guards, save errors, wrong TPL, unconditional restoration, no unsafe fallback\n",cases);
}
