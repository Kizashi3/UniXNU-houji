// SPDX-License-Identifier: BSD-2-Clause-Patent
// Adapted from UniXNU-sheng 08cde20e. Houji-specific addresses and own modem_a
// firmware only. Runs only after explicit mode 4 and successful read-only
// qualification. Resources touched by PAS are retained until reset on failure.
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IODeviceMemory.h>
#include <kern/thread.h>
#include <sys/errno.h>
#include <pexpert/pexpert.h>
extern "C" {
#include "QcomGlink.h"
#include "QcomMdt.h"
#include "QcomQmp.h"
#include "QcomRpmh.h"
#include "QcomScm.h"
#include "QcomSmem.h"
#include "QcomSmp2p.h"
#include "HoujiCmdDb.h"
#include "HoujiSmemSurvey.h"
#include "../../../../pexpert/arm/HoujiSpi.h"
#include "HoujiAdsp.h"
int houji_fw_open(const char *path, void **handle, uint64_t *size);
void houji_qrtr_start(void);
int houji_fw_read(void *handle, uint64_t offset, void *to, size_t length);
void houji_fw_close(void *handle);
}

extern "C" void houji_battery_start(void);
extern "C" void houji_ufs_checkpoint(const char *,unsigned);
// [0] stage (see Stage; negative: the step that failed), [1] last error, [2] IPCC interrupts, [3] the DSP's slave-kernel bits (-1 no
// item), [4] items (bit 0 SMP2P in 443, 1 out 429, 2 GLINK 478, 3 479, 4 480, 8 our partition, 9 global partition), [5] QMP state | AOSS
// link bits << 8, [6] RSC DRV id, [7] adsp.mbn KiB, [8] ms from the start call to "ready", [9] GLINK messages in, [10] out, [11] channels
// up (bit per client) | version agreed << 14 | link broken << 15, [12] channel opens nobody serves, [13] last SCM x0, [14] its x1,
// [15] votes: lcx index | lmx index << 8 | RSC done interrupts << 16
extern "C" {volatile int32_t native_adsp_stats[16]; char native_adsp_text[96];}

