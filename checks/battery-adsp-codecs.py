#!/usr/bin/env python3
"""Pinned upstream wire-format tests; host buffers do not emulate the ADSP."""
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'kernel/overlay/iokit/Kernel/houji-ufs-root/battery'
with tempfile.TemporaryDirectory(prefix='houji-adsp-codecs-') as temporary:
    for check,files in [('battery-adsp-codecs.c',['QcomGlink.c','QcomMdt.c','QcomQmp.c','QcomRpmh.c','QcomSmem.c','QcomSmp2p.c']),
                        ('battery-qrtr.c',['QcomQrtr.c'])]:
        binary=Path(temporary)/check
        subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                        '-I'+str(source),str(ROOT/'checks'/check),*[str(source/f) for f in files],'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
