"""Emit only TouchCom sources; lifecycle wiring belongs to the profile composer."""
import difflib
from ios16_sources import source_path, kernel_source


def touch_patch(profile, repository):
    patch = ''
    for name in ('giulia_touch.c', 'giulia_touch_report.h', 'giulia_touch_wire.h', 'giulia_touch_gpio.h'):
        data = kernel_source(source_path(repository, name).read_text())
        patch += ''.join(difflib.unified_diff([], data.splitlines(True),
                        fromfile='/dev/null', tofile='b/bsd/dev/' + name))
    (profile / '0069-giulia-touch.patch').write_text(patch, encoding='utf-8', newline='\n')
