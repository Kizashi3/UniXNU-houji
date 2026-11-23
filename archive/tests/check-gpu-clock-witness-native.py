#!/usr/bin/env python3
"""Exercise the actual read-only witness policy and UEFI glue under sanitizers.

Only the clock protocol, existing owner guards, exact read leaf and log sink
are mocked. No device access, frequency-changing API or firmware build occurs.
"""
from pathlib import Path
import re
import subprocess
import tempfile

p = Path(__file__).resolve().parents[1]
uefi = p / 'native/gpu/uefi'
policy = (uefi / 'GpuClockWitness.h').read_text()
stock = (uefi / 'GpuStockGmu.h').read_text()

def array(text, name):
    match = re.search(r'\b' + name + r'\s*\[\]\s*=\s*\{([^}]+)\}', text)
    assert match, name
    return [int(x.strip(), 0) for x in match[1].split(',')]

# Cross-check the actual running-CM3 baseline, rather than a copied fixture.
power_guard = stock[stock.index('static inline int hgf_power('):stock.index('static inline int hgf_health(')]
witness_guard = policy[policy.index('static inline int hcw_guard('):policy.index('static inline int hcw_snapshot(')]
assert array(witness_guard, 'a')[:7] == array(power_guard, 'a')
assert array(witness_guard, 'mask')[:7] == array(power_guard, 'masks')
assert array(witness_guard, 'want')[:7] == array(power_guard, 'wanted')
assert array(witness_guard, 'a')[7] == 0x3d7e000
assert array(witness_guard, 'mask')[7] == 0xffffffff

