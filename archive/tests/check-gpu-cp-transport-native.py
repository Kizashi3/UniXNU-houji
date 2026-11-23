#!/usr/bin/env python3
"""Actual native first-RAW transport, no gated reads after queue publication."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1]
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "GpuCpInit.h"
#include "GpuLiveLog.h"
#define STATIC static
#define VOID void
#define CONST const
#define Print(...) ((void)0)
#define HCI_GPU_ERROR_MASK 0x03400042u
#define GGH_INVALID 3
static struct hci_result mCpInit;
static struct hll_result mCpPreflightLog;
static unsigned mCpPollArmed=1,mCpPreflightValid=1,mCpIrqMask=HCI_GPU_ERROR_MASK,mCpGicMapped=1;
static struct {unsigned failed;}mCpPoll;
static unsigned owned=1,pre_bad,hw_checks,ram_checks,ram_fail,send_calls,doorbells,receives,delays,mode;
static int CpPolledHealthy(void*);static int CpLeaseOwned(void);
static int CpPreflightGuard(void*);static int CpReuseAperture(void*);static int CpPolledReady(void*);
static int CpRead(void*,uint32_t,uint32_t*);static int ContextDelay(void*,unsigned);
static int StockBootstrapSend(void*,const uint32_t*,unsigned);
static int StockBootstrapDoorbell(void*);static int StockBootstrapReceive(void*,unsigned,uint32_t*,unsigned*);
#include "GpuCpTransportNative.h"
static int CpPolledHealthy(void*c){(void)c;assert(!mCpTransport.published);hw_checks++;return !pre_bad;}
static int CpLeaseOwned(void){ram_checks++;return owned && ram_checks!=ram_fail;}
static int CpPreflightGuard(void*c){return !CpPolledHealthy(c);}
static int CpReuseAperture(void*c){return !CpPolledHealthy(c);}
static int CpPolledReady(void*c){return !CpPolledHealthy(c);}
static int CpRead(void*c,uint32_t a,uint32_t*v){(void)c;(void)a;(void)v;assert(0);return 1;}
static int ContextDelay(void*c,unsigned u){(void)c;assert(mCpTransport.published && u==10);delays++;return 0;}
static int StockBootstrapSend(void*c,const uint32_t*w,unsigned n){(void)c;assert(mCpTransport.published && n==11 && w[0]==0x1700b83u);for(unsigned i=0;i<10;i++)assert(w[i+1]==hci_cp_word(i));send_calls++;return mode==4;}
static int StockBootstrapDoorbell(void*c){(void)c;assert(mCpTransport.published && send_calls==1);doorbells++;return mode==5;}
static int StockBootstrapReceive(void*c,unsigned q,uint32_t*w,unsigned*n){(void)c;assert(mCpTransport.published && doorbells==1);receives++;*n=0;if(mode==3)return 1;if(mode==6)return 3;if(mode==7 && receives==1){*n=2;w[0]=0x202;w[1]=0x1234;return 0;}if(mode==8 && (receives&1)){*n=1;w[0]=0x102;return 0;}assert(q==1 || q==2);*n=3;w[0]=0x10383;w[1]=mCpInit.raw.record[0].header;w[2]=mode==1?UINT32_MAX:0;if(mode==2)w[1]^=1;return 0;}
static void reset(void){memset(&mCpTransport,0,sizeof mCpTransport);memset(&mCpInit,0,sizeof mCpInit);mCpInit.phase=2;mCpPreflightLog=(struct hll_result){.phase=5,.restored=1};mCpPollArmed=mCpPreflightValid=mCpGicMapped=owned=1;mCpIrqMask=HCI_GPU_ERROR_MASK;mCpPoll.failed=pre_bad=hw_checks=ram_checks=ram_fail=send_calls=doorbells=receives=delays=mode=0;}
int main(void){unsigned cases=0;struct hhb_result b;reset();b=(struct hhb_result){.next_sequence=23};assert(!RunCpTransport(&b));unsigned total=ram_checks;assert(total>=4 && b.next_sequence==24 && mCpInit.phase==3 && mCpInit.raw.record[0].ack && !mCpInit.idle && !mCpInit.reads && hw_checks==4 && send_calls==1 && doorbells==1 && !delays);cases++;
 for(unsigned i=1;i<=8;i++){reset();b=(struct hhb_result){.next_sequence=23};mode=i;assert(RunCpTransport(&b));assert(b.next_sequence==24 && mCpInit.phase==3 && !mCpInit.idle && !mCpInit.reads && send_calls==1 && hw_checks==4);if(i==3)assert(delays==20000);if(i==4)assert(!doorbells && !receives);cases++;}
 for(unsigned i=1;i<=total;i++){reset();b=(struct hhb_result){.next_sequence=23};ram_fail=i;assert(RunCpTransport(&b) && !mCpInit.idle && !mCpInit.reads && hw_checks==4 && send_calls==1);cases++;}
 for(unsigned i=0;i<7;i++){reset();b=(struct hhb_result){.next_sequence=23};if(i==0)mCpTransport.started=1;if(i==1)mCpPreflightValid=0;if(i==2)mCpPreflightLog.code=1;if(i==3)mCpPreflightLog.phase=4;if(i==4)mCpPreflightLog.restored=0;if(i==5)pre_bad=1;if(i==6)b.next_sequence=0;assert(RunCpTransport(&b));assert(!mCpInit.idle && !send_calls && !doorbells && !receives);cases++;}
 reset();assert(RunCpTransport(0) && !hw_checks && !send_calls);cases++;
 for(unsigned i=0;i<9;i++){reset();mCpTransport.started=mCpTransport.published=1;switch(i){case 0:owned=0;break;case 1:mCpPollArmed=0;break;case 2:mCpPoll.failed=1;break;case 3:mCpPreflightValid=0;break;case 4:mCpPreflightLog.code=1;break;case 5:mCpPreflightLog.phase=4;break;case 6:mCpPreflightLog.restored=0;break;case 7:mCpIrqMask=0;break;case 8:mCpGicMapped=0;break;}assert(!CpTransportHealthy(0) && !hw_checks && !send_calls);cases++;}
 printf("PASS: %u actual transport cases; exact fixed wire, ACK/reject/protocol/timeout/debug/partial send, no post-publish gated MMIO, retained RAM lease, no idle/FS claim\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)

# Same actual producer and wrapper compiled with the qualified isolation flag.
control=program.replace('#include "GpuCpTransportNative.h"', '#define HOUJI_CP_SUPPRESS_DOORBELL 1\n#include "GpuCpTransportNative.h"').replace('static int StockBootstrapDoorbell(', 'static __attribute__((unused)) int StockBootstrapDoorbell(')
control=control[:control.index('int main(void)')]+r'''
int main(void){unsigned cases=0;struct hhb_result b;reset();b=(struct hhb_result){.next_sequence=23};assert(RunCpTransport(&b)==HCI_EXCHANGE);assert(mCpTransport.published && send_calls==1 && !doorbells && !receives && !delays && !mCpTransport.doorbell_calls && b.next_sequence==24 && mCpInit.raw.code==HHB_IO && !mCpInit.raw.record[0].sent && !mCpInit.idle && hw_checks==4);cases++;
 reset();b=(struct hhb_result){.next_sequence=23};mode=4;assert(RunCpTransport(&b)==HCI_EXCHANGE && mCpTransport.published && send_calls==1 && !doorbells && !receives && !delays);cases++;
 for(unsigned i=0;i<6;i++){reset();b=(struct hhb_result){.next_sequence=23};if(i==0)mCpPreflightValid=0;if(i==1)mCpPreflightLog.code=1;if(i==2)mCpPreflightLog.phase=4;if(i==3)mCpPreflightLog.restored=0;if(i==4)pre_bad=1;if(i==5)b.next_sequence=1;assert(RunCpTransport(&b) && !send_calls && !doorbells && !receives && !delays);cases++;}
 printf("PASS: %u actual suppressed-doorbell cases; same published fixed RAW but intentional HHB_IO before AO notification, no reply wait or idle claim; partial publication retained\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(control)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
post=program.replace('#include "GpuCpTransportNative.h"', '#define HOUJI_CP_STOP_AFTER_DOORBELL 1\n#include "GpuCpTransportNative.h"')
post=post[:post.index('int main(void)')]+r'''
int main(void){unsigned cases=0;struct hhb_result b;reset();b=(struct hhb_result){.next_sequence=23};assert(RunCpTransport(&b)==HCI_EXCHANGE);assert(mCpTransport.published && send_calls==1 && doorbells==1 && !mCpTransport.doorbell_code && !receives && !delays && b.next_sequence==24 && mCpInit.raw.code==HHB_IO && !mCpInit.idle && hw_checks==4);cases++;
 reset();b=(struct hhb_result){.next_sequence=23};mode=4;assert(RunCpTransport(&b)==HCI_EXCHANGE && mCpTransport.published && send_calls==1 && !doorbells && !receives && !delays);cases++;
 reset();b=(struct hhb_result){.next_sequence=23};mode=5;assert(RunCpTransport(&b)==HCI_EXCHANGE && mCpTransport.doorbell_code==1 && doorbells==1 && !receives && !delays);cases++;
 for(unsigned i=0;i<6;i++){reset();b=(struct hhb_result){.next_sequence=23};if(i==0)mCpPreflightValid=0;if(i==1)mCpPreflightLog.code=1;if(i==2)mCpPreflightLog.phase=4;if(i==3)mCpPreflightLog.restored=0;if(i==4)pre_bad=1;if(i==5)b.next_sequence=1;assert(RunCpTransport(&b) && !send_calls && !doorbells && !receives && !delays);cases++;}
 printf("PASS: %u actual stop-after-real-doorbell cases; one exact AO notification, return status preserved, intentional stop before receive/poll, partial writes retained\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(post)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
