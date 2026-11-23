#!/usr/bin/env python3
"""Compile actual Power glue; mock only MMIO/retained-owner/native boundaries."""
from pathlib import Path
import re
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
power = (p/'native/gpu/uefi/GpuPower.c').read_text()

def function(name):
    match = re.search(r'STATIC int '+name+r'\([^;{}]*\)\s*\{', power)
    assert match, name
    start, position, depth = match.start(), match.end(), 1
    while depth:
        depth += (power[position] == '{') - (power[position] == '}')
        position += 1
    return power[start:position]

program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define STATIC static
#define VOID void
#define CONST const
#include "GpuHostRing.h"
#include "GpuKnownImage2d.h"
struct hzl_native_owner {void *cookie;int(*guard)(void*,unsigned);};
struct hgki_native_owner {void *cookie;int(*guard)(void*,unsigned);int(*submit_fixed_ib)(void*,const uint32_t*,unsigned);int(*bounded_idle)(void*);};
struct ggs_state {unsigned sentinel;};struct hpp_result {unsigned sentinel;};
static struct ggs_state mSecureCx;static struct hpp_result mPasProbe;
static struct hhr_result mHostRing;
static unsigned mHostRingPrepared,mHostDirectReady,mHostRingUnsafe,mGpuSaveAllowed,mHostRingCpFailed,mHostWriteFaults,mHostWriteCalls;
static struct {unsigned stage;}mHostBusStop;
static struct {unsigned valid;uint32_t last;}mHostRingBusy;
static struct {unsigned complete;}mHostMode;
static struct {unsigned complete;}mHostContext;
static struct {unsigned started,submitted,idle,phase,code,complete,stall_code;}mHostImage;
static unsigned owner_calls,pre_calls,reads,fail_owner,fail_pre,fail_read;
static uint32_t raw_rptr,raw_status,raw_irq,raw_fault,raw_busy;
static unsigned busy_valid,late_busy,events_count,pas_code,zap_prepare_code,image_prepare_code,zap_run_code,image_run_code,exercise_image;
static unsigned zap_prepared,image_prepared,zap_runs,image_runs,submits,idles,stall_calls,stall_code;
static char events[32];
static void event(char c){assert(events_count+1<sizeof events);events[events_count++]=c;events[events_count]=0;}
static int HostRingGuard(void*c){assert(!c);owner_calls++;mHostRingBusy.valid=busy_valid;mHostRingBusy.last=raw_busy;return owner_calls==fail_owner?1:0;}
static int HostPreparationGuard(void*c){assert(!c);pre_calls++;return fail_pre?1:0;}
static int HostRingRead(void*c,uint32_t address,uint32_t*v){assert(!c && v);if(HostRingGuard(NULL))return 1;reads++;assert((address==(uint32_t[]){0x3d02018,0x3d00840,0x3d00804,0x3d02084}[(reads-1)%4]));if(reads==fail_read)return 1;switch(address){case 0x3d02018:*v=raw_rptr;break;case 0x3d00840:*v=raw_status;break;case 0x3d00804:*v=raw_irq;break;default:*v=raw_fault;break;}if(late_busy && address==0x3d02084)mHostRingBusy.last|=1u<<23;return 0;}
static int HostKnownImageSubmit(void*c,const uint32_t*w,unsigned n){assert(!c && n==4 && !memcmp(w,hgki_ib,16) && mHostContext.complete && mHostRing.wptr==37 && mHostRing.rptr==37);submits++;mHostImage.submitted=1;mHostRing.wptr=41;raw_rptr=37;raw_busy=1u<<23;raw_status=2;return 0;}
static int HostKnownImageIdle(void*c){assert(!c && submits==1);idles++;mHostImage.idle=1;raw_rptr=mHostRing.rptr=mHostRing.wptr;raw_busy=0;raw_status=1;return 0;}
static unsigned CaptureGraphicsStall(unsigned stage){assert(stage==0 && mHostContext.complete && mHostImage.started && mHostImage.phase==1);stall_calls++;return stall_code;}
static int RunPasProbe(void){event('p');return pas_code;}
static void PasProbeReport(void){event('P');}
static unsigned ZapLoadNativePrepare(const struct hzl_native_owner*o,unsigned unsafe,unsigned enabled,unsigned stores){event('z');zap_prepared++;assert(o && !o->cookie && o->guard && o->guard(NULL,1)==1);assert(!unsafe && !enabled && !stores);return zap_prepare_code;}
static void ZapLoadNativeReport(void){event('Z');}
static unsigned KnownImage2dNativePrepare(void){event('k');image_prepared++;return image_prepare_code;}
static void KnownImage2dReport(void){event('K');}
static unsigned RunZapLoadNative(const struct ggs_state*q,const struct hpp_result*cap){assert(q==&mSecureCx && cap==&mPasProbe);zap_runs++;return zap_run_code;}
static unsigned RunKnownImage2d(const struct hgki_native_owner*o,unsigned preemption){assert(o && !o->cookie && o->guard && o->submit_fixed_ib==HostKnownImageSubmit && o->bounded_idle==HostKnownImageIdle && preemption==1);image_runs++;
 if(exercise_image){assert(o->guard(NULL,1)==0 && o->guard(NULL,2)==0 && o->guard(NULL,3)==0);assert(!o->submit_fixed_ib(NULL,hgki_ib,4));assert(o->guard(NULL,4)==0);assert(o->guard(NULL,5)==1);assert(!o->bounded_idle(NULL));assert(o->guard(NULL,5)==0);}
 return image_run_code;}
