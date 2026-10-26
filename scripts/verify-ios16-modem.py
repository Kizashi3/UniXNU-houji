"""One integrated modem framework acceptance run and one correlated report.

No device access. Production lifecycle, kernel worker, shared broker and wire
adapters are exercised together; recorded and revalidated evidence are labelled.
"""
from ios16_sources import source_path, include_flags
import argparse
import hashlib
import io
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
REFERENCE_PIN = 'd68e05df683f863f054b0f9c063c54d2b1342b2a'
XNU_PIN = '1b191cb58250d0705d8a51287127505aa4bc0789'
UEFI_PIN = '6c6755012728c9f7de748228758bad94d1e9a660'
STAGING = {
    '0019-stage-libpthread.sh': ('.cache/modem-libpthread-source','a6c70ca0e544347a0377babf748f831577ec24f9'),
    '0020-stage-bearssl.sh': ('.cache/wifi-sae-bearssl','7bea48e5e850ab4cafbe68d3765cdaba13a86d6f'),
    '0026-stage-hfs.sh': ('.cache/modem-hfs-source','31d5ec238dfab485e78a9a30b8b92d13e8914f03'),
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def run(args, *, cwd=ROOT, timeout=180, log=None, env=None):
    result = subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True,
                            text=True, errors='replace', timeout=timeout, env=env)
    if log:
        Path(log).write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(map(str, args)) + '\n' +
                           (result.stdout + result.stderr)[-12000:])
    return result.stdout


def mechanisms(recorded):
    path = ROOT / 'hardware/sm8650-modem-mechanisms.json'
    mapping = json.loads(path.read_text(encoding='utf-8'))
    contract = (ROOT / 'ios16/modem/giulia_modem_contract.h').read_text(encoding='utf-8')
    fields = ('id', 'group', 'producer', 'consumer', 'inputs', 'outputs', 'ownership',
              'preconditions', 'success', 'notifications', 'timeouts', 'failure',
              'recovery', 'ios_effect', 'sources', 'implementation', 'actions', 'commands', 'events')
    ids, levels = set(), {}
    for mechanism in mapping['mechanisms']:
        if set(fields) - mechanism.keys() or mechanism['id'] in ids:
            raise ValueError('Incomplete or duplicate mechanism: ' + mechanism.get('id', '?'))
        ids.add(mechanism['id'])
        for source in mechanism['sources']:
            if source not in mapping['sources']:
                raise ValueError('Unresolved mechanism source: ' + source)
        implementation=mechanism['implementation']
        level=implementation['level']
        if level not in mapping['implementation_levels']:
            raise ValueError('Unknown implementation level: '+mechanism['id'])
        levels[level]=levels.get(level,0)+1
        bodies=[]
        for name in implementation['paths']:
            path=ROOT/name
            if not path.is_file():raise ValueError('Missing mechanism implementation: '+name)
            bodies.append(path.read_text(encoding='utf-8'))
        for symbol in implementation['symbols']:
            if not any(re.search(r'\b'+re.escape(symbol)+r'\b',body) for body in bodies):
                raise ValueError('Missing mechanism symbol: '+mechanism['id']+'/'+symbol)
    for prefix, key in (('GMR_ACT_', 'actions'), ('GMR_CMD_', 'commands'), ('GMR_EV_', 'events')):
        actual = set(re.findall(r'\b' + prefix + r'[A-Z_]+\b', contract))
        covered = {symbol for m in mapping['mechanisms'] for symbol in m[key]}
        if actual != covered:
            raise ValueError(f'Mechanism {key} coverage differs: missing={actual-covered}, extra={covered-actual}')
    verified, unavailable = [], []
    for name, source in mapping['sources'].items():
        if not source.get('path'):
            continue
        source_path = (ROOT / source['path']).resolve()
        if not source_path.is_file():
            if recorded and source['path'].startswith(('.cache/', 'out/')):
                unavailable.append(name)
                continue
            raise ValueError('Missing evidence: ' + str(source_path))
        raw = source_path.read_bytes()
        if 'sha256' in source and (source['sha256'] != digest(raw) or source.get('bytes', len(raw)) != len(raw)):
            raise ValueError('Evidence digest differs: ' + name)
        verified.append(name)
    return {'groups': len(mapping['groups']), 'mechanisms': len(ids),
            'implementation_levels':levels,
            'native_hardware_backends':sum(m['implementation']['native_hardware_backend'] for m in mapping['mechanisms']),
            'sources_revalidated': verified, 'sources_recorded_only': unavailable,
            'manifest_sha256': digest(path.read_bytes())}


