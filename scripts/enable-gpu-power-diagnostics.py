"""Install an explicitly requested, fixed ADT GPU power handoff in DarwinBoot."""
from pathlib import Path
import argparse
import shutil

ROOT=Path(__file__).resolve().parents[1]
HEADERS=ROOT/'uefi-overlay/Platforms/OnePlus/giuliaPkg/Drivers/GiuliaInitrdDxe'
INCLUDE='#include "GpuPowerHandoff.h"\n'
CALL=('  (VOID)GiuliaGpuPowerDiagnostic ((VOID *)(UINTN)TreeAddress, TreeSize,\n'
      '                                  CommandLine, sizeof (CommandLine));\n')


def install(driver):
    source=driver/'DarwinBoot.c'
    text=source.read_text()
    close='  Root->Close (Root); Root = NULL;\n'
    mapping='  Status = GetMap (&Map, &Capacity, &MapSize, &Key, &Stride);'
    copied='  CopyMem ((VOID *)(UINTN)TreeAddress, Tree, TreeSize);'
    exit_call='gBS->ExitBootServices ('
    if any(text.count(anchor)!=1 for anchor in (close,mapping,copied,exit_call)):
        raise ValueError('DarwinBoot GPU power handoff anchors changed')
    if not text.index(copied)<text.index(close)<text.index(mapping)<text.index(exit_call):
        raise ValueError('GPU power hook must follow the final ADT copy and precede the memory map/EBS')
    if INCLUDE not in text:
        lines=text.splitlines(True)
        at=max(i for i,line in enumerate(lines) if line.startswith('#include '))+1
        lines.insert(at,INCLUDE)
        text=''.join(lines)
    if CALL not in text:
        if 'GiuliaGpuPowerDiagnostic (' in text:
            raise ValueError('Ambiguous existing GPU power handoff call')
        text=text.replace(close,close+CALL)
    if text.count(INCLUDE)!=1 or text.count(CALL)!=1:
        raise ValueError('Duplicate GPU power handoff integration')
    if not text.index(close)<text.index(CALL)<text.index(mapping):
        raise ValueError('Existing GPU power handoff is outside its permitted interval')
    # Resolve every input before writing the loader or copying headers.
    for name in ('GpuPowerReport.h','GpuPowerAdt.h','GpuPowerHandoff.h'):
        if not (HEADERS/name).is_file():raise ValueError('Missing GPU power header: '+name)
    for name in ('GpuPowerReport.h','GpuPowerAdt.h','GpuPowerHandoff.h'):
        shutil.copyfile(HEADERS/name,driver/name)
    source.write_text(text,encoding='utf-8',newline='\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('driver',type=Path)
    args=parser.parse_args()
    install(args.driver)
    print('GPU power hook installed: exact giulia_gpu=3 plus pristine fixed ADT request required; no bootargs report bytes')


if __name__=='__main__':main()
