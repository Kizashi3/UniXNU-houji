// SPDX-License-Identifier: BSD-2-Clause-Patent
// A read-only native firmware qualification before any PAS call. The same
// FAT and MDT reader will feed ADSP startup; this mode does not start it.
#include "battery/HoujiFirmware.h"
#include "battery/QcomMdt.h"
extern "C" int houji_adsp_preflight(void);
extern "C" void houji_adsp_run(void);
static char gHoujiFwProbe[4][384];
static unsigned gHoujiFwProbeBytes[4],gHoujiFwProbePhases;
static void houjiFwNote(const char *phase,int error,uint64_t dtbSize,uint64_t adspSize,
                       const char *dtbSha,const char *adspSha) {
    unsigned i=__atomic_load_n(&gHoujiFwProbePhases,__ATOMIC_RELAXED);if(i>=4)return;
    unsigned storage=0;uint32_t result=0,sense=0;houji_modem_status(&storage,&result,&sense);
    int n=snprintf(gHoujiFwProbe[i],sizeof(gHoujiFwProbe[i]),
        "HOUJI BATTERY FIRMWARE: phase=%s error=%d storage=%u/%x/%x source=modem_a dtb-bytes=%llu adsp-bytes=%llu "
        "dtb-sha=%s adsp-sha=%s; read-only, no PAS or carveout writes\n",
        phase,error,storage,result,sense,dtbSize,adspSize,dtbSha,adspSha);
    gHoujiFwProbeBytes[i]=n<=0?0:(unsigned)n<sizeof(gHoujiFwProbe[i])?(unsigned)n:sizeof(gHoujiFwProbe[i])-1;
    __atomic_store_n(&gHoujiFwProbePhases,i+1,__ATOMIC_RELEASE);
    IOLog("%s",gHoujiFwProbe[i]);
    houji_ufs_checkpoint("battery native firmware qualification",0);
}
static int houjiFwRead(void *file,uint64_t offset,void *to,size_t bytes) {
    return houji_fw_read(file,offset,to,bytes);
}
static int houjiFwCheck(const char *name,uint64_t base,uint64_t region,uint64_t *bytes,char digest[65]) {
    void *file=nullptr;int error=houji_fw_open(name,&file,bytes);if(error)return error;
    QcomMdtImage *mdt=static_cast<QcomMdtImage *>(IOMalloc(sizeof(QcomMdtImage)));
    constexpr size_t chunk=32768;
    uint8_t *buffer=static_cast<uint8_t *>(IOMalloc(chunk));
    if(!mdt || !buffer)error=ENOMEM;
    if(!error && (*bytes>128*1024*1024 || !*bytes))error=EFBIG;
    if(!error)error=qcom_mdt_parse(mdt,*bytes,houjiFwRead,file);
    for(unsigned i=0;!error && i<mdt->count;i++) {
        uint64_t offset=0;
        if(mdt->segment[i].load)error=qcom_mdt_place(mdt,i,base,region,&offset);
    }
    if(!error && qcom_mdt_span(mdt)>region)error=EFBIG;
    SHA256_CTX hash;SHA256_Init(&hash);
    for(uint64_t at=0;!error && at<*bytes;) {
        size_t n=*bytes-at<chunk?(size_t)(*bytes-at):chunk;
        error=houji_fw_read(file,at,buffer,n);
        if(error)break;
        SHA256_Update(&hash,buffer,n);at+=n;
    }
    uint8_t raw[32];SHA256_Final(raw,&hash);
    if(!error) {
        static const char hex[]="0123456789abcdef";
        for(unsigned i=0;i<32;i++){digest[2*i]=hex[raw[i]>>4];digest[2*i+1]=hex[raw[i]&15];}
        digest[64]=0;
    }
    if(buffer)IOFree(buffer,chunk);
    if(mdt)IOFree(mdt,sizeof(QcomMdtImage));
    houji_fw_close(file);return error;
}
static void houjiFwProbeThread(void *,wait_result_t) {
    uint64_t dtbSize=0,adspSize=0;char dtbSha[65]="unread",adspSha[65]="unread";
    houjiFwNote("before-read",0,dtbSize,adspSize,dtbSha,adspSha);
    int error=houjiFwCheck("adsp_dtb",0x9de80000,0x80000,&dtbSize,dtbSha);
    houjiFwNote("dtb-read",error,dtbSize,adspSize,dtbSha,adspSha);
    if(!error)error=houjiFwCheck("adsp",0x9df00000,0x4680000,&adspSize,adspSha);
    houjiFwNote(error?"failed":"complete",error,dtbSize,adspSize,dtbSha,adspSha);
    unsigned mode=0;PE_parse_boot_argn("houji_battery_probe",&mode,sizeof(mode));
    if(!error && mode>=3 && houji_adsp_preflight() && mode==4)houji_adsp_run();
    thread_terminate(current_thread());
}
static void houjiFwProbeStart(void) {
    unsigned mode=0;
    if(!PE_parse_boot_argn("houji_battery_probe",&mode,sizeof(mode)) || (mode<2 || mode>4))return;
    thread_t thread=THREAD_NULL;
    kern_return_t status=kernel_thread_start(houjiFwProbeThread,nullptr,&thread);
    if(status==KERN_SUCCESS)thread_deallocate(thread);
    else houjiFwNote("thread-failed",status,0,0,"unread","unread");
}
static unsigned houjiFwProbeSnapshot(char *out,unsigned capacity) {
    if(!out || !capacity)return 0;
    unsigned n=__atomic_load_n(&gHoujiFwProbePhases,__ATOMIC_ACQUIRE);
    if(!n){out[0]=0;return 0;}
    unsigned bytes=gHoujiFwProbeBytes[n-1];if(bytes>=capacity)bytes=capacity-1;
    memcpy(out,gHoujiFwProbe[n-1],bytes);out[bytes]=0;return bytes;
}