def evidence(recorded):
    import ios16_modem_board as board
    import ios16_modem_apple as apple
    import ios16_modem_stock as stock
    data = board.load_manifest()
    abi = apple.load_abi()
    header = (ROOT / 'ios16/modem/giulia_modem_apple_abi.h').read_text(encoding='utf-8')
    if header != apple.render_abi_header(abi):
        raise ValueError('Apple dispatch header differs from the pinned kernel tables')
    result = {'scope': 'recorded-source-identities' if recorded else 'original-source-bytes',
              'apple_dispatch_entries': sum(len(t['entries']) for t in abi['kernel_evidence']['dispatch_tables'])}
    result['uefi_reservations']=stock.validate_memory_overlay()
    import ios16_modem_protocol_map as protocol_map
    protocol_path=ROOT/'hardware/modem-qmi-service-map.json'
    protocol=json.loads(protocol_path.read_text(encoding='utf-8'))
    if not recorded:
        regenerated=(json.dumps(protocol_map.generate(),indent=2,ensure_ascii=False)+'\n').encode()
        if protocol_path.read_bytes()!=regenerated:
            raise ValueError('Detailed QMI/IPA/RMTFS/TFTP map differs from fixed source schemas')
    result['protocol_map']={'sha256':digest(protocol_path.read_bytes()),'statistics':protocol['statistics'],
                            'source_bytes_revalidated':not recorded}
    if not recorded:
        result['board'] = board.verify_dts(data, ROOT / data['android_device_tree']['decoded_path'])
        result['board_sources'] = board.verify_sources(data, ROOT / '.cache/audio-source')
        result['local_evidence'] = board.verify_files(data['local_evidence'], ROOT)
        result['ipa_routes'] = board.verify_ipa_sources(data)
        result['apple_cache'] = apple.verify_sources(ROOT / 'out/ios16/dyld-symbols/dyld_shared_cache_arm64')
        result['apple_kernel'] = apple.verify_kernel_sources(ROOT /
            'out/ios16/modem-apple-abi/kernelcache.raw/kernelcache.release.iphone10b.decompressed')
        result['apple_root'] = apple.verify_root_sources(ROOT / 'out/ios16/userdata/giulia-ios16-userdata.img')
        result['stock_modem_firmware_and_servers'] = stock.verify()
    result['mechanisms'] = mechanisms(recorded)
    return result


