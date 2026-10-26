"""Carry the optional native Hall preparation result into a bounded boot argument.

gh=3 permits runtime preflight after native power and clock requests complete.
Failures retain ready bits0..1 and pack power/clock stages into bits2..5/6..9,
then the low EFI status bytes into bits10..17/18..25. This does not establish
rail voltage, bus ownership, sensor identity or positions.
"""
from pathlib import Path
import argparse
import re

HELPER = '''
STATIC VOID GiuliaAppendHallDiagnostic (CHAR8 *Line, UINTN Capacity)
{
  EFI_GUID Guid = {0x1c87b711,0xeaa6,0x42cb,{0xa3,0xd5,0x8c,0x21,0x19,0x65,0x21,0x31}};
  struct { UINT32 Stage, Detail; UINT64 Status; } Power = {0}, Clock = {0};
  UINTN Size = sizeof(Power), Used, Length;
  UINT32 Ready = 0;
  UINT64 Status;
  CHAR8 Extra[24];
  Status=gRT->GetVariable(L"GiuliaHallPowerStatus",&Guid,NULL,&Size,&Power);
  if (EFI_ERROR(Status) || Size != sizeof(Power)) { Power.Stage=0;Power.Status=Status ? Status : 1; }
  else if (Power.Stage == 10 && Power.Status == 0) { Ready |= 1; }
  Size = sizeof(Clock);
  Status=gRT->GetVariable(L"GiuliaHallClockStatus",&Guid,NULL,&Size,&Clock);
  if (EFI_ERROR(Status) || Size != sizeof(Clock)) { Clock.Stage=0;Clock.Status=Status ? Status : 1; }
  else if (Clock.Stage == 10 && Clock.Status == 0) { Ready |= 2; }
  if (Ready != 3) {
    Ready |= (Power.Stage & 15u) << 2 | (Clock.Stage & 15u) << 6 |
             (UINT32)(Power.Status & 255u) << 10 | (UINT32)(Clock.Status & 255u) << 18;
  }
  AsciiSPrint(Extra,sizeof(Extra)," gh=%u",Ready);
  Used=AsciiStrLen(Line);Length=AsciiStrLen(Extra);
  if (Used >= Capacity || Length >= Capacity-Used) { return; }
  CopyMem(Line+Used,Extra,Length+1);
  DEBUG((DEBUG_ERROR,"GIULIA HALL: native-preparation bits=%u; pins and sensor unverified\\n",Ready));
}

'''
CALL = '  GiuliaAppendHallDiagnostic (CommandLine, sizeof (CommandLine));\n'


def install(driver):
    source = driver / 'DarwinBoot.c'
    inf = driver / 'DarwinBoot.inf'
    text, spec = source.read_text(), inf.read_text()
    marker = '  CopyMem (Args->CommandLine, CommandLine, sizeof (CommandLine));'
    if text.count(marker) != 1:
        raise ValueError('DarwinBoot command-line anchor changed')
    installed = CALL in text
    if installed:
        if text.count(CALL) != 1 or text.count('STATIC VOID GiuliaAppendHallDiagnostic') != 1:
            raise ValueError('Ambiguous existing Hall diagnostic integration')
        pattern = r'\nSTATIC VOID GiuliaAppendHallDiagnostic \(CHAR8 \*Line, UINTN Capacity\)\n\{.*?\n}\n\n'
        text, count = re.subn(pattern, lambda match: HELPER, text, flags=re.S)
        if count != 1:
            raise ValueError('Existing Hall diagnostic helper shape changed')
    elif 'GiuliaAppendHallDiagnostic' in text:
        raise ValueError('Incomplete existing Hall diagnostic integration')
    include = '#include <Library/UefiRuntimeServicesTableLib.h>'
    if include not in text:
        anchor = '#include <Library/PrintLib.h>'
        if text.count(anchor) != 1:
            raise ValueError('DarwinBoot include anchor changed')
        text = text.replace(anchor, anchor + '\n' + include)
    if not installed:
        lines = text.splitlines(True)
        at = max(i for i, line in enumerate(lines) if line.startswith('#include ')) + 1
        lines.insert(at, HELPER)
        text = ''.join(lines).replace(marker, CALL + marker)
    if '  UefiRuntimeServicesTableLib' not in spec:
        anchor = '  UefiBootServicesTableLib'
        if spec.count(anchor) != 1:
            raise ValueError('DarwinBoot library anchor changed')
        spec = spec.replace(anchor, anchor + '\n  UefiRuntimeServicesTableLib')
    source.write_text(text, encoding='utf-8', newline='\n')
    inf.write_text(spec, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('driver', type=Path)
    install(parser.parse_args().driver)
    print('Native Hall preparation diagnostics installed; gh=3 only permits runtime preflight')
