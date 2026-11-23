#if defined(ARM64_BOARD_CONFIG_SWEET)
// SPDX-License-Identifier: BSD-2-Clause-Patent
// Read transport from pinned UniXNU Ace 5/NativeUfs; houji-specific GPT-only probe.
// No IOBlockStorageDevice bindings. Optional preallocated-file diagnostic writer.
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <libkern/crypto/sha2.h>
#include <vm/vm_kern.h>
#include <vm/vm_map.h>
#include <sys/param.h>
#include <sys/msgbuf.h>
#if defined(NATIVE_VERIFIED_BLOCK) && NATIVE_VERIFIED_BLOCK
#include "verified_root.h"
#include "VerifiedBlockPolicy.h"
extern "C" {
extern const struct vr_crypto vr_xnu_crypto;
extern const uint8_t verified_root_key[];
}
#endif
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSIterator.h>
#include <IOKit/IOBSD.h>
#include <kern/thread.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOLib.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSString.h>
#include <libkern/libkern.h>
#include <pexpert/pexpert.h>
#include <kern/debug.h>
#include "GccUfs.h"
#include "RootDiagnostics.h"
#include "TransferPoll.h"
#include "GiuliaSmmuTakeover.h"

static UfsRootDiagnostics gRootDiagnostic;
static bool gRootDiagnosticEnabled;
static void rootDiagnosticFailure (const char *reason);
static char gNativeText[4096];
static unsigned gNativeTextBytes;
static void nativeStage(const char *stage) {
  gRootDiagnostic.stage=stage;
  IOLog("HOUJI NATIVE UFS: %s\n",stage);
  if(gNativeTextBytes<sizeof(gNativeText)-1) {
    int n=snprintf(gNativeText+gNativeTextBytes,sizeof(gNativeText)-gNativeTextBytes,
                   "HOUJI NATIVE UFS: %s\n",stage);
    if(n>0)gNativeTextBytes+=unsigned(n)<sizeof(gNativeText)-gNativeTextBytes ?
      unsigned(n) : sizeof(gNativeText)-gNativeTextBytes-1;
  }
}

static uint32_t read32 (uintptr_t base, unsigned offset)
{
  return *reinterpret_cast<volatile uint32_t *> (base + offset);
}

static void write32 (uintptr_t base, unsigned offset, uint32_t value)
{
  *reinterpret_cast<volatile uint32_t *> (base + offset) = value;
}

static uintptr_t mapPhys (uint64_t phys, uint64_t length, OSSharedPtr<IOMemoryMap> &keep)
{
  IODeviceMemory *memory = IODeviceMemory::withRange (phys, length);
  if (!memory) {
    return 0;
  }
  keep = OSSharedPtr<IOMemoryMap> (memory->map (kIOMapAnywhere | kIOMapInhibitCache), OSNoRetain);
  memory->release ();
  return keep ? static_cast<uintptr_t> (keep->getVirtualAddress ()) : 0;
}

