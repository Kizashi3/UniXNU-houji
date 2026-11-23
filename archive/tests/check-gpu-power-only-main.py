#!/usr/bin/env python3
"""Exercise the actual power-only Main branch/publication helpers; no firmware/device run."""
from pathlib import Path
import json,re,subprocess,tempfile,hashlib,argparse
parser=argparse.ArgumentParser();parser.add_argument("--run",type=int,default=141);args=parser.parse_args()
p=Path(__file__).resolve().parents[1]
u=Path('${HOUJI_UEFI_ROOT}/Platforms/Xiaomi/houjiPkg/Application/HoujiStorageProbe')
n=Path('${HOUJI_ARTIFACTS}/native-port')
s=(u/'HoujiStorageProbe.c').read_text()
helpers=s[s.index('STATIC EFI_GUID mGpuPowerHandoffGuid='):s.index('\n\nSTATIC EFI_STATUS\nRunUfsReadonly')]
branch=s[s.index('      if(HOUJI_GPU_POWER_HANDOFF_XNU_ONLY) {'):s.index('      if(HOUJI_GPU_CPU_ABI_XNU_ONLY) {')]
assert branch.endswith('      } else {\n')
branch=branch.removesuffix(' else {\n')+'\n'
assert 'for(;;)gBS->Stall(1000000);' in branch
assert 'before-XNU-power-only-handoff-observe' in branch
assert 'L"HOUJI GPU POWER HANDOFF: UEFI power/clocks only; XNU fresh RO observation\\n"' in branch
assert '#define HOUJI_GPU_POWER_HANDOFF_XNU_ONLY 1' in s
# Actual argument assembly stays byte-for-byte equal to the frozen r140 argv.
base=re.search(r'CONST CHAR16 \*BaseBootArgs = L"([^"]+)";',s).group(1)
assert base+' houji_touch=0'==(n/f'native-ios-candidate/r{args.run}-xnu-bootargs.txt').read_text().strip()
assert len(base+' houji_touch=0')<608
assert s.count(f'HOUJI LOGFS r{args.run}: app diagnostic capture; not full OEM/XNU output')==1
assert 'UnicodeSPrint(BootArgs,sizeof(BootArgs),L"%s houji_touch=%u",BaseBootArgs,mTouchHandoffReady?1:0);' in s
before=json.loads((n/'evidence/r140-power-only-app-integration/before.json').read_text())
old=Path(before[str(u/'HoujiStorageProbe.c')]['backup']).read_text()
for name,next_name in [('GpuBatchReturnRecovery','\nSTATIC EFI_STATUS\nBootNativeUfsProbe'),('GpuTrialReturnRecovery','\n\n#include "GpuPrearmedRecoveryNative.inc"')]:
 pattern='STATIC BOOLEAN\n'+name
 a=s[s.index(pattern):s.index(next_name,s.index(pattern))].strip()
 old_end='\n\nSTATIC EFI_STATUS\nRunUfsReadonly' if name=='GpuTrialReturnRecovery' else next_name
 b=old[old.index(pattern):old.index(old_end,old.index(pattern))].strip()
 assert a==b, name+' legacy recovery changed'
manifest=json.loads((p/'native/gpu/uefi/manifest.json').read_text())
for name in ['HoujiStorageProbe.c','GpuPower.c','GpuPowerOnlyHandoff.h','GpuPowerOnlyAdapter.inc','GpuPrearmedRecoveryNative.inc','GpuPowerHandoffGuid.h']:
 assert manifest['source_files']['Application/HoujiStorageProbe/'+name]==hashlib.sha256((u/name).read_bytes()).hexdigest()
