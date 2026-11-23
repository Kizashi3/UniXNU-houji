#!/usr/bin/env python3
from pathlib import Path
import os
import re
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
source=ROOT/'kernel/overlay/iokit/Kernel/houji-ufs-root/battery'
with tempfile.TemporaryDirectory(prefix='houji-battery-publisher-') as temporary:
    directory=Path(temporary)
    text=(source/'HoujiBattery.cpp').read_text()
    # Replace platform headers only; expose class members to the fixture. All
    # publisher/protocol methods and decisions are the actual source code.
    text=re.sub(r'^#include <.*>\n','',text,flags=re.M)
    text=text.replace('class HoujiBatterySource:','struct HoujiBatterySource:').replace('class HoujiBatteryManager:','struct HoujiBatteryManager:')
    (directory/'publisher-under-test.cpp').write_text('#include "battery-publisher-fixture.h"\n'+text)
    binary=directory/'test'
    codec=directory/'codec.o'
    flags=['-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-omit-frame-pointer']
    subprocess.run(['clang','-std=c11',*flags,'-c',str(source/'HoujiBattmgr.c'),'-o',str(codec)],check=True)
    subprocess.run(['clang++','-std=c++17',*flags,'-I'+str(directory),'-I'+str(source),'-I'+str(ROOT/'checks'),
                    str(ROOT/'checks/battery-publisher.cpp'),str(codec),'-o',str(binary)],check=True)
    # The deliberately inert refcount fixture retains service/event objects.
    # This checks accesses and logic; it does not claim to test IOKit lifetimes.
    subprocess.run([str(binary)],check=True,env=dict(os.environ,ASAN_OPTIONS='detect_leaks=0'))
