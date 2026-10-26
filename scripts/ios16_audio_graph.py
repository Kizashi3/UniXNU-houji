"""Inspect pinned stock ACDB and export graph data through official AudioReach AML.

No DSP, I2C or device access. Exported blobs are baseline graph definitions, not
proof that a graph runs or that per-speaker runtime calibration is available.
Source layout/API: AudioReach/audioreach-graphservices commit
76d04ffb30caa1fe609b94f9f6081210cb962fc1, acdb/{api/acdb.h,src/acdb_command.c,
src/acdb_data_proc.c,inc/acdb_types.h}. Proprietary data stays in local output.
"""
import argparse
import ctypes as c
import hashlib
import json
from pathlib import Path
import struct

STOCK_SHA256 = 'b3bc49d6a085e578199e8f13c019d2ef0b32e71644044f4af8eb41386ef5e072'
SOURCE_COMMIT = '76d04ffb30caa1fe609b94f9f6081210cb962fc1'
SIXTH_SHA256 = '1df91039581e3e0493043baf713c92582838f08818d928d60cd68c348057c54c'
MAX_BYTES = 64*1024*1024
MAX_ENTRIES = 100000
MAX_KEYS = 64


def words(data, offset, count):
    if offset < 0 or count < 0 or count > MAX_ENTRIES or offset+count*4 > len(data):
        raise ValueError('ACDB record exceeds bounds')
    return struct.unpack_from('<'+str(count)+'I', data, offset)


def subgraphs(data, count):
    result = []
    offset = 0
    if count > MAX_ENTRIES:
        raise ValueError('Too many ACDB subgraphs')
    for _ in range(count):
        ident, num_dst = words(data, offset, 2)
        offset += 8
        targets = words(data, offset, num_dst)
        offset += 4*num_dst
        result.append({'id': ident, 'destinations': list(targets)})
    if offset != len(data) or len({r['id'] for r in result}) != count:
        raise ValueError('Invalid ACDB subgraph list')
    return result


def key_vectors(data, count):
    result = []
    offset = 0
    if count > MAX_ENTRIES:
        raise ValueError('Too many ACDB key vectors')
    for _ in range(count):
        num, = words(data, offset, 1)
        if num > MAX_KEYS:
            raise ValueError('Too many keys in ACDB vector')
        row = words(data, offset+4, 2*num)
        result.append(tuple(zip(row[::2], row[1::2])))
        offset += 4+8*num
    if offset != len(data):
        raise ValueError('Invalid ACDB key vector list size')
    return result