namespace {
enum Stage {
    StMapped = 1, StSurveyed = 2, StFirmware = 3, StSmp2p = 4, StDoorbells = 5, StLoadState = 6, StRails = 7, StDtb = 8, StLoaded = 9,
    StStarted = 10, StReady = 11, StGlink = 12, StChannel = 13,
};
constexpr uint64_t kSmem = 0x81d00000, kSmemSize = 0x200000, kMutex = 0x1f40000 + 3 * 0x1000, kIpcc = 0x406000, kAoss = 0xc300000;
constexpr uint64_t kRscDrv = 0x17a20000, kRscTcs = 0xd00, kCmdDb = 0x81c60000, kCmdDbSize = 0x20000;
constexpr uint64_t kAdspBase = 0x9df00000, kAdspSize = 0x4680000, kDtbBase = 0x9de80000, kDtbSize = 0x80000;
constexpr uint32_t kPasAdsp = 1, kPasDtb = 36, kRemotePid = 2, kItemIn = 443, kItemOut = 429, kItemCrash = 423;
constexpr uint32_t kItemGlinkDesc = 478, kItemGlinkTx = 479, kItemGlinkRx = 480, kGlinkFifo = 0x4000;
constexpr uint32_t kSpiIpcc = 229, kSpiRsc = 5;
constexpr uint32_t kFatal = 1u << 0, kReady = 1u << 1, kHandover = 1u << 2;
constexpr uint32_t kEvSmp2p = 1, kEvGlink = 2, kEvAop = 4, kEvRsc = 8, kEvSend = 16;
constexpr unsigned kClients = 4, kQueue = 8;

struct Window {IOMemoryMap *map; volatile uint8_t *va;};
bool mapWindow(Window &w, uint64_t base, uint64_t size, IOOptionBits cache = kIOMapInhibitCache) {
    IODeviceMemory *memory = IODeviceMemory::withRange(base, size);
    w.map = memory ? memory->map(kIOMapAnywhere | cache) : nullptr;
    if (memory) memory->release();
    w.va = w.map ? reinterpret_cast<volatile uint8_t *>(w.map->getVirtualAddress()) : nullptr;
    return w.va != nullptr;
}
void unmap(Window &w) {if (w.map) w.map->release(); w = {};}
uint32_t rd(const Window &w, uint64_t at) {return *reinterpret_cast<volatile uint32_t *>(w.va + at);}
void wr(const Window &w, uint64_t at, uint32_t value) {*reinterpret_cast<volatile uint32_t *>(w.va + at) = value; __asm__ volatile("dsb sy" ::: "memory");}
void fail(int step, int error) {native_adsp_stats[1] = error; native_adsp_stats[0] = -step; IOLog("HOUJI ADSP failure: step=%d error=%d\n",step,error);houji_ufs_checkpoint("ADSP startup failure; resources retained",0);}
void stage(int value) {
    // serviceGlink revisits the current stage for every packet. Checkpoint only
    // transitions: repeated battery replies must not trigger storage writes.
    if(native_adsp_stats[0]==value)return;
    native_adsp_stats[0]=value;IOLog("HOUJI ADSP stage=%d\n",value);
    houji_ufs_checkpoint("ADSP startup progress",0);
}
void note(const char *prefix, const char *text) {
    size_t at = 0;
    for (; prefix[at] && at < sizeof native_adsp_text - 1; ++at) native_adsp_text[at] = prefix[at];
    for (size_t i = 0; text[i] && at < sizeof native_adsp_text - 1; ++i) native_adsp_text[at++] = text[i];
    native_adsp_text[at] = 0;
}

Window gSmemW, gMutex, gIpcc, gAoss, gRsc;
QcomSmem gSmem;
QcomSmemPartition gPart;
QcomSmp2p gP2p;
int gStopEntry = -1;
QcomQmp gQmp;
QcomGlink gGlink;
bool gGlinkStarted;
QcomRscLayout gLayout;
uint32_t gRscIrqBits;
volatile uint32_t gPending, gRscDone;

// ---- clients ----
struct Message {uint32_t length; uint8_t data[HOUJI_ADSP_MAX_MESSAGE];};
}  // namespace
struct HoujiAdspChannel {
    char name[QCOM_GLINK_NAME];
    uint32_t intent_size, intent_count;
    int initiator;
    HoujiAdspClient client;
    void *context;
    uint8_t *storage;
    QcomGlinkChannel *glink;
    Message *queue;  // kQueue slots
    uint32_t head, count;
    bool online;
};
namespace {
HoujiAdspChannel gClients[kClients];
uint32_t gClientCount;
IOLock *gClientLock;

void wake(uint32_t bits) {
    __atomic_fetch_or(&gPending, bits, __ATOMIC_RELEASE);
    thread_wakeup((event_t)&gPending);
}

// ---- interrupts: acknowledge, record, wake ----
void ipccIrq(void *) {
    uint32_t bits = 0;
    for (unsigned n = 0; n < 32; ++n) {
        const uint32_t id = rd(gIpcc, QCOM_IPCC_RECV_ID);
        if (id == QCOM_IPCC_NONE) break;
        wr(gIpcc, QCOM_IPCC_RECV_CLEAR, id);
        if (id == qcom_ipcc_id(QCOM_IPCC_CLIENT_LPASS, QCOM_IPCC_SIGNAL_SMP2P)) bits |= kEvSmp2p;
        else if (id == qcom_ipcc_id(QCOM_IPCC_CLIENT_LPASS, QCOM_IPCC_SIGNAL_GLINK_QMP)) bits |= kEvGlink;
        else if (id == qcom_ipcc_id(QCOM_IPCC_CLIENT_AOP, QCOM_IPCC_SIGNAL_GLINK_QMP)) bits |= kEvAop;
    }
    native_adsp_stats[2] = native_adsp_stats[2] + 1;
    if (bits) wake(bits);
}
void rscIrq(void *) {
    const uint32_t status = rd(gRsc, kRscTcs + gLayout.irq_status) & gRscIrqBits;
    if (!status) return;
    wr(gRsc, kRscTcs + gLayout.irq_clear, status);
    __atomic_fetch_or(&gRscDone, status, __ATOMIC_RELEASE);
    native_adsp_stats[15] = native_adsp_stats[15] + (1 << 16);
    wake(kEvRsc);
}

// Waits for an event up to ms milliseconds; returns the event bits (0: the deadline passed).
uint32_t waitEvents(uint32_t ms) {
    uint32_t bits = __atomic_exchange_n(&gPending, 0, __ATOMIC_ACQ_REL);
    if (bits) return bits;
    assert_wait_timeout((event_t)&gPending, THREAD_UNINT, ms, kMillisecondScale);
    bits = __atomic_exchange_n(&gPending, 0, __ATOMIC_ACQ_REL);
    if (bits) {clear_wait(current_thread(), THREAD_AWAKENED); return bits;}
    thread_block(THREAD_CONTINUE_NULL);
    return __atomic_exchange_n(&gPending, 0, __ATOMIC_ACQ_REL);
}

void ring(uint32_t client, uint32_t signal) {wr(gIpcc, QCOM_IPCC_SEND, qcom_ipcc_id(client, signal));}
void kickAop(void *) {ring(QCOM_IPCC_CLIENT_AOP, QCOM_IPCC_SIGNAL_GLINK_QMP);}
void kickGlink(void *) {ring(QCOM_IPCC_CLIENT_LPASS, QCOM_IPCC_SIGNAL_GLINK_QMP);}
void kickSmp2p() {ring(QCOM_IPCC_CLIENT_LPASS, QCOM_IPCC_SIGNAL_SMP2P);}

// ---- SMEM helpers (allocation under the TCSR hardware mutex) ----
bool lockSmem() {
    // The mutex is held only for the few writes of one allocation by whichever processor has it; it is tried a bounded number of times.
    for (unsigned i = 0; i < 1000; ++i) {
        wr(gMutex, 0, 1);
        if (rd(gMutex, 0) == 1) return true;
        IODelay(10);
    }
    return false;
}
void unlockSmem() {wr(gMutex, 0, 0);}
int sparseWord(void *ctx,uint32_t at,uint32_t *value) {
    const Window *w=static_cast<const Window *>(ctx);*value=rd(*w,at);return 1;
}
int partition(QcomSmemPartition *out) {
    HoujiSmemReader reader={sparseWord,&gSmemW,(uint32_t)kSmemSize,0,8192,0,0};
    HoujiSmemPart part={};int rc=houji_smem_partition_ro(&reader,0,kRemotePid,&part);
    if(rc)return rc;
    // The upstream writer uses exactly the same validated partition fields.
    return qcom_smem_partition(&gSmem,0,kRemotePid,out);
}
volatile uint8_t *item(uint16_t id,uint32_t *size) {
    HoujiSmemReader reader={sparseWord,&gSmemW,(uint32_t)kSmemSize,0,8192,0,0};
    HoujiSmemPart part={};uint32_t at=0,bytes=0;
    if(houji_smem_partition_ro(&reader,0,kRemotePid,&part) ||
       houji_smem_item_ro(&reader,&part,id,&at,&bytes) || (at&3))return nullptr;
    if(size)*size=bytes;return gSmemW.va+at;
}
int allocItem(uint16_t id,uint32_t size) {
    if(!lockSmem())return -16;
    int rc=partition(&gPart);
    if(!rc)rc=qcom_smem_alloc(&gSmem,&gPart,id,size);
    unlockSmem();
    if(rc && rc!=QcomSmemExists)return rc;
    uint32_t actual=0;return item(id,&actual) && actual>=size?0:-22;
}

void readCrashReason() {
    QcomSmemPartition global;
    uint32_t at = 0, size = 0;
    if (qcom_smem_partition(&gSmem, QCOM_SMEM_HOST_GLOBAL, QCOM_SMEM_HOST_GLOBAL, &global) ||
        qcom_smem_find(&gSmem, &global, kItemCrash, &at, &size) || !size)
        return;
    char text[80];
    size_t n = 0;
    for (; n < sizeof text - 1 && n < size; ++n) {const char c = (char)(rd(gSmemW,(at+(uint32_t)n)&~3u) >> (8*((at+n)&3))); if (!c) break; text[n] = c >= 32 && c < 127 ? c : '.';}
    text[n] = 0;
    if (n) note("crash: ", text);
}

// ---- startup survey: reads only ----
void survey() {
    int32_t bits = 0;
    if (!qcom_smem_partition(&gSmem, QCOM_SMEM_HOST_APPS, kRemotePid, &gPart)) {
        bits |= 1 << 8;
        const uint16_t ids[5] = {kItemIn, kItemOut, kItemGlinkDesc, kItemGlinkTx, kItemGlinkRx};
        for (unsigned i = 0; i < 5; ++i) if (item(ids[i], nullptr)) bits |= 1 << i;
    }
    QcomSmemPartition global;
    if (!qcom_smem_partition(&gSmem, QCOM_SMEM_HOST_GLOBAL, QCOM_SMEM_HOST_GLOBAL, &global)) bits |= 1 << 9;
    native_adsp_stats[4] = bits;
    native_adsp_stats[3] = -1;
    uint32_t inBytes=0;
    if (volatile uint8_t *in = item(kItemIn, &inBytes)) {
        if(inBytes<QCOM_SMP2P_ITEM_BYTES){native_adsp_stats[3]=1;return;}
        QcomSmp2p view = {};
        view.in = reinterpret_cast<volatile uint32_t *>(in);
        view.local_pid = 0; view.remote_pid = kRemotePid;
        const int index = qcom_smp2p_check_in(view.in, 0, kRemotePid) ? -1 : qcom_smp2p_find_in(&view, "slave-kernel");
        if (index >= 0) native_adsp_stats[3] = (int32_t)qcom_smp2p_in_value(&view, index);
    }
    const uint32_t up = 0xffff;
    native_adsp_stats[5] = (rd(gAoss, 0) == 0x4d41494cu ? 1 : 0) << 12 | (rd(gAoss, 0xc) == up) << 8 | (rd(gAoss, 0x24) == up) << 9 |
                           (rd(gAoss, 0x14) == up) << 10 | (rd(gAoss, 0x2c) == up) << 11;
    native_adsp_stats[6] = (int32_t)rd(gRsc, 0);
    readCrashReason();
}

void service(uint32_t bits);

// ---- RPMh proxy votes ----
QcomRpmhResource gLcx,gLmx,gXo;
bool gProxyHeld;
int gTcs=-1;
bool readResources() {
    Window db={};if(!mapWindow(db,kCmdDb,kCmdDbSize))return false;
    HoujiCmdDb r={sparseWord,&db,(uint32_t)kCmdDbSize,0,0};
    const bool ok=!houji_cmd_find(&r,"lcx.lvl",&gLcx) &&
      !houji_cmd_find(&r,"lmx.lvl",&gLmx) && !houji_cmd_find(&r,"xo.lvl",&gXo);
    unmap(db);return ok;
}
int vote(uint32_t lcx,uint32_t lmx) {
    const unsigned tcs=1;const uint32_t base=kRscTcs+tcs*gLayout.tcs_stride;
    if(!rd(gRsc,base+gLayout.status) || rd(gRsc,base+gLayout.cmd_enable) ||
       (rd(gRsc,kRscTcs+gLayout.irq_status)&(1u<<tcs)))return -16;
    if(gTcs<0) {
        gTcs=tcs;gRscIrqBits=1u<<tcs;
        wr(gRsc,kRscTcs,rd(gRsc,kRscTcs)|gRscIrqBits);
    }
    const uint32_t addresses[]={gLcx.address,gLmx.address,gXo.address};
    // Stock pineapple XO ARC has offset 0 and on value 3, not an aux index.
    const uint32_t values[]={lcx,lmx,(lcx||lmx)?3u:0u};
    QcomRpmhWrite writes[20];
    const unsigned n=qcom_rpmh_active_request(&gLayout,tcs,addresses,values,3,writes,20);
    if(!n)return -22;
    __atomic_store_n(&gRscDone,0,__ATOMIC_RELEASE);
    for(unsigned i=0;i<n;i++)wr(gRsc,kRscTcs+writes[i].offset,writes[i].value);
    uint64_t deadline;clock_interval_to_deadline(100,kMillisecondScale,&deadline);
    bool done=false;
    do {
        done=((__atomic_load_n(&gRscDone,__ATOMIC_ACQUIRE)|rd(gRsc,kRscTcs+gLayout.irq_status))&gRscIrqBits)!=0;
        if(done && rd(gRsc,base+gLayout.status))break;
        done=false;service(waitEvents(10));
    }while(mach_absolute_time()<deadline);
    if(!done)done=((__atomic_load_n(&gRscDone,__ATOMIC_ACQUIRE)|rd(gRsc,kRscTcs+gLayout.irq_status))&gRscIrqBits) &&
                 rd(gRsc,base+gLayout.status);
    if(!done)return -60; // Do not clear or reprogram an uncertain in-flight TCS.
    const unsigned m=qcom_rpmh_finish(&gLayout,tcs,writes,20);
    for(unsigned i=0;i<m;i++)wr(gRsc,kRscTcs+writes[i].offset,writes[i].value);
    native_adsp_stats[15]=(native_adsp_stats[15]&~0xffff)|(int32_t)(lcx|lmx<<8);
    gProxyHeld=lcx||lmx;return 0;
}

// ---- secure world calls ----
struct ScmResult {int64_t x0; uint64_t x1;};
ScmResult scm(uint32_t command, uint32_t arginfo, uint64_t a, uint64_t b, uint64_t c) {
    ScmResult result = {-1, 0};
    for (unsigned busy = 0; busy < 20; ++busy) {
        uint64_t function = qcom_scm_fn(QCOM_SCM_SVC_PIL, command), session = 0;
        unsigned resumes = 0;
        for (;;) {
            register uint64_t x0 __asm__("x0") = function, x1 __asm__("x1") = arginfo, x2 __asm__("x2") = a, x3 __asm__("x3") = b,
                              x4 __asm__("x4") = c, x5 __asm__("x5") = 0, x6 __asm__("x6") = session, x7 __asm__("x7") = 0;
            __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3), "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7)
                             :: "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
            result = {(int64_t)x0, x1};
            if ((int64_t)x0 != QCOM_SCM_INTERRUPTED || ++resumes > 256) break;
            function = QCOM_SCM_INTERRUPTED;  // resume the interrupted call in its session
            session = x6;
        }
        if (result.x0 != QCOM_SCM_V2_EBUSY) break;
        IOSleep(30);
    }
    native_adsp_stats[13] = (int32_t)result.x0;
    native_adsp_stats[14] = (int32_t)result.x1;
    return result;
}
bool scmOk(const ScmResult &r) {return r.x0 == 0 && r.x1 == 0;}

