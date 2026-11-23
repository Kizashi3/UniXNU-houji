#!/usr/bin/env python3
"""Compile the actual firmware reader against bounded mock read-only storage."""
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'kernel/overlay/iokit/Kernel/houji-ufs-root/battery'
with tempfile.TemporaryDirectory(prefix='houji-firmware-') as temporary:
    d=Path(temporary)
    for name,text in {
        # EFTYPE is part of the target Darwin ABI, absent from Linux errno.h.
        # Define it only in this host fixture, never in the production driver.
        'IOKit/IOLib.h':'#include <stddef.h>\n#include <errno.h>\n#ifndef EFTYPE\n#define EFTYPE 79\n#endif\nvoid *IOMalloc(size_t);\nvoid IOFree(void *,size_t);\n',
        'libkern/libkern.h':'#include <stdio.h>\n#include <string.h>\n#include <strings.h>\n',
    }.items():
        p=d/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    common=['-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer']
    objects=[]
    for name in ('FatVolume','QcomMdt'):
        obj=d/(name+'.o');objects.append(str(obj))
        subprocess.run(['clang','-std=c11',*common,'-c',str(source/(name+'.c')),'-o',str(obj)],check=True)
    binary=d/'firmware'
    subprocess.run(['clang++','-std=c++17',*common,'-I'+str(d),str(ROOT/'checks/battery-firmware.cpp'),
                    str(source/'HoujiFirmware.cpp'),*objects,'-o',str(binary)],check=True)
    for mode in ('ok','alloc0','alloc1','alloc2','read-fail','bad-fat','bad-elf','short-piece'):
        subprocess.run([str(binary),mode],check=True)
    transport=d/'transport'
    subprocess.run(['clang++','-std=c++17',*common,'-Wno-unused-function',
                    str(ROOT/'checks/battery-firmware-ufs.cpp'),'-o',str(transport)],check=True)
    subprocess.run([str(transport)],check=True)
