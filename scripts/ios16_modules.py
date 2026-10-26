"""Composition root for optional drivers. Leaf builders never inspect peers."""
import importlib
import json
import shutil
from ios16_module_registry import consolidate_modules

DRIVERS = ('wifi', 'gpu', 'audio', 'modem')


def emit_input_modules(out, root, *, touch=False):
    """Wire physical input workers once; no input driver knows its peers."""
    selected = (['touch'] if touch else []) + ['keys', 'slider']
    for name in selected:
        builder = importlib.import_module('ios16_' + name)
        getattr(builder, name + '_patch')(out, root)
    files = ['bsd/dev/giulia_' + name + '.c\t\t\tstandard\n' for name in selected]
    starts = ['\textern void giulia_' + name + '_start(void);\n\tgiulia_' + name + '_start();\n'
              for name in selected]
    patch = ('--- a/bsd/conf/files\n+++ b/bsd/conf/files\n'
             f'@@ -109,4 +109,{4 + len(files)} @@\n'
             ' bsd/dev/vermeer_usb_debug.c\t\tstandard\n'
             ' bsd/dev/sweet_sample.c\t\t\tstandard\n'
             + ''.join('+' + line for line in files)
             + ' bsd/dev/memdev.c\t\t\tstandard\n bsd/dev/mem.c\t\t\t\tstandard\n'
             '--- a/bsd/kern/bsd_init.c\n+++ b/bsd/kern/bsd_init.c\n'
             f'@@ -1106,5 +1106,{5 + 2 * len(starts)} @@\n'
             ' \tvermeer_usb_debug_start();\n \textern void sweet_sample_start(void);\n'
             ' \tsweet_sample_start();\n'
             + ''.join('+' + line for start in starts for line in start.splitlines(True))
             + ' #endif\n \n')
    (out / '0091-giulia-input-modules.patch').write_text(patch, encoding='utf-8', newline='\n')
    registry = {'schema': 1, 'modules': selected,
                'translation_units': [line.split()[0] for line in files],
                'registration_patch': '0091-giulia-input-modules.patch'}
    (out / 'input-module-registry.json').write_text(json.dumps(registry, indent=2) + '\n',
                                                   encoding='utf-8', newline='\n')
    return registry


def emit_optional_modules(out, root, selected):
    selected = set(selected)
    if selected - set(DRIVERS):
        raise ValueError('Unknown drivers: ' + ', '.join(sorted(selected - set(DRIVERS))))
    if not selected:
        return None
    for name in DRIVERS:
        if name in selected:
            builder = importlib.import_module('ios16_' + name + '_patch')
            getattr(builder, name + '_patch')(out, root)
    if 'gpu' in selected:
        for name in ('0085-giulia-gunyah-irq.patch', '0086-giulia-gpu-pmap.patch'):
            shutil.copyfile(root / 'ios16' / name, out / name)
    registry = consolidate_modules(out)
    registry['modules'] = ['common', 'platform', *[name for name in DRIVERS if name in selected]]
    (out / 'module-registry.json').write_text(json.dumps(registry, indent=2) + '\n',
                                             encoding='utf-8', newline='\n')
    return registry
