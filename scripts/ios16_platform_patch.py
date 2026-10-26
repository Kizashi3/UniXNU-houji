"""Emit shared contracts and the single resource broker independently of drivers."""
import difflib
from ios16_sources import source_path, kernel_source

PATCH = '0088-giulia-platform-runtime.patch'
UNITS = ('GiuliaPlatformResources.cpp', 'GiuliaPlatformQmp.cpp')


def platform_patch(out, root):
    added = ['iokit/Kernel/arm/' + name + ' optional iokitcpp\n' for name in UNITS]
    patch = ('--- a/iokit/conf/files.arm64\n+++ b/iokit/conf/files.arm64\n'
             f'@@ -15,2 +15,{2 + len(added)} @@\n'
             ' iokit/Kernel/arm/GiuliaAMFI.cpp                                  optional iokitcpp\n'
             + ''.join('+' + line for line in added)
             + ' iokit/Kernel/arm/SweetWatchdog.cpp                               optional iokitcpp\n')
    names = (*UNITS, 'giulia_platform_resources.h', 'giulia_platform_power.h',
             'giulia_scm.h', 'giulia_sha256.h', 'giulia_platform_qmp.h')
    sources = {name: source_path(root, name).read_text() for name in names}
    sources['giulia_platform_power_report.h'] = (root /
        'uefi-overlay/Platforms/OnePlus/giuliaPkg/Drivers/GiuliaInitrdDxe/GpuPowerReport.h').read_text()
    for name, data in sources.items():
        patch += ''.join(difflib.unified_diff([], kernel_source(data).splitlines(True),
                         fromfile='/dev/null', tofile='b/iokit/Kernel/arm/' + name))
    target = out / PATCH
    if target.exists() and target.read_text() != patch:
        raise ValueError('Shared platform source changed during profile generation')
    target.write_text(patch, encoding='utf-8', newline='\n')