static void smmuBypassStream (uint16_t stream, OSSharedPtr<IOMemoryMap> &keep, uint32_t *report,
                              uint64_t dma, uint64_t bytes, uintptr_t host)
{
  if ((read32(host, 0x60) & 1) || read32(host, 0x58) || read32(host, 0x78))
    panic("HOUJI NATIVE UFS: queue not quiescent before SMMU takeover");
  uintptr_t smmu = mapPhys (0x15000000ULL, 0xd0000, keep);
  if (!smmu) {
    panic ("NATIVE_UFS smmu: map failed");
  }
  GiuliaSmmuPlan selection = planGiuliaSmmu (stream, dma, bytes, [smmu](unsigned offset) { return read32 (smmu, offset); });
  const UfsSmmuPlan &plan = selection.target;
  gRootDiagnostic.smmuId1 = read32 (smmu, 0x24);
  gRootDiagnostic.smmuId2 = read32 (smmu, 0x28);
  gRootDiagnostic.smmuSlot = plan.slot;
  if (plan.error) {
    nativeStage("SMMU planning");
    gRootDiagnostic.result = static_cast<uint32_t> (kIOReturnNotReady);
    gRootDiagnostic.smr = plan.smr; gRootDiagnostic.s2cr = plan.s2cr;
    rootDiagnosticFailure (plan.error);
    panic ("NATIVE_UFS smmu: %s slot=%u smr=%x s2cr=%x", plan.error, plan.slot, plan.smr, plan.s2cr);
  }
  unsigned bank = plan.bank, index = plan.slot;
  uintptr_t cb = smmu + (plan.pages + bank) * 4096;
  const char *failure = configureGiuliaSmmu (selection, stream, true,
    [smmu](unsigned offset) { return read32 (smmu, offset); },
    [smmu](unsigned offset, uint32_t value) {
      write32 (smmu, offset, value);
      __asm__ volatile ("dsb sy" ::: "memory");
    });
  uint32_t smr = read32 (smmu, 0x800 + 4 * index), s2cr = read32 (smmu, 0xc00 + 4 * index);
  uint32_t cbar = read32 (smmu, 0x1000 + 4 * bank), sctlr = read32 (cb, 0x0);
  gRootDiagnostic.smr = smr; gRootDiagnostic.s2cr = s2cr;
  gRootDiagnostic.cbar = cbar; gRootDiagnostic.sctlr = sctlr;
  gRootDiagnostic.smmuId2 = read32 (smmu, 0x28);
  gRootDiagnostic.cba2r = read32 (smmu, 0x1800 + 4 * bank);
  if (failure) {
    nativeStage("SMMU readback");
    gRootDiagnostic.result = static_cast<uint32_t> (kIOReturnNotReady);
    rootDiagnosticFailure (failure);
    panic ("NATIVE_UFS smmu: %s idx=%u bank=%u cba2r=%x", failure, index, bank,
           gRootDiagnostic.cba2r);
  }
  report[0] = index | (bank << 16);
  report[1] = cbar;
  report[2] = sctlr;
}

