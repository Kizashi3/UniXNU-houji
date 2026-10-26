"""Reproduce complete pinned service schemas; never contact a modem or network.

This is documentation extraction, not a QMI implementation. It preserves all
messages, vendor variants, nested fields and prerequisites in the selected
upstream schemas. Unsupported source syntax fails instead of dropping fields.
"""
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache/modem-source'
OUTPUT = ROOT / 'hardware/modem-qmi-service-map.json'
LIBQMI = 'd9e8af5cae7fdf9749baf87606568d3af4d03082'
KERNEL = 'd763ed47deec55451366c1187f813f2f309d88a7'
MODULES = '453d8875f815bf9dfad9035982861226a4823a6c'
RMTFS = 'b30a3eb38f9af283f18dbd3c7755653efc52c094'
TQFTP = '0bf5b98c24229b0042554d99bb1509d813219f36'
SERVICES = ('ctl', 'uim', 'nas', 'dms', 'wds', 'wda', 'qos', 'pdc',
            'dpm', 'dsd', 'ims', 'imsa', 'voice', 'wms', 'sar')
TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.S)
SCALARS = {**{'g' + sign + str(bits): bits // 8
              for sign in ('uint', 'int') for bits in (8, 16, 32, 64)},
           'gfloat': 4, 'gdouble': 8}


def uncomment(text):
    # Preserve line numbering and quoted strings (including URLs).
    return TOKEN.sub(lambda m: m[0] if m[0].startswith('"')
                     else '\n' * m[0].count('\n'), text)


class Sources:
    def __init__(self, root):
        self.root, self.records = Path(root), {}

    def read(self, name, repository=None, commit=None, upstream=None):
        raw = (self.root / name).read_bytes()
        item = {'path': '.cache/modem-source/' + name, 'bytes': len(raw),
                'sha256': hashlib.sha256(raw).hexdigest()}
        if repository:
            item.update(repository=repository, commit=commit, upstream_path=upstream,
                        url='https://github.com/' + repository + '/blob/' + commit + '/' + upstream)
        self.records[name] = item
        return raw.decode('utf-8')

    def libqmi(self, name, upstream=None):
        return self.read(name, 'linux-mobile-broadband/libqmi', LIBQMI,
                         upstream or 'data/' + name)


def schema_json(text):
    value = json.loads(uncomment(text))
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise ValueError('Expected a QMI schema object array')
    return value


def integer(value):
    return int(str(value), 0)


def minimum_version(a, b):
    key = lambda value: tuple(int(n) for n in value.split('.'))
    return a if key(a) <= key(b) else b


