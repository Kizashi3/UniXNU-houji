"""Qualify the captured Ace 5 modem resource map without accessing hardware.

Input is decoded numeric dtc output, not source DTS with labels/includes/macros.
The existing GPU DTS reader supplies scoped nodes and typed properties. This
checker verifies pinned values and resolves provider phandles independently;
it does not load firmware, map memory, start a modem or certify radio operation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from ios16_gpu import cells, strings

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'hardware/sm8650-modem.json'


def load_manifest(path=MANIFEST):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if (data.get('schema'), data.get('board'), data.get('soc')) != (1, 'giulia', 'SM8650'):
        raise ValueError('Expected the captured Ace 5 modem map')
    if data.get('hardware_validated') is not False:
        raise ValueError('This static map cannot assert hardware validation')
    return data


def index_nodes(text):
    """Index brace-delimited decoded nodes; properties use the existing reader.

    This is not a source DTS parser. Quotes/comments are skipped when locating
    braces, and full parent paths prevent nested children impersonating nodes.
    """
    stack, result = [], {}
    end = 0
    tokens = re.compile(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*|[{}]', re.S)
    for token in tokens.finditer(text):
        if token.group() not in ('{', '}'):
            continue
        if token.group() == '{':
            match = re.search(r'([A-Za-z0-9_.,+@/#?-]+)\s*$', text[end:token.start()])
            if not match or (not stack and match[1] != '/'):
                raise ValueError('Malformed decoded DTS node')
            stack.append((match[1], token.end()))
        else:
            if not stack:
                raise ValueError('Unbalanced decoded DTS')
            path = '/' + '/'.join(name for name, _ in stack[1:])
            if path in result:
                raise ValueError('Duplicate decoded DTS node: ' + path)
            _, start = stack.pop()
            result[path] = text[start:token.start()]
        end = token.end()
    if stack or '/' not in result:
        raise ValueError('Unbalanced decoded DTS')
    return result


def node_at(text, path):
    try:
        return index_nodes(text)[path]
    except KeyError as error:
        raise ValueError('Missing decoded DTS node: ' + path) from error


def own_properties(node):
    # Drop complete child nodes while ignoring braces inside quoted strings.
    depth, last, chunks = 0, 0, []
    for token in re.finditer(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*|[{}]', node, re.S):
        if token.group() == '{':
            if depth == 0:
                name = re.search(r'[A-Za-z0-9_.,+@/#?-]+\s*$', node[last:token.start()])
                if not name:
                    raise ValueError('Malformed decoded DTS child')
                chunks.append(node[last:last + name.start()])
            depth += 1
        elif token.group() == '}':
            depth -= 1
            if depth < 0:
                raise ValueError('Malformed decoded DTS child')
            if depth == 0:
                last = token.end()
                if node[last:last + 1] == ';':
                    last += 1
    if depth:
        raise ValueError('Malformed decoded DTS child')
    return ''.join(chunks) + node[last:]


def read_property(node, name, reader=cells):
    values = re.findall(r'(?m)^\s*' + re.escape(name) + r'\s*=\s*([^;]+);', own_properties(node))
    if len(values) != 1:
        raise ValueError('Expected exactly one property: ' + name)
    # Give the existing strict typed reader only the requested property.
    return reader(name + ' = ' + values[0] + ';', name)


def require_flag(node, name):
    node = own_properties(node)
    if len(re.findall(r'(?m)^\s*' + re.escape(name) + r'\s*;', node)) != 1:
        raise ValueError('Expected exactly one boolean property: ' + name)


def verify_decoded_dts(data, text):
    """Verify public resources and actual phandle links, without a hash gate.

    Used for diagnostic qualification and adversarial fixtures. Production
    callers should use verify_dts(), which pins the complete captured input.
    """
    indexed, nodes = index_nodes(text), {}
    properties = 0
    for key, spec in data['dt_nodes'].items():
        try:
            node = indexed[spec['path']]
        except KeyError as error:
            raise ValueError('Missing decoded DTS node: ' + spec['path']) from error
        nodes[key] = node
        for kind, reader in (('cells', cells), ('strings', strings)):
            for name, expected in spec.get(kind, {}).items():
                if read_property(node, name, reader) != expected:
                    raise ValueError('DTS mismatch: ' + spec['path'] + '/' + name)
                properties += 1
        for name in spec.get('flags', []):
            require_flag(node, name)
            properties += 1
        for name in spec.get('absent', []):
            if re.search(r'(?m)^\s*' + re.escape(name) + r'\s*(?:=|;)', own_properties(node)):
                raise ValueError('Unexpected DTS property: ' + spec['path'] + '/' + name)
            properties += 1

    # Resolve phandles from the named providers. Do not assume a numeric value
    # identifies the same provider in a different device tree.
    targets = {item['target'] for link in data['dt_references'] for item in link['specifiers']}
    handles = {}
    for target in sorted(targets):
        value = read_property(nodes[target], 'phandle')
        if len(value) != 1 or not 0 < value[0] < 0xffffffff:
            raise ValueError('Invalid provider phandle: ' + target)
        if value[0] in handles.values():
            raise ValueError('Duplicate provider phandle: ' + target)
        handles[target] = value[0]
    for link in data['dt_references']:
        expected = []
        for spec in link['specifiers']:
            expected.extend([handles[spec['target']], *spec.get('args', [])])
        if read_property(nodes[link['source']], link['property']) != expected:
            raise ValueError('DTS reference mismatch: ' + link['source'] + '/' + link['property'])
    return {'nodes_verified': len(nodes), 'properties_verified': properties,
            'references_verified': len(data['dt_references']), 'hardware_validated': False}


def verify_dts(data, path):
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != data['android_device_tree']['decoded_sha256']:
        raise ValueError('Captured Android DTS hash mismatch; requalify the board map')
    return verify_decoded_dts(data, raw.decode('utf-8'))


def verify_files(records, root):
    root = Path(root).resolve()
    for source in records:
        path = (root / source['path']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Evidence path escapes source root')
        raw = path.read_bytes()
        if len(raw) != source['bytes'] or hashlib.sha256(raw).hexdigest() != source['sha256']:
            raise ValueError('Source hash/size mismatch: ' + source['path'])
    return len(records)


def verify_sources(data, root):
    return verify_files(data['source_files'], root)


def ipa_routes_from_sources(implementation, uapi, internal):
    """Read the pinned IPA 5.5 table, retaining EE and test aliases separately.

    This is a deliberately restricted initializer reader, not a C evaluator.
    Reject unparsed entries instead of silently dropping new source syntax.
    """
    numeric = lambda text: {name: int(value, 0) for name, value in re.findall(
        r'\b(IPA_\w+)\s*=\s*(0x[0-9a-fA-F]+|[0-9]+)\s*[,}]', text)}
    clients, constants = numeric(uapi), numeric(internal)
    aliases = re.findall(r'(?m)^#define\s+(IPA_CLIENT_\w+)\s+(IPA_CLIENT_\w+)\s*$', uapi)
    for _ in range(len(aliases)):
        for name, target in aliases:
            if target in clients:
                clients[name] = clients[target]
    if clients.get('IPA_HW_v5_5') != 24 or constants.get('IPA_PLAT_TYPE_MSM') != 1:
        raise ValueError('Unqualified IPA version/platform enumeration')
    group_ids = {name: int(value) for name, value in re.findall(
        r'#define\s+(IPA_v5_5_GROUP_\w+)\s+\(([0-9]+)\)', implementation)}
    pattern = re.compile(
        r'\[IPA_5_5\]\[(IPA_CLIENT_\w+)\]\s*=\s*\{\s*'
        r'(true|false)\s*,\s*(\w+)\s*,\s*(true|false)\s*,\s*'
        r'(\w+)\s*,\s*(\w+)\s*,\s*\{\s*([^{}]+)\}\s*,\s*(\w+)\s*\}')
    routes, aliases, seen = [], [], set()
    matches = list(pattern.finditer(implementation))
    if not matches or len(matches) != len(re.findall(r'\[IPA_5_5\]\[IPA_CLIENT_\w+\]\s*=', implementation)):
        raise ValueError('Incomplete IPA 5.5 endpoint table')
    for match in matches:
        name, valid, group, filtering, sequencer, master, fields, tx = match.groups()
        values = [field.strip() for field in fields.split(',')]
        if name in seen or len(values) != 7 or name not in clients or group not in group_ids:
            raise ValueError('Invalid/duplicate IPA endpoint entry: ' + name)
        seen.add(name)
        try:
            endpoint, channel, tlv, aos = map(lambda value: int(value, 0), values[:4])
            ee = constants[values[4]]
            threshold = int(values[6], 0)
        except (ValueError, KeyError) as error:
            raise ValueError('Invalid IPA GSI tuple: ' + name) from error
        if min(endpoint, channel, tlv, aos, threshold) < 0 or ee not in (0, 1, 2):
            raise ValueError('Invalid IPA GSI bounds: ' + name)
        item = {'client': name, 'client_id': clients[name], 'valid': valid == 'true',
                'endpoint': endpoint, 'gsi_channel': channel, 'execution_environment': ee,
                'execution_environment_name': values[4], 'ipa_if_tlv': tlv, 'ipa_if_aos': aos,
                'prefetch_mode': values[5], 'prefetch_threshold': threshold,
                'group': group, 'group_id': group_ids[group], 'filtering': filtering == 'true',
                'sequencer': sequencer, 'qmb_master': master, 'tx_instance': tx,
                'source_line': implementation.count('\n', 0, match.start()) + 1}
        (aliases if name.startswith('IPA_CLIENT_TEST') else routes).append(item)
    if len({item['endpoint'] for item in routes}) != len(routes):
        raise ValueError('Duplicate production IPA endpoint')
    if len({(item['execution_environment'], item['gsi_channel']) for item in routes}) != len(routes):
        raise ValueError('Duplicate production GSI channel within execution environment')
    return {'hardware_enum': 24, 'platform_enum': 1, 'table': 'IPA_5_5',
            'production_routes': routes, 'test_aliases': aliases}


def verify_ipa_sources(data, root=ROOT):
    root = Path(root)
    sources = root / '.cache/modem-source'
    actual = ipa_routes_from_sources(*((sources / name).read_text(encoding='utf-8')
                                    for name in ('ipa_utils.c', 'msm_ipa.h', 'ipa_i.h')))
    if actual != data['ipa_endpoint_map']:
        raise ValueError('IPA endpoint map differs from pinned source')
    return len(actual['production_routes'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dts', type=Path, required=True, help='Captured, decoded running-device.dts')
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--source-root', type=Path, help='Optional pinned OnePlus source cache root')
    parser.add_argument('--local-evidence', action='store_true', help='Verify additional cached UEFI and loader evidence')
    args = parser.parse_args()
    try:
        data = load_manifest(args.manifest)
        result = verify_dts(data, args.dts)
        if args.source_root:
            result['sources_verified'] = verify_sources(data, args.source_root)
        if args.local_evidence:
            result['local_evidence_verified'] = verify_files(data['local_evidence'], ROOT)
            result['ipa_production_routes_verified'] = verify_ipa_sources(data)
    except (ValueError, OSError, UnicodeError, KeyError) as error:
        parser.exit(1, 'Modem board verification failed: ' + str(error) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
