/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * CANDIDATE ONLY; include in Main after the existing recovery helpers.
 * Call Prearm BEFORE any power preparation. It does not write misc. Only a
 * native trial's exact, host-prepared no-wipe BCB plus a successful durable
 * checkpoint can arm the later reset-only exit. This is not a watchdog.
 * No promise is made that logs generated after prearming have been saved.
 */
STATIC BOOLEAN mGpuPowerRecoveryPrearmAttempted,mGpuPowerRecoveryArmed;
STATIC BOOLEAN mGpuPowerRecoveryResetAttempted;
STATIC BOOLEAN GpuPowerRecoveryPrearm(VOID) {
 STATIC UINT8 Block[4096] __attribute__((aligned(4096)));
 UINT8 Expected[864];
 if(mGpuPowerRecoveryPrearmAttempted || !mXnuUfsRun || !HoujiGpuMaySave() ||
  !mGpuCheckpointParent || !mGpuCheckpointParent->Media ||
  !mGpuCheckpointParent->ReadBlocks || !gRT || !gRT->ResetSystem)return FALSE;
 EFI_BLOCK_IO_PROTOCOL *Parent=mGpuCheckpointParent;
 EFI_BLOCK_IO_MEDIA *Media=Parent->Media;
 if(!Media->MediaPresent || Media->BlockSize!=4096 || Media->IoAlign>4096 ||
  Media->LastBlock<1024 || !hgr_record(Expected,sizeof(Expected)))return FALSE;
 UINT32 MediaId=Media->MediaId;
 mGpuPowerRecoveryPrearmAttempted=TRUE;
 EFI_STATUS Status=Parent->ReadBlocks(Parent,MediaId,1024,sizeof(Block),Block);
 BOOLEAN Match=Status==EFI_SUCCESS && CompareMem(Block,Expected,sizeof(Expected))==0;
 Print(L"HOUJI GPU PREARM: BCB read=%r exact-no-wipe-request=%u; misc unchanged\n",Status,Match);
 if(!Match || !mXnuUfsRun || !HoujiGpuMaySave() || mGpuCheckpointParent!=Parent ||
  Parent->Media!=Media || Media->MediaId!=MediaId)return FALSE;
 Status=ProbeCheckpoint("gpu-power-prearmed-exact-no-wipe-recovery");
 Print(L"HOUJI GPU PREARM: durable checkpoint=%r; later RAM logs are not promised saved\n",Status);
 if(Status!=EFI_SUCCESS || !mXnuUfsRun || !HoujiGpuMaySave() ||
  mGpuCheckpointParent!=Parent || Parent->Media!=Media || Media->MediaId!=MediaId ||
  !Media->MediaPresent || Media->BlockSize!=4096 || Media->IoAlign>4096 || Media->LastBlock<1024)return FALSE;
 mGpuPowerRecoveryArmed=TRUE;return TRUE;
}
STATIC BOOLEAN GpuPowerRecoveryResetWithoutIO(VOID) {
 if(!mXnuUfsRun || !mGpuPowerRecoveryArmed || mGpuPowerRecoveryResetAttempted ||
  HoujiGpuMaySave() || !gRT || !gRT->ResetSystem)return FALSE;
 mGpuPowerRecoveryResetAttempted=TRUE;mGpuPowerRecoveryArmed=FALSE;
 // No block access, filesystem/checkpoint/console call or last-log claim here.
 gRT->ResetSystem(EfiResetCold,EFI_SUCCESS,0,NULL);
 return FALSE; // Reset unexpectedly returned; never claim successful recovery.
}
