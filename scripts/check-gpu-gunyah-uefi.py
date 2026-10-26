"""Compile the boot-FDT provider and loader against real Mu UEFI headers."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HEADERS = ROOT / 'uefi-overlay/Platforms/OnePlus/giuliaPkg/Drivers/GiuliaInitrdDxe'


def verify(uefi):
    include = uefi / 'Mu_Basecore/MdePkg/Include'
    required = (include / 'Uefi.h', include / 'AArch64/ProcessorBind.h',
                include / 'Library/FdtLib.h', include / 'Uefi/UefiSpec.h')
    if not all(p.is_file() for p in required):
        raise ValueError('Prepared Mu UEFI headers are required')
    with tempfile.TemporaryDirectory(prefix='gpu-gunyah-uefi-') as temporary:
        folder = Path(temporary)
        wrapper = folder / 'loader.c'
        wrapper.write_text('#include <Uefi.h>\n#include <Library/BaseMemoryLib.h>\n'
                           '#include <Library/DebugLib.h>\n'
                           '#include <Library/UefiBootServicesTableLib.h>\n'
                           '#include "GpuGunyahHandoff.h"\n'
                           'EFI_STATUS ggr_native_loader_check(void *t,UINTN n,const CHAR8 *c,UINTN l)\n'
                           '{return GiuliaGpuGunyahHandoff(t,n,c,l);}\n')
        for name, source in (('provider', HEADERS / 'GpuGunyah.c'), ('loader', wrapper)):
            subprocess.run(['clang', '--target=aarch64-unknown-windows-msvc', '-ffreestanding',
                            '-fshort-wchar', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I', str(include), '-I', str(include / 'AArch64'),
                            '-I', str(HEADERS), '-c', str(source),
                            '-o', str(folder / (name + '.obj'))], check=True)
            # COFF IMAGE_FILE_MACHINE_ARM64, not a host or ELF object.
            if (folder / (name + '.obj')).read_bytes()[:2] != b'\x64\xaa':
                raise ValueError('Expected native ARM64 COFF object')
    return {'result': 'passed', 'target': 'aarch64-unknown-windows-msvc',
            'headers': str(include.resolve()), 'units': ['boot-FDT provider', 'DarwinBoot handoff'],
            'platform_header_stubs': False, 'full_firmware_link': False,
            'device_io_performed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uefi', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.uefi), indent=2))