def parse_acdb(data):
    if not isinstance(data, bytes) or not 12 <= len(data) <= MAX_BYTES:
        raise ValueError('Invalid ACDB size/type')
    if data[:8] != b'ACDB\0\0\0\0' or words(data, 8, 1)[0] != len(data)-12:
        raise ValueError('Invalid ACDB header/compression/size')
    chunks = {}
    offset = 12
    while offset < len(data):
        if len(data)-offset < 8:
            raise ValueError('Truncated ACDB chunk')
        name, size = struct.unpack_from('<4sI', data, offset)
        offset += 8
        if size > len(data)-offset or name in chunks:
            raise ValueError('Invalid ACDB chunk size or duplicate')
        chunks[name] = data[offset:offset+size]
        offset += size
    if not all(name in chunks for name in (b'GKVT', b'GKVL', b'POOL')):
        raise ValueError('Missing ACDB graph chunks')
    kt, vt, pool = (chunks[name] for name in (b'GKVT', b'GKVL', b'POOL'))
    graphs = []
    seen = set()
    offset = 4
    tables, = words(kt, 0, 1)
    if tables > MAX_KEYS:
        raise ValueError('Too many ACDB key tables')
    for _ in range(tables):
        nk, ne = words(kt, offset, 2)
        offset += 8
        if not 1 <= nk <= MAX_KEYS or ne > MAX_ENTRIES:
            raise ValueError('Invalid ACDB key table counts')
        for _ in range(ne):
            row = words(kt, offset, nk+1)
            offset += 4*(nk+1)
            if tuple(sorted(set(row[:-1]))) != row[:-1]:
                raise ValueError('Unsorted or duplicate ACDB keys')
            vo = row[-1]
            vk, vn = words(vt, vo, 2)
            vo += 8
            if vk != nk or vn > MAX_ENTRIES or len(graphs)+vn > MAX_ENTRIES:
                raise ValueError('Invalid ACDB value table counts')
            for _ in range(vn):
                values = words(vt, vo, nk+2)
                vo += 4*(nk+2)
                key = tuple(zip(row[:-1], values[:-2]))
                if key in seen:
                    raise ValueError('Duplicate ACDB graph')
                seen.add(key)
                size, count = words(pool, values[-2], 2)
                po = values[-2]+8
                if size < 4 or size-4 > len(pool)-po:
                    raise ValueError('Invalid ACDB graph pool size')
                graph = {'key_vector': key, 'subgraphs': subgraphs(pool[po:po+size-4], count),
                         'properties_pool_offset': values[-1]}
                if values[-1] >= len(pool):
                    raise ValueError('ACDB properties offset exceeds pool')
                graphs.append(graph)
    if offset != len(kt):
        raise ValueError('ACDB key table trailing data')
    aliases = {}
    if b'GALS' in chunks:
        alias = chunks[b'GALS']
        offset = 4
        tables, = words(alias, 0, 1)
        if tables > MAX_KEYS:
            raise ValueError('Too many ACDB alias tables')
        for _ in range(tables):
            nk, ne = words(alias, offset, 2)
            offset += 8
            if not 1 <= nk <= MAX_KEYS or ne > MAX_ENTRIES:
                raise ValueError('Invalid ACDB alias counts')
            for _ in range(ne):
                row = words(alias, offset, nk*2+1)
                offset += (nk*2+1)*4
                key = tuple(zip(row[:-1:2], row[1:-1:2]))
                size, length = words(pool, row[-1], 2)
                po = row[-1]+8
                if length > 256 or size < 4 or length != size-4 or length > len(pool)-po:
                    raise ValueError('Invalid ACDB alias length')
                raw = pool[po:po+length]
                if not raw.endswith(b'\0') or key in aliases:
                    raise ValueError('Invalid or duplicate ACDB alias')
                aliases[key] = raw.rstrip(b'\0').decode('utf8')
        if offset != len(alias):
            raise ValueError('ACDB alias trailing data')
    for graph in graphs:
        graph['alias'] = aliases.get(graph['key_vector'])
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
            'chunk_count': len(chunks), 'graph_count': len(graphs), 'alias_count': len(aliases),
            'graphs': graphs}


def verify_acdb(path, sha256=STOCK_SHA256):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > MAX_BYTES:
        raise ValueError('Invalid ACDB input file')
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES+1)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError('ACDB SHA256 does not match trusted pin')
    return parse_acdb(data)


class Packed(c.Structure):
    _layout_ = 'ms'
    _pack_ = 1


class File(Packed):
    _fields_ = [('length', c.c_uint32), ('name', c.c_char*256)]


class Files(Packed):
    _fields_ = [('count', c.c_uint32), ('files', File*2)]


class KV(Packed):
    _fields_ = [('key', c.c_uint32), ('value', c.c_uint32)]


class Vector(Packed):
    _fields_ = [('count', c.c_uint32), ('pairs', c.POINTER(KV))]


class UintList(c.Structure):  # The upstream AcdbUintList is NOT packed.
    _fields_ = [('count', c.c_uint32), ('ids', c.POINTER(c.c_uint32))]


class Blob(Packed):
    _fields_ = [('size', c.c_uint32), ('data', c.c_void_p)]


class ListResponse(Packed):
    _fields_ = [('count', c.c_uint32), ('size', c.c_uint32), ('data', c.c_void_p)]


class SubgraphRequest(Packed):
    _fields_ = [('count', c.c_uint32), ('ids', c.POINTER(c.c_uint32)), ('vector', Vector)]


class SubgraphResponse(Packed):
    _fields_ = [('driver', ListResponse), ('spf', Blob)]


class ConnectionsRequest(Packed):
    _fields_ = [('count', c.c_uint32), ('data', c.c_void_p)]


class CalRequest(Packed):
    _fields_ = [('count', c.c_uint32), ('ids', c.POINTER(c.c_uint32)),
                ('prior', Vector), ('new', Vector)]