def field_layout(field, definitions, provenance, message_since=None, resolve=True):
    original = copy.deepcopy(field)
    field = copy.deepcopy(field)
    ref = field.get('common-ref')
    if ref and resolve:
        # Container.py only overrides these properties of a common TLV.
        kind = 'prerequisite' if field.get('type') == 'prerequisite' else 'TLV'
        if (kind, ref) not in definitions and ('prerequisite', ref) in definitions:
            kind = 'prerequisite'
        if (kind, ref) not in definitions:
            raise ValueError('Unresolved common-ref: ' + ref)
        definition, origin = definitions[kind, ref]
        field = copy.deepcopy(definition)
        if kind == 'TLV':
            if set(original) - {'common-ref', 'id', 'name', 'since', 'prerequisites'}:
                raise ValueError('Unsupported common-ref override: ' + ref)
            for key in ('id', 'name', 'since', 'prerequisites'):
                if key in original:
                    field[key] = original[key]
            if 'since' not in original and message_since:
                field['since'] = minimum_version(field.get('since', message_since), message_since)
        field['resolved_common_source'] = origin
        field['reference_site'] = provenance
    field['schema_source'] = provenance
    if 'prerequisites' in field and isinstance(field['prerequisites'], list):
        field['prerequisites'] = [field_layout(x, definitions,
            provenance + '/prerequisites/' + str(i), message_since)
            for i, x in enumerate(field['prerequisites'])]
    fmt = field.get('format')
    if not fmt:
        if field.get('type') == 'prerequisite' or {'field', 'operation', 'value'} <= field.keys():
            return field
        raise ValueError('Field has no format: ' + str(field.get('name')))
    wire = {'format': fmt, 'fixed_bytes': None, 'minimum_bytes': 0}
    if isinstance(field.get('prerequisites'), str):
        wire['source_ordering_constraint'] = field['prerequisites']
    endian = field.get('endian', 'little')
    if endian not in ('little', 'big', 'network'):
        raise ValueError('Unknown byte order: ' + endian)
    if fmt in SCALARS or fmt == 'guint-sized':
        size = SCALARS.get(fmt) if fmt != 'guint-sized' else integer(field['guint-size'])
        if not size or size > 8:
            raise ValueError('Invalid scalar width')
        wire.update(fixed_bytes=size, minimum_bytes=size,
                    byte_order='not-applicable' if size == 1 else ('big' if endian == 'network' else endian),
                    byte_order_origin='explicit' if 'endian' in field else 'Variable.py default')
    elif fmt in ('sequence', 'struct'):
        field['contents'] = [field_layout(x, definitions, provenance + '/contents/' + str(i),
                                        message_since, False)
                             for i, x in enumerate(field['contents'])]
        sizes = [x['wire']['fixed_bytes'] for x in field['contents']]
        wire.update(fixed_bytes=sum(sizes) if all(x is not None for x in sizes) else None,
                    minimum_bytes=sum(x['wire']['minimum_bytes'] for x in field['contents']),
                    encoding='ordered concatenation; no C-ABI padding')
    elif fmt == 'array':
        if ('fixed-size' in field) == ('size-prefix-format' in field):
            raise ValueError('Array must have exactly one size source')
        field['array-element'] = field_layout(field['array-element'], definitions,
            provenance + '/array-element', message_since, False)
        element = field['array-element']['wire']
        if 'fixed-size' in field:
            count = integer(field['fixed-size'])
            if not 0 < count <= 512 or 'sequence-prefix-format' in field:
                raise ValueError('Invalid fixed array')
            wire.update(count=count, count_prefix_bytes=0,
                        fixed_bytes=None if element['fixed_bytes'] is None else count * element['fixed_bytes'],
                        minimum_bytes=count * element['minimum_bytes'])
        else:
            prefix = field['size-prefix-format']
            if prefix not in ('guint8', 'guint16', 'guint32'):
                raise ValueError('Unsupported array count prefix')
            size = SCALARS[prefix]
            wire.update(count_prefix_bytes=size, count_byte_order='little',
                        count_maximum=(1 << (8 * size)) - 1, minimum_bytes=size,
                        element_count='encoded count; must also fit containing TLV')
            if 'sequence-prefix-format' in field:
                seq = field['sequence-prefix-format']
                if seq not in SCALARS:
                    raise ValueError('Unsupported sequence prefix')
                wire.update(sequence_prefix_bytes=SCALARS[seq],
                            sequence_prefix_position='after count, before elements')
                wire['minimum_bytes'] += SCALARS[seq]
                # The pinned reader uses the count reader for this prefix.
                wire['pinned_reader_sequence_bytes'] = size
                if SCALARS[seq] != size:
                    wire['source_discrepancy'] = 'Pinned reader uses count width; writer uses sequence width.'
    elif fmt == 'string':
        if 'fixed-size' in field:
            size = integer(field['fixed-size'])
            wire.update(fixed_bytes=size, minimum_bytes=size, length_prefix_bytes=0)
        else:
            prefix = field.get('size-prefix-format')
            if prefix is None:
                size = 0 if field.get('type') == 'TLV' else 1
            elif prefix in ('guint8', 'guint16'):
                size = SCALARS[prefix]
            else:
                raise ValueError('Unsupported string size prefix')
            wire.update(minimum_bytes=size, length_prefix_bytes=size, length_byte_order='little',
                        length_source='prefix' if size else 'containing TLV length',
                        maximum_bytes=field.get('max-size'),
                        terminator='No implicit C NUL byte on wire')
    else:
        raise ValueError('Unsupported schema format: ' + fmt)
    if field.get('type') == 'TLV':
        tlv_id = integer(field['id'])
        if not 0 <= tlv_id <= 255:
            raise ValueError('TLV id exceeds one byte')
        wire.update(tlv_id=tlv_id, tlv_header_bytes=3, tlv_length_bytes=2,
                    tlv_length_byte_order='little', tlv_maximum_value_bytes=65535,
                    mandatory=(field['mandatory'] == 'yes') if 'mandatory' in field else tlv_id < 16)
    field['wire'] = wire
    return field


