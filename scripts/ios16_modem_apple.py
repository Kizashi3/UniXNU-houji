"""20H392 Apple cellular evidence and cross-artifact activation contract.

`extract` reads the original HFS image and dyld cache, never changes them. It
records real ARM64 wrapper instructions instead of assigning new selectors.
`verify` checks the committed evidence against the original cache bytes.
This module is also imported by root preparation and the unified modem suite.
"""
import argparse
import bisect
import hashlib
import json
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import xml.etree.ElementTree as ET
import zipfile

REPO = Path(__file__).resolve().parents[1]
ABI = REPO / 'hardware/ios16-modem-abi.json'
LAUNCHD = '/System/Library/xpc/launchd.plist'
COMM = '/System/Library/Frameworks/CoreTelephony.framework/Support/CommCenter'
JOB_PREFIX = '/System/Library/LaunchDaemons/'
CELLULAR_JOB = JOB_PREFIX + 'com.apple.CommCenter.plist'
NONCELLULAR_JOB = JOB_PREFIX + 'com.apple.CommCenter-noncellular.plist'
HELPER_JOBS = tuple(JOB_PREFIX + n + '.plist' for n in
                    ('com.apple.CommCenterRootHelper', 'com.apple.CommCenterMobileHelper'))
IMAGES = ('libTelephonyBasebandDynamic.dylib', 'libIOABP.dylib',
          'libIOACIPC.dylib', 'libIOACIPCBB.dylib', 'libPCITransport.dylib',
          'libBasebandCapabilities.dylib', 'libTelephonyUtilDynamic.dylib',
          'libBasebandCommandDrivers.dylib', 'libCommCenterCommandDrivers.dylib',
          'libCommCenterMCommandDrivers.dylib')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def load_abi(path=ABI):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if (value.get('schema') != 1 or value.get('system_build') != '20H392'
            or not value.get('methods') or not value.get('source_files')):
        raise ValueError('Missing or unsupported Apple cellular ABI evidence')
    return value


def verify_job_pair(jobs):
    """Both jobs deliberately share a Label; the DT predicates are inverse."""
    cellular, noncellular = jobs[CELLULAR_JOB], jobs[NONCELLULAR_JOB]
    if (cellular.get('Label') != 'com.apple.CommCenter'
            or noncellular.get('Label') != cellular['Label']
            or cellular.get('_LimitLoadToDeviceTree') != 'baseband'
            or noncellular.get('_LimitLoadFromDeviceTree') != 'baseband'
            or cellular.get('ProgramArguments') != [COMM]
            or noncellular.get('ProgramArguments') != [COMM]):
        raise ValueError('20H392 mutually exclusive CommCenter launch predicates changed')
    for name in HELPER_JOBS:
        if jobs[name].get('Label') != Path(name).stem:
            raise ValueError('20H392 CommCenter helper identity changed')


def require_managed_contract(runtime, adt, root_report=None, *, abi_path=ABI):
    """Reject labels/booleans offered as substitutes for linked ABI coverage.

    `adt` must be the actual serialized ADT, not a report saying it has a node.
    `provider_contract` is generated from the provider's linked dispatch table;
    the packaging caller must supply its report and kernel hash together.
    """
    from ios16_platform import read_nodes
    abi = load_abi(abi_path)
    if (runtime.get('schema') != 1 or runtime.get('board') != 'giulia'
            or runtime.get('system_build') != '20H392'
            or runtime.get('runtime_abi') != 1 or runtime.get('mode') != 'managed'):
        raise ValueError('Managed cellular requires the giulia/20H392/runtime ABI 1 contract')
    if not all(runtime.get(k) is True for k in
               ('platform_broker_included', 'native_provider_included')):
        raise ValueError('Managed cellular requires the native provider and shared resource broker')
    digest = sha(Path(abi_path).read_bytes())
    if runtime.get('apple_abi_sha256') != digest:
        raise ValueError('Runtime refers to different Apple cellular ABI evidence')
    if abi.get('unresolved_contracts'):
        raise ValueError('Managed cellular ABI has unresolved contracts: ' +
                         ', '.join(x['id'] for x in abi['unresolved_contracts']))
    provider = runtime.get('provider_contract', {})
    if (provider.get('system_build') != '20H392'
            or provider.get('apple_abi_sha256') != digest
            or not re.fullmatch(r'[0-9a-f]{64}', str(runtime.get('kernel_sha256', '')))
            or provider.get('kernel_sha256') != runtime.get('kernel_sha256')):
        raise ValueError('Provider dispatch evidence is not bound to the packaged kernel and ABI')
    expected = {m['id']: m['contract'] for m in abi['methods'] if m.get('required_for_managed')}
    if not expected or provider.get('methods') != expected:
        raise ValueError('Linked provider method contracts do not match recovered Apple ABI')
    nodes = read_nodes(bytes(adt))
    basebands = [(p, v) for p, v in nodes.items() if v.get('name') == b'baseband\0']
    if len(basebands) != 1:
        raise ValueError('Managed cellular requires exactly one actual baseband ADT node')
    path, props = basebands[0]
    personality = provider.get('personality', {})
    if (not personality.get('IOClass') or personality.get('IOProviderClass') != 'IOPlatformDevice'
            or not personality.get('IONameMatch')
            or personality['IONameMatch'].encode() not in props.get('compatible', b'').split(b'\0')
            or provider.get('adt_path') != path):
        raise ValueError('Linked cellular personality does not match the actual baseband ADT node')
    if root_report is not None:
        policy = root_report.get('cellular_policy', {})
        if (policy.get('mode') != 'managed' or policy.get('apple_abi_sha256') != digest
                or policy.get('retained_jobs') != [CELLULAR_JOB, *HELPER_JOBS]
                or policy.get('disabled_jobs') != [NONCELLULAR_JOB]
                or policy.get('adt_sha256') != sha(bytes(adt))
                or policy.get('kernel_sha256') != runtime['kernel_sha256']):
            raise ValueError('Root cellular policy does not match kernel, ADT and ABI')
    return {'apple_abi_sha256': digest, 'adt_sha256': sha(bytes(adt)),
            'kernel_sha256': runtime['kernel_sha256'], 'baseband_path': path,
            'required_method_count': len(expected)}