def vector(pairs):
    array = (KV*len(pairs))(*(KV(*pair) for pair in pairs))
    return Vector(len(pairs), array)


class AcdbError(ValueError):
    def __init__(self, command, status):
        super().__init__(f'ACDB command {command} failed: {status}')
        self.command, self.status = command, status


class AcdbHost:
    """Read-only native AML calls. Only load a locally built, trusted library."""
    def __init__(self, library, firmware):
        # Native AML handles binary pointer arithmetic; only hand it the pinned
        # stock input that the bounded Python parser has already inspected.
        verify_acdb(firmware)
        self.lib = c.CDLL(str(Path(library).resolve()))
        self.lib.acdb_init.argtypes = [c.POINTER(Files), c.POINTER(File)]
        self.lib.acdb_init.restype = c.c_int32
        self.lib.acdb_deinit.argtypes = []
        self.lib.acdb_deinit.restype = c.c_int32
        self.lib.acdb_ioctl.argtypes = [c.c_uint32, c.c_void_p, c.c_uint32, c.c_void_p, c.c_uint32]
        self.lib.acdb_ioctl.restype = c.c_int32
        path = str(Path(firmware).resolve()).encode()
        if len(path) >= 256:
            raise ValueError('ACDB path exceeds native API capacity')
        files = Files()
        files.count = 1
        files.files[0] = File(len(path), path)
        status = self.lib.acdb_init(c.byref(files), None)
        if status:
            raise ValueError(f'ACDB initialization failed: {status}')

    def close(self):
        self.lib.acdb_deinit()

    def call(self, command, request, response):
        status = self.lib.acdb_ioctl(0xacdb0000|command, c.byref(request), c.sizeof(request),
                                    c.byref(response), c.sizeof(response))
        if status:
            raise AcdbError(command, status)

    @staticmethod
    def allocate(blob):
        if blob.size > MAX_BYTES:
            raise ValueError('ACDB response exceeds maximum size')
        buffer = c.create_string_buffer(max(blob.size, 1))
        blob.data = c.cast(buffer, c.c_void_p)
        return buffer

    def get_vectors(self, command, request):
        rsp = ListResponse()
        self.call(command, request, rsp)
        if not rsp.size:
            return []
        buffer = self.allocate(rsp)
        capacity = len(buffer)
        self.call(command, request, rsp)
        if rsp.size > capacity:
            raise ValueError('ACDB response size grew unexpectedly')
        return key_vectors(buffer.raw[:rsp.size], rsp.count)

    def graph(self, pairs):
        req, rsp = vector(pairs), ListResponse()
        self.call(1, req, rsp)
        buffer = self.allocate(rsp)
        self.call(1, req, rsp)
        if rsp.size > len(buffer):
            raise ValueError('ACDB graph response grew unexpectedly')
        raw = buffer.raw[:rsp.size]
        return subgraphs(raw, rsp.count), raw

    def get_blob(self, command, request):
        rsp = Blob()
        self.call(command, request, rsp)
        if not rsp.size:
            return b''
        buffer = self.allocate(rsp)
        capacity = len(buffer)
        self.call(command, request, rsp)
        if rsp.size > capacity:
            raise ValueError('ACDB response size grew unexpectedly')
        return buffer.raw[:rsp.size]

    def properties(self, pairs, nodes):
        ids = (c.c_uint32*len(nodes))(*(node['id'] for node in nodes))
        req = SubgraphRequest(len(nodes), ids, vector(pairs))
        rsp = SubgraphResponse()
        self.call(2, req, rsp)
        driver, spf = self.allocate(rsp.driver), self.allocate(rsp.spf)
        self.call(2, req, rsp)
        if rsp.driver.size > len(driver) or rsp.spf.size > len(spf):
            raise ValueError('ACDB property response grew unexpectedly')
        return driver.raw[:rsp.driver.size], spf.raw[:rsp.spf.size]

    def calibration(self, nodes, pairs, persistent=False):
        ids = (c.c_uint32*len(nodes))(*(node['id'] for node in nodes))
        req = CalRequest(len(nodes), ids, Vector(), vector(pairs))
        if not persistent:
            return self.get_blob(4, req)
        rsp = ListResponse()  # AcdbSgIdPersistCalData, not AcdbBlob.
        self.call(5, req, rsp)
        if not rsp.size:
            return b''
        buffer = self.allocate(rsp)
        self.call(5, req, rsp)
        if rsp.size > len(buffer):
            raise ValueError('ACDB persistent calibration response grew unexpectedly')
        return buffer.raw[:rsp.size]


