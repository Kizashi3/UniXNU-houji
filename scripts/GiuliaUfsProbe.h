// SPDX-License-Identifier: BSD-2-Clause-Patent
// PKG110 runtime DT: GCC 0x100000, GDSCs 0x177004/0x19e000,
// UFS 0x1d84000/0x3000, apps-smmu 0x15000000/0x100000, SID 0x60.
// Register survey only: no controller, queue, SMMU or disk writes.
#include <IOKit/IOMemoryDescriptor.h>
#include <kern/debug.h>
#include <pexpert/arm64/boot.h>
#include <machine/machine_routines.h>
// osfmk/arm/machine_routines.h exposes this exact prototype only to Mach/
// pexpert private compilation. This built-in board helper links the source
// kernel's exported symbol; do not change all IOKit private feature macros.
extern "C" vm_offset_t ml_io_map_wcomb(vm_offset_t phys_addr, vm_size_t size);
extern "C" void giulia_ufs_read_root(void);

// Same prefix used by the freestanding panic renderer; no dependency on the
// normal console becoming active. Mapping lifetime covers the stopping survey.
extern "C" {
struct GiuliaPanicVideo {
  uint32_t height, width, depth, stride;
  uint64_t base;
};
GiuliaPanicVideo giulia_panic_vinfo;
}

static uintptr_t giuliaMap(uint64_t physical, uint64_t bytes,
                          OSSharedPtr<IOMemoryMap> &mapping)
{
  IODeviceMemory *memory = IODeviceMemory::withRange(physical, bytes);
  if (!memory) return 0;
  mapping = OSSharedPtr<IOMemoryMap>(memory->map(kIOMapAnywhere | kIOMapInhibitCache), OSNoRetain);
  memory->release();
  return mapping ? static_cast<uintptr_t>(mapping->getVirtualAddress()) : 0;
}

static uint32_t giuliaRead(uintptr_t base, unsigned offset)
{
  return *reinterpret_cast<volatile const uint32_t *>(base + offset);
}

extern "C" void giulia_early_console(void)
{
  unsigned requested = 0;
  PE_parse_boot_argn("giulia-ufs-probe", &requested, sizeof(requested));
  if ((requested != 1 && requested != 2) || giulia_panic_vinfo.base) return;
  const boot_args *boot = static_cast<const boot_args *>(PE_state.bootArgs);
  if (boot) {
    const Boot_Video &video = boot->Video;
    // Bound to this board's captured cont_splash_region, not arbitrary MMIO.
    if (video.v_width == 1264 && video.v_height == 2780 &&
        (video.v_depth & 0xff) == 32 && video.v_rowBytes >= 1264 * 4 &&
        video.v_rowBytes <= 16384 && video.v_baseAddr >= 0xd5100000ULL &&
        video.v_baseAddr < 0xd7c00000ULL &&
        video.v_rowBytes * video.v_height <= 0xd7c00000ULL - video.v_baseAddr) {
      uintptr_t frame = ml_io_map_wcomb(video.v_baseAddr, video.v_rowBytes * video.v_height);
      if (frame) {
        giulia_panic_vinfo = {2780, 1264, 32, static_cast<uint32_t>(video.v_rowBytes), frame};
        for (unsigned y = 2780 * 3 / 16; y < 2780 * 4 / 16; ++y)
          for (unsigned x = 0; x < 1264; ++x)
            *reinterpret_cast<volatile uint32_t *>(frame + y * video.v_rowBytes + x * 4) = 0xffffffffU;
        __asm__ volatile("dsb sy" ::: "memory");
      }
    }
  }
}

static void giuliaUfsProbe(void)
{
  unsigned requested = 0;
  PE_parse_boot_argn("giulia-ufs-probe", &requested, sizeof(requested));
  if (requested != 1 && requested != 2) return;
  giulia_early_console();
  OSSharedPtr<IOMemoryMap> clocksMap, memoryMap, hostMap, smmuMap;
  uintptr_t clocks = giuliaMap(0x177000, 0x1000, clocksMap);
  uintptr_t memory = giuliaMap(0x19e000, 0x1000, memoryMap);
  if (!clocks || !memory) panic("GIULIA UFS: GCC mapping failed");
  uint32_t power = giuliaRead(clocks, 4), memPower = giuliaRead(memory, 0);
  uint32_t axi = giuliaRead(clocks, 0x18), ahb = giuliaRead(clocks, 0x24);
  if (!(power & 0x80000000U) || !(axi & 1) || !(ahb & 1))
    panic("GIULIA UFS: power/clocks unavailable\ngdsc=%08x mem=%08x axi=%08x ahb=%08x", power, memPower, axi, ahb);
  if (requested == 2) giulia_ufs_read_root();
  uintptr_t host = giuliaMap(0x1d84000, 0x3000, hostMap);
  uintptr_t smmu = giuliaMap(0x15000000, 0x1000, smmuMap);
  if (!host || !smmu) panic("GIULIA UFS: host/SMMU mapping failed");
  unsigned entries = giuliaRead(smmu, 0x20) & 0xff;
  if (entries > 128) entries = 128;
  uint32_t slot = 0xffffffffU, match = 0, route = 0;
  for (unsigned i = 0; i < entries; ++i) {
    uint32_t smr = giuliaRead(smmu, 0x800 + i * 4);
    uint32_t mask = (smr >> 16) & 0x7fff;
    if ((smr & 0x80000000U) && (((smr & 0x7fff) ^ 0x60U) & ~mask) == 0) {
      slot = i; match = smr; route = giuliaRead(smmu, 0xc00 + i * 4); break;
    }
  }
  panic("GIULIA UFS SM8650 register survey\n"
        "gdsc=%08x mem=%08x axi=%08x ahb=%08x\n"
        "cap=%08x ver=%08x hcs=%08x hce=%08x\n"
        "list=%08x:%08x db=%08x rsr=%08x\n"
        "smmu id0=%08x id1=%08x id2=%08x\n"
        "SID60 slot=%08x smr=%08x s2cr=%08x\n"
        "read-only survey; root not mounted",
        power, memPower, axi, ahb,
        giuliaRead(host, 0), giuliaRead(host, 8), giuliaRead(host, 0x30), giuliaRead(host, 0x34),
        giuliaRead(host, 0x54), giuliaRead(host, 0x50), giuliaRead(host, 0x58), giuliaRead(host, 0x60),
        giuliaRead(smmu, 0x20), giuliaRead(smmu, 0x24), giuliaRead(smmu, 0x28), slot, match, route);
}
