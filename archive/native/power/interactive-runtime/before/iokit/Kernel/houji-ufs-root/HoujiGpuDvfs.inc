/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Same governor shape as sheng, own qualified A750 host-table levels only.
 * Runs under NativeAdreno's existing issuer lock, including HFI ACK handling.
 * Gen7 initialization ALREADY selects XO counter0, countable5 and enables it.
 */
extern "C" uint64_t houji_dvfs_touch_time(void);
static struct {
 unsigned enabled,ready,bad,level=2,low,changes,failed,busyPermille;
 uint64_t last,lastBusy,lastTouch,idleAt,wakeUntil,lastSubmits,windowNs,busyNs,at[3],invalid;
} gHoujiDvfs;
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
  v.last=now;v.lastBusy=busy;v.idleAt=now;v.ready=1;return;
 }
 uint64_t us=now-v.last;if(us<16000)return;
 uint64_t delta=busy-v.lastBusy;v.lastBusy=busy;v.last=now;
 if(delta>us*192/10+19200){++v.invalid;return;} // reject reset/backwards rather than fake 100% load
 uint64_t ns=us*1000,busyNs=delta*625/12;if(busyNs>ns)busyNs=ns;
 v.busyPermille=(unsigned)(busyNs*1000/ns);v.windowNs+=ns;v.busyNs+=busyNs;v.at[v.level]+=ns;
 uint64_t submits=gHoujiSubmit.ring.lastSubmitted();
 bool active=busyNs || submits!=v.lastSubmits || gHoujiApi.submit.outstanding();v.lastSubmits=submits;
 if(active)v.idleAt=now;
 uint64_t touch=houji_dvfs_touch_time(),touchNs=0;
 if(touch){uint64_t abs=mach_absolute_time();if(abs>=touch)absolutetime_to_nanoseconds(abs-touch,&touchNs);}
 unsigned want=v.level;
 if((touch && touchNs<1000000000ULL) || v.busyPermille>650 || gHoujiApi.submit.outstanding())want=2;
 else if(!active && now-v.idleAt>=80000)want=1;
 else if(v.level==2 && v.busyPermille<200){if(++v.low>=4)want=1;}
 else v.low=0;
 if(want!=v.level){
  uint32_t reply[6]={};const FhrRuntimeIo io={nullptr,houjiDvfsOwner,houjiDvfsDoorbell,houjiDvfsBarrier,houjiDvfsDelay};int code=fhr_runtime_vote(&gHoujiFull.storage,sizeof(gHoujiFull.storage),&io,want,reply);
  if(code){++v.failed;v.bad=1;IOLog("HOUJI GPU DVFS FAIL: request-index=%u bridge=%d HFI=%u sent=%u ACK=%u value=%u status=%u polls=%u; live worker isolates before log commit\n",want,code,reply[0],reply[1],reply[2],reply[3],reply[4],reply[5]);return;}
  v.level=want;++v.changes;v.low=0;
 }
}
static void houjiDvfsReport(){auto&v=gHoujiDvfs;
 IOLog("HOUJI GPU DVFS: enabled=%u ready=%u bad=%u request-MHz=%u HFI-index=%u changes=%u failed=%u busy-permille=%u counter-invalid=%llu samples-us=%llu busy-us=%llu at231-us=%llu at500-us=%llu; HFI ACK request, XO busy-time; not measured core clock\n",v.enabled,v.ready,v.bad,v.level==2?500:231,v.level,v.changes,v.failed,v.busyPermille,v.invalid,v.windowNs/1000,v.busyNs/1000,v.at[1]/1000,v.at[2]/1000);
}