def apm_parameters(data):
    """Decode SPF parameter headers, preserving only IDs/sizes in the report."""
    result = []
    offset = 0
    while offset < len(data):
        iid, pid, size, error = words(data, offset, 4)
        padded = (size+7)&~7
        offset += 16
        if padded > len(data)-offset or error:
            raise ValueError('Invalid APM parameter size/error')
        item = {'instance_id': iid, 'parameter_id': pid, 'bytes': size}
        if pid == 0x08001002:  # APM_PARAM_ID_MODULES_LIST, apm_module_api.h.
            payload = data[offset:offset+size]
            count, = words(payload, 0, 1)
            pos = 4
            item['module_lists'] = []
            if count > MAX_ENTRIES:
                raise ValueError('Too many APM module lists')
            for _ in range(count):
                sg, container, nm = words(payload, pos, 3)
                pos += 12
                modules = words(payload, pos, nm*2)
                pos += 8*nm
                item['module_lists'].append({'subgraph_id': sg, 'container_id': container,
                    'modules': [{'module_id': mid, 'instance_id': inst}
                                for mid, inst in zip(modules[::2], modules[1::2])]})
            if pos != len(payload):
                raise ValueError('Invalid APM module list payload size')
        result.append(item)
        offset += padded
    return result


def amdb_registration(data):
    """Decode the official AMDB CAPI v3 registration records, not ELF guesses."""
    domain, count, version = words(data, 0, 3)
    if domain != 2 or version != 1 or count > MAX_ENTRIES:
        raise ValueError('Unsupported AMDB registration header')
    result, offset = [], 12
    for _ in range(count):
        begin = offset
        if len(data)-offset < 20:
            raise ValueError('Truncated AMDB registration')
        interface, api, kind, module, nf, nt, error = struct.unpack_from('<HHIIHHI', data, offset)
        offset += 20
        if interface != 2 or api != 3 or error or not nf or not nt or nf+nt > len(data)-offset:
            raise ValueError('Invalid AMDB CAPI registration')
        filename = data[offset:offset+nf].decode('ascii')
        tag = data[offset+nf:offset+nf+nt].decode('ascii')
        offset = (offset+nf+nt+3)&~3
        if offset > len(data):
            raise ValueError('Truncated AMDB registration padding')
        result.append({'module_id': module, 'module_type': kind, 'filename': filename,
                       'tag': tag, 'offset': begin, 'bytes': offset-begin})
    if offset != len(data):
        raise ValueError('AMDB registration trailing data')
    return result


