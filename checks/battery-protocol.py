#!/usr/bin/env python3
from pathlib import Path
import subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='houji-battmgr-') as directory:
    binary=Path(directory)/'battmgr'
    subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        str(ROOT/'checks/battery-protocol.c'),
        str(ROOT/'kernel/overlay/iokit/Kernel/houji-ufs-root/battery/HoujiBattmgr.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
