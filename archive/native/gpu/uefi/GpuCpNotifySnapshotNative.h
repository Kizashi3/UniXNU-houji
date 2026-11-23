/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * One batched read-only image before RAW publication, in the existing durable
 * preflight checkpoint. Includes inherited SCIDs, code bindings, privilege,
 * trust/status/fault registers, queue cursors and fresh lease root observations.
 */
#ifndef HOUJI_GPU_CP_NOTIFY_SNAPSHOT_NATIVE_H
#define HOUJI_GPU_CP_NOTIFY_SNAPSHOT_NATIVE_H
STATIC int CpNotifyMap(UINT64 Address) {
 UINT64 Saved,Par;EFI_TPL Tpl=gBS->RaiseTPL(TPL_HIGH_LEVEL);
 __asm__ volatile("mrs %0,par_el1":"=r"(Saved));
 __asm__ volatile("at s1e1r,%1; isb; mrs %0,par_el1":"=r"(Par):"r"(Address):"memory");
 __asm__ volatile("msr par_el1,%0; isb"::"r"(Saved):"memory");gBS->RestoreTPL(Tpl);
 return (Par&1) || (Par&0x0000fffffffff000ULL)!=(Address&~4095ULL) ||
  ((Par>>56)!=0 && (Par>>56)!=4);
}
STATIC int CpNotifySnapshot(VOID) {
 CONST uint32_t Addresses[]={0x3d0f004,0x3d0f008,0x3d02020,0x3d020c0,0x3d020c4,
  0x3d02dc0,0x3d02dc4,0x3d02110,0x3d02de0,0x3d3d000,0x3d00840,0x3d0084c,
  0x3d00804,0x3d8ec30,0x3d000e0,0x3dc0000,0x3dc0058,0x3dc3000,0x3dc3058};
 if(CpPolledReady(NULL))return 1;
 UINT64 Begin=BatchCounter();
 for(unsigned I=0;I<ARRAY_SIZE(Addresses);I++) {
  uint32_t Value;
  if(CpNotifyMap(Addresses[I]) || !CpPolledHealthy(NULL) || GpuTryRead32(Addresses[I],&Value))return 1;
  Print(L"HOUJI GPU CP NOTIFY BEFORE: i=%u address=%x value=%08x valid=1\n",I,Addresses[I],Value);
 }
 struct ggh_io Hfi={mFirmwareMemory.memory[5].cpu,GGH_BYTES,GGH_IOVA,NULL,StockHfiBarrier};
 for(unsigned Q=0;Q<3;Q++) {
  volatile uint32_t *Header,*Ring;unsigned Read,Write;
  if(ggh_queue(&Hfi,Q,&Header,&Ring,&Read,&Write) || Read!=Write)return 1;
  Print(L"HOUJI GPU CP NOTIFY QUEUE: q=%u status=%x type=%x read=%u write=%u empty=1\n",Q,Header[0],Header[2],Read,Write);
 }
 GpuDoorbellFaultReport();
 for(unsigned I=0;I<HCF_REGS;I++)Print(L"HOUJI GPU CP NOTIFY LEASE: i=%u address=%x value=%x valid=%x\n",I,hcf_reg(I),mCpPoll.last.regs[I],mCpPoll.last.valid_regs);
 for(unsigned I=0;I<HCF_ROOTS;I++)Print(L"HOUJI GPU CP NOTIFY ROOT: i=%u address=%x expected=%lx actual=%lx valid=%x\n",I,hcf_root(I),mCpPollRoots[I],mCpPoll.last.roots[I],mCpPoll.last.valid_roots);
 Print(L"HOUJI GPU CP NOTIFY BEFORE: batched snapshot elapsed-us=%lu; no queue publication or hardware writes\n",BatchMicroseconds(Begin));
 return CpPolledReady(NULL);
}
#endif
