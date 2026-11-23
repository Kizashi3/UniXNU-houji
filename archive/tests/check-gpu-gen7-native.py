#!/usr/bin/env python3
"""Compile the actual native callbacks; test exact step/value/permission gates."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parents[1];s=(p/'native/gpu/uefi/GpuGen7Native.h').read_text()
def fn(name):
 a=s.index('STATIC int '+name+'(');b=s.index('{',a)+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b].replace('__asm__ volatile("dsb sy":::"memory");','')
body=fn('Gen7Read')+'\n'+fn('Gen7Write')+'\n'+fn('Gen7Publish')
program=r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "GpuGen7Config.h"
#include "GpuCodeMemory.h"
#define STATIC static
#define VOID void
#define BOOLEAN int
#define CONST const
#define TRUE 1
#define FALSE 0
#define UINTN uintptr_t
static struct h7c_result mGen7;static unsigned good=1,reads,writes,cases;
static unsigned bad_audit,bad_publish;
static _Alignas(4096) uint8_t arena[HCC_BYTES];
static struct {void *cpu;} mCodeMemory={arena};
static int Gen7Guard(void*c){(void)c;return !good;}
static int ScratchAudit(void){return (int)bad_audit;}
static int FirmwarePublish(void*c,void*m){(void)c;(void)m;return (int)bad_publish;}
static uint32_t MmioRead32(uint32_t a){(void)a;reads++;return 0;}
static void MmioWrite32(uint32_t a,uint32_t v){(void)a;(void)v;writes++;}
'''+body+r'''
int main(void){uint32_t value;
 for(unsigned i=0;i<H7C_OPS;i++) {
  mGen7.phase=2;mGen7.step=i;const struct h7c_op*o=&h7c_ops[i];struct h7c_record*r=&mGen7.records[i];
  r->before=0xa55a5aa5;r->expected=o->kind==1?(r->before&~o->mask)|o->value:o->value;r->valid=3;
  unsigned old=writes;assert((!Gen7Write(0,o->address,r->expected))==(o->kind!=3) && writes==old+(o->kind!=3));cases++;
  for(unsigned bit=0;bit<32;bit++){old=writes;assert(Gen7Write(0,o->address,r->expected^(1u<<bit)) && writes==old);cases++;}
  r->valid=0;old=writes;assert(Gen7Write(0,o->address,r->expected) && old==writes);cases++;r->valid=3;
  good=0;old=writes;assert(Gen7Write(0,o->address,r->expected) && old==writes);cases++;good=1;
  mGen7.phase=3;old=writes;assert(Gen7Write(0,o->address,r->expected) && old==writes);cases++;
 }
 for(uint32_t a=0x3d00000;a<0x3e00000;a+=4) {
  unsigned allowed=a==0x3d02020;for(unsigned i=0;i<H7C_OPS;i++)allowed|=h7c_ops[i].kind!=2 && h7c_ops[i].address==a;
  for(unsigned i=0;i<H7C_PAIRS;i++)allowed|=h7c_power_regs[i].address==a;
  unsigned old=reads;assert((!Gen7Read(0,a,&value))==!!allowed && reads==old+!!allowed);cases++;
 }
 for(unsigned i=0;i<H7C_OPS;i++) {
  mGen7.phase=2;mGen7.step=i;unsigned old=writes;assert(Gen7Write(0,0x3d02020,1) && Gen7Write(0,0x3d0f400,0) && writes==old);cases++;
 }
 good=0;unsigned old=reads;assert(Gen7Read(0,0x3d02020,&value) && reads==old);cases++;
 assert(Gen7Read(0,0x3d02020,0));cases++;
 good=1;uint32_t words[H7C_WORDS]={0};words[3]=H7C_IFPC|(H7C_PREEMPT<<8);
 mGen7.completed=H7C_OPS;mGen7.power_pairs=H7C_PAIRS;
 for(unsigned i=0;i<H7C_PAIRS;i++){mGen7.power_values[i]=0x12340000+i;words[4+2*i]=(h7c_power_regs[i].address-0x3d00000)/4;words[5+2*i]=mGen7.power_values[i];}
 memset(arena,0xa5,sizeof(arena));memset(arena+HCC_RECORD_OFFSET,0,4096);
 for(unsigned i=0;i<H7C_WORDS;i++)for(unsigned bit=0;bit<32;bit++) {
  words[i]^=1u<<bit;assert(Gen7Publish(0,words,H7C_WORDS));words[i]^=1u<<bit;
  for(unsigned at=0;at<4096;at++)assert(!arena[HCC_RECORD_OFFSET+at]);cases++;
 }
 assert(Gen7Publish(0,words,H7C_WORDS-1) && Gen7Publish(0,words,H7C_WORDS+1));cases++;
 bad_audit=1;assert(Gen7Publish(0,words,H7C_WORDS));bad_audit=0;cases++;
 good=0;assert(Gen7Publish(0,words,H7C_WORDS));good=1;cases++;
 assert(!Gen7Publish(0,words,H7C_WORDS) && mGen7.record_crc==hcc_crc32(arena+HCC_RECORD_OFFSET,4096));
 assert(!memcmp(arena+HCC_RECORD_OFFSET,words,sizeof(words)));
 for(unsigned at=0;at<HCC_BYTES;at++)if(at<HCC_RECORD_OFFSET || at>=HCC_RECORD_OFFSET+4096)assert(arena[at]==0xa5);cases++;
 assert(Gen7Publish(0,words,H7C_WORDS));cases++; // No overwrite of already populated record.
 memset(arena+HCC_RECORD_OFFSET,0,4096);bad_publish=1;assert(Gen7Publish(0,words,H7C_WORDS));cases++;
 printf("PASS: %u actual native whitelist cases; exact current step and expected data, preserved RMW bits, guard-before-I/O, CP enable/trust writes impossible\n",cases);
}
'''
with tempfile.TemporaryDirectory() as folder:
 f=Path(folder);(f/'test.c').write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(p/'native/gpu'),'-I',str(p/'native/gpu/uefi'),str(f/'test.c'),'-o',str(f/'test')],check=True)
 subprocess.run([str(f/'test')],check=True)
