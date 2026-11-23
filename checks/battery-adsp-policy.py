#!/usr/bin/env python3
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'kernel/overlay/iokit/Kernel/houji-ufs-root/battery'
text=(source/'HoujiAdspTransport.cpp').read_text()
def function(signature):
    start=text.index(signature);body=text.index('{',start);depth=1;end=body+1
    while depth:
        if text[end]=='{':depth+=1
        elif text[end]=='}':depth-=1
        end+=1
    return text[start:end]+'\n'
with tempfile.TemporaryDirectory(prefix='houji-adsp-policy-') as temporary:
    directory=Path(temporary);binary=directory/'test';codec=directory/'codec.o'
    (directory/'adsp-functions.inc').write_text(function('void stage(int value)')+function('int vote(uint32_t lcx,uint32_t lmx)'))
    flags=['-Wall','-Wextra','-Werror','-fsanitize=address,undefined']
    subprocess.run(['clang','-std=c11',*flags,'-c',str(source/'QcomRpmh.c'),'-o',str(codec)],check=True)
    subprocess.run(['clang++','-std=c++17',*flags,'-I'+str(directory),'-I'+str(source),
                    str(ROOT/'checks/battery-adsp-policy.cpp'),str(codec),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