def system_scenarios(work):
    from ios16_modem import build_header
    (work/'giulia_modem_build.h').write_text(build_header(),encoding='utf-8')
    data = json.loads((ROOT / 'hardware/sm8650-modem.json').read_text(encoding='utf-8'))
    routes = {r['client']: r for r in data['ipa_endpoint_map']['production_routes']}
    (work / 'modem_board_fixture.h').write_text(
        '#define GM_AP_WAN_EP ' + str(routes['IPA_CLIENT_APPS_WAN_PROD']['endpoint']) +
        '\n#define GM_AP_WAN_CHANNEL ' + str(routes['IPA_CLIENT_APPS_WAN_PROD']['gsi_channel']) +
        '\n#define GM_Q6_WAN_EP ' + str(routes['IPA_CLIENT_Q6_WAN_PROD']['endpoint']) + '\n', encoding='utf-8')
    service = '#include "ios16_modem_iokit_host.h"\n'
    for name in ('GiuliaPlatformResources.cpp', 'GiuliaModem.cpp'):
        code = (source_path(ROOT, name)).read_text(encoding='utf-8')
        service += re.sub(r'^#include <[^\n]+>\n', '', code, flags=re.M) + '\n'
    # Exercise the actual Wi-Fi mailbox lease callbacks against the same
    # global broker, including profiles without the optional GPU service.
    wifi=(ROOT/'ios16/wifi/GiuliaWiFi.cpp').read_text(encoding='utf-8')
    service+='''
#define GIULIA_PLATFORM_BROKER_ENABLED 1
#include "giulia_platform_qmp.h"
#include "giulia_wifi_qmi.h"
#include "giulia_wifi_pmu.h"
#include "giulia_wifi_mapping.h"
struct giulia_wifi_runtime { unsigned quarantine,qmp_retained; };
static struct { const void *lease,*platform_lease; struct gpr_token platform_token;
    giulia_wifi_runtime *owner; uintptr_t ram,ipcc; struct qpt_state state; } gw_qmp;
'''
    for signature in ('static int gqp_claim(', 'static int gqp_owns(', 'static void gqp_release(',
                      'static void gqp_drop_owner('):
        start=wifi.index(signature);end=wifi.index('\n}',start)+2
        service+=wifi[start:end]+'\n'
    service+=(ROOT/'tests/ios16_modem_qmp_hardware.inc').read_text(encoding='utf-8')
    for signature in ('static int gq_power(', 'static void gw_qmp_stop('):
        start=wifi.index(signature);end=wifi.index('\n}',start)+2
        service+=wifi[start:end]+'\n'
    service += (ROOT / 'tests/ios16_modem_iokit_scenario.inc').read_text(encoding='utf-8')
    service_path = work / 'modem-kernel-service.cpp'
    service_path.write_text(service, encoding='utf-8')
    compiler = shutil.which('clang++')
    if not compiler:
        raise ValueError('clang++ is required for the integrated service/core run')
    executable = work / 'modem-system'
    run([compiler, '-std=c++14', '-Wall', '-Wextra', '-Werror', '-g', '-pthread',
         '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
         '-I', work, '-I', ROOT/'tests', *include_flags(ROOT),
         ROOT/'tests/ios16_modem_system.cpp', service_path, '-o', executable], timeout=180)
    result = json.loads(run([executable], timeout=60))
    probe = work / 'native-core.c'
    probe.write_text('#include "giulia_modem_runtime.h"\n#include "giulia_platform_resources.h"\n'
        'int modem_native_compile(struct gmr_runtime *r,const struct gmr_ops *ops) '
        '{ return gmr_init(r,ops) || gmr_start(r) || gmr_tick(r,1); }\n', encoding='utf-8')
    run(['clang', '--target=aarch64-none-elf', '-ffreestanding', '-std=c11', '-Wall', '-Wextra',
         '-Werror', '-Wframe-larger-than=8192', *include_flags(ROOT), '-c', probe, '-o', work/'native-core.o'])
    result['native_core_target'] = 'aarch64-none-elf'
    result['kernel_service_host_compiled'] = True
    return result


