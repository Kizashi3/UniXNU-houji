/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "uefi/GpuGen7Config.h"
static uint32_t regs[0x100000/4];static unsigned reads,writes,guards,delays,published,cases;
static int fail_read,fail_write,fail_guard,corrupt,never_ready,fail_publish,fail_delay;
static struct h7c_result result;
static int guard(void*c){(void)c;return ++guards==(unsigned)fail_guard;}
static int rd(void*c,uint32_t a,uint32_t*v){(void)c;reads++;if(reads==(unsigned)fail_read)return 1;assert(a>=0x3d00000 && a<0x3e00000);*v=regs[(a-0x3d00000)/4];return 0;}
static int wr(void*c,uint32_t a,uint32_t v){(void)c;writes++;if(writes==(unsigned)fail_write)return 1;
 const struct h7c_op *o=&h7c_ops[result.step];assert(o->address==a && a!=0x3d02020 && a!=0x3d0f400 && o->kind!=3);
 if(o->kind==1)assert(v==((regs[(a-0x3d00000)/4]&~o->mask)|o->value));
 regs[(a-0x3d00000)/4]=v;
 if(o->verify==0xfffff000)regs[(a-0x3d00000)/4]&=0xfffff000;
 if((int)result.step==corrupt)regs[(a-0x3d00000)/4]^=o->verify&(-o->verify);
 return 0;
}
static int delay(void*c,unsigned us){(void)c;assert(us==1);delays++;
 if(!never_ready && delays>=3)for(unsigned i=0;i<H7C_OPS;i++)if(h7c_ops[i].kind==3)regs[(h7c_ops[i].address-0x3d00000)/4]=1;
 return fail_delay;
}
static int publish(void*c,const uint32_t*words,unsigned count){(void)c;published++;assert(count==H7C_WORDS && !words[0] && !words[1] && !words[2] && words[3]==(H7C_IFPC|(H7C_PREEMPT<<8)));
 for(unsigned i=0;i<H7C_PAIRS;i++){assert(words[4+2*i]==(h7c_power_regs[i].address-0x3d00000)/4);assert(words[5+2*i]==regs[words[4+2*i]]);}
 return fail_publish;
}
static void reset(void){memset(regs,0,sizeof(regs));memset(&result,0,sizeof(result));reads=writes=guards=delays=published=0;fail_read=fail_write=fail_guard=fail_publish=never_ready=0;corrupt=-1;
 for(unsigned i=0;i<H7C_OPS;i++)if(h7c_ops[i].kind==1)regs[(h7c_ops[i].address-0x3d00000)/4]=0xa55a5aa5;
}
static const struct h7c_op *find_op(const char *name){for(unsigned i=0;i<H7C_OPS;i++)if(!strcmp(h7c_ops[i].name,name))return &h7c_ops[i];return 0;}
static void check_profile(void){
 const struct h7c_op *ahb=find_op("CP_AHB_CNTL"),*base=find_op("RBBM_SECVID_TSB_TRUSTED_BASE_LO"),*size=find_op("RBBM_SECVID_TSB_TRUSTED_SIZE"),*protect=find_op("CP_PROTECT_CNTL");
 assert(base && size && protect && H7C_IFPC==58 && H7C_PREEMPT==17 && H7C_PAIRS==75 && H7C_WORDS==154);cases++;
 assert(base->kind==0 && size->kind==0 && base->mask==0xffffffff && size->mask==0xffffffff && base->verify==0xffffffff && size->verify==0xffffffff);cases++;
 if(H7C_LINUX_HOST){assert(H7C_OPS==102 && ahb && ahb->address==0x3d02634 && ahb->value==1 && ahb->kind==0 && ahb->mask==0xffffffff && ahb->verify==0xffffffff);assert(ahb<protect && !base->value && !size->value);}
 else {assert(H7C_OPS==101 && !ahb && base->value==0xf0000000 && size->value==0x10000000);}cases++;
}
int main(void){const struct h7c_io io={0,guard,rd,wr,delay,publish};check_profile();reset();assert(!h7c_run(&io,&result) && result.phase==6 && result.completed==H7C_OPS && result.power_pairs==H7C_PAIRS && result.record_ready && published==1 && delays==3 && !regs[0x2020/4]);cases++;
 if(H7C_LINUX_HOST){unsigned ahb_record=0;for(unsigned i=0;i<H7C_PAIRS;i++){
  if(!strcmp(h7c_power_regs[i].name,"CP_AHB_CNTL")){assert(regs[(h7c_power_regs[i].address-0x3d00000)/4]==1);ahb_record++;}
 }assert(ahb_record==1 && !regs[(find_op("RBBM_SECVID_TSB_TRUSTED_BASE_LO")->address-0x3d00000)/4] && !regs[(find_op("RBBM_SECVID_TSB_TRUSTED_SIZE")->address-0x3d00000)/4]);cases++;}
 unsigned good_reads=reads,good_writes=writes,good_guards=guards;
 for(unsigned i=0;i<H7C_OPS;i++){assert(h7c_ops[i].address!=0x3d02020 && h7c_ops[i].address!=0x3d0f400);cases++;}
 for(unsigned i=1;i<=good_reads;i++){reset();fail_read=(int)i;assert(h7c_run(&io,&result)!=0 && reads==i && result.phase!=6);cases++;}
 for(unsigned i=1;i<=good_writes;i++){reset();fail_write=(int)i;assert(h7c_run(&io,&result)==H7C_IO && writes==i && !published);cases++;}
 for(unsigned i=1;i<=good_guards;i++){reset();fail_guard=(int)i;assert(h7c_run(&io,&result)!=0 && guards==i && result.phase!=6);cases++;}
 for(unsigned i=0;i<H7C_OPS;i++)if(h7c_ops[i].verify && h7c_ops[i].kind!=3){reset();corrupt=(int)i;assert(h7c_run(&io,&result)==H7C_VERIFY && result.step==i && !published);cases++;}
 reset();never_ready=1;assert(h7c_run(&io,&result)==H7C_TIMEOUT && delays==H7C_POLLS && !published);cases++;
 reset();fail_publish=1;assert(h7c_run(&io,&result)==H7C_PUBLISH && !result.record_ready);cases++;
 reset();fail_delay=1;assert(h7c_run(&io,&result)==H7C_IO && delays==1 && !published);fail_delay=0;cases++;
 reset();assert(h7c_run(0,&result)==H7C_ARGUMENT && !writes);cases++;
 printf("PASS: %u gen7 failure/side-effect cases; %u fixed steps, %u powerup pairs, profile=%s, first failed read/write/guard stops, masks and real TXDONE required, no SQE enable\n",cases,H7C_OPS,H7C_PAIRS,H7C_LINUX_HOST?"linux-host":"vendor");
}