void cleanToPoc(const void *start, size_t length) {
    uint64_t ctr;
    __asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
    const uintptr_t line = static_cast<uintptr_t>(4) << ((ctr >> 16) & 15);
    for (uintptr_t a = reinterpret_cast<uintptr_t>(start) & ~(line - 1); a < reinterpret_cast<uintptr_t>(start) + length; a += line)
        __asm__ volatile("dc civac, %0" :: "r"(a) : "memory");
    __asm__ volatile("dsb sy" ::: "memory");
}

// ---- a firmware image: parsed from its file, metadata handed over, segments written into the carveout ----
struct Image {  // plain data, zero at start: the two live in static storage (a few KiB of header table each, kept off the stack)
    void *file;
    uint64_t size;
    QcomMdtImage mdt;
    IOBufferMemoryDescriptor *meta;
    bool prepared,submitted;
};
Image gDtbImage, gAdspImage;
int fileRead(void *context, uint64_t offset, void *to, size_t length) {return houji_fw_read(context, offset, to, length);}
void release(Image &image) {
    if (image.file) houji_fw_close(image.file);
    if(image.meta && !image.submitted) {
        if(image.prepared)image.meta->complete();
        image.meta->release();image.meta=nullptr;image.prepared=false;
    }
    // Submitted metadata is deliberately retained until reset, even on error.
    image.file=nullptr;
}
int openImage(Image &image, const char *path) {
    int rc = houji_fw_open(path, &image.file, &image.size);
    if (rc) {image.file = nullptr; return rc;}
    rc = qcom_mdt_parse(&image.mdt, image.size, fileRead, image.file);
    return rc ? 1000 - rc : 0;
}
// init_image with the metadata in physically contiguous memory, then the memory setup of a relocatable image.
int authenticateHeader(Image &image, uint32_t pas, uint64_t base) {
    const uint64_t bytes = qcom_mdt_metadata_size(&image.mdt);
    image.meta = IOBufferMemoryDescriptor::inTaskWithPhysicalMask(kernel_task, (IOOptionBits)kIODirectionInOut | (IOOptionBits)kIOMemoryPhysicallyContiguous, bytes,
                                                                 0xfffffffffffff000ull);
    if (!image.meta || image.meta->prepare() != kIOReturnSuccess) return -12;
    image.prepared=true;
    uint8_t *va = static_cast<uint8_t *>(image.meta->getBytesNoCopy());
    if (qcom_mdt_metadata(&image.mdt, fileRead, image.file, va, bytes)) return -5;
    cleanToPoc(va, bytes);
    const uint64_t phys = image.meta->getPhysicalSegment(0, nullptr, kIOMemoryMapperNone);
    if(!phys)return -12;image.submitted=true;
    if (!scmOk(scm(QCOM_SCM_PAS_INIT_IMAGE, qcom_scm_args(2, QCOM_SCM_VAL, QCOM_SCM_RW, 0), pas, phys, 0))) return -1;
    if (image.mdt.relocatable &&
        !scmOk(scm(QCOM_SCM_PAS_MEM_SETUP, qcom_scm_args(3, 0, 0, 0), pas, base, qcom_mdt_span(&image.mdt))))
        return -2;
    return 0;
}
int loadSegments(Image &image, uint64_t base, uint64_t size) {
    Window region = {};
    if (!mapWindow(region, base, size, kIOMapWriteCombineCache)) return -12;
    constexpr size_t kChunk = 256 * 1024;
    uint8_t *bounce = static_cast<uint8_t *>(IOMalloc(kChunk));
    int rc = bounce ? 0 : -12;
    for (unsigned i = 0; !rc && i < image.mdt.count; ++i) {
        const QcomMdtSegment &s = image.mdt.segment[i];
        uint64_t at = 0;
        if (!s.load) continue;
        if (qcom_mdt_place(&image.mdt, i, base, size, &at)) {rc = -7; break;}
        uint8_t *to = const_cast<uint8_t *>(region.va) + at;
        for (uint64_t done = 0; !rc && done < s.file_size;) {
            const size_t n = s.file_size - done < kChunk ? (size_t)(s.file_size - done) : kChunk;
            if (houji_fw_read(image.file, s.file_offset + done, bounce, n)) {rc = -5; break;}
            memcpy(to + done, bounce, n);
            done += n;
        }
        if (!rc && s.memory_size > s.file_size) bzero(to + s.file_size, (size_t)(s.memory_size - s.file_size));
    }
    __asm__ volatile("dsb sy" ::: "memory");
    if (bounce) IOFree(bounce, kChunk);
    unmap(region);
    return rc;
}