namespace {
#include "RootTransportLayout.h"

struct UfsHost {
  OSSharedPtr<IOMemoryMap> hcMap, smmuMap;
  uintptr_t hc;
  IOBufferMemoryDescriptor *dma;
  uint8_t *virt;
  uint64_t phys;
  IOLock *lock;
  bool ready;
  bool poisoned = false;
  uintptr_t smmu = 0, cb = 0;
};
UfsHost gHost = { OSSharedPtr<IOMemoryMap> (), OSSharedPtr<IOMemoryMap> (), 0, nullptr, nullptr, 0, nullptr, false };
static bool gLogEnabled, gLogArmed;

static IOReturn recordTransport (IOReturn result, uint32_t ocs)
{
  gRootDiagnostic.result = static_cast<uint32_t> (result);
  gRootDiagnostic.ocs = ocs;
  if (result != kIOReturnSuccess && gRootDiagnosticEnabled) {
    // Read only the already mapped HC's status/registers used by this driver.
    gRootDiagnostic.hcs = read32 (gHost.hc, 0x30);
    gRootDiagnostic.hce = read32 (gHost.hc, 0x34);
    gRootDiagnostic.doorbell = read32 (gHost.hc, 0x58);
    gRootDiagnostic.interrupt = read32 (gHost.hc, 0x20);
    gRootDiagnostic.list = uint64_t (read32 (gHost.hc, 0x50)) |
                          (uint64_t (read32 (gHost.hc, 0x54)) << 32);
    gRootDiagnostic.runStop = read32 (gHost.hc, 0x60);
    gRootDiagnostic.ahit = read32 (gHost.hc, 0x18);
    for (unsigned i = 0; i < 5; ++i) gRootDiagnostic.uic[i] = read32 (gHost.hc, 0x38 + 4 * i);
    if (gHost.smmu && gHost.cb) {
      gRootDiagnostic.gfsr = read32 (gHost.smmu, 0x48);
      gRootDiagnostic.gsyn = read32 (gHost.smmu, 0x54);
      gRootDiagnostic.fsr = read32 (gHost.cb, 0x58);
      gRootDiagnostic.fsyn = read32 (gHost.cb, 0x68);
      gRootDiagnostic.far = uint64_t (read32 (gHost.cb, 0x60)) |
                            (uint64_t (read32 (gHost.cb, 0x64)) << 32);
    }
  }
  return result;
}

static void cacheCivac (const void *start, size_t length)
{
  uintptr_t address = reinterpret_cast<uintptr_t> (start) & ~uintptr_t (63);
  uintptr_t end = reinterpret_cast<uintptr_t> (start) + length;
  for (; address < end; address += 64) {
    __asm__ volatile ("dc civac, %0" :: "r" (address) : "memory");
  }
  __asm__ volatile ("dsb sy" ::: "memory");
}

// Device-owned cache lines must not be written back over DMA results. All
// callers use complete 64-byte lines from the dedicated page-aligned buffer.
static void cacheInvalidate (const void *start, size_t length)
{
  __asm__ volatile ("dsb sy" ::: "memory");
  uintptr_t address = reinterpret_cast<uintptr_t> (start);
  for (uintptr_t end = address + length; address < end; address += 64) {
    __asm__ volatile ("dc ivac, %0" :: "r" (address) : "memory");
  }
  __asm__ volatile ("dsb sy" ::: "memory");
}

static void hostWrite (unsigned offset, uint32_t value)
{
  __asm__ volatile ("dsb sy" ::: "memory");
  write32 (gHost.hc, offset, value);
  __asm__ volatile ("dsb sy" ::: "memory");
}

#include "RootQueue.h"

#include "RootCommands.h"

// Bring the live controller up for reading: map, SMMU pass-through for the UFS stream, take over
// the request list, wake the device from UFS-PowerDown and wait for LUN 0 to be ready.
// `why` receives a short reason on failure.
static bool hostBringUp (const char **why)
{
  if (gHost.poisoned) {
    *why = "transport quarantined";
    return false;
  }
  if (gHost.ready) {
    return true;
  }
  nativeStage("controller map");
  gHost.hc = mapPhys (UFS_HC_BASE, UFS_HC_SIZE, gHost.hcMap);
  if (!gHost.hc) {
    *why = "controller map";
    return false;
  }
  if (gRootDiagnosticEnabled) {
    gRootDiagnostic.cap = read32 (gHost.hc, 0x00);
    gRootDiagnostic.version = read32 (gHost.hc, 0x08);
    gRootDiagnostic.hcs = read32 (gHost.hc, 0x30);
    gRootDiagnostic.hce = read32 (gHost.hc, 0x34);
  }
  nativeStage("DMA allocation");
  gHost.dma = IOBufferMemoryDescriptor::inTaskWithOptions (
    kernel_task, static_cast<IOOptionBits> (kIODirectionInOut) | static_cast<IOOptionBits> (kIOMemoryPhysicallyContiguous) |
    static_cast<IOOptionBits> (kIOMemoryMapperNone),
    kDmaBytes, 4096);
  gHost.lock = IOLockAlloc ();
  if (!gHost.dma || !gHost.lock) {
    *why = "dma buffer";
    return false;
  }
  gHost.virt = static_cast<uint8_t *> (gHost.dma->getBytesNoCopy ());
  IOByteCount contiguous = 0;
  gHost.phys = gHost.dma->getPhysicalSegment (0, &contiguous, kIOMemoryMapperNone);
  gRootDiagnostic.dma = gHost.phys;
  gRootDiagnostic.contiguous = contiguous;
  if (!gHost.virt || !gHost.phys || (gHost.phys & 4095) || contiguous < kDmaBytes ||
      (!(read32 (gHost.hc, 0) & 0x01000000) && gHost.phys + kDmaBytes > 0x100000000ULL)) {
    *why = "DMA address/contiguity";
    return false;
  }
  bzero (gHost.virt, kDmaBytes);
  cacheCivac (gHost.virt, kDmaBytes);
  uint32_t report[3] = { 0, 0, 0 };
  nativeStage("SMMU and request list");
  if (!hostStopQueue (why)) return false;
  smmuBypassStream (0x60, gHost.smmuMap, report, gHost.phys, kDmaBytes, gHost.hc);
  gHost.smmu = gHost.smmuMap->getVirtualAddress ();
  uint32_t idr1 = read32 (gHost.smmu, 0x24);
  gHost.cb = gHost.smmu + ((1U << (((idr1 >> 28) & 7) + 1)) + (report[0] >> 16)) * 4096;
  if (gRootDiagnosticEnabled) {
    gRootDiagnostic.gfsrBefore = read32 (gHost.smmu, 0x48);
    gRootDiagnostic.fsrBefore = read32 (gHost.cb, 0x58);
    gRootDiagnostic.smmuId2 = read32 (gHost.smmu, 0x28);
    gRootDiagnostic.cba2r = read32 (gHost.smmu, 0x1800 + 4 * (report[0] >> 16));
  }
  if (!hostStartQueue (why)) return false;
  nativeStage("NOP OUT");
  // NOP OUT proves the transport before touching the SCSI layer.
  if (hostNop () != kIOReturnSuccess) {
    gHost.ready = false;
    *why = "NOP OUT";
    return false;
  }
  uint32_t power = 0;
  nativeStage("power mode query");
  if (hostQueryRead (0x03, 0x02, &power) != kIOReturnSuccess) {
    gHost.ready = false;
    *why = "power mode query";
    return false;
  }
  gRootDiagnostic.power = power;
  if ((power & 0xff) != 0x11) {
    nativeStage("device wake");
    // START STOP UNIT, power condition ACTIVE, to the UFS Device well-known LU (as Linux resumes).
    uint8_t ssu[6] = { 0x1b, 0, 0, 0, 0x10, 0 };
    uint32_t scsi = 0;
    if (hostScsi (0xd0, ssu, 6, false, 0, 500000, &scsi) != kIOReturnSuccess) {
      gHost.ready = false;
      *why = "wake (START STOP UNIT)";
      return false;
    }
    IODelay (50000);
  }
  nativeStage("LUN ready");
  for (unsigned attempt = 0; attempt < 20; attempt++) {
    uint8_t tur[6] = { 0, 0, 0, 0, 0, 0 };
    uint32_t scsi = 0;
    if (hostScsi (0, tur, 6, false, 0, 200000, &scsi) == kIOReturnSuccess) {
      gHost.ready = true;
      return true;
    }
    if (gHost.poisoned) break;
    IODelay (10000);
  }
  gHost.ready = false;
  *why = "LUN 0 not ready";
  return false;
}
}