def libqmi_services(sources):
    common = schema_json(sources.libqmi('qmi-common.json'))
    enum_text = sources.libqmi('qmi-enums.h', 'src/libqmi-glib/qmi-enums.h')
    ids = {name: integer(number) for name, number in re.findall(
        r'QMI_SERVICE_(\w+)\s*=\s*(0x[0-9A-Fa-f]+|[0-9]+)', uncomment(enum_text))}
    result = []
    for service in SERVICES:
        filename = 'qmi-service-' + service + '.json'
        objects = schema_json(sources.libqmi(filename))
        definitions = {}
        for name, records in [('qmi-common.json', common), (filename, objects)]:
            for i, obj in enumerate(records):
                if obj.get('type') in ('TLV', 'prerequisite') and 'common-ref' in obj:
                    key = (obj['type'], obj['common-ref'])
                    if key in definitions:
                        raise ValueError('Duplicate common definition: ' + str(key))
                    definitions[key] = (obj, name + '#/' + str(i))
        messages = []
        for index, msg in enumerate(objects):
            if msg['type'] not in ('Message', 'Indication'):
                continue
            directions = [('indication', 'output')] if msg['type'] == 'Indication' else [('request', 'input'), ('response', 'output')]
            for direction, container in directions:
                origin = filename + '#/' + str(index)
                fields = [field_layout(x, definitions, origin + '/' + container + '/' + str(i), msg.get('since'))
                          for i, x in enumerate(msg.get(container, []))]
                message = {key: value for key, value in msg.items() if key not in ('input', 'output')}
                message.update(message_id=integer(msg['id']), direction=direction,
                               source_record=origin, container_present=container in msg, fields=fields,
                               roles={'request': 'client -> service', 'response': 'service -> client',
                                      'indication': 'service -> client'}[direction])
                messages.append(message)
        result.append({'name': service.upper(), 'service_id': ids[service.upper()],
            'source': filename, 'scope': 'all Message and Indication records in pinned schema, including vendor variants',
            'wire_header': {'bytes': 6 if service == 'ctl' else 7,
                            'transaction_bytes': 1 if service == 'ctl' else 2,
                            'flags': {'request': 0, 'response': 1 if service == 'ctl' else 2,
                                      'indication': 2 if service == 'ctl' else 4}},
            'runtime_instance': None, 'runtime_version': None,
            'runtime_note': 'Discover actual service/version/instance/endpoint; schema presence does not establish firmware support.',
            'definition_records': [{'source': origin, 'definition': definition} for definition, origin in definitions.values()],
            'messages': messages})
    return result


def constants(text):
    """Resolve integer-like C macros without executing source expressions."""
    text = uncomment(text).replace('\\\n', '')
    expressions = dict(re.findall(r'(?m)^\s*#define\s+(\w+)\s+([^\n]+)', text))
    result = {'QMI_COMMON_TLV_TYPE': 0}

    def evaluate(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return node.value
        if isinstance(node, ast.Name) and node.id in result:
            return result[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Invert)):
            value = evaluate(node.operand)
            return -value if isinstance(node.op, ast.USub) else ~value if isinstance(node.op, ast.Invert) else value
        if isinstance(node, ast.BinOp):
            left, right = evaluate(node.left), evaluate(node.right)
            for kind, op in ((ast.Add, lambda: left + right), (ast.Sub, lambda: left - right),
                             (ast.Mult, lambda: left * right), (ast.LShift, lambda: left << right),
                             (ast.RShift, lambda: left >> right), (ast.BitOr, lambda: left | right),
                             (ast.BitAnd, lambda: left & right)):
                if isinstance(node.op, kind):
                    return op()
        raise ValueError('Unsupported constant expression')

    for _ in range(len(expressions) + 1):
        changed = False
        for name, expression in expressions.items():
            if name in result:
                continue
            expression = re.sub(r'\b(0x[0-9a-fA-F]+|[0-9]+)[uUlL]+\b', r'\1', expression)
            try:
                result[name] = evaluate(ast.parse(expression, mode='eval').body)
                changed = True
            except (ValueError, SyntaxError, KeyError):
                pass
        if not changed:
            break
    return result


