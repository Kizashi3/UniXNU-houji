// Actual RootCommands + firmware backend, with only MMIO/DMA/lock primitives
// replaced. Synthetic GPT, no device access. A missing command-gate connection
// (the r260 failure) must fail this test before a hardware run.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cassert>
#include <initializer_list>
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/RootDiagnostics.h"
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/RootTransportLayout.h"
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/TransferPoll.h"
using IOReturn=int;
enum {kIOReturnSuccess,kIOReturnBadArgument,kIOReturnBusy,kIOReturnError,kIOReturnIOError,
      kIOReturnNotPermitted,kIOReturnNotReady,kIOReturnTimeout,kMicrosecondScale};
static uint8_t dma[kDmaBytes],disk[1024*4096];static int lockDepth,commands,failOcs;
static struct {uint8_t *virt=dma;uintptr_t hc=0;uint64_t phys=0x100000;bool ready=true,poisoned=false;int *lock=&lockDepth;} gHost;
static UfsRootDiagnostics gRootDiagnostic;
static bool gLogEnabled,gLogArmed,gRootEnabled,gRootArmed,gReturnRecovery,gRecoveryArmed;
static void IOLockLock(int *p){assert(!*p);*p=1;}
static void IOLockUnlock(int *p){assert(*p==1);*p=0;}
static void IODelay(unsigned){}
static void IOSleep(unsigned){}
static uint64_t mach_absolute_time(){return 1;}
static void clock_interval_to_deadline(unsigned,unsigned,uint64_t *out){*out=100;}
static void cacheInvalidate(void *,unsigned){}
static void cacheCivac(void *,unsigned){}
static uint32_t read32(uintptr_t,unsigned){return 0;}
static IOReturn recordTransport(IOReturn r,uint32_t ocs){gRootDiagnostic.result=r;gRootDiagnostic.ocs=ocs;return r;}
static void hostWrite(unsigned,uint32_t);
static bool houjiNativeGpuFsAllowed(){return true;}
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/RootCommands.h"
#include "../kernel/overlay/iokit/Kernel/houji-ufs-root/HoujiFirmwareUfs.inc"
static void hostWrite(unsigned offset,uint32_t value) {
    assert(lockDepth==1);
    if(offset==0x20)return;
    assert(offset==0x58 && value==1);commands++;
    const uint8_t *u=dma+kUcdOffset;const uint8_t *c=u+16;
    assert(u[0]==1 && u[2]==4 && (c[0]==0 || c[0]==0x28));
    uint8_t *rsp=dma+kUcdOffset+kRspOffset;rsp[0]=0x21;rsp[2]=u[2];rsp[3]=u[3];
    *reinterpret_cast<uint32_t *>(dma+8)=failOcs?2:0;
    if(c[0]==0x28 && !failOcs) {
        uint32_t lba=loadBe32(c+2),blocks=(unsigned(c[7])<<8)|c[8];
        assert(blocks && blocks<=32 && lba<1024 && blocks<=1024-lba);
        memcpy(dma+kDataOffset,disk+lba*4096,blocks*4096);
    }
}
static void p32(uint8_t *p,uint32_t v){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(v>>(8*i));}
static void p64(uint8_t *p,uint64_t v){p32(p,(uint32_t)v);p32(p+4,(uint32_t)(v>>32));}
static void gpt() {
    uint8_t *h=disk+4096,*e=disk+8192;
    memcpy(h,"EFI PART",8);p32(h+8,0x10000);p32(h+12,92);p64(h+24,1);p64(h+32,1023);
    p64(h+40,6);p64(h+48,1018);p64(h+72,2);p32(h+80,4);p32(h+84,128);
    e[0]=1;p64(e+32,100);p64(e+40,199);const char *name="modem_a";
    for(unsigned i=0;i<7;i++)e[56+2*i]=name[i];
    p32(h+88,houji_fw_crc32(e,512,0));p32(h+16,houji_fw_crc32(h,92,1));
    memset(disk+100*4096,0xc1,4096);
}
static void policy() {
    uint8_t u[32]={};u[0]=1;u[2]=4;HoujiFirmwareReadGrant meta={1,0,0},part={2,100,100},none={};
    assert(houjiUfsFirmwareCommandAllowed(u,32,0,0,meta));
    assert(!houjiUfsFirmwareCommandAllowed(u,32,0,0,part));
    assert(!houjiUfsFirmwareCommandAllowed(u,32,0,0,none));
    for(unsigned lba: {0u,1u,2u,3u,5u,6u,99u,100u,199u,200u,0xffffffffu})
      for(unsigned blocks=1;blocks<=33;blocks++) {
        u[1]=0x40;u[16]=0x28;putBe32(u+12,blocks*4096);putBe32(u+18,lba);u[23]=0;u[24]=(uint8_t)blocks;
        bool a=blocks<=32 && ((lba==1 && blocks==1) || (lba==2 && blocks<=4));
        bool b=blocks<=32 && lba>=100 && lba<200 && blocks<=200-lba;
        assert(houjiUfsFirmwareCommandAllowed(u,32,2,blocks*4096,meta)==a);
        assert(houjiUfsFirmwareCommandAllowed(u,32,2,blocks*4096,part)==b);
        assert(!houjiUfsFirmwareCommandAllowed(u,32,1,blocks*4096,part));
        u[16]=0x2a;assert(!houjiUfsFirmwareCommandAllowed(u,32,2,blocks*4096,part));u[16]=0x28;
        for(unsigned lun=0;lun<8;lun++){u[2]=(uint8_t)lun;assert(houjiUfsFirmwareCommandAllowed(u,32,2,blocks*4096,part)==(b && lun==4));}
        u[2]=4;
      }
}
int main() {
    policy();gpt();uint8_t buf[4096];
    assert(hostRead4k(4,1,1,buf)==kIOReturnNotPermitted && commands==0);
    uint64_t blocks=0;assert(houji_modem_partition(&blocks) && blocks==100);
    assert(commands==4 && !gFirmwareReadGrant.active && !lockDepth);
    assert(houji_modem_read(0,1,buf) && buf[0]==0xc1);
    assert(commands==5 && !gFirmwareReadGrant.active && !lockDepth);
    assert(!houji_modem_read(100,1,buf) && !houji_modem_read(99,2,buf) && !houji_modem_read(UINT64_MAX,1,buf));
    assert(commands==5);
    failOcs=1;assert(!houji_modem_read(0,1,buf));
    assert(!gFirmwareReadGrant.active && !lockDepth);
    unsigned stage=0;uint32_t result=0,sense=0;houji_modem_status(&stage,&result,&sense);
    assert(stage==8 && result==kIOReturnIOError);
    assert(hostRead4k(4,100,1,buf)==kIOReturnNotPermitted && commands==6);
    puts("PASS: actual UFS submission gate, bounded metadata/modem reads, transfer error and per-command grant cleanup");
}