'''
for name in ['GraphicsRuntimeCheck', 'GraphicsRuntimeIdle', 'AuthenticatedZapOwner',
             'KnownImageOwner', 'HostRingLoadAuthenticatedZap', 'HostRingRunKnownImage',
             'PrepareGraphicsPrerequisites']:
    program += '\n'+function(name)+'\n'
program += r'''
static void reset(unsigned live){memset(&mHostRing,0,sizeof mHostRing);memset(&mHostImage,0,sizeof mHostImage);memset(events,0,sizeof events);events_count=0;
 mHostRingPrepared=mHostDirectReady=mHostRingUnsafe=live;mGpuSaveAllowed=!live;
 mHostRingCpFailed=mHostWriteFaults=mHostWriteCalls=mHostBusStop.stage=0;
 mHostRing.enabled=mHostRing.init_idle=live;mHostRing.started=live;mHostRing.phase=4;mHostRing.wptr=mHostRing.rptr=37;
 mHostMode.complete=1;mHostContext.complete=live;raw_rptr=37;raw_status=1;raw_irq=raw_fault=raw_busy=0;busy_valid=1;
 owner_calls=pre_calls=reads=fail_owner=fail_pre=fail_read=late_busy=0;
 pas_code=zap_prepare_code=image_prepare_code=zap_run_code=image_run_code=exercise_image=0;
 zap_prepared=image_prepared=zap_runs=image_runs=submits=idles=stall_calls=stall_code=0;
}
int main(void){unsigned cases=0;
 reset(1);assert(GraphicsRuntimeIdle()==0 && reads==4 && owner_calls==5);cases++;
 for(unsigned field=0;field<11;field++){reset(1);unsigned *bad[]={&mHostRing.enabled,&mHostRing.init_idle,&mHostRing.phase,&mHostRingPrepared,&mHostDirectReady,&mHostRingUnsafe,&mGpuSaveAllowed,&mHostRing.code,&mHostRingCpFailed,&mHostWriteFaults,&mHostBusStop.stage};
  *bad[field]=field<=5?0:1;assert(GraphicsRuntimeCheck(0)==1 && !reads && !owner_calls);cases++;}
 for(unsigned n=1;n<=5;n++){reset(1);fail_owner=n;assert(GraphicsRuntimeIdle()==1 && owner_calls==n && reads==(n<2?0:n-2));cases++;}
 for(unsigned n=1;n<=4;n++){reset(1);fail_read=n;assert(GraphicsRuntimeCheck(0)==1 && reads==n);cases++;}
 for(unsigned f=0;f<4;f++){reset(1);if(f==0)raw_irq=0x80000000;else if(f==1)raw_fault=2;else if(f==2)busy_valid=0;else late_busy=1;assert(GraphicsRuntimeIdle()==1);cases++;}
 for(unsigned f=0;f<3;f++){reset(1);if(!f)raw_rptr--;else if(f==1)raw_status=2;else raw_busy=1u<<23;assert(GraphicsRuntimeIdle()==1);reset(1);if(!f)raw_rptr--;else if(f==1)raw_status=2;else raw_busy=1u<<23;assert(GraphicsRuntimeCheck(0)==0);cases++;}
 reset(0);assert(AuthenticatedZapOwner(NULL,1)==1 && pre_calls==1 && !reads);cases++;
 for(unsigned f=0;f<6;f++){reset(0);unsigned *bad[]={&mHostRingUnsafe,&mHostWriteCalls,&mHostRingPrepared,&mHostRing.started,&mGpuSaveAllowed,&fail_pre};*bad[f]=f==4?0:1;assert(AuthenticatedZapOwner(NULL,1)==0 && !reads);cases++;}
 reset(1);assert(AuthenticatedZapOwner(NULL,7)==1);reset(1);raw_busy=1u<<23;assert(AuthenticatedZapOwner(NULL,7)==0);cases+=2;
 for(unsigned phase=1;phase<=6;phase++){reset(1);mHostImage.submitted=1;raw_rptr=36;raw_busy=1u<<23;raw_status=2;assert(KnownImageOwner(NULL,phase)==(phase==4?0:1));cases++;}
 reset(1);raw_busy=1u<<23;assert(KnownImageOwner(NULL,4)==1);reset(1);mHostImage.submitted=mHostImage.idle=1;raw_busy=1u<<23;assert(KnownImageOwner(NULL,4)==1);cases+=2;
 for(unsigned f=0;f<3;f++){reset(1);mHostImage.submitted=1;if(f==0)raw_irq=1;else if(f==1)raw_fault=1;else fail_owner=1;assert(KnownImageOwner(NULL,4)==1);cases++;}
 for(unsigned code=0;code<3;code++){reset(1);zap_run_code=code==2?0x80000003u:code;assert((unsigned)HostRingLoadAuthenticatedZap()==zap_run_code && zap_runs==1);cases++;}
 for(unsigned code=0;code<3;code++){reset(1);image_run_code=code?17*code:0;unsigned result=HostRingRunKnownImage();assert(result==(code?1:0) && image_runs==1 && stall_calls==1 && mHostImage.started && mHostImage.code==image_run_code && mHostImage.complete==!code && mHostImage.phase==(code?1:5));assert(mHostRingUnsafe && !mGpuSaveAllowed);unsigned n=owner_calls;assert(HostRingRunKnownImage()==1 && image_runs==1 && stall_calls==1 && owner_calls==n);cases++;}
 reset(1);exercise_image=1;assert(!HostRingRunKnownImage() && mHostImage.complete && mHostImage.idle && submits==1 && idles==1 && stall_calls==1 && mHostRing.rptr==41 && mHostRing.wptr==41);cases++;
 for(unsigned f=0;f<5;f++){reset(1);if(!f)mHostImage.started=1;else if(f==1)mHostMode.complete=0;else if(f==2)raw_busy=1u<<23;else if(f==3)raw_irq=1;else mHostContext.complete=0;assert(HostRingRunKnownImage()==1 && !image_runs && !submits && !stall_calls);cases++;}
 reset(1);stall_code=23;assert(HostRingRunKnownImage()==1 && stall_calls==1 && mHostImage.stall_code==23 && mHostImage.started && mHostImage.phase==1 && !mHostImage.complete && !image_runs && !submits);cases++;
 reset(0);assert(!PrepareGraphicsPrerequisites() && !strcmp(events,"pPzZkK") && zap_prepared==1 && image_prepared==1);cases++;
 for(unsigned f=0;f<3;f++){reset(0);if(!f)pas_code=23;else if(f==1)zap_prepare_code=24;else image_prepare_code=25;assert(PrepareGraphicsPrerequisites()==1);assert(!strcmp(events,f==0?"pPZK":f==1?"pPzZK":"pPzZkK"));assert(zap_prepared==(f>0) && image_prepared==(f>1));cases++;}
 printf("graphics Power glue: %u actual-function cases PASS (ASAN/UBSAN).\n",cases);return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='houji-graphics-glue-') as td:
    source = Path(td)/'test.c'; source.write_text(program)
    exe = Path(td)/'test'
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                    '-fno-omit-frame-pointer', '-I', str(p/'native/gpu/uefi'),
                    str(source), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
