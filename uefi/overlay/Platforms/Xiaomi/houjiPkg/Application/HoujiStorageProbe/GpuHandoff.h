// SPDX-License-Identifier: BSD-2-Clause-Patent
// Resolve the native SM8650 interface first. No resource acquisition or MMIO.
STATIC VOID QueryGpuClockInterface(VOID) {
  EFI_CLOCK_PROTOCOL *Clock=NULL;
  EFI_STATUS Status=gBS->LocateProtocol(&gEfiClockProtocolGuid,NULL,(VOID **)&Clock);
  Print(L"HOUJI GPU UEFI RO: Clock locate=%r\n",Status);
  if(EFI_ERROR(Status) || !Clock || Clock->Version!=0x1000a || !Clock->GetClockID || !Clock->GetClockPowerDomainID) {
    Print(L"HOUJI GPU UEFI RO: incompatible native Clock interface; no calls\n");return;
  }
  CONST CHAR8 *Names[]={"gcc_gpu_cfg_ahb_clk","gpu_cc_cx_gmu_clk","gpu_cc_hub_aon_clk",
    "gpu_cc_cxo_clk","gcc_ddrss_gpu_axi_clk","gcc_gpu_memnoc_gfx_clk",
    "gcc_gpu_snoc_dvm_gfx_clk","gpu_cc_ahb_clk","gpu_cc_hlos1_vote_gpu_smmu_clk"};
  UINTN Passed=0;
  for(UINTN I=0;I<ARRAY_SIZE(Names);I++) {
    UINTN Id=0;Status=Clock->GetClockID(Clock,Names[I],&Id);
    Print(L"HOUJI GPU UEFI RO: clock=%a id=%lx lookup=%r\n",Names[I],Id,Status);
    if(!EFI_ERROR(Status) && (Id&0xffff0000)==0x10000)Passed++;
  }
  UINTN Id=0;Status=Clock->GetClockPowerDomainID(Clock,"gpu_cc_cx_gdsc",&Id);
  Print(L"HOUJI GPU UEFI RO: domain=gpu_cc_cx_gdsc id=%lx lookup=%r\n",Id,Status);
  Print(L"HOUJI GPU UEFI RO: resolved=%u/%u; no enables/rate/voltage/reset/firmware calls\n",Passed,ARRAY_SIZE(Names));
}
