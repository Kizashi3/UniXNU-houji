#!/usr/bin/env python3
"""Actual bounded candidate; optional unchanged Linux emitters with real Mesa packers.

No device or driver is accessed. The source comparison removes only the
documented previous-fence wait, TTBR bookkeeping copy and statistics reads.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
p=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--linux-gpu',type=Path)
parser.add_argument('--mesa-source',type=Path)
parser.add_argument('--mesa-build-freedreno',type=Path)
args=parser.parse_args()
if any([args.linux_gpu,args.mesa_source,args.mesa_build_freedreno]) and not all([args.linux_gpu,args.mesa_source,args.mesa_build_freedreno]):parser.error('provide all three source-qualification paths')

program=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "GpuFirstContext.h"
static unsigned guards,reads,fail_owner,fail_read;
static uint64_t raw[2];
static int owner(void*c){assert(!c);return ++guards==fail_owner?17:0;}
static int read_root(void*c,uint32_t a,uint64_t*v){assert(!c && v && reads<2 && a==0x3dc0020+8*reads);reads++;*v=0xdeadbeef;if(reads==fail_read)return 23;*v=raw[reads-1];return 0;}
static const struct hfc_io io={NULL,owner,read_root};
static struct hfc_config cfg;
static struct hfc_result r;
static uint32_t words[HFC_WORDS];
static void reset(void){guards=reads=fail_owner=fail_read=0;cfg=(struct hfc_config){0xd1def000,0xd1def000,1,1,1,1,1};memset(&r,0,sizeof r);for(unsigned i=0;i<HFC_WORDS;i++)words[i]=0xa5a5a5a5;raw[0]=(uint64_t)HFC_ASID<<48|cfg.root_physical;raw[1]=(uint64_t)HFC_ASID<<48;}
static void unchanged(void){for(unsigned i=0;i<HFC_WORDS;i++)assert(words[i]==0xa5a5a5a5);}
int main(void){unsigned cases=0;
 reset();assert(!hfc_build(&io,&cfg,words,HFC_WORDS,&r));assert(r.started && !r.code && r.ready && r.phase==3 && r.guards==4 && r.reads==2 && r.valid==3 && words[13]==0xd1def000 && words[14]==0x07510000 && !words[15] && !words[16]);struct hfc_result saved=r;uint32_t savedwords[HFC_WORDS];memcpy(savedwords,words,sizeof words);assert(hfc_build(&io,&cfg,words,HFC_WORDS,&r)==HFC_REUSED && !memcmp(&r,&saved,sizeof r) && !memcmp(words,savedwords,sizeof words));cases++;
 for(unsigned f=0;f<5;f++)for(unsigned v=0;v<3;v+=2){reset();unsigned *g[]={&cfg.same_boot_owned,&cfg.prior_full_idle,&cfg.mode_exit_idle,&cfg.single_context,&cfg.preemption_disabled};*g[f]=v;assert(hfc_build(&io,&cfg,words,HFC_WORDS,&r)==HFC_QUALIFICATION && !guards && !reads);unchanged();cases++;}
 for(unsigned f=0;f<4;f++){reset();if(!f)cfg.root_physical=0;else if(f==1)cfg.root_physical++;else if(f==2)cfg.root_physical=UINT64_C(1)<<36;else cfg.built_root_physical+=4096;assert(hfc_build(&io,&cfg,words,HFC_WORDS,&r)==HFC_QUALIFICATION && !guards);unchanged();cases++;}
 for(unsigned n=1;n<=4;n++){reset();fail_owner=n;assert(hfc_build(&io,&cfg,words,HFC_WORDS,&r)==HFC_OWNER && r.owner_code==17 && guards==n && reads==(n<=3?n-1:2));unchanged();cases++;}
 for(unsigned n=1;n<=2;n++){reset();fail_read=n;assert(hfc_build(&io,&cfg,words,HFC_WORDS,&r)==HFC_READ && r.read_code==23 && reads==n && r.valid==(n-1) && !(n==1?r.ttbr0:r.ttbr1));unchanged();cases++;}
 for(unsigned reg=0;reg<2;reg++)for(unsigned bit=0;bit<64;bit++){reset();raw[reg]^=UINT64_C(1)<<bit;assert(hfc_build(&io,&cfg,words,HFC_WORDS,&r)==HFC_ROOT && !r.ready && r.valid==3);unchanged();cases++;}
 for(unsigned f=0;f<3;f++){reset();struct hfc_io bad=io;if(!f)bad.owned=NULL;else if(f==1)bad.read_root=NULL;assert(hfc_build(&bad,&cfg,words,f==2?HFC_WORDS-1:HFC_WORDS,&r)==HFC_ARGUMENT && !guards);unchanged();cases++;}
 reset();assert(hfc_build(NULL,&cfg,words,HFC_WORDS,&r)==HFC_ARGUMENT);reset();assert(hfc_build(&io,NULL,words,HFC_WORDS,&r)==HFC_QUALIFICATION);reset();assert(hfc_build(&io,&cfg,NULL,HFC_WORDS,&r)==HFC_ARGUMENT);assert(hfc_build(&io,&cfg,words,HFC_WORDS,NULL)==HFC_ARGUMENT);cases+=4;
 reset();assert(!hfc_build(&io,&cfg,words,HFC_WORDS,&r));for(unsigned i=0;i<HFC_WORDS;i++){assert(words[i]==hfc_word(cfg.root_physical,i));cases++;}assert(!hfc_word(cfg.root_physical,HFC_WORDS) && !hfc_word(cfg.root_physical,UINT32_MAX));cases++;
 printf("first-context candidate: %u actual C cases PASS (ASAN/UBSAN); runtime not integrated.\n",cases);return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='houji-first-context-') as td:
    c=Path(td)/'test.c';exe=Path(td)/'test';c.write_text(program)
    subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(p/'native/gpu/uefi'),str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

if not args.linux_gpu:raise SystemExit(0)
linux=args.linux_gpu.read_text()
assert hashlib.sha256(args.linux_gpu.read_bytes()).hexdigest()=='3ba0192acb394ace2f7058c9c6b884c83c1763da49067f97201dad606bb3d109'
manifest=json.loads((p/'native/gpu/known-image-2d-source-plan.json').read_text())
for item in manifest['cold_context_candidate']['generated_inputs']:
    assert hashlib.sha256((args.mesa_build_freedreno/item['path']).read_bytes()).hexdigest()==item['sha256']
assert hashlib.sha256((args.mesa_source/'src/freedreno/common/freedreno_pm4.h').read_bytes()).hexdigest()=='70b5e5f6f1ee45c3bed27d08ad1a798cb2f8662a76b32e47c0907e08aea26258'

def source_function(name):
    start=linux.index('\nstatic void '+name+'(')+1
    begin=linux.index('{',start);end=begin+1;depth=1
    while depth:
        depth+=(linux[end]=='{')-(linux[end]=='}');end+=1
    return linux[start:end]

cpp=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <bit>
constexpr uint32_t fui(float f){return std::bit_cast<uint32_t>(f);}
#define __FD_DEPRECATED
#define FD_NO_DEPRECATED_PACK
#include "adreno_pm4.xml.h"
#include "adreno_common.xml.h"
#include "a6xx_enums.xml.h"
#include "a7xx_enums.xml.h"
#include "a6xx.xml.h"
#include "freedreno_pm4.h"
#include "GpuFirstContext.h"
// Spelling bridge for the excluded statistics packets only; same XML bit30.
#define CP_REG_TO_MEM_0_IS_64B CP_REG_TO_MEM_0_64B
using u32=uint32_t;using u64=uint64_t;using phys_addr_t=uint64_t;
#define BIT(n) (1u<<(n))
#define lower_32_bits(v) ((u32)(v))
#define upper_32_bits(v) ((u32)((uint64_t)(v)>>32))
enum{ADRENO_7XX_GEN1=7,MSM_GPU_SUBMIT_STATS_COUNT=8,MSM_SUBMITQUEUE_ALLOW_PREEMPT=1};
struct msm_ringbuffer{unsigned cur_ctx_seqno;std::vector<u32> words;};
struct msm_gpu{unsigned nr_rings;void*owner;};
struct adreno_info{unsigned family;};struct adreno_gpu{msm_gpu base;adreno_info*info;};struct a6xx_gpu{adreno_gpu base;};
struct drm_gpuvm{void*mmu;};struct msm_context{drm_gpuvm*vm;unsigned seqno;};struct queue{msm_context*ctx;unsigned flags;};struct msm_gem_submit{unsigned seqno;msm_ringbuffer*ring;struct queue*queue;};
static phys_addr_t selected_root;
static adreno_gpu*to_adreno_gpu(msm_gpu*g){return &((a6xx_gpu*)g->owner)->base;}
static a6xx_gpu*to_a6xx_gpu(adreno_gpu*g){return (a6xx_gpu*)g;}
static drm_gpuvm*to_msm_vm(drm_gpuvm*v){return v;}
static bool msm_gpu_sysprof_no_perfcntr_zap(msm_gpu*){return true;}
static int msm_iommu_pagetable_params(void*,phys_addr_t*root,u32*asid){*root=selected_root;*asid=HFC_ASID;return 0;}
static bool adreno_is_a7xx(adreno_gpu*){return true;}static bool adreno_is_a8xx(adreno_gpu*){return false;}
static void adreno_check_and_reenable_stall(adreno_gpu*){}
static void a6xx_emit_set_pseudo_reg(msm_ringbuffer*,a6xx_gpu*,struct queue*){assert(false);}
#define rbmemptr(r,field) UINT64_C(0x620c8100)
#define rbmemptr_stats(r,index,field) (UINT64_C(0x620c8200)+(index)*32)
#define OUT_RING(r,v) ((r)->words.push_back((u32)(v)))
#define OUT_PKT7(r,op,n) OUT_RING(r,pm4_pkt7_hdr(op,n))
#define OUT_PKT4(r,reg,n) OUT_RING(r,pm4_pkt4_hdr(reg,n))
'''
cpp+='\n'+source_function('get_stats_counter')+'\n'+source_function('a6xx_set_pagetable')+'\n'
prefix=source_function('a7xx_submit')
prefix=prefix[:prefix.index('\n\t/* Submit the commands */')]+'\n}'
cpp+='\n'+prefix+'\n'
cpp+=r'''
static int owned(void*){return 0;}
static int root_read(void*,u32 addr,u64*v){assert(addr==0x3dc0020 || addr==0x3dc0028);*v=(u64)HFC_ASID<<48|(addr==0x3dc0020?selected_root:0);return 0;}
int main(){for(u64 root:{UINT64_C(0xd1def000),UINT64_C(0x12345000),UINT64_C(0x812345000)}){
 selected_root=root;adreno_info info={ADRENO_7XX_GEN1};a6xx_gpu gpu={{{1,nullptr},&info}};gpu.base.base.owner=&gpu;drm_gpuvm vm={nullptr};msm_context ctx={&vm,1};struct queue q={&ctx,0};msm_ringbuffer ring={0,{}};msm_gem_submit submit={1,&ring,&q};a7xx_submit(&gpu.base.base,&submit);
 std::vector<u32> selected;unsigned waits=0,mirrors=0,stats=0;
 for(unsigned i=0;i<ring.words.size();){u32 h=ring.words[i];unsigned n=h&0x3fff,op=(h>>16)&127;assert((h>>28)==7 && i+1+n<=ring.words.size());bool omit=false;
  if(op==CP_WAIT_TIMESTAMP){assert(n==4 && ring.words[i+1]==0 && ring.words[i+4]==0);waits++;omit=true;}
  if(op==CP_MEM_WRITE){assert(n==5 && ring.words[i+1]==0x620c8100 && ring.words[i+3]==lower_32_bits(root) && ring.words[i+4]==upper_32_bits(root));mirrors++;omit=true;}
  if(op==CP_REG_TO_MEM){assert(n==3);stats++;omit=true;}
  if(!omit)selected.insert(selected.end(),ring.words.begin()+i,ring.words.begin()+i+1+n);i+=1+n;
 }
 assert(waits==1 && mirrors==1 && stats==2 && selected.size()==HFC_WORDS);
 hfc_config config={root,root,1,1,1,1,1};hfc_io io={nullptr,owned,root_read};hfc_result r={};u32 candidate[HFC_WORDS];assert(!hfc_build(&io,&config,candidate,HFC_WORDS,&r));for(unsigned i=0;i<HFC_WORDS;i++)assert(candidate[i]==selected[i] && hfc_word(root,i)==selected[i]);
 }puts("Pinned Linux actual first-context emitters: 25 DWORDs match all 3 roots using genuine Mesa packers (ASAN/UBSAN).");}
'''
with tempfile.TemporaryDirectory(prefix='houji-first-context-source-') as td:
    c=Path(td)/'source.cc';exe=Path(td)/'source';c.write_text(cpp)
    subprocess.run(['clang++','-std=c++20','-Wno-unused-variable','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(args.mesa_build_freedreno/'registers/adreno'),'-I',str(args.mesa_source/'src/freedreno/common'),'-I',str(p/'native/gpu/uefi'),str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