def c_tables(text, source):
    """Capture every qmi_elem_info initializer and retain its exact expressions."""
    clean = uncomment(text)
    result = {}
    for match in re.finditer(r'(?:static\s+)?(?:const\s+)?struct\s+qmi_elem_info\s+(\w+)\s*\[\s*\]\s*=\s*\{(.*?)\n\};', clean, re.S):
        name, body = match.groups()
        entries = []
        for entry in re.finditer(r'\{([^{}]*)\}', body, re.S):
            fields = {}
            pairs = list(re.finditer(r'\.(\w+)\s*=', entry[1]))
            for i, pair in enumerate(pairs):
                end = pairs[i + 1].start() if i + 1 < len(pairs) else len(entry[1])
                fields[pair[1]] = re.sub(r'\s+', ' ', entry[1][pair.end():end].strip().rstrip(',').strip())
            if fields and fields.get('data_type') != 'QMI_EOTI':
                entries.append(fields)
        if name in result:
            raise ValueError('Duplicate element table: ' + name)
        result[name] = {'source': source, 'source_line': clean.count('\n', 0, match.start()) + 1,
                        'symbol': name, 'entries': entries}
    declared = re.findall(r'(?:static\s+)?(?:const\s+)?struct\s+qmi_elem_info\s+(\w+)\s*\[\s*\]\s*=', clean)
    if set(declared) != set(result):
        raise ValueError('Unparsed C element tables: ' + str(set(declared) - set(result)))
    return result


def c_number(expression, values):
    try:
        return integer(expression)
    except ValueError:
        return values.get(expression)


def ei_fields(name, tables, values, stack=()):
    if name in stack:
        raise ValueError('Recursive C element table: ' + name)
    if name not in tables:
        raise ValueError('Unresolved C element table: ' + name)
    result = []
    for index, raw in enumerate(tables[name]['entries']):
        data_type = raw.get('data_type')
        if not data_type:
            raise ValueError('Missing qmi_elem_info data_type')
        field = {'source': tables[name]['source'], 'table': name, 'element_index': index,
                 'c_initializer': raw, 'data_type': data_type,
                 'array_type': raw.get('array_type', 'NO_ARRAY'),
                 'tlv_id': c_number(raw.get('tlv_type', '0'), values),
                 'element_capacity': c_number(raw.get('elem_len', '0'), values)}
        offset = re.fullmatch(r'offsetof\(\s*struct\s+(\w+)\s*,\s*(\w+)\s*\)', raw.get('offset', ''))
        if offset:
            field['c_struct'], field['name'] = offset.groups()
        else:
            raise ValueError('Unparsed C field offset: ' + str(raw.get('offset')))
        wire = {'byte_order': 'little on pinned SM8650 ABI',
                'c_offset_is_not_wire_offset': True,
                'c_elem_size_is_not_necessarily_wire_size': True}
        widths = {'QMI_UNSIGNED_1_BYTE': 1, 'QMI_UNSIGNED_2_BYTE': 2,
                  'QMI_UNSIGNED_4_BYTE': 4, 'QMI_UNSIGNED_8_BYTE': 8,
                  'QMI_SIGNED_2_BYTE_ENUM': 2, 'QMI_SIGNED_4_BYTE_ENUM': 4}
        if data_type in widths:
            wire['scalar_bytes'] = widths[data_type]
        elif data_type == 'QMI_OPT_FLAG':
            wire.update(encoded_bytes=0, role='host-only presence flag controlling following same-TLV fields')
        elif data_type == 'QMI_DATA_LEN':
            # qmi_encdec: sizeof(u8) -> 1 byte, any other storage width -> 2.
            width = 1 if raw.get('elem_size') in ('sizeof(uint8_t)', 'sizeof(u8)') else 2
            wire.update(encoded_bytes=width, role='encoded array count, not full C length storage')
        elif data_type == 'QMI_STRUCT':
            target = raw.get('ei_array')
            if not target:
                raise ValueError('QMI_STRUCT missing nested table')
            field['contents'] = ei_fields(target, tables, values, (*stack, name))
            wire['encoding'] = 'recursive fields; no C padding'
        elif data_type == 'QMI_STRING':
            wire.update(encoding='string bytes',
                        length_prefix='outer TLV: none; nested: 1 byte if capacity <= 255, otherwise 2',
                        terminator='not the C trailing NUL')
        else:
            raise ValueError('Unsupported C wire type: ' + data_type)
        field['wire'] = wire
        result.append(field)
    return result