class DyldCache:
    """Bounded reads via each subcache's real mapping table (no giant A2S map)."""
    def __init__(self, path):
        self.path = Path(path)
        self.maps = []
        for p in sorted(self.path.parent.glob(self.path.name + '*')):
            if not p.is_file() or p.suffix in ('.symbols', '.a2s'):
                continue
            with p.open('rb') as f:
                head = f.read(32)
                if not head.startswith(b'dyld_v'):
                    continue
                off, count = struct.unpack_from('<II', head, 16)
                if count > 64 or off + 32 * count > p.stat().st_size:
                    raise ValueError('Invalid dyld mapping table: ' + str(p))
                f.seek(off)
                for _ in range(count):
                    va, size, fileoff, _, _ = struct.unpack('<QQQII', f.read(32))
                    self.maps.append((va, size, fileoff, p))

    def locate(self, va, size):
        for start, length, offset, path in self.maps:
            if start <= va and va + size <= start + length:
                return path, offset + va - start
        raise ValueError(f'VA range is not in a cache mapping: {va:#x}+{size:#x}')

    def read(self, va, size):
        path, offset = self.locate(va, size)
        with path.open('rb') as f:
            f.seek(offset)
            data = f.read(size)
        if len(data) != size:
            raise ValueError('Truncated cache range')
        return data


def symbol_table(text):
    return {int(a, 16): n for a, n in re.findall(
        r'^(0x[0-9a-f]+):\s+\(__TEXT,__text\)[^\t]*\t([^\t\r\n]+)', text, re.M)}


def macho_segments(data, offset=0):
    if struct.unpack_from('<I', data, offset)[0] != 0xfeedfacf:
        raise ValueError('Expected ARM64 Mach-O')
    count = struct.unpack_from('<I', data, offset + 16)[0]
    at, end = offset + 32, offset + 32 + struct.unpack_from('<I', data, offset + 20)[0]
    result = []
    for _ in range(count):
        cmd, size = struct.unpack_from('<II', data, at)
        if size < 8 or at + size > end:
            raise ValueError('Invalid Mach-O load command')
        if cmd == 25:
            name = data[at + 8:at + 24].split(b'\0')[0].decode()
            va, vsize, off, fsize = struct.unpack_from('<QQQQ', data, at + 24)
            result.append({'name': name, 'address': va, 'virtual_bytes': vsize,
                           'offset': off, 'bytes': fsize})
        at += size
    return result


