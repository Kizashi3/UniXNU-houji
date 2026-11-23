/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Same governor shape as sheng, own full factory A750 host-table levels; hardware qualification pending.
 * Runs under NativeAdreno's existing issuer lock, including HFI ACK handling.
 * Gen7 initialization ALREADY selects XO counter0, countable5 and enables it.
 */
#include "HoujiGpuGovernorPolicy.h"
extern "C" uint64_t houji_dvfs_touch_time(void);
extern "C" uint64_t houji_dvfs_touch_burst_time(void);
extern "C" unsigned houji_thermal_gpu_cap(void);
extern "C" void houji_thermal_start(void);
static struct {
 unsigned enabled,ready,bad,level=HCO_BOOT_LEVEL,cap=HCO_DEFAULT_CAP,low,changes,failed,busyPermille;
 uint64_t last,lastBusy,lastTouch,idleAt,wakeUntil,lastSubmits,windowNs,busyNs,at[HCO_COUNT+1],invalid;
 unsigned wakeBoosts,touchPrewarms,touchBursts,touchActive,touchLate;bool idle;HoujiGpuGovernorPolicy policy;
 uint64_t touchWakeUntil;
 uint64_t historyAt,historyNs,historyBusy,history231,history500,maxTickUs;
} gHoujiDvfs;
struct HoujiGpuDvfsWindow {uint64_t upUs,spanUs,busyUs,at231Us,at500Us,maxTickUs;unsigned changes,wakes;};
static HoujiGpuDvfsWindow houjiGpuDvfsHistory[48];
static unsigned houjiGpuDvfsHistoryCount;
// Last input prewarms, published after the corresponding HFI decision. All
// writes occur under the issuer lock; the terminal snapshot reads cached data.
struct HoujiGpuTouchWakeRecord {uint64_t sequence,atUs,ageUs;unsigned before,after,cap,busy,active;};
static HoujiGpuTouchWakeRecord houjiGpuTouchWakeRecords[8];
static bool houjiDvfsRead(uint32_t a,uint32_t *v){
 if(!native_adreno_board_running() || !v)return false;
 auto*p=houjiFullPointer(a,4);if(!p)return false;
 *v=*(const volatile uint32_t*)p;houjiStockReadBarrier();return true;
}
static bool houjiDvfsBusy(uint64_t *out){
 uint32_t h=0,l=0,h2=0;
 if(!houjiDvfsRead(0x3d7e114,&h) || !houjiDvfsRead(0x3d7e110,&l) || !houjiDvfsRead(0x3d7e114,&h2))return false;
 if(h2!=h && !houjiDvfsRead(0x3d7e110,&l))return false;
 *out=(uint64_t(h2)<<32)|l;return true;
}
static int houjiDvfsOwner(void*){return native_adreno_board_running() && houjiCpBusLease() && !gHoujiCp.stopping && !gHoujiCp.isolated;}
static int houjiDvfsBarrier(void*){if(!houjiDvfsOwner(nullptr))return 1;houjiStockFullBarrier();return 0;}
static int houjiDvfsDelay(void*,unsigned us){if(us!=10 || !houjiDvfsOwner(nullptr))return 1;IODelay(us);return 0;}
static int houjiDvfsDoorbell(void*){if(!houjiDvfsOwner(nullptr))return 1;auto*p=houjiFullPointer(0x3d7e650,4);if(!p)return 1;*(volatile uint32_t*)p=1;houjiStockFullBarrier();return 0;}
extern "C" void houji_gpu_dvfs_tick(void){
 auto&v=gHoujiDvfs;if(!v.enabled || v.bad || !native_adreno_board_running())return;
 uint64_t now=houjiSubmitNow(nullptr),busy=0;
 if(!houjiDvfsBusy(&busy)){v.bad=1;return;}
 if(!v.ready){
  uint32_t enable=0,select=0;
  if(!houjiDvfsRead(0x3d7e100,&enable) || !houjiDvfsRead(0x3d7e104,&select) || enable!=1 || (select&255)!=32){v.bad=1;IOLog("HOUJI GPU DVFS: existing XO counter selection invalid; no vote changes\n");return;}
  v.last=now;v.lastBusy=busy;v.idleAt=now;v.historyAt=now;v.ready=1;
  IOLog("HOUJI GPU OPP: 12 advertised factory levels 231..903 MHz; cap=%u MHz, boot=500 MHz; SKU bin5/AB; firmware HFI votes, no PLL writes; TSENS junction cap active; hardware validation pending\n",hco_opp(v.cap)->khz/1000);return;
 }
 uint64_t us=now-v.last;if(us<16000)return;
 if(us>v.maxTickUs)v.maxTickUs=us;
 uint64_t delta=busy-v.lastBusy;v.lastBusy=busy;v.last=now;
 if(delta>us*192/10+19200){++v.invalid;return;} // reject reset/backwards rather than fake 100% load
 uint64_t ns=us*1000,busyNs=delta*625/12;if(busyNs>ns)busyNs=ns;
 v.busyPermille=(unsigned)(busyNs*1000/ns);v.windowNs+=ns;v.busyNs+=busyNs;v.at[v.level]+=ns;
 uint64_t submits=gHoujiSubmit.ring.lastSubmitted();
 bool active=busyNs || submits!=v.lastSubmits || gHoujiApi.submit.outstanding();v.lastSubmits=submits;
 if(!active && now-v.idleAt>=80000)v.idle=true;
 if(active && v.idle){v.idle=false;v.wakeUntil=now+50000;++v.wakeBoosts;}
 if(active)v.idleAt=now;
 uint64_t touch=houji_dvfs_touch_time(),touchNs=0;
 if(touch){uint64_t abs=mach_absolute_time();if(abs>=touch)absolutetime_to_nanoseconds(abs-touch,&touchNs);}
 uint64_t burstNs=0;absolutetime_to_nanoseconds(houji_dvfs_touch_burst_time(),&burstNs);
 const uint64_t burstUs=burstNs/1000;
 const uint64_t previousBurst=v.lastTouch;
 const bool inputWake=houjiGpuArmTouchWake(now,burstUs,v.idle,&v.lastTouch,&v.touchWakeUntil);
 if(v.lastTouch!=previousBurst){
  __atomic_fetch_add(&v.touchBursts,1u,__ATOMIC_RELAXED);
  if(!inputWake)__atomic_fetch_add(v.idle?&v.touchLate:&v.touchActive,1u,__ATOMIC_RELAXED);
 }
 const unsigned before=v.level;
 unsigned thermal=houji_thermal_gpu_cap();
 unsigned cap=thermal<v.cap?thermal:v.cap;if(!cap)cap=1;
 unsigned want=houjiGpuChoose(&v.policy,v.level,cap,v.busyPermille,active,
  touch && touchNs<1000000000ULL,(now<v.wakeUntil?1u:0u)|(now<v.touchWakeUntil?2u:0u),(unsigned)gHoujiApi.submit.outstanding());
 if(!hco_opp(want)){v.bad=1;IOLog("HOUJI GPU DVFS: invalid policy output; no vote changes\n");return;}
 if(want!=v.level){
  uint32_t reply[6]={};const FhrRuntimeIo io={nullptr,houjiDvfsOwner,houjiDvfsDoorbell,houjiDvfsBarrier,houjiDvfsDelay};int code=fhr_runtime_vote(&gHoujiFull.storage,sizeof(gHoujiFull.storage),&io,want,reply);
  if(code){++v.failed;v.bad=1;IOLog("HOUJI GPU DVFS FAIL: request-index=%u bridge=%d HFI=%u sent=%u ACK=%u value=%u status=%u polls=%u; live worker isolates before log commit\n",want,code,reply[0],reply[1],reply[2],reply[3],reply[4],reply[5]);return;}
  v.level=want;++v.changes;v.low=0;
 }
 if(inputWake){
  const uint64_t seq=__atomic_add_fetch(&v.touchPrewarms,1u,__ATOMIC_RELAXED);auto&r=houjiGpuTouchWakeRecords[(seq-1)%8];
  __atomic_store_n(&r.sequence,0ull,__ATOMIC_SEQ_CST);
  __atomic_store_n(&r.atUs,now,__ATOMIC_RELAXED);__atomic_store_n(&r.ageUs,now-burstUs,__ATOMIC_RELAXED);
  __atomic_store_n(&r.before,before,__ATOMIC_RELAXED);__atomic_store_n(&r.after,v.level,__ATOMIC_RELAXED);
  __atomic_store_n(&r.cap,cap,__ATOMIC_RELAXED);__atomic_store_n(&r.busy,v.busyPermille,__ATOMIC_RELAXED);__atomic_store_n(&r.active,(unsigned)active,__ATOMIC_RELAXED);
  __atomic_store_n(&r.sequence,seq,__ATOMIC_RELEASE);
 }
 if(now-v.historyAt>=5000000){unsigned count=__atomic_load_n(&houjiGpuDvfsHistoryCount,__ATOMIC_RELAXED);
  if(count<48){houjiGpuDvfsHistory[count]={now,(v.windowNs-v.historyNs)/1000,(v.busyNs-v.historyBusy)/1000,(v.at[1]-v.history231)/1000,(v.at[HCO_BOOT_LEVEL]-v.history500)/1000,v.maxTickUs,v.changes,v.wakeBoosts};__atomic_store_n(&houjiGpuDvfsHistoryCount,count+1,__ATOMIC_RELEASE);}
  v.historyAt=now;v.historyNs=v.windowNs;v.historyBusy=v.busyNs;v.history231=v.at[1];v.history500=v.at[HCO_BOOT_LEVEL];v.maxTickUs=0;
 }
}
extern "C" void houji_gpu_dvfs_history_report(void){
 unsigned count=__atomic_load_n(&houjiGpuDvfsHistoryCount,__ATOMIC_ACQUIRE);if(count>48)count=48;
 for(unsigned i=0;i<count;i++){const auto&w=houjiGpuDvfsHistory[i];IOLog("HOUJI GPU WINDOW: up-ms=%llu span-us=%llu busy-us=%llu nominal231-us=%llu nominal500-us=%llu max-tick-us=%llu changes=%u wakes=%u; XO busy counter, ACK levels not core clock\n",w.upUs/1000,w.spanUs,w.busyUs,w.at231Us,w.at500Us,w.maxTickUs,w.changes,w.wakes);}
}
static void houjiDvfsReport(){auto&v=gHoujiDvfs;
 for(unsigned level=1;level<=HCO_COUNT;++level)IOLog("HOUJI GPU OPP TIME: index=%u MHz=%u nominal-us=%llu; HFI ACK residency\n",level,hco_opp(level)->khz/1000,v.at[level]/1000);
 IOLog("HOUJI GPU DVFS: enabled=%u ready=%u bad=%u request-MHz=%u HFI-index=%u changes=%u failed=%u busy-permille=%u counter-invalid=%llu samples-us=%llu busy-us=%llu at231-us=%llu at500-us=%llu; HFI ACK request, XO busy-time; not measured core clock\n",v.enabled,v.ready,v.bad,hco_opp(v.level)->khz/1000,v.level,v.changes,v.failed,v.busyPermille,v.invalid,v.windowNs/1000,v.busyNs/1000,v.at[1]/1000,v.at[HCO_BOOT_LEVEL]/1000);
}