def c_calls(text, name):
    """Return complete call argument strings, not statement fragments."""
    clean = uncomment(text)
    for match in re.finditer(r'\b' + re.escape(name) + r'\s*\(', clean):
        depth, end = 1, match.end()
        while end < len(clean) and depth:
            depth += (clean[end] == '(') - (clean[end] == ')')
            end += 1
        if depth:
            raise ValueError('Unterminated C call: ' + name)
        yield clean[match.end():end - 1], clean.count('\n', 0, match.start()) + 1


def ipa_service(sources):
    base = 'vendor/qcom/opensource/dataipa/drivers/platform/msm/'
    repo = 'OnePlusOSS/android_kernel_modules_and_devicetree_oneplus_sm8650'
    header = sources.read('ipa_qmi_service_v01.h', repo, MODULES, base + 'include/uapi/linux/ipa_qmi_service_v01.h')
    schema = sources.read('ipa_qmi_service_v01.c', repo, MODULES, base + 'ipa/ipa_v3/ipa_qmi_service_v01.c')
    implementation = sources.read('ipa_qmi_service.c', repo, MODULES, base + 'ipa/ipa_v3/ipa_qmi_service.c')
    helper_header = sources.read('ipa_qmi_service.h', repo, MODULES, base + 'ipa/ipa_v3/ipa_qmi_service.h')
    kernel = sources.read('kernel-qmi_encdec.c', 'OnePlusOSS/android_kernel_oneplus_sm8650', KERNEL, 'drivers/soc/qcom/qmi_encdec.c')
    kernel_h = sources.read('kernel-qmi.h', 'OnePlusOSS/android_kernel_oneplus_sm8650', KERNEL, 'include/linux/soc/qcom/qmi.h')
    values = constants(header + '\n' + implementation + '\n' + helper_header + '\n' + kernel_h)
    tables = c_tables(schema, 'ipa_qmi_service_v01.c')
    tables.update(c_tables(kernel, 'kernel-qmi_encdec.c'))
    bindings = {}

    def bind(message, table, role, line):
        if message not in values or table not in tables:
            raise ValueError('Unresolved IPA binding: ' + message + '/' + table)
        record = {'element_table': table, 'role': role, 'source': 'ipa_qmi_service.c', 'source_line': line}
        if record not in bindings.setdefault(message, []):
            bindings[message].append(record)

    clean = uncomment(implementation)
    for match in re.finditer(r'\{\s*\.type\s*=\s*(QMI_\w+)\s*,\s*\.msg_id\s*=\s*(QMI_IPA_\w+)\s*,\s*\.ei\s*=\s*(\w+)', clean):
        kind, message, table = match.groups()
        bind(message, table, 'MPSS -> AP server (instance 1)' if kind == 'QMI_REQUEST'
             else 'MPSS service (instance 2) -> AP client', clean.count('\n', 0, match.start()) + 1)
    for call, role in [('qmi_send_response', 'AP server (instance 1) -> MPSS client'),
                       ('qmi_send_indication', 'AP server (instance 1) -> MPSS client'),
                       ('qmi_send_request', 'AP client -> MPSS service (instance 2)')]:
        for args, line in c_calls(implementation, call):
            messages = [name for name in re.findall(r'\bQMI_IPA_\w+\b', args)
                        if re.search(r'_(?:REQ|RESP|IND)(?:ICATION)?_V01$', name)]
            linked = [name for name in re.findall(r'\b\w+\b', args) if name in tables]
            if len(messages) == 1 and len(linked) == 1:
                bind(messages[0], linked[0], role, line)
    # Legacy descriptors retain exact explicit msg_id/ei_array associations.
    for match in re.finditer(r'\b(\w+)\.msg_id\s*=\s*(QMI_IPA_\w+)\s*;', clean):
        variable, message = match.groups()
        tail = clean[match.end():]
        next_id = re.search(r'\b' + variable + r'\.msg_id\s*=', tail)
        tail = tail[:next_id.start()] if next_id else tail
        table = re.search(r'\b' + variable + r'\.ei_array\s*=\s*(\w+)\s*;', tail)
        if table:
            role = 'AP client -> MPSS service (instance 2)' if '_REQ_' in message else 'MPSS service (instance 2) -> AP client'
            bind(message, table[1], role, clean.count('\n', 0, match.start()) + 1)
    message_constants = {name: value for name, value in values.items()
                         if name.startswith('QMI_IPA_') and re.search(r'_(REQ|RESP|IND|INDICATION)_V01$', name)}
    messages = []
    for name, number in sorted(message_constants.items(), key=lambda x: (x[1], x[0])):
        kind = re.search(r'_(REQ|RESP|IND|INDICATION)_V01$', name)[1]
        links = bindings.get(name, [])
        table_names = sorted({link['element_table'] for link in links})
        messages.append({'symbol': name, 'message_id': number,
            'direction': {'REQ': 'request', 'RESP': 'response', 'IND': 'indication', 'INDICATION': 'indication'}[kind],
            'bindings': links,
            'fields_by_table': {table: ei_fields(table, tables, values) for table in table_names},
            'binding_status': 'explicit source call/handler' if links else 'declared message; no call/handler binding in pinned service C',
            'unresolved_next_source': None if links else 'Inspect the declared struct/element table and additional pinned dataipa call sites; never assign by approximate name.'})
    return {'name': 'IPA', 'service_id': values['IPA_A5_SERVICE_SVC_ID'],
        'instances': [{'id': values['IPA_A5_SERVICE_INS_ID'], 'server': 'AP', 'client': 'MPSS',
                       'version': values['IPA_A5_SVC_VERS']},
                      {'id': values['IPA_Q6_SERVICE_INS_ID'], 'server': 'MPSS', 'client': 'AP',
                       'version': values['IPA_Q6_SVC_VERS']}],
        'messages': messages,
        'element_tables': {name: {**record, 'fields': ei_fields(name, tables, values)}
                           for name, record in sorted(tables.items())},
        'coverage': 'Every message-ID macro and every qmi_elem_info table retained; only explicit C usage assigns message-to-table/instance roles.',
        'native_implementation': False}


