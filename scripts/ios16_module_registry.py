"""Consolidate optional GUI module registration into one ordered patch.

Source patches remain separate; all optional translation-unit registrations and
IOKit personalities use one verified AMFI anchor in the generated profile.
"""
from pathlib import Path
import re


REGISTRY = '0090-giulia-optional-modules.patch'
OPTIONAL = ('0088-giulia-platform-runtime.patch', '0076-giulia-wifi-runtime.patch', '0077-giulia-gpu-runtime.patch',
            '0084-giulia-audio-runtime.patch', '0087-giulia-modem-runtime.patch')
FILES = 'iokit/conf/files.arm64'
TABLE = 'iokit/KernelConfigTables.cpp'


def consolidate_modules(out):
    out = Path(out)
    if (out / REGISTRY).exists():
        raise ValueError('Optional module registration already consolidated')
    staged, units, personalities = {}, [], []
    created = set()
    for name in OPTIONAL:
        path = out / name
        if not path.exists():
            continue
        text = path.read_text(encoding='utf-8')
        for target in re.findall(r'(?m)^--- /dev/null\n\+\+\+ b/(.+)$', text):
            if target in created:
                raise ValueError('Duplicate generated module source: ' + target)
            created.add(target)
        chunks = re.split(r'(?m)(?=^--- )', text)
        keep = []
        for chunk in chunks:
            match = re.match(r'--- a/([^\n]+)\n\+\+\+ b/([^\n]+)\n', chunk)
            if not match or match[1] not in (FILES, TABLE):
                keep.append(chunk)
                continue
            if match[1] != match[2]:
                raise ValueError('Optional registry path mismatch')
            body = chunk[match.end():].splitlines(True)
            if any(line.startswith('-') for line in body):
                raise ValueError('Optional registration unexpectedly removes existing entries')
            additions = [line[1:] for line in body if line.startswith('+')]
            if not additions:
                raise ValueError('Empty optional registry change')
            if match[1] == FILES:
                if any(not re.fullmatch(r'iokit/Kernel/arm/[\w./-]+\s+optional iokitcpp\n', line)
                       for line in additions):
                    raise ValueError('Unexpected optional translation unit')
                units.extend(additions)
            else:
                personalities.extend(additions)
        staged[path] = ''.join(keep)
    if not units or not personalities:
        raise ValueError('No complete optional module inventory')
    names = [line.split()[0] for line in units]
    classes = re.findall(r"'IOClass'\s*=\s*([\w]+);", ''.join(personalities))
    categories = re.findall(r"'IOMatchCategory'\s*=\s*([\w]+);", ''.join(personalities))
    if len(names) != len(set(names)) or len(classes) != len(set(classes)) or classes != categories:
        raise ValueError('Duplicate or inconsistent optional module registration')
    patch = ('--- a/' + FILES + '\n+++ b/' + FILES + '\n'
             f'@@ -15,2 +15,{2 + len(units)} @@\n'
             ' iokit/Kernel/arm/GiuliaAMFI.cpp                                  optional iokitcpp\n'
             + ''.join('+' + line for line in units)
             + ' iokit/Kernel/arm/SweetWatchdog.cpp                               optional iokitcpp\n'
             '--- a/' + TABLE + '\n+++ b/' + TABLE + '\n'
             f'@@ -55,3 +55,{3 + len(personalities)} @@\n'
             '     "     \'IOMatchCategory\' = AppleMobileFileIntegrity;"\n'
             '     "   },"\n'
             + ''.join('+' + line for line in personalities)
             + '     "   {"\n')
    # Validate the complete inventory before changing any generated source patch.
    for path, text in staged.items():
        path.write_text(text, encoding='utf-8', newline='\n')
    (out / REGISTRY).write_text(patch, encoding='utf-8', newline='\n')
    return {'schema': 1, 'translation_units': names, 'personalities': classes,
            'registration_patch': REGISTRY}
