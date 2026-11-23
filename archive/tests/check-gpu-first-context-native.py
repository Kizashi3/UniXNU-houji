#!/usr/bin/env python3
"""Actual CPU-only first-context adapter; only live-owner and MMIO boundaries mocked."""
from pathlib import Path
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
program = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#define STATIC static
#define VOID void
#define CONST const
typedef uint64_t UINT64;
static unsigned owner_calls,read_calls,fail_owner,fail_read,report_lines;
static unsigned mutate_guard,mutate_kind,mutate_mode;
static uint64_t raw[2];
static uint64_t mScratchTablePhysical;
static uint64_t table_storage[2];
static void *mScratchTables;
static struct {uint64_t root_physical;}mScratchBuilt;
static struct {uint64_t table_physical;}mScratchConfig;
static uint64_t mHostRingRoots[4];
static unsigned mHostRingUnsafe,mGpuSaveAllowed;
static struct {unsigned started,authenticated,published,submitted,idle,complete,phase,code;}mHostMode;
static int GraphicsRuntimeCheck(unsigned require_idle);
static int GpuTryRead64(uint32_t address,uint64_t *value);
static void Print(const wchar_t *format,...){assert(format);report_lines++;}
#include "GpuFirstContextNative.h"
static unsigned *mode_field(unsigned i){unsigned *fields[]={&mHostMode.started,&mHostMode.authenticated,&mHostMode.published,&mHostMode.submitted,&mHostMode.idle,&mHostMode.complete,&mHostMode.phase,&mHostMode.code};assert(i<8);return fields[i];}
static void mutate_identity(unsigned kind){switch(kind){
 case 0:mScratchTablePhysical+=4096;break;
 case 1:mScratchBuilt.root_physical+=4096;break;
 case 2:mScratchConfig.table_physical+=4096;break;
 case 3:mScratchTables=&table_storage[1];break;
 case 4:mHostRingRoots[0]^=4096;break;
 case 5:mHostRingRoots[1]^=UINT64_C(1)<<48;break;
 case 6:mScratchTablePhysical+=4096;mScratchBuilt.root_physical=mScratchConfig.table_physical=mScratchTablePhysical;mHostRingRoots[0]=(uint64_t)HFC_ASID<<48|mScratchTablePhysical;raw[0]=mHostRingRoots[0];break;
 default:assert(0);
}}
static int GraphicsRuntimeCheck(unsigned require_idle){assert(require_idle==1);owner_calls++;
 if(owner_calls==mutate_guard){if(mutate_mode)*mode_field(mutate_kind)=mutate_kind==7?1:0;else mutate_identity(mutate_kind);}
 return owner_calls==fail_owner?37:0;}
static int GpuTryRead64(uint32_t address,uint64_t *value){assert(value && read_calls<2 && address==0x3dc0020+8*read_calls);read_calls++;*value=UINT64_C(0xdeadbeef11223344);if(read_calls==fail_read)return 53;*value=raw[read_calls-1];return 0;}
static void reset(uint64_t root){owner_calls=read_calls=fail_owner=fail_read=report_lines=mutate_guard=mutate_kind=mutate_mode=0;
 memset(&mFirstContext,0,sizeof mFirstContext);memset(&mFirstContextNative,0,sizeof mFirstContextNative);
 mScratchTablePhysical=mScratchBuilt.root_physical=mScratchConfig.table_physical=root;mScratchTables=table_storage;
 mHostRingRoots[0]=(uint64_t)HFC_ASID<<48|root;mHostRingRoots[1]=(uint64_t)HFC_ASID<<48;mHostRingRoots[2]=0x7500000d1df6000;mHostRingRoots[3]=0x750000000000000;
 raw[0]=mHostRingRoots[0];raw[1]=mHostRingRoots[1];mHostRingUnsafe=1;mGpuSaveAllowed=0;
 mHostMode=(__typeof__(mHostMode)){1,1,1,1,1,1,5,0};}
