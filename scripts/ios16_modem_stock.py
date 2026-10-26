"""Reconstruct stock modem/IPA ELF and server evidence from local cached inputs.

Only hashes, ELF metadata, service tables and instruction facts enter JSON.
No firmware, executable, NV or subscriber bytes are exported by this script.
This checks structural provenance, not TrustZone signature authentication.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.cache/modem-stock'
MANIFEST = ROOT / 'hardware/sm8650-modem-stock.json'
MEMORY_MAP_PATH = 'Platforms/OnePlus/giuliaPkg/Library/MemoryMapLib/MemoryMapLib.c'
MEMORY_MAP_BASELINE_LF_SHA256 = 'ccee893f3569b1b16f4e609a11a27e08c572d69debeacf09b3ecfda14f6734a5'
UEFI_SOURCE_COMMIT = '6c6755012728c9f7de748228758bad94d1e9a660'
MEMORY_MAP_BASELINE_GIT_BLOB = 'f9023c8561c70d75dc128fa8af98211cc353dbae'
MODEM_MEMORY_RESERVATIONS = {
    'QLINK_Logging': (0x84800000, 0x00200000),
    'MPSS_DSM0': (0x86b00000, 0x04900000),
    'MPSS_DSM1': (0x8b400000, 0x00800000),
}


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def pin(path, relative):
    return {'path': relative, 'bytes': Path(path).stat().st_size, 'sha256': digest_file(path)}


class Elf:
    def __init__(self, path):
        self.path, self.data = Path(path), Path(path).read_bytes()
        if self.data[:4] != b'\x7fELF' or self.data[5] != 1:
            raise ValueError('Expected a little-endian ELF: ' + str(path))
        self.bits = self.data[4] * 32
        if self.bits not in (32, 64):
            raise ValueError('Unsupported ELF class')
        self.header = self.unpack('<16sHHIIIIIHHHHHH' if self.bits == 32 else '<16sHHIQQQIHHHHHH', 0)
        h = self.header
        if h[9] != (32 if self.bits == 32 else 56):
            raise ValueError('Unexpected program header size')
        self.programs = []
        for i in range(h[10]):
            values = self.unpack('<8I' if self.bits == 32 else '<II6Q', h[5] + i * h[9])
            if self.bits == 32:
                kind, offset, va, pa, filesz, memsz, flags, align = values
            else:
                kind, flags, offset, va, pa, filesz, memsz, align = values
            self.programs.append(dict(index=i, type=kind, offset=offset, vaddr=va, paddr=pa,
                                      filesz=filesz, memsz=memsz, flags=flags, align=align))
        self.sections, self.symbols, self.relocations = [], [], {}
        if self.bits == 64:
            if h[12] and h[11] != 64:
                raise ValueError('Unexpected section header size')
            for i in range(h[12]):
                self.sections.append(self.unpack('<II4QII2Q', h[6] + i * h[11]))
            for section in self.sections:
                if section[1] != 11:  # SHT_DYNSYM
                    continue
                strings = self.sections[section[6]]
                table = self.slice(strings[4], strings[5])
                if section[9] != 24:
                    raise ValueError('Unexpected dynamic symbol size')
                for offset in range(section[4], section[4] + section[5], 24):
                    name, info, other, index, value, size = self.unpack('<IBBHQQ', offset)
                    end = table.find(b'\0', name)
                    if end < 0:
                        raise ValueError('Unterminated symbol name')
                    self.symbols.append({'name': table[name:end].decode(), 'info': info,
                                         'section': index, 'value': value, 'size': size})
            for section in self.sections:
                if section[1] != 4:  # SHT_RELA
                    continue
                if section[9] != 24:
                    raise ValueError('Unexpected RELA size')
                for offset in range(section[4], section[4] + section[5], 24):
                    target, info, addend = self.unpack('<QQq', offset)
                    self.relocations[target] = {'type': info & 0xffffffff,
                                                'symbol': info >> 32, 'addend': addend}

    def slice(self, offset, size):
        if offset < 0 or size < 0 or offset > len(self.data) or size > len(self.data) - offset:
            raise ValueError('ELF file range out of bounds')
        return self.data[offset:offset + size]

    def unpack(self, fmt, offset):
        return struct.unpack(fmt, self.slice(offset, struct.calcsize(fmt)))

    def va(self, address, size):
        for p in self.programs:
            if p['type'] == 1 and p['vaddr'] <= address and address + size <= p['vaddr'] + p['filesz']:
                return self.slice(p['offset'] + address - p['vaddr'], size)
        raise ValueError('ELF virtual range is not backed by file: ' + hex(address))

    def pointer(self, address):
        relocation = self.relocations.get(address)
        if relocation:
            if relocation['type'] == 1027:  # R_AARCH64_RELATIVE
                return relocation['addend'], None
            if relocation['type'] in (257, 1025, 1026):
                symbol = self.symbols[relocation['symbol']]
                if symbol['section']:
                    return symbol['value'] + relocation['addend'], None
                return None, symbol['name']
            raise ValueError('Unsupported pointer relocation')
        return struct.unpack('<Q', self.va(address, 8))[0], None


def firmware_record(cache, name, extension):
    path = cache / 'firmware' / (name + extension)
    elf = Elf(path)
    if elf.bits != 32:
        raise ValueError('Pinned firmware changed ELF class')
    segments = []
    for p in elf.programs:
        item = dict(p)
        load = p['type'] == 1 and p['memsz'] > 0 and (p['flags'] & 0x07000000) != 0x02000000
        split = cache / 'firmware' / (name + '.b%02d' % p['index'])
        data = split.read_bytes() if split.is_file() else elf.slice(p['offset'], p['filesz']) if extension == '.elf' else None
        actual = None if data is None else len(data)
        matches = actual == p['filesz'] if p['filesz'] else actual in (None, 0)
        if load and (not matches or p['filesz'] > p['memsz']):
            raise ValueError('Missing/wrong-sized load segment: ' + name + '/' + str(p['index']))
        item.update(mdt_loadable=load, relocatable=bool(p['flags'] & 0x08000000),
                    split_path='.cache/modem-stock/firmware/' + split.name if split.is_file() else None,
                    source_bytes=actual, source_sha256=hashlib.sha256(data).hexdigest() if data is not None else None,
                    file_size_matches=matches, zero_fill_bytes=p['memsz'] - p['filesz'] if load else None)
        segments.append(item)
    loads = [p for p in segments if p['mdt_loadable']]
    metadata = None
    if extension == '.mdt':
        hashes = [p for p in segments if (p['flags'] & 0x07000000) == 0x02000000]
        if len(hashes) != 1:
            raise ValueError('Expected one signed MDT hash/metadata segment')
        header_part = cache / 'firmware' / (name + '.b00')
        hash_part = cache / 'firmware' / (name + '.b%02d' % hashes[0]['index'])
        if header_part.read_bytes() + hash_part.read_bytes() != elf.data:
            raise ValueError('MDT does not match header plus metadata split files')
        metadata = {'header_segment': 0, 'hash_segment': hashes[0]['index'],
                    'header_plus_hash_split_equals_mdt': True,
                    'secure_signature_validation': 'not performed'}
    return {'name': name, **pin(path, '.cache/modem-stock/firmware/' + path.name),
            'elf_class': elf.bits, 'byte_order': 'little', 'machine': elf.header[2], 'entry': elf.header[4],
            'program_header_count': len(segments), 'load_min': min(p['paddr'] for p in loads),
            'load_end': max(p['paddr'] + p['memsz'] for p in loads),
            'all_load_payloads_present_and_sized': True, 'metadata_consistency': metadata, 'segments': segments}


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def adr_target(elf, pc, register):
    word = struct.unpack('<I', elf.va(pc, 4))[0]
    if word & 0x9f000000 != 0x10000000 or word & 31 != register:
        raise ValueError('Expected pinned ADR instruction')
    immediate = ((word >> 29) & 3) | (((word >> 5) & 0x7ffff) << 2)
    return pc + signed(immediate, 21)


def movz_value(elf, pc, register):
    word = struct.unpack('<I', elf.va(pc, 4))[0]
    if word & 0x7f800000 != 0x52800000 or word & 31 != register:
        raise ValueError('Expected pinned MOVZ instruction')
    return ((word >> 5) & 0xffff) << (((word >> 21) & 3) * 16)


def service_object(elf, address, name):
    header = struct.unpack('<4I3H', elf.va(address, 22))
    if header[0] not in range(1, 7):
        raise ValueError('Unsupported stock QMI IDL object ABI')
    messages = []
    for direction, count, index in zip(('request', 'response', 'indication'), header[4:], range(3)):
        table, external = elf.pointer(address + 24 + 8 * index)
        if external or count > 4096 or (count and not table):
            raise ValueError('Invalid stock service message table')
        for i in range(count):
            message_id, type_index, maximum = struct.unpack('<HHH', elf.va(table + 6 * i, 6))
            messages.append({'direction': direction, 'message_id': message_id,
                             'type_table_selector': type_index, 'maximum_encoded_bytes': maximum})
    parent, external_parent = elf.pointer(address + 64)
    type_table, external_type = elf.pointer(address + 48)
    return {'symbol': name, 'virtual_address': address, 'library_version': header[0],
            'idl_major_version': header[1], 'service_id': header[2], 'maximum_message_bytes': header[3],
            'message_counts': dict(zip(('request', 'response', 'indication'), header[4:])),
            'idl_minor_version': struct.unpack('<I', elf.va(address + 56, 4))[0],
            'parent_address': parent, 'external_parent': external_parent,
            'type_table_address': type_table, 'external_type_table': external_type,
            'messages': messages}


def server_records(cache):
    rmt = Elf(cache / 'vendor/bin/rmt_storage')
    object_address = adr_target(rmt, 0x7cf8, 0)
    if object_address != 0xc610:
        raise ValueError('Stock RMTFS service object changed')
    branch = struct.unpack('<I', rmt.va(0x7d20, 4))[0]
    if branch & 0xfc000000 != 0x94000000 or 0x7d20 + signed(branch & 0x03ffffff, 26) * 4 != 0xaa30:
        raise ValueError('Stock RMTFS register call changed')
    relocation = rmt.relocations.get(0xb448)
    if not relocation or rmt.symbols[relocation['symbol']]['name'] != 'qmi_csi_register':
        raise ValueError('RMTFS register PLT relocation mismatch')
    encoder = Elf(cache / 'vendor/lib64/libqmi_encdec.so')
    layout = []
    for pc, opcode, scale, expected, fact in (
            (0x2100, 0xb9400000, 4, 8, 'service_id'),
            (0x213c, 0xb9400000, 4, 12, 'maximum service length'),
            (0x2214, 0x79400000, 2, 16, 'message count indexed by direction'),
            (0x2224, 0xf9400000, 8, 24, 'message table pointer indexed by direction')):
        word = struct.unpack('<I', encoder.va(pc, 4))[0]
        if word & 0xffc00000 != opcode or ((word >> 10) & 0xfff) * scale != expected:
            raise ValueError('QMI IDL service-object layout evidence changed')
        layout.append({'va': pc, 'field': fact, 'load_offset': expected})
    tftp = Elf(cache / 'vendor/bin/tftp_server')
    if movz_value(tftp, 0x1a958, 1) != 4096 or movz_value(tftp, 0x15338, 8) != 4:
        raise ValueError('Stock TFTP QRTR publication changed')
    catalog = []
    for library in ('libqmiservices.so', 'libqmiextservices.so'):
        elf = Elf(cache / 'vendor/lib64' / library)
        for symbol in elf.symbols:
            if symbol['section'] and symbol['size'] == 72 and 'qmi_idl_service_object' in symbol['name']:
                catalog.append({'binary': '.cache/modem-stock/vendor/lib64/' + library,
                                **service_object(elf, symbol['value'], symbol['name'])})
    rfsa = [item['symbol'] for item in catalog if item['service_id'] == 0x1c]
    return {'service_object_layout_evidence': {'binary': '.cache/modem-stock/vendor/lib64/libqmi_encdec.so',
                'loads': layout, 'message_table_entry_bytes': 6,
                'message_entry_layout': ['message_id:u16', 'type_table_selector:u16', 'maximum_encoded_bytes:u16']},
            'rmt_storage': {'binary': '.cache/modem-stock/vendor/bin/rmt_storage',
                'register_call_va': 0x7d20, 'service_argument_adr_va': 0x7cf8,
                'register_function': 'qmi_csi_register (PLT 0xaa30; relocation at 0xb448)',
                'service_object': service_object(rmt, object_address, 'embedded-rmtfs-service'),
                'roles': 'AP QMI server; remote modem requests storage'},
            'tftp_server': {'binary': '.cache/modem-stock/vendor/bin/tftp_server',
                'protocol': 'TFTP over QRTR; no QMI service object inferred', 'service_id': 4096,
                'evidence': [{'va': 0x1a958, 'fact': 'MOV W1,#4096 before address-builder call'},
                             {'va': 0x1a904, 'fact': 'entry initialization loop over indices 1..10; index0 skipped'},
                             {'va': 0x14e14, 'fact': 'service copied to sockaddr offset8; raw instance copied to offset12 at 0x14e20'},
                             {'va': 0x15338, 'fact': 'QRTR control NEW_SERVER command4, service/instance from sockaddr'},
                             {'va': 0x16dd4, 'fact': 'each enabled entry passes its address to the publish helper'}],
                'raw_instance_candidates': list(range(1, 11)),
                'instance_note': 'Stock uses raw selector values1..10; do not silently substitute the upstream tqftpserv single version1/instance0 publication.',
                'roles': 'AP file server; firmware-dependent path routing'},
            'stock_qmi_service_catalog': sorted(catalog, key=lambda x: (x['service_id'], x['symbol'])),
            'rfsa_catalog_check': {'objects_examined': len(catalog), 'service_id': 0x1c,
                                   'matching_symbols': rfsa, 'present_in_examined_catalog': bool(rfsa)},
            'rfsa_scope': ('RFSA service object found in this catalog.' if rfsa else
                          'No RFSA0x1c service object in these extracted QMI libraries or RMTFS executable.') +
                          ' This is a scoped binary inventory, not proof that no other vendor object or firmware uses RFSA.'}


UEFI_SOURCES = [
    '.cache/modem-uefi-base/Platforms/OnePlus/giuliaPkg/Library/MemoryMapLib/MemoryMapLib.c',
    '.cache/modem-uefi-base/Platforms/OnePlus/giuliaPkg/Library/MemoryMapLib/MemoryMapLib.inf',
    '.cache/modem-uefi-base/Platforms/OnePlus/giuliaPkg/giulia.dsc',
    '.cache/modem-uefi-base/Platforms/OnePlus/giuliaPkg/giulia.fdf',
    '.cache/modem-uefi-base/Silicon/Silicium/SiliciumPkg/Library/MemoryMapHelperLib/MemoryMapHelper.c',
    '.cache/modem-uefi-base/Silicon/Silicium/SiliciumPkg/Library/MemoryInitPeiLib/MemoryInitPei.c',
    '.cache/modem-uefi-base/Silicon/Silicium/SiliciumPkg/Drivers/RamManagerDxe/RamManager.c',
    '.cache/modem-uefi-base/Silicon/Qualcomm/QcomPkg/Library/RamManagerLib/RamManager.c',
    '.cache/modem-uefi-base/Silicon/Silicium/SiliciumPkg/Library/MemoryAllocationHelperLib/MemoryAllocationHelper.c']


def memory_source_text(raw):
    return raw.decode('utf-8').replace('\r\n', '\n')


def without_modem_memory_rows(text):
    return ''.join(line for line in text.splitlines(keepends=True)
                   if not any(re.match(r'\s*\{"' + re.escape(name) + r'",', line)
                              for name in MODEM_MEMORY_RESERVATIONS))


def qualified_memory_baseline(root=ROOT):
    """Recover the pinned original snapshot, including on clean workspaces.

    The independently pinned original LF hash prevents the overlay from
    redefining its own baseline. The fixed upstream commit does contain this
    board file; post-patch validation avoids relying on a mutable/shallow HEAD.
    """
    text = memory_source_text((Path(root) / 'uefi-overlay' / MEMORY_MAP_PATH).read_bytes())
    original = without_modem_memory_rows(text).encode('utf-8')
    if hashlib.sha256(original).hexdigest() != MEMORY_MAP_BASELINE_LF_SHA256:
        raise ValueError('Pinned giulia memory baseline cannot be reconstructed from the overlay')
    return original


def memory_map_rows(text):
    match = re.search(r'gMemoryDescriptor\[\]\s*=\s*\{(.*?)\n\};', text, re.S)
    if not match:
        raise ValueError('Missing giulia memory descriptor table')
    rows = []
    pattern = re.compile(r'\s*\{"([^"\n]+)",\s*(0x[\da-fA-F]+),\s*(0x[\da-fA-F]+),'
                         r'\s*(\w+),\s*(\w+),\s*(\w+),\s*(\w+),\s*(\w+)\},?\s*')
    for line in match[1].splitlines():
        if not line.strip() or line.lstrip().startswith('//'):
            continue
        parsed = pattern.fullmatch(line)
        if not parsed:
            raise ValueError('Unsupported memory descriptor syntax')
        name, address, size, hob, resource, attributes, memory, arm = parsed.groups()
        rows.append({'name': name, 'base': int(address, 16), 'bytes': int(size, 16),
                     'hob': hob, 'resource': resource, 'attributes': attributes,
                     'memory': memory, 'arm': arm})
    if len({row['name'] for row in rows}) != len(rows):
        raise ValueError('Duplicate memory descriptor name')
    ordered = sorted(rows, key=lambda row: row['base'])
    for row in ordered:
        if not row['bytes'] or row['base'] + row['bytes'] > 2**64:
            raise ValueError('Invalid memory descriptor range')
    for first, second in zip(ordered, ordered[1:]):
        if first['base'] + first['bytes'] > second['base']:
            raise ValueError('Overlapping memory descriptors: ' + first['name'] + '/' + second['name'])
    return rows


def validate_memory_overlay(root=ROOT, *, baseline=None, stock=None):
    """Pure source/layout check; no firmware/cache or device access required.

    baseline can be the qualified original bytes after board patches.
    stock may be the freshly reconstructed stock dictionary from this module.
    """
    root = Path(root)
    if baseline is None:
        baseline = qualified_memory_baseline(root)
    before = memory_source_text(baseline)
    if hashlib.sha256(before.encode()).hexdigest() != MEMORY_MAP_BASELINE_LF_SHA256:
        raise ValueError('Pinned giulia MemoryMapLib baseline drift; requalify the overlay before copying')
    overlay_path = root / 'uefi-overlay' / MEMORY_MAP_PATH
    raw = overlay_path.read_bytes()
    after = memory_source_text(raw)
    original = memory_map_rows(before)
    augmented = memory_map_rows(after)
    if without_modem_memory_rows(after) != before:
        raise ValueError('Modem memory overlay changed unrelated baseline source')
    if len(augmented) != len(original) + len(MODEM_MEMORY_RESERVATIONS):
        raise ValueError('Expected exactly three additional modem reservations')
    expected_attributes = {'hob': 'AddMem', 'resource': 'MEM_RES', 'attributes': 'UNCACHEABLE',
                           'memory': 'Reserv', 'arm': 'UNCACHED_UNBUFFERED_XN'}
    by_name = {row['name']: row for row in augmented}
    for name, (base, size) in MODEM_MEMORY_RESERVATIONS.items():
        row = by_name[name]
        if (row['base'], row['bytes']) != (base, size) or any(row[k] != v for k, v in expected_attributes.items()):
            raise ValueError('Wrong modem carveout range/attributes: ' + name)
    if stock is None:
        stock = json.loads((root / 'hardware/sm8650-modem-stock.json').read_text(encoding='utf-8'))
    firmware = {item['name']: item for item in stock['firmware']}
    required = [(name, base, base + size) for name, (base, size) in MODEM_MEMORY_RESERVATIONS.items()]
    required += [('MPSS_reserved', 0x8bc00000, 0x9b000000), ('DTB_reserved', 0x9b000000, 0x9b080000),
                 ('IPA_GSI_reserved', 0x9b090000, 0x9b09a000)]
    for name in ('modem', 'modem_dtb'):
        required.append((name + '_actual_load', firmware[name]['load_min'], firmware[name]['load_end']))
    ipa = firmware['ipa_fws']
    required.append(('IPA_actual_relocated_load', 0x9b090000,
                     0x9b090000 + ipa['load_end'] - ipa['load_min']))
    coverage = []
    for name, start, end in required:
        covering = [row for row in augmented if row['base'] <= start and end <= row['base'] + row['bytes']
                    and all(row[k] == v for k, v in expected_attributes.items())]
        if len(covering) != 1 or end <= start:
            raise ValueError('Stock/modem range not covered by one reserved descriptor: ' + name)
        coverage.append({'object': name, 'base': start, 'end': end, 'descriptor': covering[0]['name']})
    return {'baseline_lf_sha256': MEMORY_MAP_BASELINE_LF_SHA256,
            'baseline_commit': UEFI_SOURCE_COMMIT, 'baseline_git_blob': MEMORY_MAP_BASELINE_GIT_BLOB,
            'overlay': pin(overlay_path, 'uefi-overlay/' + MEMORY_MAP_PATH),
            'baseline_descriptors': len(original), 'overlay_descriptors': len(augmented),
            'added_reservations': [by_name[name] for name in MODEM_MEMORY_RESERVATIONS],
            'all_other_source_text_unchanged': True, 'overlap_count': 0, 'coverage': coverage,
            'scope': 'PEI HOB/MMU descriptor reservation before RamManager gap filling; not SCM permission or live ownership proof'}


def preflight_memory_overlay(uefi_root, root=ROOT, *, stock=None):
    """Run after board patches, before overlay copy; exact reruns are allowed."""
    root, uefi_root = Path(root), Path(uefi_root)
    baseline = qualified_memory_baseline(root)
    report = validate_memory_overlay(root, baseline=baseline, stock=stock)
    target = memory_source_text((uefi_root / MEMORY_MAP_PATH).read_bytes())
    overlay = memory_source_text((root / 'uefi-overlay' / MEMORY_MAP_PATH).read_bytes())
    if target not in (memory_source_text(baseline), overlay):
        raise ValueError('Prepared board MemoryMapLib drift before overlay; refusing to overwrite unrelated changes')
    report['precopy_state'] = 'already-qualified-overlay' if target == overlay else 'qualified-baseline'
    return report


def verify_prepared_memory_map(uefi_root, root=ROOT, *, baseline=None, stock=None):
    """Verify the actual staged source and LibraryClass/INF/FDF wiring."""
    uefi_root, root = Path(uefi_root), Path(root)
    if baseline is None:
        baseline = qualified_memory_baseline(root)
    report = validate_memory_overlay(root, baseline=baseline, stock=stock)
    if memory_source_text((uefi_root / MEMORY_MAP_PATH).read_bytes()) != memory_source_text(
            (root / 'uefi-overlay' / MEMORY_MAP_PATH).read_bytes()):
        raise ValueError('Prepared UEFI did not receive the qualified modem memory overlay')
    board = uefi_root / 'Platforms/OnePlus/giuliaPkg'
    dsc = (board / 'giulia.dsc').read_text(encoding='utf-8')
    bindings = re.findall(r'(?m)^\s*MemoryMapLib\|([^\r\n]+)', dsc)
    if bindings != ['giuliaPkg/Library/MemoryMapLib/MemoryMapLib.inf']:
        raise ValueError('Prepared giulia DSC MemoryMapLib binding changed')
    inf = (board / 'Library/MemoryMapLib/MemoryMapLib.inf').read_text(encoding='utf-8')
    section = re.search(r'(?ms)^\[Sources\]\s*\n(.*?)(?=^\[|\Z)', inf)
    if not section or [line.strip() for line in section[1].splitlines() if line.strip() and not line.lstrip().startswith('#')] != ['MemoryMapLib.c']:
        raise ValueError('Prepared MemoryMapLib INF no longer compiles the qualified C file')
    fdf = (board / 'giulia.fdf').read_text(encoding='utf-8')
    if not re.search(r'(?m)^\s*INF\s+SiliciumPkg/Drivers/RamManagerDxe/RamManagerDxe.inf\s*$', fdf):
        raise ValueError('Prepared giulia RamManagerDxe path changed')
    report['prepared_dsc_inf_fdf_wiring_verified'] = True
    return report


def generate(root=ROOT, cache=CACHE):
    root, cache = Path(root), Path(cache)
    firmware = [firmware_record(cache, name, extension) for name, extension in
                [('modem', '.mdt'), ('modem_dtb', '.mdt'), ('ipa_fws', '.mdt'), ('fw_ipa_gsi_5.5_h', '.elf')]]
    if firmware[0]['load_min'] != 0x8bc00000 or firmware[0]['load_end'] != 0x99e00000:
        raise ValueError('Qualified modem load span changed')
    if firmware[1]['load_min'] != 0x9b000000 or firmware[1]['load_end'] != 0x9b003d3c:
        raise ValueError('Qualified modem DTB load span changed')
    equal = len(firmware[2]['segments']) == len(firmware[3]['segments']) and all(
        a['source_sha256'] == b['source_sha256'] for a, b in zip(firmware[2]['segments'], firmware[3]['segments']))
    if not equal:
        raise ValueError('IPA split payloads differ from GSI ELF')
    vendor = [pin(path, '.cache/modem-stock/' + path.relative_to(cache).as_posix())
              for path in sorted((cache / 'vendor').rglob('*')) if path.is_file()]
    source_pins = [{**pin(root / name, name), 'repository': 'Project-Silicium/Mu-Silicium',
                    'commit': UEFI_SOURCE_COMMIT,
                    'upstream_path': name.removeprefix('.cache/modem-uefi-base/')}
                   for name in UEFI_SOURCES]
    result = {'schema': 1, 'board': 'giulia', 'system_build': '20H392',
            'stock_release': 'PKG110domestic_11_16.0.3.500CN01_2026010902170644',
            'source_images': [
                {'path': '.cache/wifi-stock-16.0.3.500/vendor.raw', 'bytes': 829018112,
                 'sha256': '6e9c1c8cc6674f8f1a3ce1a5fc128394e3397ec5b84837cdac5eededf83884d0'},
                {'path': '.cache/wifi-stock-16.0.3.500/odm.raw', 'bytes': 1891565568,
                 'sha256': 'b0330357e971ce2288bb896633a16d3aef03add8759690c4e80a44f65084fdf1'},
                {'package_relative_path': 'IMAGES/NON-HLOS.bin', 'bytes': 313634816,
                 'sha256': '1964e1f89b887b3c1d5e2bfef5583d50f61f903cb14106a648341963d5b072f0'}],
            'extraction': {'vendor_tool': 'dump.erofs --cat --path=PATH vendor.raw',
                           'firmware_tool': 'mcopy -i NON-HLOS.bin ::/image/NAME .cache/modem-stock/firmware/'},
            'firmware': firmware, 'ipa_split_and_gsi_elf_payloads_identical': equal,
            'vendor_files': vendor, 'server_evidence': server_records(cache), 'uefi_sources': source_pins,
            'uefi_memory_reasoning': {
                'static_pil_reserved': [0x8bc00000, 0xa3180000],
                'static_descriptor_missing': [[0x84800000, 0x84a00000], [0x86b00000, 0x8b400000], [0x8b400000, 0x8bc00000]],
                'helper_semantics': 'MemoryMapHelper only searches descriptors by name or exact address; it does not reserve or filter RAM.',
                'pei_semantics': 'MemoryInitPei creates resource/allocation HOBs only for explicit memory descriptors.',
                'dxe_semantics': 'giulia.fdf includes RamManagerDxe. It imports Base/AvailableLength from EFI_RAMPARTITION, subtracts existing EFI descriptors and adds uncovered gaps as EfiConventionalMemory.',
                'baseline_conditional_result': 'Without the overlay, if firmware RAM partitions cover DSM/QLINK and no earlier EFI descriptor excludes them, RamManager attempts to add those gaps as conventional RAM.',
                'overlay_fix': 'The repository now adds exactly three AddMem/MEM_RES/UNCACHEABLE/Reserv/UNCACHED_UNBUFFERED_XN descriptors before RamManager. prepare verifies the qualified post-board-patch baseline or exact previous overlay, copies the overlay, and verifies DSC/INF/FDF wiring.',
                'not_proven': 'Source reservation does not establish SCM permission, secure-domain ownership, an observed final EFI/ADT map or absence of prior firmware writes.',
                'next_input': 'Verify the built artifact contains the qualified overlay and retain final memory/ADT ownership evidence before assigning DSM.'},
            'qualification': {'firmware_structure_verified': True, 'hardware_boot_verified': False,
                              'secure_signature_authentication_performed': False,
                              'native_service_execution_performed': False,
                              'note': 'Factory ROM bytes remain private local cache; this artifact contains only provenance and structural metadata.'}}
    result['uefi_memory_overlay'] = validate_memory_overlay(root, stock=result)
    result['uefi_preparation_pipeline'] = pin(root / 'scripts/prepare.py', 'scripts/prepare.py')
    return result


def verify_images(data, root=ROOT, package_root=None):
    count = 0
    for source in data['source_images']:
        if 'path' in source:
            path = Path(root) / source['path']
        elif package_root:
            path = Path(package_root) / source['package_relative_path']
        else:
            continue
        if path.stat().st_size != source['bytes'] or digest_file(path) != source['sha256']:
            raise ValueError('Stock image hash mismatch: ' + str(path))
        count += 1
    return count


def verify(manifest=MANIFEST, root=ROOT, cache=CACHE, *, images=False, package_root=None):
    """Unified-gate entry: compare reconstructed metadata, optionally raw images.

    manifest may be the saved JSON path or an already loaded dictionary.
    Firmware/executable inputs stay in cache and are never returned as bytes.
    """
    expected = manifest if isinstance(manifest, dict) else json.loads(Path(manifest).read_text(encoding='utf-8'))
    actual = generate(root, cache)
    if actual != expected:
        raise ValueError('Saved stock metadata differs from local ELF/source reconstruction')
    return {'firmware_images': len(actual['firmware']), 'vendor_elf_files': len(actual['vendor_files']),
            'stock_service_objects': len(actual['server_evidence']['stock_qmi_service_catalog']),
            'rfsa_in_examined_catalog': actual['server_evidence']['rfsa_catalog_check']['present_in_examined_catalog'],
            'uefi_reserved_descriptors': actual['uefi_memory_overlay']['overlay_descriptors'],
            'uefi_modem_reservations_added': len(actual['uefi_memory_overlay']['added_reservations']),
            'source_images_rehashed': verify_images(actual, root, package_root) if images else 0,
            'hardware_boot_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=CACHE)
    parser.add_argument('--output', type=Path, default=MANIFEST)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--verify-images', action='store_true', help='Also hash large original/raw filesystem inputs')
    parser.add_argument('--package-root', type=Path, help='Directory containing the original IMAGES directory')
    args = parser.parse_args()
    try:
        data = generate(ROOT, args.cache)
        raw = (json.dumps(data, indent=2) + '\n').encode()
        if args.write:
            args.output.write_bytes(raw)
        elif args.output.read_bytes() != raw:
            raise ValueError('Saved stock metadata differs from local ELF/source reconstruction')
        images = verify_images(data, ROOT, args.package_root) if args.verify_images else 0
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, 'Stock modem verification failed: ' + str(error) + '\n')
    print(json.dumps({'firmware_images': len(data['firmware']), 'vendor_elf_files': len(data['vendor_files']),
                      'stock_service_objects': len(data['server_evidence']['stock_qmi_service_catalog']),
                      'source_images_rehashed': images, 'hardware_boot_verified': False}, indent=2))


if __name__ == '__main__':
    main()
