"""Reject unowned sources and private dependencies between sibling drivers."""
from pathlib import Path
import re
from ios16_sources import MODULES, module_for

ROOT = Path(__file__).resolve().parents[1]
DRIVERS = {'audio', 'display', 'gpu', 'keys', 'modem', 'slider', 'storage', 'touch', 'trust', 'wifi'}
ALLOWED = {name: {'common', 'platform', 'vendor'} for name in DRIVERS}
ALLOWED.update(common=set(), platform={'common'}, terminal={'common', 'platform'})


def validate(root=ROOT):
    base = Path(root) / 'ios16'
    errors, owners = [], {}
    sources = [p for module in MODULES for p in (base / module).rglob('*')
               if p.suffix in ('.c', '.cpp', '.h', '.inc')]
    for path in base.iterdir():
        if path.is_dir() and path.name not in (*MODULES, 'vendor', 'userland'):
            errors.append('Unowned source directory: ' + str(path.relative_to(root)))
        if path.is_file() and path.suffix in ('.c', '.cpp', '.h', '.inc'):
            errors.append('Unowned flat source: ' + str(path.relative_to(root)))
    for path in sources:
        module = path.relative_to(base).parts[0]
        if path.name in owners:
            errors.append('Duplicate source basename: ' + path.name)
        owners[path.name] = module
        try:
            if module_for(path.name) != module:
                errors.append('Wrong source owner: ' + str(path.relative_to(root)))
        except ValueError as error:
            errors.append(str(error))
    public = (base / 'common/giulia_input_provider.h').read_text(encoding='utf-8')
    public_symbols = set(re.findall(r'\b(giulia_\w+)\s*\(', public))
    for path in sources:
        module = owners[path.name]
        source = path.read_text(encoding='utf-8')
        for include in re.findall(r'^\s*#\s*include\s*"([^"\n]+)"', source, re.M):
            target = owners.get(Path(include).name)
            if target and target != module and target not in ALLOWED[module]:
                errors.append(f'{path.name}: private include from {target}: {include}')
            if target and not (path.parent / include).is_file():
                errors.append(f'{path.name}: unresolved repository include: {include}')
        if module in DRIVERS:
            code = re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S)
            for full, target in re.findall(r'\b(giulia_(audio|display|gpu|keys|modem|slider|touch|wifi)_\w+)\s*\(', code):
                if target != module and full not in public_symbols:
                    errors.append(f'{path.name}: direct call/declaration into {target}: {full}')
    for module in ('wifi', 'gpu', 'audio', 'modem'):
        builder = (Path(root) / f'scripts/ios16_{module}_patch.py').read_text(encoding='utf-8')
        for peer in ('wifi', 'gpu', 'audio', 'modem'):
            if peer != module and re.search(r'giulia-' + peer + r'-runtime\.patch|ios16/' + peer + r'\b', builder):
                errors.append(f'{module} builder inspects/mutates sibling {peer}')
    for module in ('keys', 'slider', 'touch'):
        builder = (Path(root) / f'scripts/ios16_{module}.py').read_text(encoding='utf-8')
        if 'bsd/conf/files' in builder or 'bsd/kern/bsd_init.c' in builder:
            errors.append(f'{module} builder owns registration instead of the composition root')
    if errors:
        raise ValueError('\n'.join(errors))
    return len(sources)


if __name__ == '__main__':
    print(f'Driver boundaries verified: {validate()} sources, {len(MODULES)} modules')