// ---- events ----
uint32_t gSlave;
bool gHandedOver;
void serviceSmp2p() {
    if (!gP2p.in) {
        uint32_t bytes=0;volatile uint8_t *in=item(kItemIn,&bytes);
        if (in && bytes>=QCOM_SMP2P_ITEM_BYTES) gP2p.in = reinterpret_cast<volatile uint32_t *>(in);
        else return;
    }
    uint32_t value = 0, changed = 0;
    if (qcom_smp2p_service(&gP2p, "slave-kernel", &value, &changed)) kickSmp2p();
    gSlave = value;
    native_adsp_stats[3] = (int32_t)value;
    if ((changed & value & kFatal)) readCrashReason();
    if ((value & kHandover) && !gHandedOver) {
        gHandedOver = true;
        // Defer dropping proxy votes to the main loop; never recurse into vote().
    }
}

void applyClients();
void pumpSends();
void serviceGlink() {
    if (!gGlinkStarted) return;
    if (!gGlink.rx.data) {
        uint32_t size = 0;
        if (volatile uint8_t *rx = item(kItemGlinkRx, &size)) qcom_glink_set_rx(&gGlink, rx, size);
    }
    qcom_glink_poll(&gGlink);
    pumpSends();
    uint32_t up = 0;
    for (unsigned i = 0; i < gClientCount; ++i) if (gClients[i].glink && gClients[i].glink->up) up |= 1u << i;
    native_adsp_stats[9] = (int32_t)gGlink.rx_messages;
    native_adsp_stats[10] = (int32_t)gGlink.tx_messages;
    native_adsp_stats[11] = (int32_t)(up | (uint32_t)gGlink.version_agreed << 14 | (uint32_t)gGlink.broken << 15);
    native_adsp_stats[12] = (int32_t)gGlink.unknown_opens;
    if (gGlink.unknown_opens && strncmp(native_adsp_text, "crash: ", 7)) note("open: ", gGlink.unknown_names);
    if (gGlink.version_agreed && native_adsp_stats[0] >= StReady && native_adsp_stats[0] < StGlink) stage(StGlink);
    if (up && native_adsp_stats[0] >= StGlink) stage(StChannel);
}
void service(uint32_t bits) {
    if (bits & kEvAop) qcom_qmp_step(&gQmp);
    if (bits & (kEvSmp2p | kEvGlink)) serviceSmp2p();
    if (bits & (kEvGlink | kEvSend)) {applyClients(); serviceGlink();}
}
// Runs events until done() holds or ms pass; returns done().
template <typename F> bool waitUntil(uint32_t ms, F done) {
    uint64_t deadline;
    clock_interval_to_deadline(ms, kMillisecondScale, &deadline);
    while (!done()) {
        const uint64_t now = mach_absolute_time();
        if (now >= deadline) return done();
        uint64_t left = 0;
        absolutetime_to_nanoseconds(deadline - now, &left);
        service(waitEvents((uint32_t)(left / 1000000) + 1));
    }
    return true;
}