def original_files(xnu, paths, pin=XNU_PIN):
    tracked = set(run(['git', '-C', xnu, 'ls-tree', '-r', '--name-only', pin]).splitlines())
    names = sorted(set(paths) & tracked)
    result = subprocess.run(['git', '-C', str(xnu), 'archive', '--format=tar', pin, '--', *names],
                            capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        return {member.name: archive.extractfile(member).read() for member in archive if member.isfile()}


def stage_dependencies(profile, tree):
    staged=[]
    scripts=sorted(profile.glob('*.sh'))
    if {p.name for p in scripts} != set(STAGING):
        raise ValueError('Pinned profile staging inventory changed')
    for script in scripts:
        relative,pin=STAGING[script.name];source=ROOT/relative
        if run(['git','-C',source,'rev-parse','HEAD']).strip()!=pin:
            raise ValueError('Staging source pin differs: '+script.name)
        text=script.read_text(encoding='utf-8')
        bodies=re.findall(r"<<'PY'\n(.*?)\nPY\n",text,re.S)
        if len(bodies)!=1 or pin not in text:
            raise ValueError('Staging program shape/source pin changed: '+script.name)
        # Execute the exact source-copy/adaptation program used by the build.
        # SDK-only TargetConditionals staging is not a patch input and is
        # provided by Xcode during the real kernel build, not synthesized here.
        completed=subprocess.run([sys.executable,'-',str(source)],input=bodies[0],cwd=tree,
                                 capture_output=True,text=True,timeout=90)
        if completed.returncode:
            raise RuntimeError('Staging failed: '+script.name+'\n'+completed.stdout+completed.stderr)
        staged.append({'script':script.name,'source_commit':pin,'script_sha256':digest(script.read_bytes())})
    for directory in ('bsd/pthread/sweet_libpthread','bsd/sweet_hfs','libkern/crypto/sweet_bearssl'):
        for file in (tree/directory).rglob('*'):
            if file.is_file() and file.suffix in ('.c','.h','.inc','.txt'):
                raw=file.read_bytes()
                if b'\r\n' in raw:file.write_bytes(raw.replace(b'\r\n',b'\n'))
    return staged


def profiles(work, reference, xnu):
    if run(['git', '-C', reference, 'rev-parse', 'HEAD']).strip() != REFERENCE_PIN:
        raise ValueError('Reference checkout is not pinned')
    if run(['git', '-C', xnu, 'rev-parse', 'HEAD']).strip() != XNU_PIN:
        raise ValueError('Original XNU checkout is not pinned')
    matrix, generated, paths = [], [], set()
    for wifi, gpu, audio in itertools.product((False, True), repeat=3):
        name = f'w{int(wifi)}g{int(gpu)}a{int(audio)}'
        folder = work/name
        args = [sys.executable, ROOT/'scripts/prepare-ios16.py', '--reference', reference,
                '--work', folder/'source', '--out', folder/'profile', '--gui', '--modem']
        args += [option for yes, option in ((wifi,'--wifi'),(gpu,'--gpu'),(audio,'--audio')) if yes]
        run(args, timeout=180)
        patches = sorted((folder/'profile').glob('*.patch'))
        for patch in patches:
            paths.update(re.findall(r'^--- a/(.+)$', patch.read_text(encoding='utf-8',errors='surrogateescape'), re.M))
        generated.append((name, folder, patches, wifi, gpu, audio))
    originals = original_files(xnu, paths)
    for name, folder, patches, wifi, gpu, audio in generated:
        tree = folder/'tree';tree.mkdir()
        for path, raw in originals.items():
            target = tree/path;target.parent.mkdir(parents=True, exist_ok=True);target.write_bytes(raw)
        run(['git', 'init', '-q', tree])
        staged=stage_dependencies(folder/'profile',tree)
        # Apply the entire generated patch chain, not an isolated registration hunk.
        for patch in patches:
            run(['git', 'apply', '--whitespace=nowarn', patch], cwd=tree, timeout=45)
        registry = json.loads((folder/'profile/module-registry.json').read_text())
        units = (tree/'iokit/conf/files.arm64').read_text()
        for unit in registry['translation_units']:
            if units.count(unit) != 1 or not (tree/unit).is_file():
                raise ValueError('Translation unit registration mismatch: ' + unit)
        kernel_config = (tree/'iokit/KernelConfigTables.cpp').read_text()
        from ios16_modem import build_binding, build_header
        if json.loads((folder/'profile/modem-config.json').read_text())!=build_binding() or \
           (tree/'iokit/Kernel/arm/giulia_modem_build.h').read_text()!=build_header():
            raise ValueError('Compiled modem evidence binding differs from its profile declaration')
        for cls in registry['personalities']:
            if len(re.findall(r"'IOClass'\s*=\s*"+cls+r';', kernel_config)) != 1:
                raise ValueError('IOKit personality mismatch: ' + cls)
        usb = (tree/'bsd/dev/vermeer_usb_debug.c').read_text(encoding='utf-8',errors='surrogateescape')
        if 'giulia_modem_terminal(cmd)' not in usb or 'modem.status' not in usb:
            raise ValueError('Modem terminal is not in the actual patched CDC source')
        if gpu and '#define GIULIA_PLATFORM_BROKER_ENABLED 1' not in (tree/'iokit/Kernel/arm/GiuliaGPU.cpp').read_text():
            raise ValueError('GPU uses a different IPC owner from modem')
        for enabled,unit_name in ((wifi,'GiuliaWiFi.cpp'),(audio,'GiuliaAudio.cpp')):
            if enabled and '#define GIULIA_PLATFORM_BROKER_ENABLED 1' not in (tree/'iokit/Kernel/arm'/unit_name).read_text():
                raise ValueError('Optional service does not share the modem resource broker: '+unit_name)
        matrix.append({'profile': name, 'patches_applied': len(patches),
                       'modules': registry['personalities'], 'wifi':wifi, 'gpu':gpu, 'audio':audio,
                       'staged_dependencies':staged})
    return {'reference': REFERENCE_PIN, 'xnu': XNU_PIN, 'combinations': matrix}


def artifact_contracts():
    import ios16_modem as modem
    import ios16_modem_apple as apple
    from ios16_startup_compat import prepare_cellular, LAUNCHD
    from ios16_root_layout import VERSION
    import plistlib
    # Exercise root policy using actual recorded source jobs, with no image writes.
    abi = apple.load_abi()
    jobs = abi.get('launch_jobs', {})
    if not jobs:
        raise ValueError('Apple evidence lacks the original launchd jobs')
    class Root:
        def __init__(self):
            self.files={VERSION:plistlib.dumps({'ProductBuildVersion':'20H392'}),
                        LAUNCHD:plistlib.dumps({'LaunchDaemons': jobs})}
        def exists(self, path):return path in self.files
        def read(self, path):return self.files[path]
        def write(self, path, data, **kwargs):self.files[path]=data
    root=Root();report=prepare_cellular(root)
    if plistlib.loads(root.read(LAUNCHD))['LaunchDaemons']:
        raise ValueError('Disabled cellular policy retained a source cellular job')
    kernel=modem.RUNTIME_MARKER+b'\0'+modem.BROKER_MARKER+b'\0'+modem.build_marker()
    def node(name, children=()):
        value=name.encode()+b'\0'
        return (struct.pack('<II',1,len(children))+b'name'.ljust(32,b'\0')+
                struct.pack('<I',len(value))+value+bytes(-len(value)%4)+b''.join(children))
    adt=node('device-tree')
    metadata=modem.kernel_declaration(kernel)
    actual=modem.check_contract(kernel,metadata,adt,report,'diagnostic')
    bad_binding=kernel.replace(modem.build_binding()['firmware_manifest_sha256'].encode(),b'0'*64)
    try:modem.kernel_declaration(bad_binding)
    except ValueError:pass
    else:raise ValueError('Kernel compiled against a different firmware manifest accepted')
    if actual['native_provider_included'] or actual['baseband_paths']:
        raise ValueError('Diagnostic profile exposed a native baseband')
    for changed, mode, tree in ((dict(metadata,modem_runtime_abi=99),'diagnostic',adt),
                                (metadata,'managed',adt),
                                (metadata,'diagnostic',node('device-tree',(node('baseband'),)))):
        try:modem.check_contract(kernel,changed,tree,report,mode)
        except ValueError:pass
        else:raise ValueError('Inconsistent managed/runtime contract accepted')
    return {'cellular_policy':report, 'managed_without_provider_rejected':True,
            'kernel_metadata_mismatch_rejected':True}


def uefi_profile(work, source):
    import prepare
    import ios16_modem_stock as stock
    pins=json.loads((ROOT/'sources.json').read_text(encoding='utf-8'))
    if pins['uefi']['commit']!=UEFI_PIN or run(['git','-C',source,'rev-parse','HEAD']).strip()!=UEFI_PIN:
        raise ValueError('UEFI source pin differs from the qualified memory map')
    patch=ROOT/'patches/giulia-unixnu.patch'
    paths=set(re.findall(r'^--- a/(.+)$',patch.read_text(encoding='utf-8'),re.M))
    paths.update((stock.MEMORY_MAP_PATH,'Platforms/OnePlus/giuliaPkg/Library/MemoryMapLib/MemoryMapLib.inf'))
    originals=original_files(source,paths,UEFI_PIN)
    if set(originals)!=paths:
        raise ValueError('Qualified UEFI pin lacks a required original board/patch source')
    tree=work/'uefi';tree.mkdir()
    for name,raw in originals.items():
        target=tree/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw.replace(b'\r\n',b'\n'))
    run(['git','init','-q',tree])
    run(['git','apply','--check',patch],cwd=tree)
    run(['git','apply',patch],cwd=tree)
    prepare.apply_uefi_overlay(tree)
    report=stock.verify_prepared_memory_map(tree)
    prepare.apply_uefi_overlay(tree)
    if stock.verify_prepared_memory_map(tree)!=report:
        raise ValueError('UEFI overlay is not idempotent')
    target=tree/stock.MEMORY_MAP_PATH;qualified=target.read_bytes()
    target.write_bytes(qualified+b'\n// unrelated memory map drift\n')
    try:prepare.apply_uefi_overlay(tree)
    except ValueError:pass
    else:raise ValueError('UEFI overlay overwrote an unqualified board memory map')
    if target.read_bytes()!=qualified+b'\n// unrelated memory map drift\n':
        raise ValueError('UEFI preflight modified the rejected source')
    return {'source_commit':UEFI_PIN,'complete_board_patch_applied':True,
            'production_overlay_stager_executed':True,'idempotence_verified':True,
            'drift_rejected_before_copy':True,'memory':report}