extern "C" unsigned houji_gpu_dvfs_snapshot(char*out,unsigned capacity){
 if(!out || !capacity)return 0;unsigned used=0;out[0]=0;auto&v=gHoujiDvfs;
 auto append=[&](const char*f,auto...a){if(used>=capacity-1)return;int n=snprintf(out+used,capacity-used,f,a...);if(n>0)used+=(unsigned)n<capacity-used?(unsigned)n:capacity-used-1;};
 append("HOUJI OPP SNAPSHOT: ready=%u bad=%u level=%u cap-MHz=%u thermal-level=%u changes=%u failed=%u busy=%u reason=%u\n",v.ready,v.bad,v.level,hco_opp(v.cap)->khz/1000,houji_thermal_gpu_cap(),v.changes,v.failed,v.busyPermille,v.policy.reason);
 for(unsigned i=1;i<=HCO_COUNT;i++)append("HOUJI OPP RESIDENCY: MHz=%u request-us=%llu\n",hco_opp(i)->khz/1000,__atomic_load_n(&v.at[i],__ATOMIC_RELAXED)/1000);
 append("HOUJI INPUT PREWARM: count=%u bursts=%u already-active=%u late=%u duration-us=50000 quiet-gap-us=80000; first contact burst only, factory/thermal cap retained\n",__atomic_load_n(&v.touchPrewarms,__ATOMIC_RELAXED),__atomic_load_n(&v.touchBursts,__ATOMIC_RELAXED),__atomic_load_n(&v.touchActive,__ATOMIC_RELAXED),__atomic_load_n(&v.touchLate,__ATOMIC_RELAXED));
 for(const auto&r:houjiGpuTouchWakeRecords){
  const uint64_t seq=__atomic_load_n(&r.sequence,__ATOMIC_ACQUIRE);if(!seq)continue;
  uint64_t at=__atomic_load_n(&r.atUs,__ATOMIC_RELAXED),age=__atomic_load_n(&r.ageUs,__ATOMIC_RELAXED);
  unsigned before=__atomic_load_n(&r.before,__ATOMIC_RELAXED),after=__atomic_load_n(&r.after,__ATOMIC_RELAXED),cap=__atomic_load_n(&r.cap,__ATOMIC_RELAXED),busy=__atomic_load_n(&r.busy,__ATOMIC_RELAXED),active=__atomic_load_n(&r.active,__ATOMIC_RELAXED);
  __atomic_thread_fence(__ATOMIC_SEQ_CST);if(seq!=__atomic_load_n(&r.sequence,__ATOMIC_ACQUIRE))continue;
  append("HOUJI INPUT WAKE: n=%llu up-us=%llu age-us=%llu before-level=%u after-level=%u cap=%u busy=%u active=%u; ACK level, not core clock\n",seq,at,age,before,after,cap,busy,active);
 }
 return used;
}