def macho_import_calls(data, requested):
    """Locate real BL call sites via Mach-O indirect symbols and function starts."""
    segments = macho_segments(data)
    text_base = next(s['address'] for s in segments if s['name'] == '__TEXT')
    at, sections, symtab, indirect, starts = 32, [], None, None, []
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<II', data, at)
        if cmd == 25:
            for i in range(struct.unpack_from('<I', data, at + 64)[0]):
                sec = struct.unpack_from('<16s16sQQIIIIIIII', data, at + 72 + 80 * i)
                sections.append({'name': sec[0].split(b'\0')[0].decode(), 'address': sec[2],
                                 'bytes': sec[3], 'offset': sec[4], 'reserved1': sec[9],
                                 'reserved2': sec[10]})
        elif cmd == 2:
            symtab = struct.unpack_from('<IIII', data, at + 8)
        elif cmd == 11:
            indirect = struct.unpack_from('<II', data, at + 56)
        elif cmd == 0x26:
            off, length = struct.unpack_from('<II', data, at + 8)
            value, shift, address = 0, 0, text_base
            for byte in data[off:off + length]:
                value |= (byte & 127) << shift
                if byte & 128:
                    shift += 7
                else:
                    if value == 0:
                        break
                    address += value
                    starts.append(address)
                    value, shift = 0, 0
        at += size
    if symtab is None or indirect is None or not starts:
        raise ValueError('Missing Mach-O import/function metadata')
    stub = next(s for s in sections if s['name'] == '__stubs')
    code = next(s for s in sections if s['name'] == '__text')
    syms, _, strings, _ = symtab
    targets = {}
    for index in range(stub['bytes'] // stub['reserved2']):
        symbol_index = struct.unpack_from('<I', data, indirect[0] + 4 * (stub['reserved1'] + index))[0]
        if symbol_index & 0xc0000000:
            continue
        string_offset = struct.unpack_from('<I', data, syms + 16 * symbol_index)[0]
        name = data[strings + string_offset:].split(b'\0', 1)[0].decode()
        if name in requested:
            targets[stub['address'] + index * stub['reserved2']] = name
    results = []
    for off in range(code['offset'], code['offset'] + code['bytes'], 4):
        word = struct.unpack_from('<I', data, off)[0]
        if word & 0xfc000000 != 0x94000000:
            continue
        address = code['address'] + off - code['offset']
        imm = word & 0x03ffffff
        if imm & 0x02000000:
            imm -= 0x04000000
        target = address + 4 * imm
        if target not in targets:
            continue
        index = bisect.bisect_right(starts, address) - 1
        start = starts[index]
        end = starts[index + 1] if index + 1 < len(starts) else code['address'] + code['bytes']
        function_offset = code['offset'] + start - code['address']
        results.append({'import': targets[target], 'stub_address': hex(target),
                        'call_address': hex(address), 'call_bytes': data[off:off + 4].hex(),
                        'function_address': hex(start), 'function_bytes': end - start,
                        'function_file_offset': function_offset,
                        'function_sha256': sha(data[function_offset:function_offset + end - start])})
    return results


def extract_kernel(archive, ipsw, output):
    """Recover original provider topology and dispatch contracts from 20H392.

    The kernel is prelinked, not MH_FILESET. Parse its real segment mappings and
    XML IDREF graph instead of treating each kext's file offsets as standalone.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    member = 'kernelcache.release.iphone10b'
    with zipfile.ZipFile(archive) as z:
        manifest = plistlib.loads(z.read('BuildManifest.plist'))
        if manifest.get('ProductBuildVersion') != '20H392':
            raise ValueError('Kernel ABI extraction requires exact 20H392')
        packed = z.read(member)
    source = output / member
    source.write_bytes(packed)
    dest = output / 'kernelcache.raw'
    subprocess.run([str(ipsw), 'kernel', 'dec', str(source), '--output', str(dest)], check=True,
                   capture_output=True)
    raw = dest / (member + '.decompressed')
    data = raw.read_bytes()
    segments = macho_segments(data)
    def offset(va):
        for seg in segments:
            if seg['address'] <= va < seg['address'] + seg['bytes']:
                return seg['offset'] + va - seg['address']
        raise ValueError('Kernel VA not in file-backed mapping')
    def address(off):
        for seg in segments:
            if seg['offset'] <= off < seg['offset'] + seg['bytes']:
                return seg['address'] + off - seg['offset']
        raise ValueError('Kernel offset not in file-backed mapping')
    info = next(s for s in segments if s['name'] == '__PRELINK_INFO')
    xml = data[info['offset']:info['offset'] + info['bytes']].split(b'\0')[0]
    tree = ET.fromstring(xml)
    ids = {n.attrib['ID']: n for n in tree.iter() if 'ID' in n.attrib}
    def value(n):
        if 'IDREF' in n.attrib:
            return value(ids[n.attrib['IDREF']])
        if n.tag == 'dict':
            children = list(n)
            return {k.text: value(v) for k, v in zip(children[::2], children[1::2])}
        if n.tag == 'array':
            return [value(v) for v in n]
        if n.tag == 'integer':
            return int(n.text, 0)
        if n.tag in ('true', 'false'):
            return n.tag == 'true'
        return n.text or ''
    info_dict = value(list(tree)[0] if tree.tag == 'plist' else tree)
    kexts = [k for k in info_dict['_PrelinkInfoDictionary']
             if 'Baseband' in k.get('CFBundleIdentifier', '')]
    report = {'system_build': '20H392', 'ipsw_member': member,
              'packed_sha256': sha(packed), 'kernel_sha256': sha(data),
              'kernel_bytes': len(data), 'raw_file': str(raw.resolve()),
              'prelink_info_sha256': sha(xml), 'kexts': kexts, 'dispatch_tables': []}
    specs = [('com.apple.driver.AppleBasebandD20', 'AppleBasebandUserClient', 44,
              [(1, 0, 0, 0), (1, 0, 0, 0), (1, 0, 0, 0), (0, 0, 1, 0)]),
             ('com.apple.driver.AppleBasebandPCI', 'AppleBasebandPCIUserClient', 13,
              [(1, 0, 0, 0), (0, 0, 0, 0), (2, 0xffffffff, 0, 0), (2, 0, 0, 0xffffffff)]),
             ('com.apple.driver.AppleBasebandPCI', 'AppleBasebandPCIControlUserClient', 4,
              [(1, 0, 0, 0), (0, 0, 0, 0), (3, 0, 0, 0xffffffff), (4, 0, 0, 0)])]
    # Exact-version externalMethod instruction ranges: selector bounds, table
    # address materialization and 24-byte indexing, independently of wrappers.
    dispatch_selection = {'AppleBasebandUserClient': (0xfffffff006bb8dd4, 28),
                          'AppleBasebandPCIUserClient': (0xfffffff0062d6bac, 36),
                          'AppleBasebandPCIControlUserClient': (0xfffffff0062d1704, 36)}
    for bundle, client, count, first_entries in specs:
        kext = next(k for k in kexts if k['CFBundleIdentifier'] == bundle)
        ksegments = macho_segments(data, offset(kext['_PrelinkExecutableLoadAddr']))
        text = next(s for s in ksegments if s['name'] == '__TEXT_EXEC')
        pattern = b''.join(b'.{8}' + re.escape(struct.pack('<IIII', *entry)) for entry in first_entries)
        matches = [m.start() for m in re.finditer(pattern, data, re.S)
                   if text['address'] <= struct.unpack_from('<Q', data, m.start())[0]
                   < text['address'] + text['virtual_bytes']]
        if len(matches) != 1:
            raise ValueError('Ambiguous original dispatch table: ' + client)
        at = matches[0]
        entries = []
        for selector in range(count):
            fn, scalar_in, struct_in, scalar_out, struct_out = struct.unpack_from('<QIIII', data, at + selector * 24)
            if not text['address'] <= fn < text['address'] + text['virtual_bytes']:
                raise ValueError('Dispatch function escaped its kext')
            entries.append({'selector': selector, 'function_address': hex(fn),
                            'scalar_input_count': scalar_in, 'struct_input_bytes': struct_in,
                            'scalar_output_count': scalar_out, 'struct_output_bytes': struct_out})
        bound_va, bound_size = dispatch_selection[client]
        bound_off = offset(bound_va)
        report['dispatch_tables'].append({'bundle': bundle, 'userclient': client,
            'source': {'address': hex(address(at)), 'offset': at, 'bytes': count * 24,
                       'sha256': sha(data[at:at + count * 24])},
            'dispatch_selection_source': {'address': hex(bound_va), 'offset': bound_off,
                'bytes': bound_size, 'sha256': sha(data[bound_off:bound_off + bound_size])},
            'entries': entries})
    (output / 'kernel-abi.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def extract(root_image, cache_path, ipsw, output):
    """Emit reproducible bounded assembly/source evidence for the unified audit."""
    import capstone
    import pytsk3
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    cache = DyldCache(cache_path)
    fs = pytsk3.FS_Info(pytsk3.Img_Info(str(root_image)))
    def read(path):
        f = fs.open(path)
        if f.info.meta.size > 64 * 1024**2:
            raise ValueError('Unexpected HFS source size: ' + path)
        return f.read_random(0, f.info.meta.size)
    version = plistlib.loads(read('/System/Library/CoreServices/SystemVersion.plist'))
    if version.get('ProductBuildVersion') != '20H392':
        raise ValueError('Apple ABI extraction requires exact 20H392')
    jobs = plistlib.loads(read(LAUNCHD))['LaunchDaemons']
    verify_job_pair(jobs)
    source = {p: {'sha256': sha(read(p)), 'bytes': len(read(p))}
              for p in (COMM, LAUNCHD, '/System/Library/CoreServices/SystemVersion.plist')}
    report = {'schema': 1, 'system_build': '20H392', 'root_sources': source,
              'launch_jobs': {p: jobs[p] for p in (CELLULAR_JOB, NONCELLULAR_JOB, *HELPER_JOBS)},
              'images': {}, 'functions': []}
    report['network_calls'] = macho_import_calls(read(COMM), {
        '_IPConfigurationServiceCreate', '_IPConfigurationServiceCopyInformation',
        '_IPConfigurationServiceGetNotificationKey', '_IPConfigurationServiceRefreshConfiguration',
        '_if_nametoindex'})
    decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    for name in IMAGES:
        args = [str(ipsw), 'dyld', 'macho', str(cache_path), name, '--symbols', '--strings', '--loads']
        proc = subprocess.run(args, capture_output=True, check=True)
        text = proc.stdout.decode('utf-8')
        (output / (name + '.txt')).write_text(text, encoding='utf-8')
        symbols = symbol_table(text)
        addresses = sorted(symbols)
        report['images'][name] = {'symbol_count': len(symbols), 'inventory_sha256': sha(proc.stdout)}
        for i, address in enumerate(addresses[:-1]):
            symbol = symbols[address]
            if not (re.match(r'_+TelephonyBaseband', symbol) or
                    re.match(r'_+ZN\d+IO(?:ABP|ACIPC)', symbol) or
                    symbol in ('__TelephonyRadiosDetermineRadio', '_TelephonyRadiosGetRadioVendor',
                        '__ZN21CommandDriversFactory6createERKNSt3__110shared_ptrI8RegistryEE',
                        '__ZN20CommandDriverFactory21create_default_globalEv',
                        '__ZN22MCommandDriversFactory30createDataFactoryCommandDriverEN8dispatch5queueE',
                        '__ZN27QMIDataFactoryCommandDriver6createENSt3__110shared_ptrIK8RegistryEEN8dispatch5queueE',
                        '__ZN9abpKernel26pciTransportInterfaceToABPE21PCITransportInterface') or
                    (name == 'libPCITransport.dylib' and 'PDPListener' in symbol)):
                continue
            size = addresses[i + 1] - address
            if size > 16384:
                raise ValueError('Unexpected wrapper extent: ' + symbol)
            data = cache.read(address, size)
            file, offset = cache.locate(address, size)
            instructions = [{'address': hex(v.address), 'bytes': bytes(v.bytes).hex(),
                             'instruction': v.mnemonic + ' ' + v.op_str}
                            for v in decoder.disasm(data, address)]
            report['functions'].append({'image': name, 'symbol': symbol,
                'address': hex(address), 'bytes': size, 'sha256': sha(data),
                'cache_file': file.name, 'cache_offset': offset, 'instructions': instructions})
    (output / 'extracted.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def extract_qmi_semantics(cache_path, inventory_dir):
    """Recover bounded Apple QMI bootstrap/factory evidence from actual code.

    This does not infer native service versions or vendor TLV equivalence from
    symbols. A missing GetVersionInfo in this bounded closure is not a claim
    that no other component can ever request it.
    """
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    from capstone.arm64 import ARM64_OP_IMM
    cache = DyldCache(cache_path)
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    decoder.detail = True
    symbols, images = {}, {}
    inventories = ('libATCommandStudioDynamic.dylib', 'libQMIParserDynamic.dylib',
                   'libBasebandCapabilities.dylib', 'libBasebandCommandDriversQMI.dylib',
                   'libCommCenterMCommandDrivers.dylib', 'libTelephonyUtilDynamic.dylib')
    for image in inventories:
        path = Path(inventory_dir) / (image + '.txt')
        rows = symbol_table(path.read_text(encoding='utf-8-sig'))
        symbols.update(rows)
        images.update({address: image for address in rows})
    addresses, veneers = sorted(symbols), {}

    def resolve(address):
        if address in symbols:
            return address, symbols[address]
        if address not in veneers:
            ins = list(decoder.disasm(cache.read(address, 12), address))
            if (len(ins) == 3 and ins[0].mnemonic == 'adrp'
                    and ins[1].mnemonic == 'add' and ins[2].mnemonic == 'br'):
                target = ins[0].operands[1].imm + ins[1].operands[2].imm
                veneers[address] = (target, symbols.get(target, hex(target)))
            else:
                veneers[address] = (address, hex(address))
        return veneers[address]

    sources, constructors, factories, control_members = [], [], [], []
    extra = {0x1ae1d8974, 0x1ae1d8b54, 0x1ae241674, 0x1ae241f3c}
    for address in addresses:
        name = symbols[address]
        control = bool(re.match(r'_+ZN10QMIControl', name))
        factory = bool(re.match(r'_+ZN(?:K)?(?:22MCommandDriversFactory|23QMICommandDriverFactory)', name)
                       and 'create' in name)
        if not (control or factory or address in extra):
            continue
        end = addresses[bisect.bisect_right(addresses, address)]
        size = end - address
        if size > 16384:
            raise ValueError('Unbounded QMI function extent: ' + name)
        data = cache.read(address, size)
        path, offset = cache.locate(address, size)
        sources.append({'id': 'qmi_' + hex(address), 'symbol': name,
                        'image': images[address], 'address': hex(address), 'bytes': size,
                        'cache_file': path.name, 'cache_offset': offset, 'sha256': sha(data)})
        if control:
            control_members.append({'symbol': name, 'address': hex(address)})
        instructions = list(decoder.disasm(data, address))
        calls = []
        for index, ins in enumerate(instructions):
            if ins.mnemonic not in ('bl', 'b') or ins.operands[0].type != ARM64_OP_IMM:
                continue
            target, target_name = resolve(ins.operands[0].imm)
            call = {'address': hex(ins.address), 'bytes': bytes(ins.bytes).hex(),
                    'target': hex(target), 'target_symbol': target_name,
                    'branch_target': hex(ins.operands[0].imm)}
            if factory and ('create' in target_name or 'isMav' in target_name):
                calls.append(call)
            if 'MutableMessageBaseC2Et' not in target_name:
                continue
            before = instructions[index - 1] if index else None
            record = {'function': name, 'function_address': hex(address), 'call': call,
                      'scope': 'CTL bootstrap' if control else 'compiled baseband request path'}
            if (before and before.mnemonic == 'mov' and before.op_str.startswith('w1, #')
                    and before.operands[1].type == ARM64_OP_IMM):
                record['message_id'] = before.operands[1].imm
                record['constant_instruction'] = {'address': hex(before.address),
                    'bytes': bytes(before.bytes).hex(), 'assembly': before.mnemonic + ' ' + before.op_str}
            else:
                record['message_id'] = None
                record['reason'] = 'not an immediately preceding constant assignment; not guessed'
            constructors.append(record)
        if factory:
            factories.append({'symbol': name, 'address': hex(address), 'direct_create_calls': calls})
    for address, (target, target_name) in sorted(veneers.items()):
        if address == target:
            continue
        path, offset = cache.locate(address, 12)
        sources.append({'id': 'qmi_branch_veneer_' + hex(address), 'address': hex(address),
                        'bytes': 12, 'cache_file': path.name, 'cache_offset': offset,
                        'sha256': sha(cache.read(address, 12)), 'target': hex(target),
                        'target_symbol': target_name})
    for address, count in ((0x1ae1d898c, 5), (0x1ae1d8b6c, 4)):
        ins = list(decoder.disasm(cache.read(address, 12), address))
        expected = [('sub', 'w8, w0, #9'), ('cmp', 'w8, #' + str(count)), ('cset', 'w8, lo')]
        if [(i.mnemonic, i.op_str) for i in ins] != expected:
            raise ValueError('20H392 D22 radio capability arithmetic changed')
    ids = sorted({row['message_id'] for row in constructors
                  if row['scope'] == 'CTL bootstrap' and row['message_id'] is not None})
    return {'schema': 1, 'system_build': '20H392', 'dyld_sources': sources,
            'control_members': control_members, 'message_constructors': constructors,
            'factory_dispatch': factories, 'observed_ctl_message_ids': ids,
            'version_negotiation': {
                'get_version_info_0x21_observed_in_bounded_control_constructors': 0x21 in ids,
                'scope': 'all symbol-bounded QMIControl member bodies in fixed libATCommandStudioDynamic; direct constructors only',
                'global_absence_claim': False,
                'native_qrtr_service_version_equivalence_proved': False},
            'D22_bootstrap': {
                'radio_enum': 5, 'supportsDataService': False, 'isMav20Plus': False,
                'supportsDataService_formula': 'unsigned(radio-9)<5 at0x1ae1d898c..8994',
                'isMav20Plus_formula': 'unsigned(radio-9)<4 at0x1ae1d8b6c..8b74',
                'set_data_format_0x26_required': True,
                'set_power_mode_0x2a_initial_profile': 0,
                'sync_0x27_timeout_ms': 2000,
                'client_and_power_operation_timeout_ms': 25000,
                'radio_factory_selected': 'radio::QMICommandDriver, not QMICommandDriverM20'},
            'compatibility_boundary': {
                'factory_inventory_is_not_proof_all_methods_execute_on_boot': True,
                'native_vendor_tlv_equivalence_proved': False,
                'concrete_vendor_request': 'bsp::abm::GetFactoryCalibrationStatus constructs0xe018 at0x1ae241f60',
                'remaining_work': 'implement evidenced CTL bootstrap/power semantics and establish selected Apple service/vendor response equivalence to native SM8650; do not advertise invented service versions'}}


def verify_sources(cache_path, abi_path=ABI):
    abi = load_abi(abi_path)
    cache = DyldCache(cache_path)
    checked = 0
    for name, source in abi['source_files'].items():
        path = Path(cache_path).parent / name
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if path.stat().st_size != source['bytes'] or digest != source['sha256']:
            raise ValueError('Apple ABI source file changed: ' + name)
    for item in abi['methods']:
        source = item['source']
        data = cache.read(int(source['address'], 16), source['bytes'])
        path, offset = cache.locate(int(source['address'], 16), source['bytes'])
        if (sha(data) != source['sha256'] or path.name != source['cache_file']
                or offset != source['cache_offset']):
            raise ValueError('Apple ABI source changed: ' + item['id'])
        for ins in source.get('selector_instructions', []):
            if cache.read(int(ins['address'], 16), 4).hex() != ins['bytes']:
                raise ValueError('Apple selector instruction changed: ' + item['id'])
        checked += 1
    for source in abi.get('supporting_functions', []):
        if sha(cache.read(int(source['address'], 16), source['bytes'])) != source['sha256']:
            raise ValueError('Apple supporting function changed: ' + source['symbol'])
    for item in abi.get('data_evidence', []):
        if sha(cache.read(int(item['address'], 16), item['bytes'])) != item['sha256']:
            raise ValueError('Apple ABI data changed: ' + item['id'])
    semantic_sources = (abi.get('semantic_contracts', {}).get('dyld_sources', []) +
                        abi.get('pdp_contracts', {}).get('dyld_sources', []) +
                        abi.get('subscription_contract', {}).get('dyld_sources', []) +
                        abi.get('qmi_semantic_contract', {}).get('dyld_sources', []))
    for source in semantic_sources:
        if sha(cache.read(int(source['address'], 16), source['bytes'])) != source['sha256']:
            raise ValueError('Apple semantic contract source changed: ' + source['id'])
    for row in abi.get('qmi_semantic_contract', {}).get('message_constructors', []):
        for instruction in (row['call'], row.get('constant_instruction')):
            if instruction and cache.read(int(instruction['address'], 16), 4).hex() != instruction['bytes']:
                raise ValueError('Apple QMI constructor instruction changed: ' + row['function'])
    for event in abi.get('pdp_contracts', {}).get('error_notifications', []):
        value, pointer = struct.unpack('<QQ', cache.read(0x20d423320 + event['index'] * 16, 16))
        if value != int(event['message'], 16):
            raise ValueError('Apple PDP consumer error ID mismatch')
        pointer &= 0xfffffffff  # The recorded arm64 cache's slide-chain value bits.
        name = cache.read(pointer, len(event['name']) + 1)
        if pointer != int(event['name_address'], 16) or name != event['name'].encode() + b'\0':
            raise ValueError('Apple PDP consumer error-name mapping mismatch')
    subscription = abi.get('subscription_contract', {})
    if subscription:
        frontend = subscription['apple_frontend']
        branch = frontend['configuration_branch']
        displacement = cache.read(int(branch['jump_table'], 16) + branch['index'], 1)[0]
        target = int(branch['base'], 16) + displacement * 4
        word = struct.unpack('<I', cache.read(target, 4))[0]
        if (displacement != branch['byte_value'] or target != int(branch['target'], 16)
                or word & 0xffe0001f != 0x52800013
                or (word >> 5) & 0xffff != frontend['hardware_configuration']):
            raise ValueError('D22 hardware-configuration selection differs from original branch')
        candidates = list(struct.unpack('<II', cache.read(0x1f03c9df4, 8)))
        if (candidates != frontend['candidate_slot_ids']
                or cache.read(0x1f0320bf0, 12).hex() != '1f040071e0179f1ac0035fd6'
                or cache.read(0x1f0370838, 4).hex() != 'c0035fd6'):
            raise ValueError('D22 slot filter or override implementation changed')
        config = frontend['hardware_configuration']
        multi = int(((config - 12) & 255) < 45) & ((0x1f021e078e07 >> ((config - 12) & 63)) & 1)
        accepted = candidates if multi else [s for s in candidates if s == 1]
        if (bool(multi) != frontend['capability_value'] or accepted != frontend['accepted_slot_ids']
                or len(accepted) != frontend['expected_sim_count']):
            raise ValueError('D22 exposed SIM count does not follow its original capability/filter')
    header = REPO / 'ios16/modem/giulia_modem_apple_abi.h'
    if header.read_text(encoding='utf-8') != render_abi_header(abi):
        raise ValueError('Apple ABI C boundary drifted from recovered kernel dispatch')
    return {'system_build': '20H392', 'apple_abi_sha256': sha(Path(abi_path).read_bytes()),
            'source_method_count': checked, 'unresolved_contracts': abi.get('unresolved_contracts', []),
            'source_evidence_verified': True, 'provider_functionality_verified': False}


def verify_kernel_sources(kernel_path, abi_path=ABI):
    abi = load_abi(abi_path)
    evidence = abi['kernel_evidence']
    data = Path(kernel_path).read_bytes()
    if sha(data) != evidence['kernel_sha256'] or len(data) != evidence['kernel_bytes']:
        raise ValueError('Original 20H392 kernel source changed')
    for table in evidence['dispatch_tables']:
        s = table['source']
        if sha(data[s['offset']:s['offset'] + s['bytes']]) != s['sha256']:
            raise ValueError('Original kernel dispatch table changed')
        bound = table['dispatch_selection_source']
        if sha(data[bound['offset']:bound['offset'] + bound['bytes']]) != bound['sha256']:
            raise ValueError('Original kernel selector bounds/indexing changed')
        for index, entry in enumerate(table['entries']):
            raw = struct.unpack_from('<QIIII', data, s['offset'] + index * 24)
            expected = (int(entry['function_address'], 16), entry['scalar_input_count'],
                        entry['struct_input_bytes'], entry['scalar_output_count'], entry['struct_output_bytes'])
            if raw != expected or entry['selector'] != index:
                raise ValueError('Decoded kernel dispatch entry does not match source bytes')
    semantic_sources = (abi.get('semantic_contracts', {}).get('kernel_sources', []) +
                        abi.get('pdp_contracts', {}).get('kernel_sources', []))
    for source in semantic_sources:
        off, size = source['offset'], source['bytes']
        if sha(data[off:off + size]) != source['sha256']:
            raise ValueError('Apple kernel semantic evidence changed: ' + source['id'])
    pdp = abi.get('pdp_contracts', {})
    if pdp:
        table = next(s for s in pdp['kernel_sources'] if s['id'] == 'pdp_error_table')
        for event in pdp['error_notifications']:
            if struct.unpack_from('<I', data, table['offset'] + event['index'] * 16)[0] != int(event['message'], 16):
                raise ValueError('Apple kernel PDP producer ID differs from consumer table')
    return {'kernel_sha256': evidence['kernel_sha256'],
            'dispatch_entry_count': sum(len(t['entries']) for t in evidence['dispatch_tables'])}


def verify_root_sources(root_image, abi_path=ABI):
    import pytsk3
    abi = load_abi(abi_path)
    fs = pytsk3.FS_Info(pytsk3.Img_Info(str(root_image)))
    files = {}
    for name, source in abi['root_sources'].items():
        f = fs.open(name)
        if f.info.meta.size != source['bytes']:
            raise ValueError('Original Apple root source size changed: ' + name)
        data = f.read_random(0, f.info.meta.size)
        if sha(data) != source['sha256']:
            raise ValueError('Original Apple root source hash changed: ' + name)
        files[name] = data
    verify_job_pair(plistlib.loads(files[LAUNCHD])['LaunchDaemons'])
    requested = {e['import'] for e in abi['network_calls']}
    if macho_import_calls(files[COMM], requested) != abi['network_calls']:
        raise ValueError('CommCenter network call chain differs from recovered evidence')
    pdp = abi.get('pdp_contracts', {})
    for source in pdp.get('commcenter_sources', []):
        off, size = source['offset'], source['bytes']
        if sha(files[COMM][off:off + size]) != source['sha256']:
            raise ValueError('CommCenter PDP lifecycle source changed: ' + source['id'])
    if pdp:
        observed = {v['call_address']: v for v in macho_import_calls(
            files[COMM], {v['import'] for v in pdp['source_import_calls']})}
        for expected in pdp['source_import_calls']:
            if observed.get(expected['call_address']) != expected:
                raise ValueError('CommCenter PDP notification call site changed')
    return {'root_source_count': len(files), 'network_call_count': len(abi['network_calls']),
            'launch_predicates_verified': True}


def render_abi_header(abi):
    """C call-shape boundary generated only from the original kernel tables."""
    tables = abi['kernel_evidence']['dispatch_tables']
    text = ['/* Generated from exact 20H392 kernel dispatch tables. Shape validation',
            ' * does not execute an operation, authorize access, or imply radio success.',
            ' * Source kernel SHA256: ' + abi['kernel_evidence']['kernel_sha256'] + ' */',
            '#ifndef GIULIA_MODEM_APPLE_ABI_H', '#define GIULIA_MODEM_APPLE_ABI_H',
            '#include <stdint.h>', '',
            '#define GIULIA_MODEM_APPLE_ABI_VERSION 1u',
            '#define GIULIA_MODEM_APPLE_ABI_VARIABLE 0xffffffffu',
            'enum giulia_modem_apple_client {',
            '    GIULIA_MODEM_APPLE_BASEBAND = 0,',
            '    GIULIA_MODEM_APPLE_ABP = 1,',
            '    GIULIA_MODEM_APPLE_ABP_CONTROL = 2', '};',
            'enum giulia_modem_apple_shape_result {',
            '    GIULIA_MODEM_APPLE_SHAPE_VALID = 0,',
            '    GIULIA_MODEM_APPLE_SHAPE_UNKNOWN_CLIENT = -1,',
            '    GIULIA_MODEM_APPLE_SHAPE_UNKNOWN_SELECTOR = -2,',
            '    GIULIA_MODEM_APPLE_SHAPE_BAD_COUNTS = -3', '};',
            'struct giulia_modem_apple_dispatch_shape {',
            '    uint32_t scalar_input_count, struct_input_bytes;',
            '    uint32_t scalar_output_count, struct_output_bytes;', '};', '']
    names = ['baseband', 'abp', 'abp_control']
    for table, name in zip(tables, names):
        text += ['/* ' + table['userclient'] + '; table ' + table['source']['address'] +
                 '; SHA256 ' + table['source']['sha256'] + ' */',
                 'static const struct giulia_modem_apple_dispatch_shape',
                 'giulia_modem_apple_' + name + '_shapes[] = {']
        for e in table['entries']:
            values = [e[k] for k in ('scalar_input_count', 'struct_input_bytes',
                                    'scalar_output_count', 'struct_output_bytes')]
            text.append('    {' + ', '.join(f'{v}u' for v in values) +
                        '}, /* selector ' + str(e['selector']) + ' */')
        text += ['};', '']
    text += ['static inline const struct giulia_modem_apple_dispatch_shape *',
             'giulia_modem_apple_abi_lookup(uint32_t client, uint32_t selector)', '{',
             '    switch (client) {']
    for i, (table, name) in enumerate(zip(tables, names)):
        text += [f'    case {i}u: return selector < {len(table["entries"])}u ?',
                 f'        &giulia_modem_apple_{name}_shapes[selector] : 0;']
    text += ['    default: return 0;', '    }', '}', '',
             'static inline int giulia_modem_apple_abi_validate(uint32_t client, uint32_t selector,',
             '    uint32_t scalar_in, uint64_t struct_in, uint32_t scalar_out, uint64_t struct_out)',
             '{', '    const struct giulia_modem_apple_dispatch_shape *s;',
             '    if (client > GIULIA_MODEM_APPLE_ABP_CONTROL)',
             '        return GIULIA_MODEM_APPLE_SHAPE_UNKNOWN_CLIENT;',
             '    s = giulia_modem_apple_abi_lookup(client, selector);',
             '    if (!s) return GIULIA_MODEM_APPLE_SHAPE_UNKNOWN_SELECTOR;',
             '    if (scalar_in != s->scalar_input_count || scalar_out != s->scalar_output_count ||',
             '        (s->struct_input_bytes != GIULIA_MODEM_APPLE_ABI_VARIABLE &&',
             '         struct_in != s->struct_input_bytes) ||',
             '        (s->struct_output_bytes != GIULIA_MODEM_APPLE_ABI_VARIABLE &&',
             '         struct_out != s->struct_output_bytes))',
             '        return GIULIA_MODEM_APPLE_SHAPE_BAD_COUNTS;',
             '    return GIULIA_MODEM_APPLE_SHAPE_VALID;', '}', '#endif', '']
    return '\n'.join(text)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('extract', 'extract-kernel', 'extract-qmi', 'verify', 'header'))
    p.add_argument('--cache', type=Path, default=REPO / 'out/ios16/dyld-symbols/dyld_shared_cache_arm64')
    p.add_argument('--root-image', type=Path, default=REPO / 'out/ios16/userdata/giulia-ios16-userdata.img')
    p.add_argument('--ipsw', type=Path, default=REPO / '.cache/ipsw-tool/ipsw.exe')
    p.add_argument('--archive', type=Path, default=REPO /
                   'out/ios16/firmware/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw')
    p.add_argument('--out', type=Path, default=REPO / 'out/ios16/modem-apple-abi')
    p.add_argument('--kernel', type=Path, default=REPO /
                   'out/ios16/modem-apple-abi/kernelcache.raw/kernelcache.release.iphone10b.decompressed')
    a = p.parse_args()
    if a.action == 'header':
        header = REPO / 'ios16/modem/giulia_modem_apple_abi.h'
        header.write_text(render_abi_header(load_abi()), encoding='utf-8')
        result = {'header': str(header)}
    elif a.action == 'extract-qmi':
        evidence = extract_qmi_semantics(a.cache, a.out)
        abi = load_abi()
        abi['qmi_semantic_contract'] = evidence
        for issue in abi.get('unresolved_contracts', []):
            if issue['id'] == 'apple_qmi_service_version_and_vendor_semantics':
                issue['trace'] = ('20H392 QMIControl direct constructors, D22 capability branches, '
                                  'M/QMI factory dispatch and BSP calibration0xe018 now pinned in qmi_semantic_contract')
                issue['reason'] = ('The bounded QMIControl closure constructs CTL0x22/23/26/27/29/2a/32, '
                                   'not an observed0x21 version query. D22 executes0x26 and initial power0x2a. '
                                   'Native equivalence for those control semantics and Apple vendor request0xe018 '
                                   'is not established; no service-version list or vendor reply may be invented.')
        ABI.write_text(json.dumps(abi, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        result = {'dyld_sources': len(evidence['dyld_sources']),
                  'message_constructors': len(evidence['message_constructors']),
                  'factory_dispatch': len(evidence['factory_dispatch']),
                  'ctl_ids': evidence['observed_ctl_message_ids'], 'unresolved_preserved': True}
    elif a.action == 'extract-kernel':
        evidence = extract_kernel(a.archive, a.ipsw, a.out)
        result = {'dispatch_tables': len(evidence['dispatch_tables']), 'output': str(a.out)}
    elif a.action == 'extract':
        evidence = extract(a.root_image, a.cache, a.ipsw, a.out)
        result = {'functions': len(evidence['functions']), 'output': str(a.out)}
    else:
        result = verify_sources(a.cache)
        result['kernel'] = verify_kernel_sources(a.kernel)
        result['root'] = verify_root_sources(a.root_image)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