// ---- client glue (DSP thread side) ----
void clientState(void *context, QcomGlinkChannel *, int up) {
    HoujiAdspChannel *c = static_cast<HoujiAdspChannel *>(context);
    IOLockLock(gClientLock);c->online=up!=0;c->head=c->count=0;IOLockUnlock(gClientLock);
    if (c->client.state) c->client.state(c->context, up);
}
void clientReceive(void *context, QcomGlinkChannel *, const uint8_t *data, uint32_t length) {
    HoujiAdspChannel *c = static_cast<HoujiAdspChannel *>(context);
    if (c->client.receive) c->client.receive(c->context, data, length);
}
void applyClients() {
    if (!gGlinkStarted) return;
    const QcomGlinkClient glue = {clientState, clientReceive};
    IOLockLock(gClientLock);
    for (unsigned i = 0; i < gClientCount; ++i) {
        HoujiAdspChannel &c = gClients[i];
        if (!c.glink) c.glink = qcom_glink_channel(&gGlink, c.name, c.intent_size, c.intent_count, c.storage, &glue, &c, c.initiator);
    }
    IOLockUnlock(gClientLock);
}
void pumpSends() {
    for (unsigned i = 0; i < gClientCount; ++i) {
        HoujiAdspChannel &c = gClients[i];
        if (!c.glink || !c.glink->up) continue;
        for (;;) {
            IOLockLock(gClientLock);
            if (!c.count) {IOLockUnlock(gClientLock); break;}
            Message *m = &c.queue[c.head];
            IOLockUnlock(gClientLock);
            // Only this thread takes messages off the queue, so m stays valid while the lock is dropped for the send.
            const int rc = qcom_glink_send(&gGlink, c.glink, m->data, m->length);

            if (rc != QcomGlinkOk) break;
            IOLockLock(gClientLock);
            c.head = (c.head + 1) % kQueue;
            c.count--;
            IOLockUnlock(gClientLock);
        }
    }
}

