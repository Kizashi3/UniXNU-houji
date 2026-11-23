#!/usr/bin/env python3
"""Actual selected-word/verification paths; no GPU or EFI access."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "uefi/GpuHostRing.h"
#include "uefi/GpuKnownImage2d.h"
static unsigned checks;
#define C(X) do{++checks;assert(X);}while(0)
static uint8_t cpu[HGKI_BYTES];
static void device_write_markers(void) {
 for(unsigned m=0;m<HGKI_PROGRESS_MARKERS;m++)for(unsigned b=0;b<4;b++)
  cpu[4*m+b]=(uint8_t)(hgki_marker_value(m)>>(8*b));
}
static void device_write_pixels(void) {
 for(unsigned i=0;i<HGKI_OUTPUT_BYTES;i++)cpu[5*HGKI_PAGE+i]=(i%4==0 || i%4==3)?255:0;
}
int main(void) {
 C(HGKI_COMMAND_WORDS==247 && HGKI_SELECTED_COMMAND_WORDS==(HGKI_PROGRESS?287:247));
 C(hgki_source_ib()[0]==hhr_pkt7(0x3f,3) && hgki_source_ib()[1]==HGKI_COMMAND);
 C(hgki_source_ib()[3]==247 && hgki_ib[3]==HGKI_SELECTED_COMMAND_WORDS);
 const unsigned boundaries[]={0,2,11,185,213,240,242,247};
 unsigned source=0,selected=0,markers=0;
 while(source<HGKI_COMMAND_WORDS || selected<HGKI_SELECTED_COMMAND_WORDS) {
  if(HGKI_PROGRESS && markers<8 && source==boundaries[markers]) {
   C(hgki_marker_boundary(markers)==source);
   C(hgki_command_word(selected)==hhr_pkt7(0x3d,3));
   C(hgki_command_word(selected+1)==HGKI_BASE+markers*4);
   C(hgki_command_word(selected+2)==0);
   C(hgki_command_word(selected+3)==hgki_marker_value(markers));
   C(hgki_command_word(selected+4)==hhr_pkt7(0x12,0));
   C(hgki_command_word(selected+1)<HGKI_BASE+64 && hgki_command_word(selected+1)!=HGKI_OUTPUT);
   selected+=5;markers++;
   if(source==HGKI_COMMAND_WORDS)break;
  }
  uint32_t h=hgki_source_word(source);unsigned kind=h>>28,n=h&(kind==4?127:16383);
  C(kind==4 || kind==7);C(source+n+1<=HGKI_COMMAND_WORDS);
  for(unsigned i=0;i<=n;i++)C(hgki_command_word(selected+i)==hgki_source_word(source+i));
  source+=n+1;selected+=n+1;
 }
 C(source==247 && selected==HGKI_SELECTED_COMMAND_WORDS && markers==HGKI_PROGRESS_MARKERS);
 C(hgki_command_word(HGKI_SELECTED_COMMAND_WORDS)==0);
 C(hgki_marker_boundary(8)==UINT32_MAX && !hgki_marker_value(8));
 C(!hgki_build(cpu,sizeof cpu));
 for(unsigned i=0;i<HGKI_MARKER_BYTES;i++)C(cpu[i]==0xa5);
 for(unsigned i=0;i<HGKI_OUTPUT_BYTES;i++)C(cpu[5*HGKI_PAGE+i]==0x6d);
 for(unsigned i=0;i<HGKI_SELECTED_COMMAND_WORDS;i++) {
  uint32_t v=0;for(unsigned b=0;b<4;b++)v|=(uint32_t)cpu[4*HGKI_PAGE+4*i+b]<<(8*b);
  C(v==hgki_command_word(i));
 }
 struct hgki_result r={0};C(hgki_verify(cpu,sizeof cpu,&r)!=HGKI_OK && !r.verified);
 device_write_markers();memset(&r,0,sizeof r);
 C(hgki_verify(cpu,sizeof cpu,&r)==HGKI_COLOR && !r.verified);
 device_write_pixels();memset(&r,0,sizeof r);
 C(hgki_verify(cpu,sizeof cpu,&r)==HGKI_OK && r.verified && r.output_crc==0xe843b26a);
 cpu[64]^=1;C(hgki_verify(cpu,sizeof cpu,&r)==HGKI_CHANGED && !r.verified);cpu[64]^=1;
 for(unsigned m=0;m<HGKI_PROGRESS_MARKERS;m++) {
  cpu[m*4]^=1;memset(&r,0,sizeof r);
  C(hgki_verify(cpu,sizeof cpu,&r)==HGKI_CHANGED && !r.verified && r.first_bad==m*4);
  cpu[m*4]^=1;
 }
 /* Neither complete markers nor complete pixels can excuse a changed guard,
  * border, preamble, command byte, padding or any image byte. */
 const unsigned bad[]={64,4095,4096,8191,8192,12288,16384,20479,20480,24575,24576,28671};
 for(unsigned i=0;i<sizeof bad/sizeof *bad;i++) {
  cpu[bad[i]]^=1;memset(&r,0,sizeof r);C(hgki_verify(cpu,sizeof cpu,&r)!=HGKI_OK && !r.verified);
  C(r.first_bad==bad[i]);cpu[bad[i]]^=1;
 }
 C(HGKI_MARKER_BYTES<=64 && HGKI_SELECTED_COMMAND_WORDS*4<HGKI_PAGE);
 printf("%u actual selected-2D/marker checks PASS progress=%u\n",checks,HGKI_PROGRESS);
}
'''
with tempfile.TemporaryDirectory(prefix="houji-2d-progress-") as tmp:
    source, binary = Path(tmp)/"progress.c", Path(tmp)/"progress"
    source.write_text(SOURCE)
    for progress in (0, 1):
        subprocess.run([
            "clang", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer", f"-DHGKI_PROGRESS={progress}",
            "-I", str(ROOT/"native/gpu"), str(source), "-o", str(binary)
        ], check=True)
        env=os.environ.copy()
        env.update(ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",UBSAN_OPTIONS="halt_on_error=1")
        subprocess.run([str(binary)],check=True,env=env)
