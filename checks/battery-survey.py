#!/usr/bin/env python3
"""Check the actual portable survey parser with address/undefined sanitizers."""
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'kernel/overlay/iokit/Kernel/houji-ufs-root'
with tempfile.TemporaryDirectory(prefix='houji-battery-') as directory:
    binary = Path(directory) / 'survey'
    subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(ROOT / 'checks/battery-survey.c'),
                    str(source / 'battery/QcomSmem.c'), str(source / 'battery/QcomSmp2p.c'),
                    '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