def rmtfs_service(sources):
    schema = sources.read('rmtfs/qmi_rmtfs.qmi', 'linux-msm/rmtfs', RMTFS, 'qmi_rmtfs.qmi')
    generated = sources.read('rmtfs/qmi_rmtfs.c', 'linux-msm/rmtfs', RMTFS, 'qmi_rmtfs.c')
    sources.read('rmtfs/qmi_tlv.c', 'linux-msm/rmtfs', RMTFS, 'qmi_tlv.c')
    server = sources.read('rmtfs/rmtfs.c', 'linux-msm/rmtfs', RMTFS, 'rmtfs.c')
    server_values = constants(server)
    tables = c_tables(generated, 'rmtfs/qmi_rmtfs.c')
    records, messages = [], []
    for match in re.finditer(r'\b(struct|request|response|indication)\s+(\w+)\s*\{([^}]+)\}\s*(?:=\s*(0x[\da-fA-F]+|\d+))?\s*;', uncomment(schema)):
        kind, name, body, number = match.groups()
        record = {'kind': kind, 'name': name, 'source_line': schema.count('\n', 0, match.start()) + 1,
                  'declarations': [re.sub(r'\s+', ' ', line.strip()) for line in body.split(';') if line.strip()]}
        records.append(record)
        if kind == 'struct':
            continue
        table = 'rmtfs_' + name + '_ei'
        messages.append({'name': name, 'direction': kind, 'message_id': integer(number),
                         'roles': 'MPSS client -> AP server' if kind == 'request' else
                                  'AP server -> MPSS client' if kind == 'response' else
                                  'schema indication; not sent or handled in pinned rmtfs.c',
                         'source_definition': record, 'element_table': table,
                         'fields': ei_fields(table, tables, {})})
    if not messages:
        raise ValueError('No RMTFS messages extracted')
    return {'name': 'RMTFS', 'service_id': server_values['RMTFS_QMI_SERVICE'], 'server': 'AP', 'client': 'MPSS',
            'reference_instance': server_values['RMTFS_QMI_INSTANCE'],
            'reference_version': server_values['RMTFS_QMI_VERSION'],
            'runtime_instance': None, 'definitions': records, 'messages': messages,
            'element_tables': {name: {**record, 'fields': ei_fields(name, tables, {})}
                               for name, record in sorted(tables.items())},
            'coverage': 'All request/response/indication declarations and generated element tables; native server not implemented.',
            'native_implementation': False}


