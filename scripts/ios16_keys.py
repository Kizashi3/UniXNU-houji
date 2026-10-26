"""Add the measured Ace 5 physical keys to every GUI profile."""
from ios16_sources import source_path, kernel_source
import difflib


def keys_patch(profile, repository):
    patch = ''
    for name in ('giulia_keys.c', 'giulia_keys.h', 'giulia_keys_terminal.inc'):
        data = kernel_source(source_path(repository, name).read_text())
        patch += ''.join(difflib.unified_diff([], data.splitlines(True),
                        fromfile='/dev/null', tofile='b/bsd/dev/' + name))
    (profile / '0083-giulia-physical-keys.patch').write_text(patch)
