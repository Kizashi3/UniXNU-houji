"""Show the RAM payload driver's volatile status in the existing menu footer."""
from pathlib import Path
import sys

path=Path(sys.argv[1])/'UniXNU/package/UniXNUPkg/Library/UniXNULib/Main.c'
text=path.read_text()
marker='  Countdown = TRUE;'
hook='''  // giulia bring-up: preserve the real payload-discovery status on screen.
  {
    EFI_GUID Guid = {0x1c87b711,0xeaa6,0x42cb,{0xa3,0xd5,0x8c,0x21,0x19,0x65,0x21,0x31}};
    UINTN Size = sizeof (Ui.Info);
    EFI_STATUS Diag = gRT->GetVariable (L"GiuliaInitrdStatus", &Guid, NULL, &Size, Ui.Info);
    if (EFI_ERROR (Diag)) {
      UnicodeSPrint (Ui.Info, sizeof (Ui.Info), L"initrd: diagnostic unavailable (%r)", Diag);
    }
  }

'''
if 'GiuliaInitrdStatus' not in text:
    if text.count(marker)!=1:
        raise SystemExit('Unexpected upstream menu main function')
    path.write_text(text.replace(marker,hook+marker))