def remote_file_boundaries(sources):
    listing = json.loads(sources.read('libqmi-data-listing.json'))
    if listing['commit'] != LIBQMI or any('rfsa' in item['name'].lower() for item in listing['entries']):
        raise ValueError('RFSA absence evidence no longer matches pinned directory')
    tftp = sources.read('tqftpserv/tqftpserv.c', 'linux-msm/tqftpserv', TQFTP, 'tqftpserv.c')
    sources.read('tqftpserv/translate.c', 'linux-msm/tqftpserv', TQFTP, 'translate.c')
    sources.read('tqftpserv/README.md', 'linux-msm/tqftpserv', TQFTP, 'README.md')
    stock_path = ROOT / 'hardware/sm8650-modem-stock.json'
    stock_raw = stock_path.read_bytes()
    stock = json.loads(stock_raw)
    sources.records['sm8650-modem-stock.json'] = {
        'path': 'hardware/sm8650-modem-stock.json', 'bytes': len(stock_raw),
        'sha256': hashlib.sha256(stock_raw).hexdigest()}
    publish = list(c_calls(tftp, 'qrtr_publish'))
    literal = re.fullmatch(r'\s*fd\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*', publish[0][0]) if len(publish) == 1 else None
    if not literal:
        raise ValueError('Unresolved TFTP service publication')
    block = re.search(r'enum\s*\{\s*(OP_RRQ.*?)}\s*;', uncomment(tftp), re.S)
    if not block:
        raise ValueError('Missing TFTP opcode enum')
    opcodes, value = {}, 0
    for part in block[1].split(','):
        part = part.strip()
        if not part:
            continue
        if '=' in part:
            name, number = part.split('=', 1)
            value = integer(number.strip())
        else:
            name, value = part, value + 1
        opcodes[name.strip()] = value
    rfsa = {'name': 'RFSA', 'service_id': 28, 'schema_status': 'absent from pinned libqmi data directory',
            'messages': [], 'native_implementation': False,
            'absence_evidence': {'repository': 'linux-mobile-broadband/libqmi', 'commit': LIBQMI,
                'path': 'data/qmi-service-rfsa.json', 'fetch_result': 'GitHub NOT_FOUND HTTP 404',
                'directory_evidence': 'libqmi-data-listing.json'},
            'boundary': 'QMI service 0x1c is not the TFTP QRTR service 4096 and not RMTFS 0x0e.',
            'next_authoritative_sources': [
                'Extract matching stock /vendor/bin/tftp_server and linked QMI/RFSA objects; inspect actual service registration instead of assuming its name implies RFSA.',
                'Locate the corresponding vendor RFSA generated service-object headers/element tables or public authoritative RFSA IDL; decode only fields supported by those sources.'],
            'offline_observation': 'Matching factory rmt_storage/tftp_server and QMI libraries have now been extracted. RMTFS registers service14; TFTP publishes service4096; the scoped catalog of40 exported QMI service objects contains no RFSA0x1c. This does not prove RFSA is absent from all vendor or firmware components.',
            'stock_evidence': 'sm8650-modem-stock.json'}
    transport = {'name': 'Qualcomm TFTP over QRTR', 'protocol': 'RFC1350-derived, not QMI',
                 'service_id': integer(literal[1]), 'version': integer(literal[2]), 'instance': integer(literal[3]),
                 'roles': 'remote processor file client -> AP file server', 'opcodes': opcodes,
                 'opcode_byte_order': 'big/network; htons/ntohs in pinned tqftpserv.c',
                 'source': 'tqftpserv/tqftpserv.c', 'publication_line': publish[0][1],
                 'path_translation_source': 'tqftpserv/translate.c',
                 'firmware_paths_note': 'Actual requested paths depend on firmware; source examples do not establish giulia requests or permit arbitrary filesystem access.',
                 'native_implementation': False}
    transport['matching_stock_binary'] = stock['server_evidence']['tftp_server']
    transport['stock_evidence'] = 'sm8650-modem-stock.json'
    transport['reference_vs_stock'] = 'The public reference publishes version1/instance0. The matching factory binary initializes raw selector candidates1..10. Keep the two declarations distinct and discover actual running endpoints.'
    return rfsa, transport


