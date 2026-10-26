"""Attach iOS RequestPowerChange to the proven native DSI0 display command."""
import difflib
from ios16_sources import source_path, kernel_source
from pathlib import Path
import subprocess
import tempfile


def display_power_patch(profile, repository):
    target = 'iokit/Kernel/arm/SweetFramebuffer.cpp'
    with tempfile.TemporaryDirectory(prefix='giulia-power-profile-') as folder:
        work = Path(folder)
        subprocess.run(['git','init','-q',folder],check=True)
        for patch in sorted(profile.glob('*.patch')):
            if int(patch.name[:4])>=85:
                continue
            subprocess.run(['git','apply','--whitespace=nowarn','--include='+target,
                            str(patch.resolve())],cwd=work,check=True,capture_output=True)
        old=(work/target).read_text()

    def replace(text,before,after):
        if text.count(before)!=1:
            raise ValueError('Display power source drift: '+repr(before[:100]))
        return text.replace(before,after)

    new=replace(old,'#include "giulia_display.h"',
                '#include "giulia_display.h"\n#include "giulia_display_power.h"')
    new=replace(new,'\tkSweetFBGetDisplaySize          = 8,',
                '\tkSweetFBGetDisplaySize          = 8,\n\tkSweetFBRequestPowerChange      = 12,')
    new=replace(new,'\tbool          fDirty;',
                '\tIOLock       *fDisplayPowerLock;\n\tvm_offset_t   fDisplayRegisters;\n'
                '\tstruct gdp_state fDisplayPower;\n\tbool          fDisplayPowerOff;\n'
                '\tIOReturn setDisplayPower(uint64_t requested);\n\tbool          fDirty;')
    new=replace(new,'#include "giulia_screen_framebuffer.inc"',
                '#include "giulia_screen_framebuffer.inc"\n#include "giulia_display_power.inc"')
    new=replace(new,'\tfVsync->setTimeoutUS(SWEET_FB_VSYNC_US);\n',
                '\tfDisplayPowerLock=IOLockAlloc();\n'
                '\tif(!fDisplayPowerLock)return false;\n'
                '\tfDisplayRegisters=0;fDisplayPowerOff=false;\n'
                '\tbzero(&fDisplayPower,sizeof(fDisplayPower));\n'
                '\tfVsync->setTimeoutUS(SWEET_FB_VSYNC_US);\n')
    new=replace(new,'\tIOLockLock(fCaptureLock);\n\tuint32_t mask',
                '\tIOLockLock(fCaptureLock);\n'
                '\tif(fDisplayPowerOff){IOLockUnlock(fCaptureLock);return;}\n\tuint32_t mask')
    new=replace(new,'\tcase kSweetFBSwapWait:\n\tdefault:',
                '\tcase kSweetFBRequestPowerChange:\n'
                '\t\tif(args->scalarInputCount!=1 || !args->scalarInput || args->structureInputSize || args->structureInputDescriptor) {\n'
                '\t\t\tret=kIOReturnBadArgument;\n\t\t} else ret=fFB->setDisplayPower(args->scalarInput[0]);\n'
                '\t\tbreak;\n\tcase kSweetFBSwapWait:\n\tdefault:')
    patch=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),
                                     fromfile='a/'+target,tofile='b/'+target))
    for name in ('giulia_display_power.h','giulia_display_power.inc'):
        data=kernel_source(source_path(repository,name).read_text())
        patch+=''.join(difflib.unified_diff([],data.splitlines(True),fromfile='/dev/null',
                        tofile='b/iokit/Kernel/arm/'+name))
    (profile/'0085-giulia-native-display-power.patch').write_text(patch,encoding='utf-8',newline='\n')