def neighbour_regression(report_path):
    # Existing subsystem checks remain internal assertions of this one gate.
    # Run them because modem now changes their production arbitration paths.
    result=[];env=os.environ.copy()
    env['PATH']=str(Path(sys.executable).parent)+os.pathsep+env.get('PATH','')
    for subsystem in ('wifi-runtime','audio','gpu'):
        script=ROOT/f'scripts/test-ios16-{subsystem}.sh'
        log=report_path.with_suffix('.'+subsystem+'.log')
        print('Modem system: shared-resource neighbour regression '+subsystem,flush=True)
        run(['bash',script],timeout=1800,log=log,env=env)
        result.append({'subsystem':subsystem,'log':str(log),'sha256':digest(log.read_bytes())})
    return result


def linked_kernel(path):
    import ios16_modem as modem
    raw=path.read_bytes()
    if len(raw)<32 or struct.unpack_from('<I',raw)[0]!=0xfeedfacf:
        raise ValueError('Compiled modem kernel is not a 64-bit Mach-O')
    if struct.unpack_from('<I',raw,4)[0]!=0x100000c:
        raise ValueError('Compiled modem kernel is not ARM64')
    actual=modem.kernel_declaration(raw)
    if not actual['modem_runtime_included'] or not actual['modem_platform_broker_included']:
        raise ValueError('Compiled kernel lacks the modem service/broker')
    return {'path':str(path),'sha256':digest(raw),'bytes':len(raw),'declaration':actual,
            'scope':'linked ARM64 kernel bytes; native provider readiness remains independently gated'}


