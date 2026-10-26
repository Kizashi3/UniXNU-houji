"""One modem declaration for kernel, payload, ADT and cellular root policy."""
import hashlib
import json
from pathlib import Path

from ios16_platform import read_nodes

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_MARKER = b'GIULIA MODEM: runtime ABI=1;'
BROKER_MARKER = b'GIULIA PLATFORM: resource broker ABI=1;'
ABI = 1
BUILD_PREFIX = b'GIULIA MODEM CONTRACT: '


def build_binding(root=ROOT):
    root=Path(root)
    sources=sorted(set((root/'ios16/modem').glob('giulia_modem_*.h')) |
                   {root/'ios16/modem/GiuliaModem.cpp',root/'ios16/platform/GiuliaPlatformResources.cpp',
                    root/'ios16/platform/giulia_platform_resources.h'})
    code=hashlib.sha256()
    for path in sources:
        code.update(path.name.encode()+b'\0'+path.read_bytes().replace(b'\r\n',b'\n')+b'\0')
    return {'schema':1,'board':'giulia','system_build':'20H392','runtime_abi':ABI,
            'core_sources_sha256':code.hexdigest(),
            'firmware_manifest_sha256':hashlib.sha256((root/'hardware/sm8650-modem-stock.json').read_bytes()).hexdigest(),
            'resources_manifest_sha256':hashlib.sha256((root/'hardware/sm8650-modem.json').read_bytes()).hexdigest(),
            'apple_abi_sha256':hashlib.sha256((root/'hardware/ios16-modem-abi.json').read_bytes()).hexdigest()}


def build_marker(root=ROOT):
    return BUILD_PREFIX+json.dumps(build_binding(root),sort_keys=True,separators=(',', ':')).encode()+b'\0'


def build_header(root=ROOT):
    marker=build_marker(root)[:-1].decode()
    return ('/* Generated from the exact modem firmware/resource/Apple evidence. */\n'
            '#ifndef GIULIA_MODEM_BUILD_H\n#define GIULIA_MODEM_BUILD_H\n'
            '#define GIULIA_MODEM_BUILD_MARKER '+json.dumps(marker)+'\n#endif\n')


def kernel_declaration(kernel):
    included = RUNTIME_MARKER in kernel
    broker = BROKER_MARKER in kernel
    if included and not broker:
        raise ValueError('Modem runtime and shared platform broker must be linked together')
    binding=None
    if included:
        start=kernel.find(BUILD_PREFIX)
        if start<0 or kernel.find(BUILD_PREFIX,start+len(BUILD_PREFIX))>=0:
            raise ValueError('Modem kernel must include exactly one compiled evidence binding')
        end=kernel.find(b'\0',start)
        if end<0 or end-start>1024:raise ValueError('Malformed modem kernel evidence binding')
        try:binding=json.loads(kernel[start+len(BUILD_PREFIX):end])
        except (ValueError,UnicodeError) as error:raise ValueError('Malformed modem kernel evidence binding') from error
        if binding!=build_binding():
            raise ValueError('Modem kernel was compiled against different firmware/resources/Apple ABI')
    elif BUILD_PREFIX in kernel:
        raise ValueError('Modem build binding exists without the compiled service')
    return {'modem_runtime_included': included,
            'modem_runtime_abi': ABI if included else None,
            'modem_platform_broker_included': included and broker,
            'modem_build_binding':binding,
            # The framework cannot manufacture a native provider by a bootarg
            # or by registering a host-test callback. A real producer must be
            # independently included and qualified before this changes.
            'modem_native_provider_included': False}


def check_runtime(kernel, metadata):
    actual = kernel_declaration(kernel)
    for key, value in actual.items():
        expected = metadata.get(key, False if isinstance(value, bool) else None)
        if expected != value:
            raise ValueError('Modem kernel declaration mismatch: ' + key)
    if not actual['modem_runtime_included']:
        return None
    return {'schema': 1, 'board': 'giulia', 'system_build': '20H392',
            'runtime_abi': ABI, 'platform_broker_included': True,
            'native_provider_included': False,
            'build_binding':actual['modem_build_binding'],
            'kernel_sha256': hashlib.sha256(kernel).hexdigest()}


def check_contract(kernel, metadata, adt, root_report, mode):
    runtime = check_runtime(kernel, metadata)
    if mode not in (None, 'diagnostic', 'managed'):
        raise ValueError('Unknown modem mode')
    if mode and not runtime:
        raise ValueError('Modem mode requires the compiled unified runtime')
    if not runtime:
        return None
    nodes = read_nodes(adt)
    baseband = [path for path in nodes if path.rsplit('/', 1)[-1] == 'baseband']
    cellular = (root_report or {}).get('cellular_policy', {})
    policy = cellular.get('mode', 'disabled')
    if mode == 'managed':
        if not runtime['native_provider_included']:
            raise ValueError('Managed cellular requires a linked and qualified native provider')
        from ios16_modem_apple import require_managed_contract
        require_managed_contract(runtime, adt, root_report)
    elif baseband or policy != 'disabled':
        raise ValueError('Diagnostic modem cannot advertise a managed baseband or enable CommCenter')
    return dict(runtime, mode=mode or 'disabled', baseband_paths=baseband,
                cellular_policy=policy,
                adt_sha256=hashlib.sha256(adt).hexdigest(),
                root_policy_sha256=hashlib.sha256(json.dumps(cellular, sort_keys=True,
                    separators=(',', ':')).encode()).hexdigest())


def metadata_from_runtime(runtime):
    if not runtime:
        return kernel_declaration(b'')
    return {'modem_runtime_included': True, 'modem_runtime_abi': runtime.get('runtime_abi'),
            'modem_build_binding':runtime.get('build_binding'),
            'modem_platform_broker_included': runtime.get('platform_broker_included'),
            'modem_native_provider_included': runtime.get('native_provider_included')}
