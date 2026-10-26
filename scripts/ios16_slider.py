"""Add the default-disabled Hall diagnostic worker to GUI kernels."""
from ios16_sources import source_path, kernel_source
import difflib


def slider_patch(profile, repository):
    patch = ''
    for name in ('giulia_slider.c', 'giulia_slider.h', 'giulia_slider_pins.h'):
        data = kernel_source(source_path(repository, name).read_text())
        data = data.replace('#include <stddef.h>\n', '')
        patch += ''.join(difflib.unified_diff([], data.splitlines(True),
                        fromfile='/dev/null', tofile='b/bsd/dev/'+name))
    (profile/'0084-giulia-alert-slider.patch').write_text(patch)
