#!/usr/bin/env python3
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='houji-spi-') as temp:
    binary=Path(temp)/'test'
    subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    str(ROOT/'checks/battery-spi.c'),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
