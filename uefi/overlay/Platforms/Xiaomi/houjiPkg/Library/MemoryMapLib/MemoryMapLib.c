// SPDX-License-Identifier: BSD-2-Clause-Patent
// Generated from captured houji xbl_config, SHA256 1fd55850171f68f8658c2342820b76ee60d28733dfcc93ad365dd43e660f490d
#include <Library/MemoryMapLib.h>
#include <Library/PcdLib.h>
#include <Library/BaseMemoryLib.h>
#include <Protocol/HoujiRootRAM.h>

STATIC EFI_MEMORY_REGION_DESCRIPTOR gMemoryDescriptor[] = {
  {"RSRV0", 0x816E0000, 0x00320000, AddMem, 0, 0x703C07, 0, WRITE_BACK_XN},
  {"XBL_DT", 0x81A00000, 0x00040000, AddMem, 5, 0x703C07, 0, WRITE_BACK_XN},
  {"Minidump_Regions", 0x81BFF000, 0x00001000, AddMem, 5, 0x400, 0, UNCACHED_UNBUFFERED_XN},
  {"AOP", 0x81C00000, 0x000A0000, AddMem, 5, 0x400, 0, UNCACHED_UNBUFFERED_XN},
  {"UEFI_Log", 0x81CE4000, 0x00010000, AddMem, 5, 0x400, 0, UNCACHED_UNBUFFERED_XN},
  {"SMEM", 0x81D00000, 0x00200000, AddMem, 5, 0x400, 0, UNCACHED_UNBUFFERED_XN},
  {"PvmFw", 0x824A0000, 0x00100000, AddMem, 0, 0x703C07, 0, WRITE_BACK_XN},
  {"XBL_Ramdump", 0x84800000, 0x00200000, AddMem, 5, 0x400, 0, UNCACHED_UNBUFFERED_XN},
  {"PIL_Reserved", 0x8BC00000, 0x16F80000, AddMem, 5, 0x400, 0, UNCACHED_UNBUFFERED_XN},
  {"Display_Demura", 0xA3600000, 0x02B00000, AddMem, 5, 0x703C07, 0, WRITE_THROUGH_XN},
  {"DBI_Dump", 0xA6100000, 0x00F00000, NoHob, 1, 0x2, 7, UNCACHED_UNBUFFERED_XN},
  {"FD_Reserved", 0xA7000000, 0x00100000, AddMem, 0, 0x703C07, 0, WRITE_BACK},
  {"UEFI_FD", 0xA7100000, 0x00300000, AddMem, 0, 0x703C07, 4, WRITE_BACK},
  {"UEFI_FD_Reserved", 0xA7400000, 0x00200000, AddMem, 0, 0x703C07, 4, WRITE_BACK},
  {"CPU_Vectors", 0xA7600000, 0x00001000, AddMem, 0, 0x703C07, 4, WRITE_BACK},
  {"Info_Blk", 0xA7601000, 0x00001000, AddMem, 0, 0x703C07, 6, WRITE_BACK_XN},
  {"MMU_PageTables", 0xA7602000, 0x00003000, AddMem, 0, 0x703C07, 4, WRITE_BACK_XN},
  {"Log_Buffer", 0xA7605000, 0x00008000, AddMem, 0, 0x703C07, 6, WRITE_BACK_XN},
  {"UEFI_Stack", 0xA760D000, 0x00040000, AddMem, 0, 0x703C07, 4, WRITE_BACK_XN},
  {"SEC_Heap", 0xA764D000, 0x0008C000, AddMem, 0, 0x703C07, 4, WRITE_BACK_XN},
  {"Sched_Heap", 0xA76D9000, 0x00400000, AddMem, 0, 0x703C07, 4, WRITE_BACK_XN},
  {"FV_Region", 0xA7AD9000, 0x00400000, AddMem, 0, 0x703C07, 4, WRITE_BACK_XN},
  {"UEFI_RESV", 0xA7ED9000, 0x00127000, AddMem, 0, 0x703C07, 4, WRITE_BACK_XN},
  {"Kernel", 0xA8000000, 0x10000000, AddMem, 0, 0x703C07, 0, WRITE_BACK_XN},
  {"DXE_Heap", 0xB8000000, 0x1BA00000, AddMem, 0, 0x703C07, 7, WRITE_BACK_XN},
  {"TZApps_Reserved", 0xD8800000, 0x1B000000, AddMem, 5, 0x400, 0, UNCACHED_UNBUFFERED_XN},
  {"Display_Reserved", 0xFC400000, 0x02B00000, AddMem, 5, 0x703C07, 0, WRITE_THROUGH_XN},
  {"IMEM_Base", 0x14680000, 0x0002A000, NoHob, 1, 0x2, 7, NS_DEVICE},
  {"IMEM_Cookie_Base", 0x146AA000, 0x00016000, AddDev, 1, 0x2, 7, NS_DEVICE},
  {"IPC_ROUTER_TOP", 0x00400000, 0x00100000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"SECURITY_CONTROL", 0x00780000, 0x00007000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"QUP", 0x00800000, 0x00300000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"PRNG_CFG_PRNG", 0x010C0000, 0x0000C000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"CRYPTO0_CRYPTO", 0x01DC0000, 0x00040000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"CLK_TCSR_TCSR_REGS", 0x01F00000, 0x00100000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"PERIPH_SS", 0x08800000, 0x00100000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"USB", 0x0A600000, 0x00200000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"AOSS", 0x0B000000, 0x04000000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"TLMM", 0x0F000000, 0x01000000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"SMMU", 0x15000000, 0x00200000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"APSS_HM", 0x17000000, 0x02000000, AddDev, 1, 0x400, 11, NS_DEVICE},
  // WB-only cache capability; this MU GetMemoryMap reports GCD capabilities.
  {"Houji_HighRAM_Experimental", HOUJI_ROOT_RAM_LOW, HOUJI_ROOT_RAM_HIGH - HOUJI_ROOT_RAM_LOW, AddMem, 0, 0x702007, 7, WRITE_BACK_XN},
};