// ---- the bring-up ----
bool gIrq;
bool attachIrqs() {
    // Do not enable a level interrupt with an unhandled old source pending.
    if(rd(gRsc,kRscTcs+gLayout.irq_status)&rd(gRsc,kRscTcs)) {
        fail(StDoorbells,-16);return false;
    }
    int rc=houji_spi_attach(32+kSpiIpcc,0,ipccIrq,nullptr,nullptr,nullptr);
    if(rc){fail(StDoorbells,rc);return false;}
    rc=houji_spi_attach(32+kSpiRsc,0,rscIrq,nullptr,nullptr,nullptr);
    if(rc){fail(StDoorbells,rc);return false;}
    const uint32_t enable[]={qcom_ipcc_id(QCOM_IPCC_CLIENT_LPASS,QCOM_IPCC_SIGNAL_SMP2P),
      qcom_ipcc_id(QCOM_IPCC_CLIENT_LPASS,QCOM_IPCC_SIGNAL_GLINK_QMP),
      qcom_ipcc_id(QCOM_IPCC_CLIENT_AOP,QCOM_IPCC_SIGNAL_GLINK_QMP)};
    for(uint32_t id:enable)wr(gIpcc,QCOM_IPCC_RECV_ENABLE,id);
    gIrq=true;return true;
}