def export_graph(firmware, library, graph, output):
    """Export static AML graph/connection/CKV data, without choosing live tuning."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    host = AcdbHost(library, firmware)
    report = {'source_commit': SOURCE_COMMIT, 'firmware_sha256': STOCK_SHA256,
              'key_vector': graph['key_vector'], 'alias': graph['alias'],
              'hardware_executed': False, 'playback_verified': False, 'files': []}

    def save(name, data):
        (output/name).write_bytes(data)
        report['files'].append({'path': name, 'bytes': len(data),
                                'sha256': hashlib.sha256(data).hexdigest()})

    try:
        nodes, raw = host.graph(graph['key_vector'])
        if nodes != graph['subgraphs']:
            raise ValueError('ACDB parser/native GET_GRAPH disagree')
        report['subgraphs'] = nodes
        save('subgraphs.bin', raw)
        driver, spf = host.properties(graph['key_vector'], nodes)
        save('driver-properties.bin', driver)
        save('apm-graph-open.bin', spf)
        report['apm_parameters'] = apm_parameters(spf)
        amdb = host.get_blob(15, c.c_uint32(2))
        module_ids = {m['module_id'] for p in report['apm_parameters']
                      for ml in p.get('module_lists', []) for m in ml['modules']}
        needed = [entry for entry in amdb_registration(amdb) if entry['module_id'] in module_ids]
        report['dynamic_module_dependencies'] = needed
        registration = struct.pack('<III', 2, len(needed), 1)
        registration += b''.join(amdb[e['offset']:e['offset']+e['bytes']] for e in needed)
        save('amdb-speaker-register.bin', registration)
        for dependency in needed:
            dependency['file_verified'] = False
            if dependency['module_id'] != 0x1700e900 or dependency['filename'] != 'libsixth_rx_v3.so':
                continue
            path = Path(firmware).parent/dependency['filename']
            if path.exists():
                if path.is_symlink() or path.stat().st_size != 409528:
                    raise ValueError('Invalid pinned SIPA DSP module file')
                binary = path.read_bytes()
                if hashlib.sha256(binary).hexdigest() != SIXTH_SHA256:
                    raise ValueError('SIPA DSP module SHA256 mismatch')
                if binary[:6] != b'\x7fELF\x01\x01' or struct.unpack_from('<HH', binary, 16) != (3, 164):
                    raise ValueError('SIPA DSP module is not a Hexagon ELF32 shared object')
                save(dependency['filename'], binary)
                dependency['file_verified'] = True
                dependency['sha256'] = SIXTH_SHA256
                dependency['elf_needed'] = ['libc.so', 'libgcc.so']
                dependency['dsp_file_service_available'] = False
        data = c.create_string_buffer(raw)
        connections = host.get_blob(3, ConnectionsRequest(len(nodes), c.cast(data, c.c_void_p)))
        save('apm-connections.bin', connections)
        ckvs = host.get_vectors(20, vector(graph['key_vector']))
        report['calibration_key_vectors'] = ckvs
        report['calibration'] = []
        for index, ckv in enumerate(ckvs):
            entry = {'key_vector': ckv, 'index': index}
            for persistent in (False, True):
                kind = 'persist' if persistent else 'nonpersist'
                name = f'cal-{index:04d}-{kind}.bin'
                try:
                    blob = host.calibration(nodes, ckv, persistent)
                except AcdbError as error:
                    if error.status != 19:  # AR_ENOTEXIST in ar_osal_error.h.
                        raise
                    entry[kind] = {'status': 'absent', 'acdb_status': error.status}
                else:
                    save(name, blob)
                    entry[kind] = {'status': 'exported', 'path': name}
            report['calibration'].append(entry)
        report['status'] = 'static-graph-exported-runtime-calibration-unverified'
        report['baseline_ckv'] = []
        report['runtime_requirements'] = [
            'AMDB dynamic modules loaded via a working ADSP file service',
            'verified I2S endpoint media/clock configuration and shared-memory PCM DMA',
            'per-device speaker protection calibration and runtime settings',
            'correlated OPEN, every SET_CFG, PREPARE and START acknowledgements']
    finally:
        host.close()
    (output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', type=Path)
    parser.add_argument('--library', type=Path, help='locally built official libacdb.so for native verification/export')
    parser.add_argument('--output', type=Path, help='new local export directory (contains proprietary blobs)')
    parser.add_argument('--key', action='append', default=[], help='exact graph key=value, decimal or 0x hex')
    args = parser.parse_args()
    try:
        parsed = verify_acdb(args.firmware)
        requested = tuple(sorted(tuple(int(v, 0) for v in pair.split('=')) for pair in args.key))
        selected = [g for g in parsed['graphs'] if not requested or g['key_vector'] == requested]
        if requested and len(selected) != 1:
            raise ValueError('Exact requested GKV not found in stock ACDB')
        if args.output:
            if not args.library or not requested:
                raise ValueError('Export requires --library and an exact --key vector')
            result = export_graph(args.firmware, args.library, selected[0], args.output)
        else:
            result = dict(parsed, graphs=selected, hardware_executed=False, playback_verified=False)
            if args.library:
                host = AcdbHost(args.library, args.firmware)
                try:
                    native = host.get_vectors(21, UintList())
                    if set(native) != {g['key_vector'] for g in parsed['graphs']}:
                        raise ValueError('ACDB parser/native supported GKV enumeration disagree')
                    for graph in selected:
                        if host.graph(graph['key_vector'])[0] != graph['subgraphs']:
                            raise ValueError('ACDB parser/native GET_GRAPH disagree')
                    result['native_verified_graph_count'] = len(selected)
                finally:
                    host.close()
        print(json.dumps(result, indent=2))
    except (ValueError, OSError, UnicodeError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
