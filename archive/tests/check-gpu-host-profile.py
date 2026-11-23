#!/usr/bin/env python3
"""Exercise actual host-profile entry with real owned17-queue transport."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1]
program=r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "GpuHostProfile.h"
#include "vendor/Ace5Gmu/giulia_gpu_hfi.h"
struct model {uint32_t ram[GGH_BYTES/4];struct ggh_io q;unsigned count[6],kind,at,mode,pending;uint32_t header;};
static int fail(struct model*m,unsigned k){return ++m->count[k]==m->at && k==m->kind;}
static void barrier(void*c){(void)c;}
static int StockBootstrapHealthy(void*c){return !fail(c,1);}
static int StockBootstrapSend(void*c,const uint32_t*w,unsigned n){
 struct model*m=c;if(fail(m,2))return 1;unsigned st=m->count[2]-1;
 const unsigned ids[]={4,3,14,10,12},sizes[]={59,160,2,1,3};
 assert(st<5 && n==sizes[st] && w[0]==((st+2)<<20|n<<8|ids[st]));
 if(!st){
  const uint32_t first[]={2,3,0,UINT32_MAX,0,0x340201,UINT32_MAX,231000};
  const uint32_t cx[]={0,0,0x400202,260000,0x800303,625000};
  assert(!memcmp(w+1,first,sizeof(first)) && !memcmp(w+51,cx,sizeof(cx)));
  for(unsigned i=8;i<50;i++)assert(!w[i+1]);for(unsigned i=56;i<58;i++)assert(!w[i+1]);
 }
 if(st==1)assert(!memcmp(w+1,hhb_bw,sizeof(hhb_bw)));
 if(st==2)assert(w[1]==0);if(st==4)assert(w[1]==125 && !w[2]);
 return ggh_send(&m->q,w,n);
}
static int StockBootstrapReceive(void*c,unsigned queue,uint32_t*w,unsigned*n){struct model*m=c;if(fail(m,3))return 3;return ggh_receive(&m->q,queue,w,255,n);}
static int StockBootstrapDoorbell(void*c){struct model*m=c;if(fail(m,4))return 1;volatile uint32_t*h,*ring;unsigned r,w;assert(!ggh_queue(&m->q,0,&h,&ring,&r,&w) && r!=w);m->header=ring[r];h[10]=w;m->pending=1;return 0;}
static int ContextDelay(void*c,unsigned us){
 struct model*m=c;assert(us==10);if(fail(m,5))return 1;
 if(!m->pending || m->mode==1)return 0;m->pending=0;
 unsigned id=m->header&255,n=4,q=m->mode==9?2:1;
 uint32_t out[11]={0x10400|id,m->header,id==12?1:0,0};
 if(m->mode==2)out[1]^=1;if(m->mode==3)out[0]^=1;
 if(m->mode==4)out[3]=1;if(m->mode==5 && id!=12)out[2]=99;
 if(m->mode==6 || (m->mode==7 && id!=12)){n=3;out[0]=(out[0]&~0xff00u)|(n<<8);}
 if(m->mode==8)out[0]&=~0x10000u;
 if(m->mode==11 && id==12)out[2]=0;
 if(m->mode==9){out[0]=0x464;m->pending=1;}
 if(m->mode==10){n=11;memset(out,0,sizeof(out));out[0]=0xb14;out[1]=1;out[4]=0x33f;out[5]=2;out[7]=2;out[9]=4096;}
 uint32_t*h=m->ram+6+q*12,*ring=m->ram+GGH_RING_OFFSET/4+q*1024;unsigned at=h[11];
 for(unsigned i=0;i<((n+3)&~3u);i++)ring[(at+i)&1023]=i<n?out[i]:0xfafafafa;
 h[11]=(at+((n+3)&~3u))&1023;return 0;
}
#define STATIC static
#define VOID void
#define CONST const
#define Print(...) ((void)0)
static unsigned mHostProfileReady;
#include "GpuHostProfileNative.h"
static void init(struct model*m){memset(m,0,sizeof(*m));assert(!ggh_init(m->ram,sizeof(m->ram),GGH_IOVA));m->q=(struct ggh_io){m->ram,sizeof(m->ram),GGH_IOVA,m,barrier};}
int main(void){struct model*m=malloc(sizeof(*m));struct hhb_result*r=malloc(sizeof(*r));assert(m && r);unsigned cases=0,baseline[6];
 init(m);assert(!RunHostProfile(r,m) && r->completed==5 && r->next_sequence==7 && r->record[4].ack && r->record[4].value==1 && !r->resource_acks);memcpy(baseline,m->count,sizeof baseline);cases++;
 for(unsigned k=1;k<=5;k++)for(unsigned at=1;at<=baseline[k];at++){init(m);m->kind=k;m->at=at;assert(RunHostProfile(r,m) && r->completed<5 && !r->resource_acks);cases++;}
 const unsigned expected[]={0,HHB_TIMEOUT,HHB_PROTOCOL,HHB_PROTOCOL,HHB_REJECTED,HHB_REJECTED,HHB_PROTOCOL,HHB_OK,HHB_PROTOCOL,HHB_PROTOCOL,HHB_RESOURCE,HHB_REJECTED};
 for(unsigned mode=1;mode<=11;mode++){init(m);m->mode=mode;unsigned code=RunHostProfile(r,m);assert(code==expected[mode] && !r->resource_acks && mHostProfileReady==!code);if(mode==6)assert(r->completed==4 && !r->record[4].status_present);if(mode==10)assert(r->resource_request && r->resource_count==1 && !r->resources[0].sent);cases++;}
 const struct hhb_io missing={0};assert(hhp_run(&missing,r)==HHB_ARGUMENT && hhp_run(NULL,r)==HHB_ARGUMENT && hhp_run(&missing,NULL)==HHB_ARGUMENT && hhp_perf(NULL));cases++;
 printf("PASS: %u actual native host-profile/transport cases; exact Linux PERF4 layout with own2GPU/3GMU votes,5ordinary messages, real17queue RAM, every transport failure/ACK rejection/malformed/query-status/resource-stop, zero RAW/features/GPU writes\n",cases);
 free(m);free(r);
}
'''
with tempfile.TemporaryDirectory() as d:
 f=Path(d);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu/uefi'),'-I',str(p/'native/gpu'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