int openFirmware(Image &dtb,Image &adsp) {
    int rc=openImage(dtb,"adsp_dtb");if(!rc)rc=openImage(adsp,"adsp");
    if(!rc && (qcom_mdt_span(&dtb.mdt)>kDtbSize || qcom_mdt_span(&adsp.mdt)>kAdspSize))rc=-7;
    return rc;
}

bool start() {
    Image &dtb=gDtbImage,&adsp=gAdspImage;
    int rc=openFirmware(dtb,adsp);
    if(rc){fail(StFirmware,rc);release(dtb);release(adsp);return false;}
    native_adsp_stats[7] = (int32_t)(adsp.size >> 10);
    stage(StFirmware);
    if (native_adsp_stats[3] > 0) {fail(StFirmware, -114); release(dtb); release(adsp); return false;}  // running already: left alone

    // Our SMP2P item, before the DSP starts (it looks for it at boot).
    if ((rc = allocItem(kItemOut, QCOM_SMP2P_ITEM_BYTES))) {fail(StSmp2p, rc); release(dtb); release(adsp); return false;}
    if((rc=allocItem(kItemGlinkDesc,32)) || (rc=allocItem(kItemGlinkTx,kGlinkFifo))){fail(StSmp2p,rc);return false;}
    qcom_smp2p_init_out(&gP2p, reinterpret_cast<volatile uint32_t *>(item(kItemOut, nullptr)), 0, kRemotePid);
    gStopEntry = qcom_smp2p_add_entry(&gP2p, "master-kernel");
    if(gStopEntry<0){fail(StSmp2p,gStopEntry);return false;}
    stage(StSmp2p);
    if (!attachIrqs()) {release(dtb); release(adsp); return false;}
    kickSmp2p();
    stage(StDoorbells);

    qcom_qmp_init(&gQmp, reinterpret_cast<volatile uint32_t *>(gAoss.va), 0x400, kickAop, nullptr);
    for (int phase = 0; phase < 4 && qcom_qmp_step(&gQmp) > 0 && gQmp.state != QcomQmpOpen; ++phase)
        waitUntil(1000, [] {return qcom_qmp_step(&gQmp) == QcomQmpOpen || gQmp.state < 0;});
    native_adsp_stats[5] = (native_adsp_stats[5] & ~0xff) | (gQmp.state & 0xff);
    if (gQmp.state != QcomQmpOpen) {fail(StLoadState, gQmp.state); release(dtb); release(adsp); return false;}
    if(qcom_qmp_send(&gQmp, "{class: image, res: load_state, name: adsp, val: on}")!=QcomQmpSending){fail(StLoadState,-16);return false;}
    if (!waitUntil(1000, [] {return qcom_qmp_step(&gQmp) == QcomQmpOpen;})) {
        // A timeout does not establish mailbox ownership: leave it intact.
        fail(StLoadState, -60); release(dtb); release(adsp); return false;
    }
    stage(StLoadState);

    uint32_t lcx=0,lmx=0;
    if(!readResources() || qcom_rpmh_level_index(&gLcx,0xffffffffu,&lcx) ||
       qcom_rpmh_level_index(&gLmx,0xffffffffu,&lmx)) {
        fail(StRails,-2);release(dtb);release(adsp);return false;
    }
    if ((rc = vote(lcx, lmx))) {fail(StRails, rc); release(dtb); release(adsp); return false;}
    stage(StRails);

    // The DSP's devicetree image first, as its own authenticated image, then the DSP image.
    if ((rc = authenticateHeader(dtb, kPasDtb, kDtbBase)) || (rc = loadSegments(dtb, kDtbBase, kDtbSize)) ||
        (rc = scmOk(scm(QCOM_SCM_PAS_AUTH_AND_RESET, qcom_scm_args(1, 0, 0, 0), kPasDtb, 0, 0)) ? 0 : -3)) {
        fail(StDtb, rc); release(dtb); release(adsp); return false;
    }
    stage(StDtb);
    if ((rc = authenticateHeader(adsp, kPasAdsp, kAdspBase)) || (rc = loadSegments(adsp, kAdspBase, kAdspSize))) {
        fail(StLoaded, rc); release(dtb); release(adsp); return false;
    }
    stage(StLoaded);
    const uint64_t began = mach_absolute_time();
    if (!scmOk(scm(QCOM_SCM_PAS_AUTH_AND_RESET, qcom_scm_args(1, 0, 0, 0), kPasAdsp, 0, 0))) {
        fail(StStarted, -3); release(dtb); release(adsp); return false;
    }
    stage(StStarted);
    const bool ready = waitUntil(5000, [] {return (gSlave & (kReady | kFatal)) != 0;});
    uint64_t ns = 0;
    absolutetime_to_nanoseconds(mach_absolute_time() - began, &ns);
    native_adsp_stats[8] = (int32_t)(ns / 1000000);
    release(dtb);
    release(adsp);  // PAS metadata remains retained until reset
    if (!ready || (gSlave & kFatal)) {
        readCrashReason();
        fail(StReady, ready ? -5 : -60);
        return false;
    }
    stage(StReady);
    return true;
}

