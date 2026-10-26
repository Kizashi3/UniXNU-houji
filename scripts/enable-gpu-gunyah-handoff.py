"""Wire the current-boot FDT resource report into the final DarwinBoot ADT."""
from pathlib import Path
import argparse
import shutil

ROOT = Path(__file__).resolve().parents[1]
HEADERS = ROOT / 'uefi-overlay/Platforms/OnePlus/giuliaPkg/Drivers/GiuliaInitrdDxe'
INCLUDE = '#include "GpuGunyahHandoff.h"\n'
CALL = ('  (VOID)GiuliaGpuGunyahHandoff ((VOID *)(UINTN)TreeAddress, TreeSize,\n'
        '                                CommandLine, sizeof (CommandLine));\n')


def install(driver):
    source = driver / 'DarwinBoot.c'
    text = source.read_text()
    close = '  Root->Close (Root); Root = NULL;\n'
    copied = '  CopyMem ((VOID *)(UINTN)TreeAddress, Tree, TreeSize);'
    mapping = '  Status = GetMap (&Map, &Capacity, &MapSize, &Key, &Stride);'
    exit_call = 'gBS->ExitBootServices ('
    if any(text.count(a) != 1 for a in (close, copied, mapping, exit_call)):
        raise ValueError('DarwinBoot Gunyah handoff anchors changed')
    if not text.index(copied) < text.index(close) < text.index(mapping) < text.index(exit_call):
        raise ValueError('Gunyah handoff must follow final ADT copy and precede GetMap/EBS')
    if INCLUDE not in text:
        lines = text.splitlines(True)
        at = max(i for i, line in enumerate(lines) if line.startswith('#include ')) + 1
        lines.insert(at, INCLUDE)
        text = ''.join(lines)
    if CALL not in text:
        if 'GiuliaGpuGunyahHandoff (' in text:
            raise ValueError('Ambiguous existing Gunyah handoff')
        text = text.replace(close, close + CALL)
    if text.count(INCLUDE) != 1 or text.count(CALL) != 1 or not text.index(close) < text.index(CALL) < text.index(mapping):
        raise ValueError('Duplicate or misplaced Gunyah handoff')
    names = ('GpuGunyahReport.h', 'GpuGunyahHandoff.h', 'GpuPowerAdt.h')
    for name in names:
        if not (HEADERS / name).is_file():
            raise ValueError('Missing Gunyah handoff header: ' + name)
    for name in names:
        shutil.copyfile(HEADERS / name, driver / name)
    source.write_text(text, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('driver', type=Path)
    a = p.parse_args()
    install(a.driver)
    print('Gunyah boot-FDT resource handoff installed; no HVC, IRQ lease or captured defaults')
