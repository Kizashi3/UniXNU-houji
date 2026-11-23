##
#
#  Copyright (c) 2011 - 2022, ARM Limited. All rights reserved.
#  Copyright (c) 2014, Linaro Limited. All rights reserved.
#  Copyright (c) 2015 - 2020, Intel Corporation. All rights reserved.
#  Copyright (c) 2018, Bingxing Wang. All rights reserved.
#  Copyright (c) Microsoft Corporation.
#
#  SPDX-License-Identifier: BSD-2-Clause-Patent
#
##

################################################################################
#
# Defines Section - statements that will be processed to create a Makefile.
#
################################################################################
[Defines]
  PLATFORM_NAME                  = houji
  PLATFORM_GUID                  = 777656F0-55E0-558F-B5AB-3976C89A40F2
  PLATFORM_VERSION               = 0.1
  DSC_SPECIFICATION              = 0x00010005
  OUTPUT_DIRECTORY               = Build/houjiPkg
  SUPPORTED_ARCHITECTURES        = AARCH64
  BUILD_TARGETS                  = RELEASE|DEBUG
  SKUID_IDENTIFIER               = DEFAULT
  FLASH_DEFINITION               = houjiPkg/houji.fdf
  USE_CUSTOM_DISPLAY_DRIVER      = 0
  DEFINE WITH_DARWINBOOT          = 0
  DEFINE WITH_PAYLOAD             = 0
  DEFINE WITH_HOUJI_HIGH_RAM      = FALSE
  DEFINE WITH_HOUJI_ROOT_RAM      = FALSE
  DEFINE WITH_HOUJI_RAM_PROBE     = FALSE
  DEFINE WITH_HOUJI_STORAGE_PROBE = FALSE
  DEFINE WITH_HOUJI_CLOCK_MMIO    = FALSE
  DEFINE WITH_HOUJI_UFS_MMIO      = FALSE

  #
  # 0 = SM8650-AA
  # 1 = SM8650-Q-AA
  # 2 = SM8650-AB
  # 3 = SM8650-Q-AB
  # 4 = SM8650-AC
  #
  SOC_TYPE                       = 2

!include LanaiPkg/LanaiPkg.dsc.inc

[BuildOptions]
!if $(WITH_HOUJI_HIGH_RAM) == TRUE
  # Automatic pool/page allocations stay compatible with OEM 32-bit addresses.
  *_CLANGPDB_AARCH64_CC_FLAGS = -D HOUJI_LOW_UEFI_ALLOCS=1
!endif

[PcdsFeatureFlag]
  gHoujiPkgTokenSpaceGuid.PcdHoujiHighRAMEnable|$(WITH_HOUJI_HIGH_RAM)
  gHoujiPkgTokenSpaceGuid.PcdHoujiRootRAMEnable|$(WITH_HOUJI_ROOT_RAM)
  gHoujiPkgTokenSpaceGuid.PcdHoujiHighRAMProbeEnable|$(WITH_HOUJI_RAM_PROBE)
  gHoujiPkgTokenSpaceGuid.PcdHoujiClockMmioEnable|$(WITH_HOUJI_CLOCK_MMIO)
  gHoujiPkgTokenSpaceGuid.PcdHoujiUfsMmioEnable|$(WITH_HOUJI_UFS_MMIO)

[PcdsFixedAtBuild]
!if $(WITH_HOUJI_HIGH_RAM) == TRUE
!if $(TARGET) == DEBUG
  # Preserve debug/assert behavior, but FreePages must not poison gigabytes.
  gEfiMdePkgTokenSpaceGuid.PcdDebugPropertyMask|0x27
!endif
!endif
  # No SetupBrowser/driver-health forms in the RAM-only first-entry image.
  # UefiBootManagerLib documents ZeroGuid as the switch to skip that UI.
  gEfiMdeModulePkgTokenSpaceGuid.PcdDriverHealthConfigureForm|{0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00}
  #
  # DDR Memory
  #
  gArmTokenSpaceGuid.PcdSystemMemoryBase|0x80000000

  #
  # UEFI Stack
  #
  gArmPlatformTokenSpaceGuid.PcdCPUCoresStackBase|0xA760D000
  gArmPlatformTokenSpaceGuid.PcdCPUCorePrimaryStackSize|0x40000

  #
  # SMBIOS
  #
  gSiliciumPkgTokenSpaceGuid.PcdSmbiosSystemManufacturer|"Xiaomi"
  gSiliciumPkgTokenSpaceGuid.PcdSmbiosSystemRetailModel|"houji"
  gSiliciumPkgTokenSpaceGuid.PcdSmbiosSystemModel|"Xiaomi 14"
  gSiliciumPkgTokenSpaceGuid.PcdSmbiosSystemRetailSku|"23127PN0CC"
  gSiliciumPkgTokenSpaceGuid.PcdSmbiosSystemBoardModel|"houji"

  #
  # Simple Frame Buffer
  #
  gSiliciumPkgTokenSpaceGuid.PcdFrameBufferWidth|1200
  gSiliciumPkgTokenSpaceGuid.PcdFrameBufferHeight|2670
  gSiliciumPkgTokenSpaceGuid.PcdFrameBufferColorDepth|32

  #
  # Platform PEI
  #
  gQcomPkgTokenSpaceGuid.PcdPlatformType|"LA"

[LibraryClasses]
  #
  # Memory Libraries
  #
  MemoryMapLib|houjiPkg/Library/MemoryMapLib/MemoryMapLib.inf

  #
  # QCOM Libraries
  #
  ConfigurationMapLib|houjiPkg/Library/ConfigurationMapLib/ConfigurationMapLib.inf

  DeviceBootManagerLib|SiliciumNullPkg/Library/PlatformBootManagerLibNull/PlatformBootManagerLibNull.inf
  PlatformBootOptionsLib|SiliciumNullPkg/Library/PlatformBootOptionsLibNull/PlatformBootOptionsLibNull.inf
  FdtLib|MdePkg/Library/BaseFdtLib/BaseFdtLib.inf
  UniXNULib|UniXNUPkg/Library/UniXNULib/UniXNULib.inf

[Components]
!if $(WITH_HOUJI_STORAGE_PROBE) == TRUE
  houjiPkg/Application/HoujiStorageProbe/HoujiStorageProbe.inf
!endif
!if $(WITH_HOUJI_RAM_PROBE) == TRUE
  houjiPkg/Application/HoujiHighRAMProbe/HoujiHighRAMProbe.inf
!endif
!if $(WITH_HOUJI_ROOT_RAM) == TRUE
  houjiPkg/Drivers/HoujiRootRAMDxe/HoujiRootRAMDxe.inf
!endif
  UniXNUPkg/Application/UniXNU/UniXNU.inf
  UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
  HoujiVendorPkg/EnvDxeEnhanced/EnvDxeEnhanced.inf
  houjiPkg/Drivers/NoCapsuleRuntimeDxe/NoCapsuleRuntimeDxe.inf
!if $(WITH_DARWINBOOT) == 1
  # Build the loader separately for the RAM payload; not part of the stage-1 FV.
  DarwinBootPkg/Driver/DarwinBoot.inf
!endif
!if $(WITH_PAYLOAD) == 1
  houjiPkg/Drivers/HoujiRamDiskDxe/HoujiRamDiskDxe.inf
!endif
  #
  # ACPI Tables
  #
  #houji/AcpiTables.inf
