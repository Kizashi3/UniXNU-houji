"""Call the opt-in board PCIe prepare protocol and preserve its complete status."""
from pathlib import Path
import shutil
import sys
import re
import os

ROOT=Path(__file__).resolve().parents[1]
driver=Path(sys.argv[1])
source=driver/'DarwinBoot.c'
shutil.copyfile(ROOT/'uefi-overlay/Platforms/OnePlus/giuliaPkg/Drivers/GiuliaInitrdDxe/WifiPcieReport.h',
                driver/'GiuliaWifiReport.h')
shutil.copyfile(ROOT/'uefi-overlay/Platforms/OnePlus/giuliaPkg/Drivers/GiuliaInitrdDxe/WifiPcieEncoding.h',
                driver/'GiuliaWifiEncoding.h')
text=source.read_text()
if 'GiuliaAppendWifiDiagnostic' not in text:
    marker='  CopyMem (Args->CommandLine, CommandLine, sizeof (CommandLine));'
    if text.count(marker)!=1:raise ValueError('DarwinBoot command-line anchor changed')
    text=text.replace(marker,'  GiuliaAppendWifiDiagnostic (CommandLine, sizeof (CommandLine));\n'+marker)
# The checked Wi-Fi handoff owns live resources. Reserve it before the optional
# touch-power text; terminal boot flags otherwise push the total beyond 608.
power_call='  GiuliaAppendPowerDiagnostic (CommandLine, sizeof (CommandLine));\n'
wifi_call='  GiuliaAppendWifiDiagnostic (CommandLine, sizeof (CommandLine));\n'
if power_call in text:
    assert text.count(power_call)==text.count(wifi_call)==1
    text=text.replace(power_call,'').replace(wifi_call,wifi_call+power_call)
helper='''
#include "GiuliaWifiReport.h"
#include "GiuliaWifiEncoding.h"
STATIC VOID GiuliaAppendWifiDiagnostic (CHAR8 *Line, UINTN Capacity)
{
  EFI_GUID Guid={0xf5b737f6,0x3b39,0x438d,{0x84,0xc0,0x17,0xcb,0x11,0x07,0x00,0x01}};
  typedef struct { UINT64 Version; EFI_STATUS (EFIAPI *Prepare)(struct gw_report *,UINTN); } WIFI_PROTOCOL;
  WIFI_PROTOCOL *Protocol;
  struct gw_report Report;
  EFI_STATUS Status;
  CHAR8 Extra[240];
  CONST CHAR8 *Prefix=" giulia_wifi5=";
  UINTN Used=AsciiStrLen(Line),Length;
  STATIC_ASSERT(sizeof(struct gw_report)==168,"Wi-Fi report ABI");
  Status=gBS->LocateProtocol(&Guid,NULL,(VOID **)&Protocol);
  if(EFI_ERROR(Status) || Protocol->Version!=5 || Protocol->Prepare==NULL) return;
  /* Reserve the worst-case diagnostic space before touching hardware. */
  if(Used>=Capacity || sizeof(Extra)>=Capacity-Used) return;
  ZeroMem(&Report,sizeof(Report));
  Status=Protocol->Prepare(&Report,sizeof(Report));
  if(Report.version!=5) return;
  if(Report.stage==18 && !Report.error && Report.detail==GW_XNU_LINK_TAG)
    Prefix=" giulia_wifip=";
  CopyMem(Extra,Prefix,AsciiStrLen(Prefix));
  if(!gw_report_base64(Extra+AsciiStrLen(Prefix),
       sizeof(Extra)-AsciiStrLen(Prefix),&Report)) return;
  Length=AsciiStrLen(Extra);
  if(Length<Capacity-Used) CopyMem(Line+Used,Extra,Length+1);
  DEBUG((DEBUG_ERROR,"GIULIA WIFI: prepare=%r %a\\n",Status,Extra));
}

'''
# Other installers may insert an include between our headers and function.
# Match the function independently; otherwise rebuilding with GPU enabled
# appends a second definition instead of updating the existing helper.
pattern=r'\nSTATIC VOID GiuliaAppendWifiDiagnostic \(CHAR8 \*Line, UINTN Capacity\)\n\{.*?\n}\n'
if os.environ.get('GIULIA_WIFI_SNAPSHOT') == '1':
    # Same bounded space as v5; only a failed link substitutes a snapshot.
    # A distinct prefix prevents XNU from treating diagnostic words as a
    # successful device handoff. Normal and successful boots retain v5.
    helper=helper.replace('  CopyMem(Extra,Prefix,AsciiStrLen(Prefix));', '''  if(Report.stage==13 && Report.error) {
    EFI_GUID SnapshotGuid={0xf5b737f6,0x3b39,0x438d,{0x84,0xc0,0x17,0xcb,0x11,0x07,0x00,0x02}};
    WIFI_PROTOCOL *SnapshotProtocol;
    struct gw_report Snapshot;
    if(!EFI_ERROR(gBS->LocateProtocol(&SnapshotGuid,NULL,(VOID **)&SnapshotProtocol)) &&
       SnapshotProtocol->Version==1 && SnapshotProtocol->Prepare &&
       !EFI_ERROR(SnapshotProtocol->Prepare(&Snapshot,sizeof(Snapshot))) &&
       (Snapshot.version==0x31535047u || Snapshot.version==0x32535047u)) {
      CopyMem(&Report,&Snapshot,sizeof(Report));
      Prefix=Snapshot.version==0x32535047u?" giulia_pcid2=":" giulia_pcid1=";
    }
  }
  CopyMem(Extra,Prefix,AsciiStrLen(Prefix));''')
if re.search(pattern,text,re.S):
    function=helper[helper.index('\nSTATIC VOID'):].rstrip()+'\n'
    text,count=re.subn(pattern,lambda _:function,text,flags=re.S)
    if count!=1:raise ValueError('Ambiguous Wi-Fi diagnostic helper')
    for header in ('GiuliaWifiReport.h','GiuliaWifiEncoding.h'):
        include='#include "'+header+'"\n'
        if text.count(include)>1:raise ValueError('Duplicate Wi-Fi diagnostic include')
        if include not in text:
            text=text.replace('\nSTATIC VOID GiuliaAppendWifiDiagnostic',
                              '\n'+include+'STATIC VOID GiuliaAppendWifiDiagnostic',1)
else:
    if 'STATIC VOID GiuliaAppendWifiDiagnostic' in text:
        raise ValueError('Unrecognized Wi-Fi diagnostic helper')
    lines=text.splitlines(True)
    at=max(i for i,line in enumerate(lines) if line.startswith('#include '))+1
    lines.insert(at,helper)
    text=''.join(lines)
source.write_text(text)
print('Explicit PCIe prepare call and versioned Wi-Fi diagnostics enabled')
if os.environ.get('GIULIA_WIFI_SNAPSHOT') == '1':
    print('Link failures will carry versioned giulia_pcid snapshots instead of runtime handoffs')
