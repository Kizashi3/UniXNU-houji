#!/usr/bin/env python3
"""Check the actual firmware dispatcher retains gates on all context errors."""
from pathlib import Path
import subprocess
import tempfile
p=Path(__file__).resolve().parents[1]
s=(p/'native/gpu/uefi/GpuPower.c').read_text()
body='STATIC unsigned RunGmuProbe'+s.split('STATIC unsigned RunGmuProbe',1)[1].split('STATIC int TableAllocate',1)[0]
program=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "GpuGmuProbe.h"
#include "GpuSmmuContext.h"
#define STATIC static
#define CONST const
#define VOID void
#define NULL ((void*)0)
#define TRUE 1
#define EFI_ERROR(x) ((x)!=0)
#define Print(...) ((void)0)
typedef uint64_t EFI_STATUS;
static struct hgd_result mGmuResult;
static struct hgp_result mContextResult;
static unsigned mGmuCalled,mode,called,secure_called,stock_called;
static GPP_U64 GmuRead(void*c,GPP_U32 a,GPP_U32*v){(void)c;(void)a;(void)v;return 0;}
static GPP_U64 GmuWrite(void*c,GPP_U32 a,GPP_U32 v){(void)c;(void)a;(void)v;return 0;}
static GPP_U64 Delay(void*c,unsigned us){(void)c;(void)us;return 0;}
static GPP_U64 GmuCheckpoint(void*c,unsigned stage){(void)c;(void)stage;return 0;}
static EFI_STATUS MapMmio(uint64_t a,uint64_t n){(void)a;(void)n;return 0;}
static EFI_STATUS PrepareGmuHub(const struct gpp_report*p,const struct hgb_result*b){(void)p;(void)b;return mode==9;}
static unsigned fake_probe(const struct hgd_io*io,const struct gpp_report*p,const struct hgb_result*b,struct hgd_result*r){
 (void)io;(void)p;(void)b;r->reset_held=mode!=7;r->code=mode==8;return r->code;}
static unsigned RunDisabledContext(void){called++;mContextResult.safe_to_release=mode!=6;return mode==10?6:(mode<=5?mode:0);}
static unsigned RunSecureCxBatch(void){secure_called++;return mode==11;}
static unsigned RunStockGmuBatch(void){stock_called++;return mode==12;}
#define hgd_probe fake_probe
'''+body+r'''
int main(void){
 struct gpp_report p={0};struct hgb_result b={0};
 for(mode=0;mode<13;mode++){
  called=mGmuCalled=secure_called=stock_called=0;unsigned code=RunGmuProbe(&p,&b);
  if(!mode)assert(!code && called==1 && secure_called==1);
  else if(mode==11)assert(code==HGB_RETAIN && called==1 && secure_called==1 && !stock_called);
  else if(mode==12)assert(code==HGB_RETAIN && called==1 && secure_called==1 && stock_called==1);
  else if(mode<=6 || mode==10)assert(code==HGB_RETAIN && called==1 && !secure_called);
  else if(mode==7)assert(code==HGB_RETAIN && !called);
  else assert(code==HGB_ACTION && !called);
 }
 puts("PASS: actual dispatcher; every disabled-context error retains bus/tables, unknown CM3 reset retains resources, preconditions never dispatch a context");
}
'''
with tempfile.TemporaryDirectory() as directory:
 d=Path(directory);(d/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-Wno-macro-redefined',
  '-fsanitize=address,undefined','-I',str(p/'native/gpu'),'-I',str(p/'native/gpu/uefi'),
  str(d/'test.c'),'-o',str(d/'test')],check=True)
 subprocess.run([str(d/'test')],check=True)
