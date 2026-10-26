"""Include the unified modem core and shared platform broker in GUI profiles."""
from ios16_sources import source_path, kernel_source
from ios16_platform_patch import platform_patch
import difflib
import json
from ios16_modem import build_binding, build_header


def modem_patch(out, root):
    platform_patch(out, root)
    units = ['GiuliaModem.cpp']
    names = units + [p.name for p in sorted((root / 'ios16/modem').glob('giulia_modem_*.h'))]
    if len(names) != len(set(names)):
        raise ValueError('Duplicate modem source inventory')
    added = ['iokit/Kernel/arm/' + name + ' optional iokitcpp\n' for name in units]
    patch = ('--- a/iokit/conf/files.arm64\n+++ b/iokit/conf/files.arm64\n'
             f'@@ -15,2 +15,{2 + len(added)} @@\n'
             ' iokit/Kernel/arm/GiuliaAMFI.cpp                                  optional iokitcpp\n'
             + ''.join('+' + line for line in added)
             + ' iokit/Kernel/arm/SweetWatchdog.cpp                               optional iokitcpp\n'
             '--- a/iokit/KernelConfigTables.cpp\n+++ b/iokit/KernelConfigTables.cpp\n'
             '@@ -55,3 +55,9 @@\n'
             '     "     \'IOMatchCategory\' = AppleMobileFileIntegrity;"\n'
             '     "   },"\n'
             '+    "   {"\n'
             '+    "     \'IOClass\'         = GiuliaModem;"\n'
             '+    "     \'IOProviderClass\' = IOResources;"\n'
             '+    "     \'IOResourceMatch\' = IOBSD;"\n'
             '+    "     \'IOMatchCategory\' = GiuliaModem;"\n'
             '+    "   },"\n'
             '     "   {"\n')
    for name in names:
        data = (source_path(root, name)).read_text(encoding='utf-8')
        data = kernel_source(data)
        patch += ''.join(difflib.unified_diff([], data.splitlines(True),
                        fromfile='/dev/null', tofile='b/iokit/Kernel/arm/' + name))
    patch+=''.join(difflib.unified_diff([],build_header(root).splitlines(True),
                    fromfile='/dev/null',tofile='b/iokit/Kernel/arm/giulia_modem_build.h'))
    (out/'modem-config.json').write_text(json.dumps(build_binding(root),indent=2)+'\n',encoding='utf-8',newline='\n')
    (out / '0087-giulia-modem-runtime.patch').write_text(patch, encoding='utf-8', newline='\n')
    return names
