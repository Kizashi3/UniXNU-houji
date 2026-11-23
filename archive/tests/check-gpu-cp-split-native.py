#!/usr/bin/env python3
"""Actual two-packet producer and native split flow with guarded idle snapshot."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1]
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "GpuCpInit.h"
#include "GpuCpPoll.h"
#include "GpuLiveLog.h"
#define ggh_queue real_ggh_queue
#include "GpuFirmwareMemory.h"
#undef ggh_queue
#define STATIC static
#define VOID void
#define CONST const
#define Print(...) ((void)0)
#define HCI_GPU_ERROR_MASK 0x03400042u
static struct hci_result mCpInit;
static struct hll_result mCpPreflightLog;
static unsigned mCpPreflightValid,mCpPollArmed,mCpGicMapped,mCpIrqMask;
static struct hcf_result mCpPoll;
static struct {unsigned code,phase,record_ready;}mGen7;
static unsigned mCodeReady;
static struct hfm_result mFirmwareMemory;
static struct hfm_allocation mCodeMemory,mGpuOnlyMemory;
static uint64_t mScratchTablePhysical,*mScratchTables;
static unsigned healths,reads,fail_read,sends[2],bells[2],headers[2],saves,tpl,memchecks,fail_mem;
static unsigned failure,fail_stage,owned=1;
static int bad_queue=-1;
static int CpPolledHealthy(void*c){(void)c;healths++;return owned;}
static int CpPolledReady(void*c){(void)c;return !owned;}
static int CpLeaseOwned(void){return owned;}
static int CpPreflightGuard(void*c){(void)c;return !owned;}
static int CpReuseAperture(void*c){(void)c;return !owned;}
static int CpRead(void*c,uint32_t a,uint32_t*v){(void)c;(void)a;(void)v;assert(0);return 1;}
static int ScratchAudit(void){return failure==9;}
static int SecureDomainGuard(void*c){(void)c;return failure==10;}
static int FirmwareVerifyPages(uint64_t p,void*c,unsigned n,unsigned nc){(void)p;(void)c;(void)n;(void)nc;return ++memchecks==fail_mem;}
static unsigned LiveLogTpl(void*c){(void)c;return tpl;}
static void LiveLogLower(void*c){(void)c;assert(tpl==16);tpl=4;}
static int LiveLogRestore(void*c){(void)c;assert(tpl==4);tpl=16;return failure==12;}
static uint64_t ProbeCheckpoint(const char*s){assert(tpl==4 && !strcmp(s,"THREAD-CONTROL-ACK-idle-before-ME-INIT"));saves++;return failure==11?UINT64_C(0x8000000000000015):0;}
static void StockHfiBarrier(void*c){(void)c;}
static int ggh_queue(const struct ggh_io*i,unsigned q,volatile uint32_t**h,volatile uint32_t**r,unsigned*rd,unsigned*wr){(void)i;(void)h;(void)r;assert(q<17);*rd=4*q;*wr=*rd;return bad_queue==(int)q;}
static int StockBootstrapSend(void*,const uint32_t*,unsigned);
static int StockBootstrapDoorbell(void*);
static int StockBootstrapReceive(void*,unsigned,uint32_t*,unsigned*);
static int ContextDelay(void*,unsigned);
static int GpuTryRead32(uint64_t,uint32_t*);
#include "GpuCpSplitNative.h"
static unsigned stage(void){assert(mCpSplit.mode==1 || mCpSplit.mode==2);return mCpSplit.mode-1;}
static int StockBootstrapSend(void*c,const uint32_t*w,unsigned n){(void)c;unsigned st=stage();assert(n==(st?9:3) && (w[0]&255)==131 && ((w[0]>>8)&255)==n && (w[0]>>20)==23+st);const uint32_t expected[]={0x70970001,0x8000000,0x70c80007,0x94b,3,0x20000000,2,0x6303f000,0,0x80000000};for(unsigned i=0;i<n-1;i++)assert(w[i+1]==expected[i+(st?2:0)]);assert(++sends[st]==1);headers[st]=w[0];return failure==3 && fail_stage==st+1;}
static int StockBootstrapDoorbell(void*c){(void)c;unsigned st=stage();assert(sends[st]==1 && ++bells[st]==1);return failure==4 && fail_stage==st+1;}
static int StockBootstrapReceive(void*c,unsigned q,uint32_t*w,unsigned*n){(void)c;unsigned st=stage();assert(bells[st]==1 && q>=1 && q<=2);if(fail_stage==st+1 && failure==5)return 3;if(fail_stage==st+1 && failure==6)return 1;if(q==2)return 1;*n=3;w[0]=0x10383;w[1]=headers[st];w[2]=fail_stage==st+1 && failure==1?UINT32_MAX:0;if(fail_stage==st+1 && failure==2)w[1]^=1;return 0;}
static int ContextDelay(void*c,unsigned u){(void)c;assert(u==10);return 0;}
static int GpuTryRead32(uint64_t a,uint32_t*v){unsigned st=stage();reads++;if(reads==fail_read)return 2;switch(a){case 0x3d8ec30:*v=(failure==7 && fail_stage==st+1)?1u<<23:0;break;case 0x3d00840:*v=failure==8?1:0;break;case 0x3d00804:*v=failure==13?1:0;break;case 0x3d02020:*v=1;break;default:assert(0);}return 0;}
static void reset(void){memset(&mCpSplit,0,sizeof mCpSplit);memset(&mCpInit,0,sizeof mCpInit);memset(&mCpPoll,0,sizeof mCpPoll);mCpPreflightLog=(struct hll_result){.phase=5,.restored=1};mCpPreflightValid=mCpPollArmed=mCpGicMapped=mCodeReady=owned=1;mCpIrqMask=HCI_GPU_ERROR_MASK;mGen7.code=0;mGen7.phase=6;mGen7.record_ready=1;mFirmwareMemory.count=1;healths=reads=fail_read=saves=memchecks=fail_mem=failure=fail_stage=0;memset(sends,0,sizeof sends);memset(bells,0,sizeof bells);bad_queue=-1;tpl=16;}
int main(void){unsigned cases=0;struct hhb_result b;reset();b=(struct hhb_result){.next_sequence=23};assert(!RunCpSplit(&b) && b.next_sequence==25 && mCpInit.phase==6 && sends[0]==1 && sends[1]==1 && bells[0]==1 && bells[1]==1 && saves==1 && tpl==16 && mCpSplit.prefix.raw.record[0].ack && mCpSplit.checkpoint.restored && mCpSplit.prefix.phase==5);unsigned total_reads=reads,total_mem=memchecks;cases++;
 for(unsigned f=1;f<=7;f++)for(unsigned st=1;st<=2;st++){reset();b=(struct hhb_result){.next_sequence=23};failure=f;fail_stage=st;assert(RunCpSplit(&b) && mCpInit.phase!=6 && sends[0]==1 && (st==2 || !sends[1]) && tpl==16);cases++;}
 for(unsigned f=8;f<=13;f++){reset();b=(struct hhb_result){.next_sequence=23};failure=f;assert(RunCpSplit(&b) && !sends[1] && tpl==16);cases++;}
 for(unsigned i=1;i<=total_reads;i++){reset();b=(struct hhb_result){.next_sequence=23};fail_read=i;assert(RunCpSplit(&b) && mCpInit.phase!=6 && tpl==16);cases++;}
 for(unsigned i=1;i<=total_mem;i++){reset();b=(struct hhb_result){.next_sequence=23};fail_mem=i;assert(RunCpSplit(&b) && !sends[1] && tpl==16);cases++;}
 for(int q=0;q<17;q++){reset();b=(struct hhb_result){.next_sequence=23};bad_queue=q;assert(RunCpSplit(&b) && !sends[1] && tpl==16);cases++;}
 for(unsigned i=0;i<7;i++){reset();b=(struct hhb_result){.next_sequence=23};if(i==0)owned=0;if(i==1)mCpPreflightValid=0;if(i==2)mCpPreflightLog.code=1;if(i==3)mCpPreflightLog.phase=4;if(i==4)mCpPreflightLog.restored=0;if(i==5)b.next_sequence=1;if(i==6)b.next_sequence=4092;assert(RunCpSplit(&b) && !sends[0] && !saves);cases++;}
 // The only accepted bodies are the exact existing2/8/10 vendor word slices.
 struct hci_io io={0};struct hci_result r={0};uint32_t words[10];for(unsigned i=0;i<10;i++)words[i]=hci_cp_word(i);
 for(unsigned n=0;n<20;n++)if(n!=2 && n!=8 && n!=10){assert(hci_exchange_words(&io,&r,words,n)==HHB_ARGUMENT);cases++;}
 for(unsigned count=2;count<=10;count+=2)if(count==2 || count==8 || count==10){for(unsigned i=0;i<count;i++)for(unsigned bit=0;bit<32;bit++){for(unsigned j=0;j<count;j++)words[j]=hci_cp_word(j+(count==8?2:0));words[i]^=1u<<bit;assert(hci_exchange_words(&io,&r,words,count)==HHB_ARGUMENT);cases++;}}
 printf("PASS: %u actual split/packet cases; same2+8 vendor words, fresh sequences, prefix realACK+idle+graphs/TPL snapshot before ME, every read/FS/guard/queue failure prevents continuation\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
