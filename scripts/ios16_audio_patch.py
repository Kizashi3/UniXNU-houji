"""Link the opt-in audio coordinator; platform ownership remains explicit."""
import difflib
from ios16_sources import kernel_source
from ios16_platform_patch import platform_patch


def audio_patch(out, root):
    platform_patch(out, root)
    patch = ('--- a/iokit/conf/files.arm64\n+++ b/iokit/conf/files.arm64\n'
             '@@ -15,2 +15,3 @@\n'
             ' iokit/Kernel/arm/GiuliaAMFI.cpp                                  optional iokitcpp\n'
             '+iokit/Kernel/arm/GiuliaAudio.cpp                                 optional iokitcpp\n'
             ' iokit/Kernel/arm/SweetWatchdog.cpp                               optional iokitcpp\n'
             '--- a/iokit/KernelConfigTables.cpp\n+++ b/iokit/KernelConfigTables.cpp\n'
             '@@ -55,3 +55,9 @@\n'
             '     "     \'IOMatchCategory\' = AppleMobileFileIntegrity;"\n'
             '     "   },"\n'
             '+    "   {"\n'
             '+    "     \'IOClass\'         = GiuliaAudio;"\n'
             '+    "     \'IOProviderClass\' = IOResources;"\n'
             '+    "     \'IOResourceMatch\' = IOBSD;"\n'
             '+    "     \'IOMatchCategory\' = GiuliaAudio;"\n'
             '+    "   },"\n'
             '     "   {"\n')
    sources = {p.name:p.read_text() for p in (root/'ios16/audio').glob('giulia_audio_*.h')}
    sources['GiuliaAudio.cpp'] = (root/'ios16/audio/GiuliaAudio.cpp').read_text()
    for name, data in sorted(sources.items()):
        data = kernel_source(data)
        patch += ''.join(difflib.unified_diff([], data.splitlines(True),
            fromfile='/dev/null', tofile='b/iokit/Kernel/arm/'+name))
    (out/'0084-giulia-audio-runtime.patch').write_text(patch, encoding='utf-8', newline='\n')