program=r'''
#define main portable_test_main
#include "PORTABLE_TEST"
#undef main
#include <setjmp.h>
#include <stdarg.h>
#include <wchar.h>
#include "GpuRecoveryRequest.h"
#include "GpuPowerHandoffGuid.h"
#define STATIC static
#define CONST const
#define VOID void
#define TRUE 1
#define FALSE 0
#define HOUJI_GPU_POWER_HANDOFF_XNU_ONLY 1
typedef unsigned BOOLEAN;
typedef void *EFI_HANDLE;
typedef uint64_t EFI_STATUS;
typedef unsigned EFI_TPL;
typedef uint8_t UINT8;
typedef uint32_t UINT32;
typedef unsigned long UINTN;
typedef char CHAR8;
typedef struct {uint32_t A;uint16_t B,C;uint8_t D[8];} EFI_GUID;
typedef struct {EFI_GUID VendorGuid;void *VendorTable;} EFI_CONFIGURATION_TABLE;
typedef struct {UINTN NumberOfTableEntries;EFI_CONFIGURATION_TABLE *ConfigurationTable;} EFI_SYSTEM_TABLE;
#define EFI_SUCCESS UINT64_C(0)
#define EFI_INVALID_PARAMETER UINT64_C(0x8000000000000002)
#define EFI_UNSUPPORTED UINT64_C(0x8000000000000003)
#define EFI_DEVICE_ERROR UINT64_C(0x8000000000000007)
#define EFI_ACCESS_DENIED UINT64_C(0x800000000000000f)
#define EFI_ALREADY_STARTED UINT64_C(0x8000000000000014)
#define EFI_COMPROMISED_DATA UINT64_C(0x8000000000000021)
#define EFI_ERROR(s) (((uint64_t)(s)>>63)!=0)
#define CompareMem memcmp
#define CompareGuid(a,b) (!memcmp((a),(b),sizeof(EFI_GUID)))
#define EfiResetCold 0
enum {TPL_APPLICATION=4,TPL_NOTIFY=16,TPL_HIGH_LEVEL=31};
typedef struct EFI_BLOCK_IO_MEDIA {
 unsigned MediaPresent,BlockSize,IoAlign;uint64_t LastBlock;uint32_t MediaId;
} EFI_BLOCK_IO_MEDIA;
typedef struct EFI_BLOCK_IO_PROTOCOL EFI_BLOCK_IO_PROTOCOL;
struct EFI_BLOCK_IO_PROTOCOL {
 EFI_BLOCK_IO_MEDIA *Media;
 EFI_STATUS (*ReadBlocks)(EFI_BLOCK_IO_PROTOCOL *,uint32_t,uint64_t,unsigned,void *);
};
static unsigned mXnuUfsRun,may_save;
static EFI_BLOCK_IO_PROTOCOL *mGpuCheckpointParent;
static EFI_BLOCK_IO_MEDIA media;
static EFI_BLOCK_IO_PROTOCOL parent;
struct runtime {void (*ResetSystem)(unsigned,EFI_STATUS,unsigned,void *);};
static struct runtime runtime,*gRT;
static EFI_SYSTEM_TABLE st,*gST;
static EFI_CONFIGURATION_TABLE tables[257];
static unsigned current_tpl,seq,reads,commits,resets,power_calls,installs,safe_exits,stalls;
static unsigned fail_read,warn_read,bad_bcb,fail_commit,warn_commit,fail_final_commit;
static unsigned fail_power,warn_power,unsafe_power,corrupt_record,not_complete,late_collision;
static unsigned fail_install,warn_install,flip_bit;
static struct hph_record known_good;
static jmp_buf stopped;
static BOOLEAN HoujiGpuMaySave(void) {return may_save;}
static void Print(const wchar_t *format,...) {assert(format);}
static EFI_STATUS ProbeCheckpoint(const char *);
static void Reset(unsigned,EFI_STATUS,unsigned,void *);
static EFI_STATUS Install(EFI_GUID *,void *);
static unsigned RaiseTpl(unsigned tpl) {unsigned old=current_tpl;assert(tpl>=old);current_tpl=tpl;return old;}
static void RestoreTpl(unsigned tpl) {assert(tpl<=current_tpl);current_tpl=tpl;}
static void Stall(unsigned us) {assert(us==1000000);stalls++;longjmp(stopped,1);}
static const struct {unsigned(*RaiseTPL)(unsigned);void(*RestoreTPL)(unsigned);EFI_STATUS(*InstallConfigurationTable)(EFI_GUID *,void *);void(*Stall)(unsigned);} bs={RaiseTpl,RestoreTpl,Install,Stall};
static const __typeof__(bs) *gBS=&bs;
static BOOLEAN GpuTrialReturnRecovery(const char *reason) {
 assert(reason && may_save && !resets);safe_exits++;return FALSE;
}
#include "GpuPrearmedRecoveryNative.inc"
static EFI_STATUS HoujiGpuPowerOnlyPrepare(EFI_HANDLE image,struct hph_record *out) {
 assert(image==(void *)0x1234 && current_tpl==TPL_APPLICATION && !power_calls++ && reads==1 && commits==1);
 assert(seq==2 && mGpuPowerRecoveryArmed && !installs);seq=3;
 *out=known_good;
 if(unsafe_power)may_save=0;
 if(corrupt_record)out->crc32^=1;
 if(not_complete) {out->complete=0;out->code=HPH_READ;hph_seal(out);assert(hph_record_valid(out));}
 if(flip_bit<HPH_RECORD_BYTES*8u)((uint8_t *)out)[flip_bit/8u]^=(uint8_t)(1u<<(flip_bit%8u));
 if(late_collision) {tables[0].VendorGuid=(EFI_GUID)HOUJI_GPU_POWER_HANDOFF_GUID;st.NumberOfTableEntries=1;}
 return fail_power?EFI_DEVICE_ERROR:warn_power?1:EFI_SUCCESS;
}
HELPERS
static EFI_STATUS Read(EFI_BLOCK_IO_PROTOCOL *io,uint32_t id,uint64_t lba,unsigned bytes,void *out) {
 assert(io==&parent && id==media.MediaId && lba==1024 && bytes==4096 && !((uintptr_t)out&4095));
 assert(current_tpl==TPL_APPLICATION && !reads++ && !commits && !power_calls && !installs && !seq);seq=1;
 memset(out,0xa5,bytes);assert(hgr_record(out,864));if(bad_bcb)((uint8_t *)out)[3]^=1;
 return fail_read?EFI_DEVICE_ERROR:warn_read?1:EFI_SUCCESS;
}
static EFI_STATUS ProbeCheckpoint(const char *name) {
 assert(current_tpl==TPL_APPLICATION && may_save && name);commits++;
 if(commits==1) {
  assert(!strcmp(name,"gpu-power-prearmed-exact-no-wipe-recovery") && seq==1 && reads==1 && !power_calls);seq=2;
  return fail_commit?EFI_DEVICE_ERROR:warn_commit?1:EFI_SUCCESS;
 }
 assert(commits==2 && !strcmp(name,"before-XNU-power-only-handoff-observe") && seq==4 && power_calls==1 && installs==1);
 return fail_final_commit?1:EFI_SUCCESS;
}
static EFI_STATUS Install(EFI_GUID *guid,void *record) {
 assert(current_tpl==TPL_NOTIFY && seq==3 && power_calls==1 && !installs++ && may_save);
 assert(CompareGuid(guid,&mGpuPowerHandoffGuid) && record==&mGpuPowerHandoffRecord);
 assert(hph_record_valid(record) && ((struct hph_record *)record)->complete==1);
 assert(!memcmp(record,&known_good,sizeof(known_good)));seq=4;
 return fail_install?EFI_DEVICE_ERROR:warn_install?1:EFI_SUCCESS;
}
static void Reset(unsigned kind,EFI_STATUS status,unsigned bytes,void *extra) {
 assert(!may_save && kind==EfiResetCold && !status && !bytes && !extra && !resets++);
 assert(mGpuPowerRecoveryResetAttempted && !mGpuPowerRecoveryArmed && current_tpl==TPL_APPLICATION);
}
static void Fresh(void) {
 current_tpl=TPL_APPLICATION;seq=reads=commits=resets=power_calls=installs=safe_exits=stalls=0;
 fail_read=warn_read=bad_bcb=fail_commit=warn_commit=fail_final_commit=0;
 fail_power=warn_power=unsafe_power=corrupt_record=not_complete=late_collision=fail_install=warn_install=0;
 flip_bit=HPH_RECORD_BYTES*8u;
 memset(tables,0,sizeof(tables));st=(EFI_SYSTEM_TABLE){0,tables};gST=&st;
 media=(EFI_BLOCK_IO_MEDIA){1,4096,4096,0x100000,77};parent=(EFI_BLOCK_IO_PROTOCOL){&media,Read};mGpuCheckpointParent=&parent;
 runtime.ResetSystem=Reset;gRT=&runtime;mXnuUfsRun=may_save=1;
 mGpuPowerRecoveryPrearmAttempted=mGpuPowerRecoveryArmed=mGpuPowerRecoveryResetAttempted=0;
 mGpuPowerHandoffAttempted=0;memset(&mGpuPowerHandoffRecord,0,sizeof(mGpuPowerHandoffRecord));
}
static EFI_STATUS Profile(void) {
 EFI_STATUS Status=EFI_SUCCESS;EFI_HANDLE ImageHandle=(void *)0x1234;
 BRANCH
 return Status;
}
int main(void) {
 struct gpp_report pwr=power();struct mock hardware=initial();
 assert(run(&hardware,&pwr,&known_good)==HPH_OK && hph_record_valid(&known_good));
 Fresh();assert(GpuPowerHandoffPrepare((void *)0x1234)==EFI_SUCCESS && installs==1 && current_tpl==4);
 unsigned old_reads=reads,old_commits=commits;assert(GpuPowerHandoffPrepare((void *)0x1234)==EFI_ALREADY_STARTED);
 assert(reads==old_reads && commits==old_commits && power_calls==1 && installs==1);cases++;
 for(unsigned i=0;i<4;i++) {
  Fresh();if(i==0)gST=NULL;if(i==1)st.NumberOfTableEntries=257;
  if(i==2) {st.NumberOfTableEntries=1;st.ConfigurationTable=NULL;}
  if(i==3) {tables[0].VendorGuid=mGpuPowerHandoffGuid;tables[0].VendorTable=NULL;st.NumberOfTableEntries=1;}
  assert(GpuPowerHandoffPrepare((void *)0x1234)==EFI_ALREADY_STARTED);
  assert(!reads && !commits && !power_calls && !installs && current_tpl==4);cases++;
 }
 Fresh();current_tpl=TPL_NOTIFY;assert(GpuPowerHandoffPrepare((void *)0x1234)==EFI_UNSUPPORTED);
 assert(current_tpl==TPL_NOTIFY && !reads && !commits && !power_calls && !installs);cases++;
 // Every scalar bit participates in actual decode/CRC qualification before publication.
 for(unsigned i=0;i<HPH_RECORD_BYTES*8u;i++) {
  Fresh();flip_bit=i;assert(GpuPowerHandoffPrepare((void *)0x1234)==EFI_COMPROMISED_DATA);
  assert(reads==1 && commits==1 && power_calls==1 && !installs && current_tpl==4);cases++;
 }
 for(unsigned i=0;i<12;i++) {
  Fresh();switch(i) {
   case 0:fail_read=1;break;case 1:warn_read=1;break;case 2:bad_bcb=1;break;
   case 3:fail_commit=1;break;case 4:warn_commit=1;break;case 5:fail_power=1;break;
   case 6:warn_power=1;break;case 7:corrupt_record=1;break;case 8:not_complete=1;break;
   case 9:late_collision=1;break;case 10:fail_install=1;break;case 11:warn_install=1;break;
  }
  assert(EFI_ERROR(GpuPowerHandoffPrepare((void *)0x1234)) && current_tpl==4);
  assert(installs==(i>=10) && power_calls==(i>=5));cases++;
 }
 Fresh();assert(Profile()==EFI_SUCCESS && commits==2 && installs==1 && !resets && !safe_exits && !stalls);cases++;
 for(unsigned i=0;i<4;i++) {
  Fresh();if(i==0)fail_read=1;
  if(i==1)fail_power=1;
  if(i==2) {fail_power=unsafe_power=1;}
  if(i==3)fail_final_commit=1;
  if(!setjmp(stopped)) { (void)Profile();assert(!"failed profile fell through to XNU"); }
  assert(stalls==1 && current_tpl==4);
  assert(resets==(i==2) && safe_exits==(i!=2));
  if(i==2) {assert(reads==1 && commits==1 && !installs);assert(!GpuPowerHandoffReturnRecovery("repeat") && resets==1);}
  cases++;
 }
 printf("PASS: actual power-only Main %u cases; strict scalar publication, early/late collision, prearm order, recovery split, reset-return STOP; ASAN/UBSAN/-Werror\\n",cases);
}
'''
program=program.replace('PORTABLE_TEST',str(p/'tests/check-gpu-power-only-handoff.c')).replace('HELPERS',helpers).replace('BRANCH',branch)
with tempfile.TemporaryDirectory(prefix='houji-r140-main-') as d:
 src=Path(d)/'main.c';binary=Path(d)/'main';src.write_text(program)
 subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I',str(u),'-I',str(p/'native/gpu/handoff'),str(src),'-o',str(binary)],check=True)
 subprocess.run([str(binary)],check=True)
print(f'PASS: authoritative r{args.run} argv/capture title, legacy recovery bytes unchanged, installed source hashes match manifest')
