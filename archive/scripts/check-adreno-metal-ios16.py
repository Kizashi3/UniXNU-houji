#!/usr/bin/env python3
"""Check nonoptional imports against stubs generated from the owner's iOS 16 cache.

This static check follows re-exported images; it does not prove Objective-C
selector compatibility, dyld execution, GPU submission or desktop acceleration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import yaml


def read(cmd):
    return subprocess.check_output([str(x) for x in cmd], text=True, stderr=subprocess.PIPE, timeout=30)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ipsw', type=Path, required=True)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--cache', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('binaries', nargs='+', type=Path)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    (a.output / 'result.json').unlink(missing_ok=True)
    cli = [a.ipsw, '--no-color', '--config', a.config, 'dyld']
    cache_info = json.loads(read([*cli, 'info', '--dylibs', '--json', a.cache]))
    available = {x['name'] for x in cache_info['dylibs']}
    symbols, edges = {}, {}

    def load(path):
        if path in symbols:
            return
        if path not in available:
            raise RuntimeError('dependency absent from iOS 16 cache: ' + path)
        key = hashlib.sha256(path.encode()).hexdigest()[:16]
        toc = json.loads(read([*cli, 'macho', '--json', a.cache, path]))
        stub_dir = a.output / 'tbd' / key
        stub_dir.mkdir(parents=True, exist_ok=True)
        read([*cli, 'tbd', a.cache, path, '--output', stub_dir])
        files = list(stub_dir.glob('*.tbd'))
        if len(files) != 1:
            raise RuntimeError('expected exactly one generated export stub: ' + path)
        documents = list(yaml.safe_load_all(files[0].read_text().replace('--- !tapi-tbd', '---')))
        matches = [d for d in documents if d and d.get('install-name') == path]
        if len(matches) != 1:
            raise RuntimeError('generated stub has an ambiguous image identity: ' + path)
        stub = matches[0]
        if stub['install-name'] != path or 'arm64-ios' not in stub['targets']:
            raise RuntimeError('export stub identity differs: ' + path)
        (a.output / (key + '.toc.json')).write_text(json.dumps(toc, indent=2) + '\n')
        defined = set()
        for row in stub.get('exports', []):
            if 'arm64-ios' not in row['targets']:
                continue
            defined.update(row.get('symbols', []))
            defined.update(row.get('weak-def-symbols', []))
            for name in row.get('objc-classes', []):
                defined.update(('_OBJC_CLASS_$_' + name, '_OBJC_METACLASS_$_' + name))
            defined.update('_OBJC_EHTYPE_$_' + name for name in row.get('objc-eh-types', []))
            defined.update('_OBJC_IVAR_$_' + name for name in row.get('objc-ivars', []))
        symbols[path] = defined
        targets = {x['name'] for x in toc['loads'] if x['load_cmd'] == 'LC_REEXPORT_DYLIB'}
        for row in stub.get('reexported-libraries', []):
            if 'arm64-ios' in row['targets']:
                targets.update(row['libraries'])
        edges[path] = sorted(targets)
        for target in edges[path]:
            load(target)

    def closure(path, seen=None):
        seen = set() if seen is None else seen
        if path in seen:
            return set()
        seen.add(path)
        result = set(symbols[path])
        for target in edges[path]:
            result.update(closure(target, seen))
        return result

    results = []
    for binary in a.binaries:
        deps = re.findall(r'^\s+(/\S+) \(compatibility', read(['otool', '-L', binary]), re.M)
        # LC_ID_DYLIB is this file's identity, not an import from the cache.
        # Query it explicitly so an absolute app-local ID is handled too.
        own_ids = set(read(['otool', '-D', binary]).splitlines()[1:])
        deps = [p for p in deps if p not in own_ids]
        aliases = {}
        for path in deps:
            load(path)
            name = Path(path).name
            name = re.sub(r'(?:\.[0-9A-Z]+)*\.dylib$', '', name)
            aliases[name] = path
        imports = read(['xcrun', 'dyld_info', '-imports', binary])
        own_exports = set(re.findall(r'^\s+0x[0-9a-fA-F]+\s+(\S+)',
                                    read(['xcrun', 'dyld_info', '-exports', binary]), re.M))
        (a.output / (binary.name + '.imports.txt')).write_text(imports)
        checked, weak, missing = 0, 0, []
        for line in imports.splitlines():
            match = re.match(r'^\s+(?:0x[0-9a-fA-F]+\s+)?(\S+)\s+(\[weak-import\]\s+)?\(from (.+)\)$', line)
            if not match:
                if '(from ' in line:
                    raise RuntimeError('unparsed import: ' + line)
                continue
            symbol, weak_mark, library = match.groups()
            if weak_mark:
                weak += 1
                continue
            checked += 1
            path = aliases.get(library)
            if library == '<weak-def-coalesce>':
                # A coalesced definition must actually exist in this image or
                # one of its declared dependency/re-export closures.
                found = symbol in own_exports or any(symbol in closure(p) for p in deps)
            else:
                found = bool(path and symbol in closure(path))
            if not found:
                missing.append({'symbol': symbol, 'from': library, 'path': path})
        results.append({'binary': str(binary), 'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                        'nonoptional_symbols_checked': checked, 'weak_imports': weak, 'missing': missing})
    result = {'cache_uuid': cache_info['uuid'], 'cache_platform': cache_info['platform'],
              'scope': 'cache-generated export stubs and re-export closures, not runtime binding or Objective-C selectors',
              'images_checked': len(symbols), 'binaries': results,
              'pass': all(x['nonoptional_symbols_checked'] and not x['missing'] for x in results),
              'hardware_tested': False}
    (a.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['pass'] else 1)


if __name__ == '__main__':
    main()
