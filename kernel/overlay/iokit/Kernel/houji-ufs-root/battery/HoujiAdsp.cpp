// SPDX-License-Identifier: BSD-2-Clause-Patent
// Houji ADSP platform preflight. Physical resources are from this device's FDT;
// cmd-db/RSC formats follow UniXNU-sheng 08cde20e and MiCode pineapple.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOMemoryDescriptor.h>
#include "HoujiCmdDb.h"
extern "C" void houji_ufs_checkpoint(const char *,unsigned);
extern "C" {extern volatile int32_t native_adsp_stats[16],native_qrtr_stats[16],houji_battery_stats[16];}
namespace {
struct Window { IOMemoryMap *map;volatile uint32_t *base; };
bool map(Window &w,uint64_t address,uint64_t bytes) {
    IODeviceMemory *m=IODeviceMemory::withRange(address,bytes);
    w.map=m?m->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
    if(m)m->release();
    w.base=w.map?reinterpret_cast<volatile uint32_t *>(w.map->getVirtualAddress()):nullptr;
    return w.base!=nullptr;
}
int readWord(void *ctx,uint32_t at,uint32_t *value) {*value=static_cast<Window *>(ctx)->base[at/4];return 1;}
char reports[4][512];unsigned lengths[4],published;
void report(const char *phase,int error,const HoujiCmdDb &db,const QcomRpmhResource (&r)[3],
            const uint32_t (&tcs)[9],uint32_t rscId,uint32_t aoss) {
    unsigned i=__atomic_load_n(&published,__ATOMIC_RELAXED);if(i>=4)return;
    int n=snprintf(reports[i],sizeof(reports[i]),
      "HOUJI ADSP: phase=%s error=%d cmd-reads=%u last=%x resources=%x/%u,%x/%u,%x/%u rsc=%x aoss=%x "
      "tcs(status,control,enable)=%x,%x,%x;%x,%x,%x;%x,%x,%x; read-only preflight, no DSP start or battery publication\n",
      phase,error,db.reads,db.last,r[0].address,r[0].level_count,r[1].address,r[1].level_count,r[2].address,r[2].level_count,
      rscId,aoss,tcs[0],tcs[1],tcs[2],tcs[3],tcs[4],tcs[5],tcs[6],tcs[7],tcs[8]);
    lengths[i]=n<0?0:(unsigned)n<sizeof(reports[i])?(unsigned)n:sizeof(reports[i])-1;
    __atomic_store_n(&published,i+1,__ATOMIC_RELEASE);
    IOLog("%s",reports[i]);houji_ufs_checkpoint("ADSP platform preflight",0);
}
}
extern "C" int houji_adsp_preflight(void) {
    Window db={},rsc={},aoss={};HoujiCmdDb reader={readWord,&db,0x20000,0,0};
    QcomRpmhResource resources[3]={};uint32_t tcs[9]={},rscId=0,aossMagic=0;
    report("before-map",0,reader,resources,tcs,rscId,aossMagic);
    int error=0;
    if(!map(db,0x81c60000,0x20000) || !map(rsc,0x17a20000,0x10000) || !map(aoss,0xc300000,0x1000))error=-12;
    if(!error) {
        report("before-read",0,reader,resources,tcs,rscId,aossMagic);
        const char *names[]={"lcx.lvl","lmx.lvl","xo.lvl"};
        for(unsigned i=0;i<3 && !error;i++)error=houji_cmd_find(&reader,names[i],&resources[i]);
        if(!error) {
            rscId=rsc.base[0];aossMagic=aoss.base[0];
            QcomRscLayout layout=qcom_rsc_layout(rscId);
            for(unsigned i=0;i<3;i++) {
                uint32_t base=0xd00+i*layout.tcs_stride;
                tcs[i*3]=rsc.base[(base+layout.status)/4];
                tcs[i*3+1]=rsc.base[(base+layout.control)/4];
                tcs[i*3+2]=rsc.base[(base+layout.cmd_enable)/4];
            }
        }
    }
    report(error?"failed":"complete",error,reader,resources,tcs,rscId,aossMagic);
    if(db.map)db.map->release();if(rsc.map)rsc.map->release();if(aoss.map)aoss.map->release();
    return error==0;
}
extern "C" unsigned houji_adsp_snapshot(char *out,unsigned capacity) {
    if(!out || !capacity)return 0;
    unsigned n=__atomic_load_n(&published,__ATOMIC_ACQUIRE);if(!n){out[0]=0;return 0;}
    unsigned bytes=lengths[n-1];if(bytes>=capacity)bytes=capacity-1;
    memcpy(out,reports[n-1],bytes);out[bytes]=0;
    if(!native_adsp_stats[0] || bytes+1>=capacity)return bytes;
    int added=snprintf(out+bytes,capacity-bytes,
      "HOUJI ADSP LIVE: stage=%d error=%d irqs=%d slave=%x items=%x qmp=%x ready-ms=%d rx=%d tx=%d channels=%x scm=%x/%x votes=%x\n"
      "HOUJI QRTR: stage=%d rx=%d bad=%d tx=%d refused=%d locator=%d/%d node=%d services=%d up/down=%d/%d\n"
      "HOUJI BATTERY LIVE: stage=%d capacity-raw=%d status=%d usb=%d valid=%x replies=%d errors=%d timeouts=%d cycles=%d ignored=%d dropped=%d send-fail=%d skipped=%x fault=%d generation=%d\n",
      native_adsp_stats[0],native_adsp_stats[1],native_adsp_stats[2],native_adsp_stats[3],native_adsp_stats[4],native_adsp_stats[5],
      native_adsp_stats[8],native_adsp_stats[9],native_adsp_stats[10],native_adsp_stats[11],native_adsp_stats[13],native_adsp_stats[14],native_adsp_stats[15],
      native_qrtr_stats[0],native_qrtr_stats[1],native_qrtr_stats[3],native_qrtr_stats[4],native_qrtr_stats[5],native_qrtr_stats[6],native_qrtr_stats[7],
      native_qrtr_stats[8],native_qrtr_stats[9],native_qrtr_stats[10],native_qrtr_stats[11],
      houji_battery_stats[0],houji_battery_stats[1],houji_battery_stats[2],houji_battery_stats[3],houji_battery_stats[4],houji_battery_stats[5],
      houji_battery_stats[6],houji_battery_stats[7],houji_battery_stats[8],houji_battery_stats[9],houji_battery_stats[10],houji_battery_stats[11],
      houji_battery_stats[12],houji_battery_stats[13],houji_battery_stats[14]);
    if(added>0)bytes+=(unsigned)added<capacity-bytes?(unsigned)added:capacity-bytes-1;
    return bytes;
}