#include "HoujiGptCheck.h"
#include "HoujiLogFile.h"
#include "HoujiLogCommit.h"

extern "C" bool bsd_log_lock(bool);
extern "C" void bsd_log_unlock(void);

// Normal BSD initialization context only. Never invoked from a panic handler,
// interrupt, or while owning the log lock. No allocation/I/O while locked.
static unsigned copyKernelMessages(char *dst,unsigned capacity) {
  unsigned done=0;
  bsd_log_lock(true);
  const struct msgbuf *m=msgbufp;
  if(m && m->msg_magic==MSG_MAGIC && m->msg_bufc && m->msg_size>0 &&
     m->msg_bufx>=0 && m->msg_bufx<m->msg_size) {
    unsigned size=unsigned(m->msg_size), count=size<capacity?size:capacity;
    unsigned at=(unsigned(m->msg_bufx)+size-count)%size;
    for(unsigned i=0;i<count;i++) {
      char c=m->msg_bufc[at];at=(at+1)%size;
      if(c)dst[done++]=c;
    }
  }
  bsd_log_unlock();
  return done;
}

static IOReturn writeLogBlock(unsigned index,const uint8_t *data) {
  if(!gLogArmed || !gHost.ready || gHost.poisoned || index>=16 || !data) return kIOReturnNotPermitted;
  IOLockLock(gHost.lock);
  if(!hostClearUcd()) {IOLockUnlock(gHost.lock);return kIOReturnNotReady;}
  memcpy(gHost.virt+kDataOffset,data,4096);
  uint32_t lba=kHoujiLogLbas[index],scsi=0;
  uint8_t cdb[10]={0x2a,0,uint8_t(lba>>24),uint8_t(lba>>16),uint8_t(lba>>8),uint8_t(lba),0,0,1,0};
  IOReturn r=hostScsiDir(0,cdb,10,1,4096,1000000,&scsi);
  IOLockUnlock(gHost.lock);
  return r;
}
static IOReturn flushLog(void) {
  if(!gLogArmed || !gHost.ready || gHost.poisoned) return kIOReturnNotPermitted;
  IOLockLock(gHost.lock);
  uint8_t cdb[10]={0x35,0,0,0,0,0,0,0,0,0};uint32_t scsi=0;
  IOReturn r=hostScsiDir(0,cdb,10,0,0,1000000,&scsi);
  IOLockUnlock(gHost.lock);
  return r;
}
static const char *saveNativeLog(void) {
  static uint8_t metadata[7*4096],image[65536];
  nativeStage("logfs metadata read");
  for(unsigned i=0;i<7;i++)
    if(hostRead4k(0,4096+i,1,metadata+i*4096)!=kIOReturnSuccess) return "log metadata read failed";
  const char *why=houjiLogFatError(metadata,sizeof(metadata));
  if(why)return why;
  nativeStage("reserved file allocation verified");
  for(unsigned i=0;i<16;i++)
    if(hostRead4k(0,kHoujiLogLbas[i],1,image+i*4096)!=kIOReturnSuccess) return "initial log file read failed";
  if(!houjiLogInitialValid(image,sizeof(image)))return "initial log file/run ID changed";
  nativeStage("READ PASS; saving XNU snapshot before diagnostic stop");
  bzero(image,sizeof(image));
  unsigned used=gNativeTextBytes;
  memcpy(image+4096,gNativeText,used);
  static const char marker[]="\n--- XNU kernel message buffer (tail; NULs removed) ---\n";
  memcpy(image+4096+used,marker,sizeof(marker)-1);used+=sizeof(marker)-1;
  used+=copyKernelMessages(reinterpret_cast<char *>(image+4096+used),sizeof(image)-4096-used);
  houjiLogHeader(image,image+4096,used);
  // The armed window contains only the 16 preallocated file data sectors.
  // Commit header last, with a cache flush at each boundary. No FAT writes.
  gLogArmed=true;
  why=houjiCommitLog(image,sizeof(image),
    [](unsigned i,const uint8_t *p){return writeLogBlock(i,p)==kIOReturnSuccess;},
    [](){return flushLog()==kIOReturnSuccess;},
    [](unsigned i,uint8_t *p){return hostRead4k(0,kHoujiLogLbas[i],1,p)==kIOReturnSuccess;});
  gLogArmed=false;
  if(why)return why;
  IOLog("HOUJI XNU LOG: COMMIT/FLUSH/READBACK PASS bytes=%u crc=%08x\n",used,houjiLe32(image+36));
  return nullptr;
}
static void logTrialReset(void) {
  // Real houji FDT /soc/psci: compatible arm,psci-1.0, method smc.
  // Only after successful file readback; no partition/boot selection writes.
  IOLog("HOUJI XNU LOG: verified snapshot; returning to Android through PSCI\n");
  __asm__ volatile("dsb sy" ::: "memory");
  register uint64_t x0 __asm__("x0")=0x84000009U;
  __asm__ volatile("smc #0" : "+r"(x0) :: "x1","x2","x3","x4","x5","x6","x7",
                   "x8","x9","x10","x11","x12","x13","x14","x15","x16","x17","cc","memory");
  panic("HOUJI XNU LOG: saved, PSCI reset unexpectedly returned %llx",x0);
}
static void rootDiagnosticFailure(const char *why) {
  char text[2048];
  formatUfsRootDiagnostics(text,sizeof(text),gRootDiagnostic,why);
  panic("HOUJI NATIVE UFS READ FAILED\n%s",text);
}
extern "C" void houji_ufs_read_gpt(void) {
  gRootDiagnosticEnabled=true;
  int logMode=0;
  gLogEnabled=PE_parse_boot_argn("houji_ufs_log",&logMode,sizeof(logMode)) && logMode==1;
  IOLog("HOUJI NATIVE UFS: GPT probe; native fixed-file log=%u\n",unsigned(gLogEnabled));
  const char *why="unknown";
  if(!hostBringUp(&why))rootDiagnosticFailure(why);
  static uint8_t header[4096],entries[8192];
  nativeStage("read primary GPT header");
  if(hostRead4k(0,1,1,header)!=kIOReturnSuccess)rootDiagnosticFailure("primary GPT read");
  nativeStage("read 64 GPT entries");
  if(hostRead4k(0,2,2,entries)!=kIOReturnSuccess)rootDiagnosticFailure("GPT entry array read");
  why=houjiGptError(header,sizeof(header),entries,sizeof(entries));
  if(why)rootDiagnosticFailure(why);
  nativeStage("HOUJI NATIVE UFS READ PASS; GPT CRC=631fc7ea/9f1bb496");
  IOLog("HOUJI NATIVE UFS: DMA=%llx SMMU slot=%u bank=%u\n",gHost.phys,
        gRootDiagnostic.smmuSlot,gRootDiagnostic.s2cr&255);
  if(gLogEnabled) {
    why=saveNativeLog();
    if(why)rootDiagnosticFailure(why);
    logTrialReset();
  }
  panic("HOUJI NATIVE UFS READ PASS\nReal XNU DMA, NOP, LUN0 header and 64 entries verified\n"
    "header CRC=631fc7ea entries CRC=9f1bb496\nDMA=%llx SMMU slot=%u bank=%u\n"
    "Diagnostic stop; iOS volume not mounted; no media write commands",
    gHost.phys,gRootDiagnostic.smmuSlot,gRootDiagnostic.s2cr&255);
}

#endif