static void no_packet(void){assert(!mFirstContextNative.ready && !mFirstContextNative.running);for(unsigned i=0;i<HFC_WORDS;i++)assert(!mFirstContextNative.words[i]);}
int main(void){unsigned cases=0;const uint64_t roots[]={0xd1def000,0x12345000,UINT64_C(0x812345000)};
 for(unsigned n=0;n<3;n++){reset(roots[n]);assert(FirstContextNativeBuild(1)==HFCN_OK);assert(mFirstContextNative.started && mFirstContextNative.ready && !mFirstContextNative.code && !mFirstContextNative.running && mFirstContextNative.phase==3 && mFirstContextNative.identity_valid && owner_calls==4 && read_calls==2 && mFirstContextNative.actual_reads==2 && !mFirstContextNative.rejected_reads && mFirstContext.valid==3 && mFirstContext.ready);
  assert(mFirstContextNative.root_physical==roots[n] && mFirstContextNative.words[13]==(uint32_t)roots[n] && mFirstContextNative.words[14]==((uint32_t)(roots[n]>>32)|0x07510000u));
  assert(FirstContextNativeOwned(NULL)==1); // Completed adapter cannot be reused as a live callback.
  unsigned saved_owner=owner_calls,saved_reads=read_calls;__typeof__(mFirstContextNative) saved=mFirstContextNative;struct hfc_result saved_portable=mFirstContext;
  assert(FirstContextNativeBuild(1)==HFCN_REUSED && !memcmp(&saved,&mFirstContextNative,sizeof saved) && !memcmp(&saved_portable,&mFirstContext,sizeof saved_portable) && owner_calls==saved_owner && read_calls==saved_reads);
  FirstContextNativeReport();assert(!report_lines);mHostRingUnsafe=0;FirstContextNativeReport();assert(!report_lines);mGpuSaveAllowed=1;FirstContextNativeReport();assert(report_lines==2 && mFirstContextNative.reported && owner_calls==saved_owner && read_calls==saved_reads);FirstContextNativeReport();assert(report_lines==2);cases++;
 }
 for(unsigned v=0;v<3;v+=2){reset(roots[0]);assert(FirstContextNativeBuild(v)==HFCN_POLICY && !owner_calls && !read_calls);no_packet();cases++;}
 for(unsigned field=0;field<8;field++){reset(roots[0]);*mode_field(field)=field==7?1:0;assert(FirstContextNativeBuild(1)==HFCN_STATE && !owner_calls && !read_calls);no_packet();cases++;}
 for(unsigned field=0;field<10;field++){reset(roots[0]);switch(field){case 0:mScratchTablePhysical=0;break;case 1:mScratchTablePhysical++;break;case 2:mScratchTablePhysical=UINT64_C(1)<<36;break;case 3:mScratchBuilt.root_physical+=4096;break;case 4:mScratchConfig.table_physical+=4096;break;case 5:mScratchTables=NULL;break;case 6:mHostRingRoots[0]^=UINT64_C(1)<<48;break;case 7:mHostRingRoots[0]^=4096;break;case 8:mHostRingRoots[1]^=UINT64_C(1)<<48;break;default:mHostRingRoots[1]|=4096;break;}
  assert(FirstContextNativeBuild(1)==HFCN_ROOT && !owner_calls && !read_calls && !mFirstContextNative.identity_valid);no_packet();cases++;}
 for(unsigned n=1;n<=4;n++){reset(roots[0]);fail_owner=n;assert(FirstContextNativeBuild(1)==HFCN_BUILD && mFirstContext.code==HFC_OWNER && mFirstContext.owner_code==37 && owner_calls==n && read_calls==(n<3?n-1:2));no_packet();cases++;}
 for(unsigned n=1;n<=2;n++){reset(roots[0]);fail_read=n;assert(FirstContextNativeBuild(1)==HFCN_BUILD && mFirstContext.code==HFC_READ && mFirstContext.read_code==53 && read_calls==n && mFirstContextNative.actual_reads==n && mFirstContext.valid==n-1 && !(n==1?mFirstContext.ttbr0:mFirstContext.ttbr1));no_packet();cases++;}
 for(unsigned reg=0;reg<2;reg++)for(unsigned bit=0;bit<64;bit++){reset(roots[0]);raw[reg]^=UINT64_C(1)<<bit;assert(FirstContextNativeBuild(1)==HFCN_BUILD && mFirstContext.code==HFC_ROOT && mFirstContext.valid==3 && read_calls==2);no_packet();cases++;}
 for(unsigned guard=1;guard<=4;guard++)for(unsigned field=0;field<7;field++){reset(roots[0]);mutate_guard=guard;mutate_kind=field;assert(FirstContextNativeBuild(1)==HFCN_BUILD && mFirstContext.code==HFC_OWNER && owner_calls==guard && read_calls==(guard<3?guard-1:2));no_packet();cases++;}
 for(unsigned guard=1;guard<=4;guard++)for(unsigned field=0;field<8;field++){reset(roots[0]);mutate_guard=guard;mutate_kind=field;mutate_mode=1;assert(FirstContextNativeBuild(1)==HFCN_BUILD && mFirstContext.code==HFC_OWNER && owner_calls==guard && read_calls==(guard<3?guard-1:2));no_packet();cases++;}
 for(unsigned field=0;field<7;field++){reset(roots[0]);mFirstContextNative.started=mFirstContextNative.running=mFirstContextNative.identity_valid=1;mFirstContextNative.root_physical=roots[0];mFirstContextNative.built_root_physical=roots[0];mFirstContextNative.config_root=roots[0];mFirstContextNative.tables=mScratchTables;mFirstContextNative.host_root[0]=mHostRingRoots[0];mFirstContextNative.host_root[1]=mHostRingRoots[1];mFirstContext=(struct hfc_result){.started=1,.phase=1};uint64_t v=0xa5;
  const uint32_t forbidden[]={0x3dc0018,0x3dc0024,0x3dc002c,0x3dc2020,0,0x3d0201c};assert(FirstContextNativeReadRoot(NULL,field<6?forbidden[field]:0x3dc0020,field==6?NULL:&v)==HFCN_ARGUMENT && !read_calls && !owner_calls && mFirstContextNative.rejected_reads==1 && v==0xa5);cases++;}
 reset(roots[0]);mFirstContext.started=1;assert(FirstContextNativeBuild(1)==HFCN_BUILD && mFirstContext.code==0 && mFirstContextNative.portable_return_code==HFC_REUSED && !owner_calls && !read_calls);no_packet();cases++;
 reset(roots[0]);mScratchConfig.table_physical+=4096;assert(FirstContextNativeBuild(1)==HFCN_ROOT && mFirstContextNative.root_physical==roots[0] && mFirstContextNative.config_root==roots[0]+4096 && !mFirstContextNative.identity_valid);mHostRingUnsafe=0;mGpuSaveAllowed=1;FirstContextNativeReport();assert(report_lines==2 && !owner_calls && !read_calls);cases++;
 reset(roots[0]);fail_read=2;assert(FirstContextNativeBuild(1)==HFCN_BUILD && mFirstContext.valid==1 && !mFirstContext.ttbr1);unsigned owners_before_report=owner_calls,reads_before_report=read_calls;mHostRingUnsafe=0;mGpuSaveAllowed=1;mFirstContextNative.running=1;FirstContextNativeReport();assert(!report_lines);mFirstContextNative.running=0;FirstContextNativeReport();assert(report_lines==2 && owner_calls==owners_before_report && read_calls==reads_before_report);cases++;
 // A mutable packet buffer must never be its own expected image. Each of all
 // 800 individual bits is rejected even when the caller passes that very same
 // buffer; a separate canonical image remains acceptable without extra MMIO.
 for(unsigned n=0;n<3;n++){reset(roots[n]);assert(!FirstContextNativeBuild(1));uint32_t canonical[HFC_WORDS];memcpy(canonical,mFirstContextNative.words,sizeof canonical);assert(FirstContextNativePacketMatches(canonical,HFC_WORDS));unsigned owners=owner_calls,reads=read_calls;
  for(unsigned word=0;word<HFC_WORDS;word++)for(unsigned bit=0;bit<32;bit++){mFirstContextNative.words[word]^=1u<<bit;assert(!FirstContextNativePacketMatches(mFirstContextNative.words,HFC_WORDS) && FirstContextNativePacketMatches(canonical,HFC_WORDS));mFirstContextNative.words[word]^=1u<<bit;assert(FirstContextNativePacketMatches(mFirstContextNative.words,HFC_WORDS));cases++;}
  assert(owner_calls==owners && read_calls==reads);cases++;
 }
 reset(roots[0]);assert(!FirstContextNativeBuild(1));uint32_t short_packet[1]={0};for(unsigned count=0;count<HFC_WORDS;count++){assert(!FirstContextNativePacketMatches(short_packet,count));cases++;}assert(!FirstContextNativePacketMatches(short_packet,HFC_WORDS+1) && !FirstContextNativePacketMatches(short_packet,UINT32_MAX) && !FirstContextNativePacketMatches(NULL,HFC_WORDS));assert(owner_calls==4 && read_calls==2);cases+=3;
 for(unsigned field=0;field<13;field++)for(unsigned iteration=0;iteration<2;iteration++){reset(roots[0]);assert(!FirstContextNativeBuild(1));unsigned *proof[]={&mFirstContextNative.started,&mFirstContextNative.running,&mFirstContextNative.ready,&mFirstContextNative.phase,&mFirstContextNative.code,&mFirstContextNative.portable_return_code,&mFirstContextNative.kmd_preemption_disabled,&mFirstContextNative.identity_valid,&mFirstContext.started,&mFirstContext.code,&mFirstContext.phase,&mFirstContext.ready,&mFirstContext.valid};unsigned original=*proof[field];*proof[field]=iteration?4:(original?0:1);assert(!FirstContextNativePacketMatches(mFirstContextNative.words,HFC_WORDS) && owner_calls==4 && read_calls==2);cases++;}
 for(unsigned field=0;field<8;field++)for(unsigned value=0;value<3;value+=2){reset(roots[0]);assert(!FirstContextNativeBuild(1));*mode_field(field)=field==7?value+1:value;assert(!FirstContextNativePacketMatches(mFirstContextNative.words,HFC_WORDS) && owner_calls==4 && read_calls==2);cases++;}
 for(unsigned field=0;field<7;field++){reset(roots[0]);assert(!FirstContextNativeBuild(1));mutate_identity(field);assert(!FirstContextNativePacketMatches(mFirstContextNative.words,HFC_WORDS) && owner_calls==4 && read_calls==2);cases++;}
 for(unsigned field=0;field<8;field++){reset(roots[0]);assert(!FirstContextNativeBuild(1));switch(field){case 0:mFirstContextNative.root_physical+=4096;break;case 1:mFirstContextNative.built_root_physical+=4096;break;case 2:mFirstContextNative.config_root+=4096;break;case 3:mFirstContextNative.tables=&table_storage[1];break;case 4:mFirstContextNative.host_root[0]^=4096;break;case 5:mFirstContextNative.host_root[1]^=UINT64_C(1)<<48;break;case 6:mFirstContext.ttbr0^=4096;break;default:mFirstContext.ttbr1^=UINT64_C(1)<<48;break;}assert(!FirstContextNativePacketMatches(mFirstContextNative.words,HFC_WORDS) && owner_calls==4 && read_calls==2);cases++;}
 printf("first-context actual native adapter: %u cases PASS (ASAN/UBSAN); no submission or GPU writes.\n",cases);return 0;}
'''
with tempfile.TemporaryDirectory(prefix='houji-first-context-native-') as td:
    source = Path(td)/'test.c'
    source.write_text(program)
    exe = Path(td)/'test'
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-I', str(p/'native/gpu/uefi'), str(source), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
