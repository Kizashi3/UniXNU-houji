"""Generate only the Wi-Fi service and its crypto integration."""
import difflib
from ios16_sources import kernel_source
from ios16_platform_patch import platform_patch


def wifi_patch(out, root):
    platform_patch(out, root)
    patch = ('--- a/iokit/conf/files.arm64\n+++ b/iokit/conf/files.arm64\n'
             '@@ -15,2 +15,3 @@\n'
             ' iokit/Kernel/arm/GiuliaAMFI.cpp                                  optional iokitcpp\n'
             '+iokit/Kernel/arm/GiuliaWiFi.cpp                                  optional iokitcpp\n'
             ' iokit/Kernel/arm/SweetWatchdog.cpp                               optional iokitcpp\n'
             '--- a/iokit/KernelConfigTables.cpp\n+++ b/iokit/KernelConfigTables.cpp\n'
             '@@ -55,3 +55,9 @@\n'
             '     "     \'IOMatchCategory\' = AppleMobileFileIntegrity;"\n'
             '     "   },"\n'
             '+    "   {"\n'
             '+    "     \'IOClass\'         = IO80211Controller;"\n'
             '+    "     \'IOProviderClass\' = IOResources;"\n'
             '+    "     \'IOResourceMatch\' = IOBSD;"\n'
             '+    "     \'IOMatchCategory\' = IO80211Controller;"\n'
             '+    "   },"\n'
             '     "   {"\n')
    source = root / 'ios16/wifi'
    names = ['GiuliaWiFi.cpp', *[p.name for p in sorted(source.glob('giulia_wifi_*.h'))]]
    for name in names:
        data = (source / name).read_text()
        data = kernel_source(data)
        patch += ''.join(difflib.unified_diff([], data.splitlines(True),
                         fromfile='/dev/null', tofile='b/iokit/Kernel/arm/'+name))
    from ios16_wifi_sae import wifi_sae_patch
    patch += wifi_sae_patch(out, root)
    (out/'0076-giulia-wifi-runtime.patch').write_text(patch)
