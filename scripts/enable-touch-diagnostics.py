"""Carry only fixed-size volatile touch-power status into the kernel boot log."""
from pathlib import Path
import sys

driver=Path(sys.argv[1])
source=driver/'DarwinBoot.c'; inf=driver/'DarwinBoot.inf'
text=source.read_text()
if 'GiuliaAppendPowerDiagnostic' not in text:
    anchor='#include <Library/PrintLib.h>'
    assert text.count(anchor)==1
    text=text.replace(anchor,anchor+'\n#include <Library/UefiRuntimeServicesTableLib.h>')
    marker='  CopyMem (Args->CommandLine, CommandLine, sizeof (CommandLine));'
    assert text.count(marker)==1
    text=text.replace(marker,'  GiuliaAppendPowerDiagnostic (CommandLine, sizeof (CommandLine));\n'+marker)
    # Insert before the first function, after the includes and static data.
    helper='''
STATIC VOID GiuliaAppendPowerDiagnostic (CHAR8 *Line, UINTN Capacity)
{
  EFI_GUID Guid = {0x1c87b711,0xeaa6,0x42cb,{0xa3,0xd5,0x8c,0x21,0x19,0x65,0x21,0x31}};
  struct { UINT32 Stage, Address; UINT64 Status; } Value;
  UINTN Size = sizeof(Value), Used, Length;
  CHAR8 Extra[96];
  if (EFI_ERROR (gRT->GetVariable (L"GiuliaTouchPowerStatus",&Guid,NULL,&Size,&Value)) || Size != sizeof(Value)) { return; }
  AsciiSPrint (Extra,sizeof(Extra)," giulia_vdd_stage=%u giulia_vdd_status=%lx giulia_vdd_addr=%x",Value.Stage,Value.Status,Value.Address);
  Used = AsciiStrLen (Line); Length = AsciiStrLen (Extra);
  if (Used >= Capacity || Length >= Capacity-Used) { return; }
  CopyMem (Line+Used,Extra,Length+1);
}

'''
    # Its types/helpers are available after all includes. Avoid forward references.
    lines=text.splitlines(True)
    at=max(i for i,l in enumerate(lines) if l.startswith('#include '))+1
    lines.insert(at,helper);source.write_text(''.join(lines))
text=inf.read_text()
if '  UefiRuntimeServicesTableLib' not in text:
    text=text.replace('  UefiBootServicesTableLib','  UefiBootServicesTableLib\n  UefiRuntimeServicesTableLib')
    inf.write_text(text)
print('Volatile touch-power diagnostics enabled; no persistent EFI variables')
