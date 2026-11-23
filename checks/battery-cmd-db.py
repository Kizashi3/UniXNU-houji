#!/usr/bin/env python3
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='houji-cmd-db-') as temporary:
    out=Path(temporary)/'test'
    subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    str(ROOT/'checks/battery-cmd-db.c'),
                    str(ROOT/'kernel/overlay/iokit/Kernel/houji-ufs-root/battery/QcomRpmh.c'),
                    '-o',str(out)],check=True)
    subprocess.run([str(out)],check=True)