def source_generation():
    selected=set()
    for folder,pattern in (('ios16/modem','*modem*'),('ios16/modem','*Modem*'),
                           ('ios16/platform','*platform_resources*'),('ios16/platform','GiuliaPlatformResources.cpp'),
                           ('scripts','*modem*'),('hardware','*modem*'),('docs','MODEM*'),
                           ('tests','*modem*')):
        selected.update(p for p in (ROOT/folder).glob(pattern) if p.is_file())
    for name in ('ios16/gpu/GiuliaGPU.cpp','ios16/gpu/giulia_gpu_ipcc_owner.h','scripts/prepare-ios16.py',
                 'ios16/wifi/GiuliaWiFi.cpp','ios16/audio/GiuliaAudio.cpp',
                 'scripts/ios16_module_registry.py','scripts/ios16_startup_compat.py',
                 'scripts/ios16_terminal.py','scripts/make-ios16-payload.py','scripts/verify-payload.py',
                 'scripts/prepare.py','sources.json','patches/giulia-unixnu.patch',
                 '.github/workflows/ios16-xnu.yml'):
        selected.add(ROOT/name)
    for folder in ('ios16','tests','uefi-overlay'):
        selected.update(p for p in (ROOT/folder).rglob('*') if p.is_file() and
                        '__pycache__' not in p.parts and p.suffix not in ('.pyc','.o'))
    selected.update(p for p in (ROOT/'scripts').glob('*') if p.is_file())
    return {p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in sorted(selected)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,default=ROOT/'.cache/gpu-fixed-reference')
    parser.add_argument('--xnu-source',type=Path,default=ROOT/'.cache/modem-xnu-base')
    parser.add_argument('--uefi-source',type=Path,default=ROOT/'.cache/modem-uefi-base')
    parser.add_argument('--linked-kernel',type=Path,help='CI: include the actual compiled ARM64 kernel in this report')
    parser.add_argument('--recorded-evidence',action='store_true',help='CI: verify committed source identities without private Apple images')
    parser.add_argument('--report',type=Path,default=ROOT/'reports/modem-system.json')
    args=parser.parse_args();started=time.monotonic()
    result={'schema':1,'board':'giulia','system_build':'20H392','result':'failed',
            'hardware_validated':False,'scope':'unified-framework-and-mechanism-mapping',
            'native_modem_operational':False,'full_xnu_kernel_linked_in_this_run':False,'checks':{}}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    try:
        result['source_generation']=source_generation()
        print('Modem system: source and cross-layer mechanism evidence',flush=True)
        result['checks']['evidence']=evidence(args.recorded_evidence)
        with tempfile.TemporaryDirectory(prefix='giulia-modem-system-') as directory:
            work=Path(directory)
            print('Modem system: production core, kernel service, broker, wire and recovery scenarios',flush=True)
            result['checks']['runtime']=system_scenarios(work)
            print('Modem system: complete profile patch matrix and registration',flush=True)
            result['checks']['profiles']=profiles(work,args.reference.resolve(),args.xnu_source.resolve())
            print('Modem system: complete UEFI board patch, production overlay and firmware reservations',flush=True)
            result['checks']['uefi']=uefi_profile(work,args.uefi_source.resolve())
            print('Modem system: cellular root and kernel/ADT artifact contract',flush=True)
            result['checks']['artifacts']=artifact_contracts()
            if args.linked_kernel:
                result['checks']['linked_kernel']=linked_kernel(args.linked_kernel.resolve())
                result['full_xnu_kernel_linked_in_this_run']=True
            print('Modem system: complete repository regression',flush=True)
            log=args.report.with_suffix('.regression.log')
            run([sys.executable,'-m','unittest','discover','-s','tests','-v'],timeout=600,log=log)
            result['checks']['regression']={'log':str(log),'sha256':digest(log.read_bytes())}
            result['checks']['shared_resource_regression']=neighbour_regression(args.report)
        run(['git','diff','--check'])
        if result['source_generation']!=source_generation():
            raise ValueError('Source generation changed during the unified run; no mixed-source acceptance')
        result['result']='passed'
    except Exception as error:
        result['error']=str(error)
    result['elapsed_seconds']=round(time.monotonic()-started,3)
    args.report.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'result':result['result'],'report':str(args.report),'error':result.get('error')},ensure_ascii=False),flush=True)
    return 0 if result['result']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