// Optional additions cover the eight ClockBSP base windows in this phone's
// original ClockDxe (RVA 0x20280, count 8 at 0x2bbb0), cross-checked against
// original DALSys HWIO parents. APSS_HM and CORE_TOP_CSR are already mapped.
// Keep the original 41 regions unchanged and never add overlapping aliases.
STATIC CONST EFI_MEMORY_REGION_DESCRIPTOR mClockMmio[] = {
  {"Houji_Clock_GCC", 0x00100000, 0x00200000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"Houji_Clock_CAMCC", 0x0AC00000, 0x00200000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"Houji_Clock_DISPCC", 0x0AE00000, 0x00200000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"Houji_Clock_GPUCC", 0x03D00000, 0x00100000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"Houji_Clock_VIDEOCC", 0x0AA00000, 0x00200000, AddDev, 1, 0x400, 11, NS_DEVICE},
  {"Houji_Clock_PCIE_RSCC", 0x01D00000, 0x00015000, AddDev, 1, 0x400, 11, NS_DEVICE},
};
// Original DAL HWIO UFS_MEM_UFS_2LANE_G5_REGS parent, including ICE/MCQ.
// Enable only for the explicitly selected storage diagnostic build.
STATIC CONST EFI_MEMORY_REGION_DESCRIPTOR mUfsMmio =
  {"Houji_UFS", 0x01D80000, 0x00040000, AddDev, 1, 0x400, 11, NS_DEVICE};
STATIC EFI_MEMORY_REGION_DESCRIPTOR mClockMap[ARRAY_SIZE (gMemoryDescriptor) + ARRAY_SIZE (mClockMmio) + 1];

VOID GetMemoryMap (OUT EFI_MEMORY_REGION_DESCRIPTOR **Map, OUT UINT8 *Count)
{
  // The probe maps high RAM as WB but reserves it from every allocator.
  gMemoryDescriptor[ARRAY_SIZE (gMemoryDescriptor) - 1].MemoryType =
    FeaturePcdGet (PcdHoujiHighRAMProbeEnable) ? EfiReservedMemoryType : EfiConventionalMemory;
  *Map = gMemoryDescriptor;
  *Count = (UINT8)(ARRAY_SIZE (gMemoryDescriptor) - ((FeaturePcdGet (PcdHoujiHighRAMEnable) || FeaturePcdGet (PcdHoujiHighRAMProbeEnable)) ? 0 : 1));
  if (FeaturePcdGet (PcdHoujiClockMmioEnable) || FeaturePcdGet (PcdHoujiUfsMmioEnable)) {
    CopyMem (mClockMap, gMemoryDescriptor, *Count * sizeof (*mClockMap));
    if (FeaturePcdGet (PcdHoujiClockMmioEnable)) {
      CopyMem (&mClockMap[*Count], mClockMmio, sizeof (mClockMmio));
      *Count += ARRAY_SIZE (mClockMmio);
    }
    if (FeaturePcdGet (PcdHoujiUfsMmioEnable)) {
      CopyMem (&mClockMap[(*Count)++], &mUfsMmio, sizeof (mUfsMmio));
    }
    *Map = mClockMap;
  }
}