def walk_fields(value):
    if isinstance(value, dict):
        if 'wire' in value:
            yield value
        for item in value.values():
            yield from walk_fields(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_fields(item)


def generate(source_root=CACHE):
    sources = Sources(source_root)
    # Pin the exact generator semantics used for defaults and common-ref
    # overrides. No code from these files is imported or executed.
    for name in ('Variable.py', 'VariableInteger.py', 'VariableString.py', 'VariableArray.py',
                 'VariableSequence.py', 'VariableStruct.py', 'Field.py', 'Container.py',
                 'Message.py', 'MessageList.py'):
        sources.libqmi('qmi-codegen/' + name, 'build-aux/qmi-codegen/' + name)
    services = libqmi_services(sources)
    lib_messages = sum(len(service['messages']) for service in services)
    lib_fields = sum(1 for service in services for _ in walk_fields(service['messages']))
    ipa = ipa_service(sources)
    rmtfs = rmtfs_service(sources)
    rfsa, tftp = remote_file_boundaries(sources)
    services.extend([rmtfs, ipa, rfsa])
    return {'schema': 1, 'board': 'giulia', 'system_build': '20H392',
            'generator': 'scripts/ios16_modem_protocol_map.py',
            'scope': 'Complete declarations in pinned source schemas; not the complete proprietary firmware ABI.',
            'implementation_level': 'schema-derived-detail', 'native_implementation': False,
            'generation_rules': [
                'Every libqmi Message produces request and response records; every Indication is retained separately, including vendor-qualified ID collisions.',
                'Common TLVs and prerequisites expand using the pinned Container.py/Field.py rules; nested layouts preserve all original properties.',
                'Numeric default byte order is little; explicit network/big values remain big. Byte-array/string size prefixes follow the pinned variable classes.',
                'C qmi_elem_info offsets and sizeof are decoded C layout, never wire offsets or implicit wire padding; optional-valid flags are not serialized.',
                'All IPA declared message-ID macros and all element tables are retained; missing explicit call-site links remain visible rather than guessed from names.',
                'Source schema coverage does not expand the implemented codec subset, native provider capabilities, service discovery or Apple ABI support.',
                'RFSA QMI, RMTFS QMI and Qualcomm TFTP over QRTR remain separate protocols.'],
            'sources': sources.records, 'services': services, 'non_qmi_transports': [tftp],
            'statistics': {'services_with_schema': len(services) - 1, 'services_without_schema': 1,
                           'libqmi_directional_messages': lib_messages, 'libqmi_nested_field_nodes': lib_fields,
                           'ipa_declared_messages': len(ipa['messages']), 'ipa_element_tables': len(ipa['element_tables']),
                           'ipa_messages_with_explicit_bindings': sum(bool(x['bindings']) for x in ipa['messages']),
                           'rmtfs_directional_messages': len(rmtfs['messages'])}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=CACHE)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--write', action='store_true', help='Write the reproducible schema map')
    mode.add_argument('--check', action='store_true', help='Compare against the saved map (default)')
    args = parser.parse_args()
    try:
        data = generate(args.source_root)
        raw = (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
        if args.write:
            args.output.write_bytes(raw)
        elif args.output.read_bytes() != raw:
            raise ValueError('Saved QMI service map differs from pinned source reconstruction')
    except (ValueError, KeyError, OSError, UnicodeError) as error:
        parser.exit(1, 'QMI schema mapping failed: ' + str(error) + '\n')
    print(json.dumps({'mode': 'write' if args.write else 'check', **data['statistics'],
                      'map_bytes': len(raw), 'map_sha256': hashlib.sha256(raw).hexdigest()}, indent=2))


if __name__ == '__main__':
    main()