bool startGlink() {
    int rc = 0; // Both AP-owned items were allocated before DSP startup.
    uint32_t size = 0;
    volatile uint8_t *desc = item(kItemGlinkDesc, nullptr), *txf = item(kItemGlinkTx, &size);
    if (rc || !desc || !txf || size<kGlinkFifo) {fail(StGlink, rc ? rc : -2); return false;}
    volatile uint32_t *d = reinterpret_cast<volatile uint32_t *>(desc);
    // Descriptor words: our FIFO's tail and head, then the DSP's FIFO's tail and head.
    const QcomGlinkFifo tx = {&d[1], &d[0], txf, size}, rx = {&d[3], &d[2], nullptr, 0};
    qcom_glink_init(&gGlink, tx, rx, kickGlink, nullptr);
    gGlinkStarted = true;
    applyClients();
    serviceGlink();
    return true;
}

void adspWorker() {
    if(!mapWindow(gSmemW,kSmem,kSmemSize) || !mapWindow(gMutex,kMutex,0x1000) ||
       !mapWindow(gIpcc,kIpcc,0x1000) || !mapWindow(gAoss,kAoss,0x1000) || !mapWindow(gRsc,kRscDrv,0x10000)) {
        fail(StMapped,-12);return;
    }
    gSmem={gSmemW.va,(uint32_t)kSmemSize};gLayout=qcom_rsc_layout(rd(gRsc,0));
    stage(StMapped);survey();stage(StSurveyed);
    if(!(native_adsp_stats[4]&(1<<8)) || !start() || !startGlink())return;
    for(;;) {
        if((gSlave&kFatal) || gGlink.broken) {
            for(unsigned i=0;i<gClientCount;i++)clientState(&gClients[i],gClients[i].glink,0);
            fail(StChannel,-5);return;
        }
        if(gHandedOver && gProxyHeld) {
            int rc=vote(0,0);if(rc){fail(StRails,rc);return;}
        }
        bool pending=false;IOLockLock(gClientLock);
        for(unsigned i=0;i<gClientCount;i++)pending|=gClients[i].count!=0;
        IOLockUnlock(gClientLock);
        service(waitEvents(pending?1000:3600000u)|(pending?kEvSend:0));
    }
}
}  // namespace

extern "C" HoujiAdspChannel *houji_adsp_channel(const char *name, uint32_t intent_size, uint32_t intent_count, int initiator,
                                                const HoujiAdspClient *client, void *context) {
    if (!gClientLock || !name || !client || !intent_size || intent_size>4096 || strlen(name)>=QCOM_GLINK_NAME || !intent_count || intent_count > QCOM_GLINK_MAX_LOCAL_INTENTS) return nullptr;
    uint8_t *storage = static_cast<uint8_t *>(IOMalloc((vm_size_t)intent_size * intent_count));
    Message *queue = static_cast<Message *>(IOMalloc(sizeof(Message) * kQueue));
    IOLockLock(gClientLock);
    HoujiAdspChannel *c = gClientCount < kClients && storage && queue ? &gClients[gClientCount] : nullptr;
    if (c) {
        bzero(c, sizeof *c);
        strlcpy(c->name, name, sizeof c->name);
        c->intent_size = intent_size; c->intent_count = intent_count; c->initiator = initiator;
        c->client = *client; c->context = context; c->storage = storage; c->queue = queue;
        __atomic_store_n(&gClientCount, gClientCount + 1, __ATOMIC_RELEASE);
    }
    IOLockUnlock(gClientLock);
    if (!c) {
        if (storage) IOFree(storage, (vm_size_t)intent_size * intent_count);
        if (queue) IOFree(queue, sizeof(Message) * kQueue);
        return nullptr;
    }
    wake(kEvSend);
    return c;
}

extern "C" int houji_adsp_send(HoujiAdspChannel *c, const void *data, uint32_t length) {
    if (!c || !data || !length) return -2;
    if (length > HOUJI_ADSP_MAX_MESSAGE) return -1;
    IOLockLock(gClientLock);
    if (!c->online || c->count == kQueue) {IOLockUnlock(gClientLock); return -1;}
    Message &m = c->queue[(c->head + c->count) % kQueue];
    memcpy(m.data, data, length);
    m.length = length;
    c->count++;
    IOLockUnlock(gClientLock);
    wake(kEvSend);
    return 0;
}

extern "C" void houji_adsp_run(void) {
    if(native_adsp_stats[0])return;
    gClientLock=IOLockAlloc();if(!gClientLock){fail(StMapped,-12);return;}
    houji_qrtr_start();houji_battery_start();adspWorker();
    // No clients may use a failed generation. The registered IRQ contexts and
    // any PAS-referenced memory stay alive until this temporary boot resets.
    for(unsigned i=0;i<gClientCount;i++)clientState(&gClients[i],gClients[i].glink,0);
}