# Compile the real call-site prefix too: a failed R0 must retain gates and
# return through the existing outer retained-stop/durable recovery path.
power_source = (uefi / 'GpuPower.c').read_text()
start = power_source.index('STATIC unsigned RunGmuProbe(VOID *Cookie,CONST struct hgb_result *Bus) {')
end = power_source.index('  EFI_STATUS Config=MapMmio(', start)
prelude = power_source[start:end].replace('RunGmuProbe(', 'RunWitnessPrelude(', 1) + '  return 0;\n}\n'
prelude = re.sub(r'  CONST struct hgd_io Io=\{[^;]*;\n', '', prelude)
assert 'return HGB_RETAIN' in prelude
program = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
#define STATIC static
#define CONST const
#define VOID void
typedef uint64_t UINTN;
typedef uint64_t EFI_STATUS;
#define EFI_INVALID_PARAMETER UINT64_C(0x8000000000000002)
#define NOT_STARTED UINT64_C(0x8000000000000013)
enum {GPP_GMU_RATE,GPP_HUB_RATE,GPP_GMU_CLK,GPP_HUB_CLK,GPP_RESOURCE_COUNT};
struct gpp_report {unsigned owned;};
struct hgb_result {unsigned complete;};
typedef struct clock_protocol CLOCK_PROTOCOL;
struct clock_protocol {uint64_t Version;EFI_STATUS (*GetClockFreqHz)(CLOCK_PROTOCOL *,UINTN,uint32_t *);};
static CLOCK_PROTOCOL protocol,*mClock;
static UINTN mIds[GPP_RESOURCE_COUNT];
static unsigned mode_now,owner_calls,bus_calls,host_calls,read_calls,query_calls,prints;
static unsigned hub_calls,checkpoint_calls;
static EFI_STATUS hub_status,checkpoint_status;
static unsigned fail_owner,fail_bus,fail_host,fail_read,cases,unstable_index,bad_guard_at,bad_guard_index;
static uint32_t xor_guard,xor_raw,raw[20],raw_second[20];
static uint64_t statuses[2];
static uint32_t configured[2];
static unsigned address_count[20],guard_reads[8];
static struct gpp_report power;
static struct hgb_result bus;
static int hgb_owned(const struct gpp_report *pwr) {assert(pwr==&power);return pwr->owned && ++owner_calls!=fail_owner;}
static int hgd_bus_complete(const struct hgb_result *b) {assert(b==&bus);return b->complete && ++bus_calls!=fail_bus;}
static int HostPreparationGuard(void *cookie) {assert(cookie==NULL);return ++host_calls==fail_host;}
static int GpuTryRead32(uint64_t,uint32_t *);
static void CapturePrint(const wchar_t *,...);
#define Print CapturePrint
#include "GpuClockWitnessNative.h"
enum {HGB_ACTION=100,HGB_RETAIN=101};
#define EFI_ERROR(status) (((uint64_t)(status)>>63)!=0)
static EFI_STATUS PrepareGmuHub(const struct gpp_report *pwr,const struct hgb_result *b) {
 assert(pwr==&power && b==&bus && !hub_calls++);return hub_status;
}
static uint64_t GmuCheckpoint(void *cookie,unsigned stage) {
 assert(cookie==NULL && stage==0 && !checkpoint_calls++ && mClockWitness[0].started && !mClockWitness[0].code);return checkpoint_status;
}
/*ACTUAL_PRELUDE*/
static EFI_STATUS GetConfigured(CLOCK_PROTOCOL *clock,UINTN id,uint32_t *out) {
 assert(clock==&protocol && out && query_calls<2);
 unsigned which=query_calls++;
 assert(id==mIds[which?GPP_HUB_RATE:GPP_GMU_RATE]);
 assert(read_calls==8+14+(address_count[HCW_PLL0_MODE]?6:0));
 *out=configured[which];return statuses[which];
}
static int GpuTryRead32(uint64_t address,uint32_t *value) {
 static const uint32_t guards[]={0x171004,0x171010,0x171018,0x3d97000,
  0x3d99108,0x3d99168,0x3d9911c,0x3d7e000};
 static const uint32_t values[]={1,1,1,1,0,0x80000000,0,0};
 assert(value && ++read_calls<100);
 if(read_calls==fail_read)return 1;
 for(unsigned i=0;i<8;i++)if(address==guards[i]) {
  unsigned at=guard_reads[i]++;
  *value=i==7?(mode_now?0:1):values[i];
  if(at==bad_guard_at && i==bad_guard_index)*value^=xor_guard;
  return 0;
 }
 for(unsigned i=0;i<HCW_REGS;i++)if(address==hcw_address(i)) {
  unsigned at=address_count[i]++;
  assert(at<2);
  unsigned sample=query_calls?1u:0u;
  uint32_t cfg=sample?raw_second[HCW_GMU_CFG]:raw[HCW_GMU_CFG];
  if(sample && unstable_index==HCW_GMU_CFG)cfg^=xor_raw;
  if(i>=HCW_PLL0_MODE)assert(((cfg>>8)&7)==1);
  *value=sample?raw_second[i]:raw[i];
  if(sample && i==unstable_index)*value^=xor_raw;
  return 0;
 }
 assert(!"unexpected MMIO read");return 1;
}
static void CapturePrint(const wchar_t *fmt,...) {
 assert(fmt);prints++;
 if(wcsstr(fmt,L"CLOCK CONFIGURED")) {
  assert(wcsstr(fmt,L"software cache only") && wcsstr(fmt,L"Not started means unavailable rather than 0 Hz") && wcsstr(fmt,L"not measured"));
 } else if(wcsstr(fmt,L"CLOCK DERIVED")) {
  assert(wcsstr(fmt,L"nominal-hz") && wcsstr(fmt,L"not measured") && wcsstr(fmt,L"unavailable"));
 }
}
static void reset(unsigned mode,unsigned src) {
 memset(mClockWitness,0,sizeof mClockWitness);memset(raw,0,sizeof raw);
 memset(raw_second,0,sizeof raw_second);memset(address_count,0,sizeof address_count);memset(guard_reads,0,sizeof guard_reads);
 protocol=(CLOCK_PROTOCOL){0x1000a,GetConfigured};mClock=&protocol;
 mIds[GPP_GMU_RATE]=mIds[GPP_GMU_CLK]=0x10159;
 mIds[GPP_HUB_RATE]=mIds[GPP_HUB_CLK]=0x10164;
 power.owned=bus.complete=1;mode_now=mode;
 owner_calls=bus_calls=host_calls=read_calls=query_calls=prints=0;
 fail_owner=fail_bus=fail_host=fail_read=xor_guard=xor_raw=0;
 hub_calls=checkpoint_calls=0;hub_status=checkpoint_status=0;
 unstable_index=bad_guard_at=bad_guard_index=~0u;
 statuses[0]=NOT_STARTED;statuses[1]=0;configured[0]=0;configured[1]=200000000;
 raw[HCW_GMU_CFG]=(src<<8)|(src==1 || src==3?3:0);
 raw[HCW_HUB_CFG]=0x505;
 raw[HCW_PLL1_MODE]=raw[HCW_PLL0_MODE]=0x80000005;
 raw[HCW_PLL1_OPMODE]=raw[HCW_PLL0_OPMODE]=1;
 raw[HCW_PLL1_L]=0x41;raw[HCW_PLL1_ALPHA]=0x1aaa;raw[HCW_PLL1_USER]=1;
 raw[HCW_PLL0_L]=0x1b;raw[HCW_PLL0_ALPHA]=0x1555;raw[HCW_PLL0_USER]=1;
 memcpy(raw_second,raw,sizeof raw);
}
static unsigned run(void) {return mode_now?GpuClockWitnessR1():GpuClockWitnessR0(&power,&bus);}
static void success(unsigned mode,unsigned src) {
 reset(mode,src);assert(!run());struct hcw_result *r=&mClockWitness[mode];
 assert(r->code==0 && r->phase==7 && r->stable && r->guards==2 && r->queries==2);
 assert(query_calls==2 && r->configured_status[0]==NOT_STARTED && !r->configured_hz[0]);
 assert(r->configured_hz[1]==200000000 && !r->derived_valid[1] && !r->derived_hz[1]);
 assert(r->source[0]==src && r->hid[0]==(src==1 || src==3?3:0));
 assert(owner_calls==(mode?0u:2u) && bus_calls==(mode?0u:2u) && host_calls==(mode?2u:0u));
 assert(read_calls==16+2*(src==1?20:14) && prints==(src==1?11u:9u));
 assert(r->valid[0]==(src==1?0xfffffu:0x3fffu) && r->valid[1]==r->valid[0]);
 for(unsigned i=0;i<HCW_REGS;i++)assert(address_count[i]==(i<14 || src==1?2u:0u));
 for(unsigned i=0;i<8;i++)assert(guard_reads[i]==2);
 if(src==0)assert(r->derived_valid[0] && r->derived_hz[0]==19200000);
 else if(src==3)assert(r->derived_valid[0] && r->derived_hz[0]==624999902);
 else if(src==1)assert(r->derived_valid[0] && r->derived_hz[0]==259999951);
 else assert(!r->derived_valid[0] && !r->derived_hz[0]);
 unsigned before=read_calls,queries=query_calls,owners=owner_calls,hosts=host_calls;
 assert(run()==HCW_REUSED && read_calls==before && query_calls==queries && owner_calls==owners && host_calls==hosts);cases++;
}
int main(void) {
 for(unsigned mode=0;mode<2;mode++)for(unsigned src=0;src<8;src++)success(mode,src);
 for(unsigned mode=0;mode<2;mode++)for(unsigned src=1;src<=3;src+=2) {
  unsigned total=16+2*(src==1?20:14);
  for(unsigned n=1;n<=total;n++) {
   reset(mode,src);fail_read=n;assert(run() && read_calls==n && !mClockWitness[mode].stable);
   assert(!mClockWitness[mode].derived_valid[0] && !mClockWitness[mode].derived_valid[1]);cases++;
  }
 }
 // Every bit checked in both pre/post owned power/reset masks must refuse.
 const uint32_t masks[]={0x80000003,0x80000003,0x80000001,0x80000001,1,0x80000000,0x80000000,0xffffffff};
 for(unsigned mode=0;mode<2;mode++)for(unsigned at=0;at<2;at++)for(unsigned i=0;i<8;i++)for(unsigned bit=0;bit<32;bit++)if(masks[i]&(1u<<bit)) {
  reset(mode,3);bad_guard_at=at;bad_guard_index=i;xor_guard=1u<<bit;
  assert(run()==HCW_GUARD && !mClockWitness[mode].stable);
  assert(query_calls==(at?2u:0u));cases++;
 }
 for(unsigned mode=0;mode<2;mode++)for(unsigned which=0;which<4;which++)for(unsigned bit=0;bit<32;bit++) {
  const unsigned regs[]={HCW_GMU_CMD,HCW_GMU_CFG,HCW_HUB_CMD,HCW_HUB_CFG};
  reset(mode,3);unstable_index=regs[which];xor_raw=1u<<bit;
  assert(run()==HCW_UNSTABLE && !mClockWitness[mode].stable && !mClockWitness[mode].derived_valid[0]);cases++;
 }
 for(unsigned mode=0;mode<2;mode++)for(unsigned which=0;which<6;which++) {
  reset(mode,3);
  if(which==0)raw[HCW_GMU_CMD]|=1;
  if(which==1)raw[HCW_GMU_CMD]|=0x80000000;
  if(which==2)raw[HCW_GMU_BRANCH]|=0x80000000;
  if(which==3)raw[HCW_GMU_CFG]|=0x2000;
  if(which==4)raw[HCW_PLL1_MODE]&=~0x80000000u;
  if(which==5)raw[HCW_PLL1_OPMODE]=0;
  memcpy(raw_second,raw,sizeof raw);assert(!run() && !mClockWitness[mode].derived_valid[0]);cases++;
 }
 for(unsigned mode=0;mode<2;mode++)for(unsigned i=0;i<6;i++)if(i!=2) {
  reset(mode,3);raw_second[HCW_PLL1_MODE+i]^=1;assert(!run() && !mClockWitness[mode].derived_valid[0]);cases++;
 }
 for(unsigned mode=0;mode<2;mode++)for(unsigned gate=0;gate<9;gate++) {
  reset(mode,3);
  if(gate==0)mClock=NULL;
  if(gate==1)protocol.Version++;
  if(gate==2)protocol.GetClockFreqHz=NULL;
  if(gate==3)mIds[GPP_GMU_RATE]++;
  if(gate==4)mIds[GPP_HUB_RATE]++;
  if(gate==5)mIds[GPP_GMU_RATE]=mIds[GPP_GMU_CLK]=0x20159;
  if(gate==6)mIds[GPP_HUB_RATE]=mIds[GPP_HUB_CLK]=0x20164;
  if(gate==7)mIds[GPP_GMU_RATE]=mIds[GPP_GMU_CLK]=UINT64_C(0x10000010159);
  if(gate==8)mIds[GPP_HUB_RATE]=mIds[GPP_HUB_CLK]=UINT64_C(0x10000010164);
  assert(run()==HCW_GUARD && !read_calls && !query_calls);cases++;
 }
 for(unsigned mode=0;mode<2;mode++)for(unsigned at=1;at<=2;at++) {
  reset(mode,3);if(mode)fail_host=at;else fail_owner=at;
  assert(run()==HCW_GUARD && query_calls==(at==2?2u:0u));cases++;
  if(!mode){reset(mode,3);fail_bus=at;assert(run()==HCW_GUARD && query_calls==(at==2?2u:0u));cases++;}
 }
 for(unsigned mode=0;mode<2;mode++)for(unsigned which=0;which<2;which++) {
  reset(mode,3);statuses[which]=EFI_INVALID_PARAMETER;configured[which]=0;
  assert(!run() && mClockWitness[mode].configured_status[which]==EFI_INVALID_PARAMETER && mClockWitness[mode].stable);cases++;
 }
 struct hcw_result r={0};const struct hcw_io io={NULL,ClockWitnessOwned,ClockWitnessRead,ClockWitnessConfigured};
 assert(hcw_run(NULL,0,&r)==HCW_ARGUMENT);cases++;
 r=(struct hcw_result){0};assert(hcw_run(&io,2,&r)==HCW_ARGUMENT);cases++;
 assert(hcw_run(&io,0,NULL)==HCW_ARGUMENT);cases++;
 reset(0,3);assert(!RunWitnessPrelude(&power,&bus) && hub_calls==1 && checkpoint_calls==1 && mClockWitness[0].phase==7);cases++;
 reset(0,3);hub_status=EFI_INVALID_PARAMETER;assert(RunWitnessPrelude(&power,&bus)==HGB_ACTION && !mClockWitness[0].started && !checkpoint_calls && !read_calls);cases++;
 reset(0,3);fail_read=1;assert(RunWitnessPrelude(&power,&bus)==HGB_RETAIN && mClockWitness[0].code==HCW_GUARD && !checkpoint_calls);cases++;
 reset(0,3);checkpoint_status=EFI_INVALID_PARAMETER;assert(RunWitnessPrelude(&power,&bus)==HGB_ACTION && mClockWitness[0].phase==7 && checkpoint_calls==1);cases++;
 printf("PASS: %u actual GMU/HUB clock witness cases; native ownership/ABI/cache glue, every read/guard failure, double-sample changes, conditional PLL0, target PLL/div formulas, no hardware writes or measurement\n",cases);
}
'''
with tempfile.TemporaryDirectory() as d:
    tmp = Path(d)
    (tmp / 'test.c').write_text(program.replace('/*ACTUAL_PRELUDE*/', prelude))
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-I', str(p / 'native/gpu/uefi'),
                    str(tmp / 'test.c'), '-o', str(tmp / 'test')], check=True)
    subprocess.run([str(tmp / 'test')], check=True)
