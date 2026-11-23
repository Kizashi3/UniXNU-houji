#!/usr/bin/env python3
"""Exercise the real runtime coordinator and fixed-file primitive, no ADB/device.

All subprocess calls are intercepted. The actual prepare-xnu-log main(), FAT
parser, snapshot decoders and preparation coordinator run over a bounded fake
Recovery/FAT peer. Unknown commands fail rather than reaching the computer.
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import zlib

P = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


runtime = load(P / 'scripts/prepare-xnu-runtime-trial.py', 'runtime_preparation_test')
allocator = load(P / 'scripts/prepare-xnu-log.py', 'runtime_allocation_test')
reader = load(P / 'scripts/capture-logfs.py', 'runtime_capture_test')
assert runtime.HELPER_SHA == '716048584c1c6e85e64335e9528704f0e80c46a893f0e3e5d723bb3bd778b6a0'
HELPER = b'bounded test O_DIRECT helper identity'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def xnu_image(run_id):
    payload = b'HOUJI GPU CPU PAGE PROBE: fixture committed actual bytes\n'
    header = bytearray(4096)
    header[:8] = b'HJXNU001'
    struct.pack_into('<II', header, 8, 1, 1)
    header[16:32] = run_id
    struct.pack_into('<II', header, 32, len(payload), zlib.crc32(payload))
    struct.pack_into('<I', header, 40, zlib.crc32(header))
    return bytes(header) + payload + bytes(61440 - len(payload))


def fat_set(raw, cluster, value):
    for base in (4096, 8192):
        offset = base + cluster + cluster // 2
        old = struct.unpack_from('<H', raw, offset)[0]
        new = ((old & 0x000f) | (value << 4)) if cluster & 1 else ((old & 0xf000) | value)
        struct.pack_into('<H', raw, offset, new)


class Peer:
    def __init__(self, project, native):
        self.project, self.native = project, native
        self.port = 5038
        self.commands, self.pushes = [], []
        self.rw, self.reset, self.deleted = False, False, False
        self.log_writes = 0
        self.injection = lambda command, count: None
        self.primitive_after = lambda: None
        self.before_primitive = lambda: None
        self.helper_present = True
        self.helper_hash = sha(HELPER)
        self.identity = b'0\nhouji\n1\n/dev/block/sda13\n8388608\n'
        self.stage = {}
        self.old_id = bytes(range(1, 17))
        self.xnu = xnu_image(self.old_id)
        payload = (b'HOUJI LOGFS r137:\nfixture native snapshot\n'
                   b'r137 snapshot end; app text only; commit/readback follows\n')
        self.native_log = payload + (f'HOUJI LOGFS CHECKSUM: payload-bytes={len(payload)} '
                                    f'payload-crc32={zlib.crc32(payload):08x}\n').encode()
        self.raw = bytearray(8388608)
        struct.pack_into('<HBHBHHBHHH', self.raw, 11, 4096, 1, 1, 2, 512, 1280, 248, 1, 1, 1)
        self.raw[510:512] = b'\x55\xaa'
        for cluster in range(2, 18):
            fat_set(self.raw, cluster, cluster + 1 if cluster < 17 else 0xfff)
        fat_set(self.raw, 18, 0xfff)
        for offset, name, cluster, size in ((12288, b'XNULOG  BIN', 2, 65536),
                                           (12320, b'UNIXNU  LOG', 18, len(self.native_log))):
            self.raw[offset:offset + 11] = name
            self.raw[offset + 11] = 0x20
            struct.pack_into('<H', self.raw, offset + 26, cluster)
            struct.pack_into('<I', self.raw, offset + 28, size)
        self.raw[7 * 4096:23 * 4096] = self.xnu
        self.raw[23 * 4096:23 * 4096 + len(self.native_log)] = self.native_log
        self.allocation = allocator.layout(bytes(self.raw))
        self.allocation.update(run_id=self.old_id.hex())
        self.misc = bytes(864) + b'M' * (4194304 - 864)
        self.boot = {name: sha(name.encode()) for name in
                     ('boot_a', 'boot_b', 'init_boot_a', 'init_boot_b', 'recovery_a')}
        self.gpt = {(f'/dev/block/sd{chr(97 + i)}', kind): bytes([i * 2 + j + 1]) * 4096
                    for i in range(6) for j, kind in enumerate(('primary', 'backup'))}
        self.disks = [{'device': f'/dev/block/sd{chr(97 + i)}', 'backup_start_lba': 500 + i}
                      for i in range(6)]
        self.expected_gpt = copy.deepcopy(self.gpt)
        self.expected_boot = dict(self.boot)
        self.policy = {'log_file': 'XnuLog.bin', 'log_run_id': self.old_id.hex(),
                       'log_data_lbas': self.allocation['lbas'], 'log_initial_sha256': '0' * 64}
        self.make_inputs()

    def make_inputs(self):
        c = self.native / 'native-ios-candidate'
        capture = self.native / 'evidence/logfs-recovery-r137'
        capture.mkdir(parents=True, exist_ok=True)
        dump(c / 'r137-policy.json', self.policy)
        dump(c / 'r137-allocation/layout.json', self.allocation)
        (capture / 'XnuLog.bin').write_bytes(self.xnu)
        (capture / 'UniXNU.log').write_bytes(self.native_log)
        report = {'files': [{'file': name, 'status': 'captured', 'bytes': len(data),
                             'stable': True, 'sha256': sha(data)} for name, data in
                            (('XnuLog.bin', self.xnu), ('UniXNU.log', self.native_log))],
                  'native_snapshot_integrity': reader.verify_native_snapshot(self.native_log),
                  'xnu_snapshot_integrity': reader.decode_xnu_snapshot(self.xnu, self.old_id.hex())[0]}
        dump(capture / 'capture.json', report)
        dump(self.native / 'partition-backup-20261024/manifest.json', {'disks': self.disks})
        baseline = self.native / 'device-baseline/misc-before-native-ios-r137.bin'
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_bytes(self.misc)
        helper = self.native / 'native-log-candidate/logfs-direct-read'
        helper.parent.mkdir(parents=True, exist_ok=True)
        helper.write_bytes(HELPER)

    def push(self, source, destination):
        self.pushes.append(destination)
        self.stage[destination] = Path(source).read_bytes()
        if destination == '/tmp/houji-logfs-read':
            self.helper_present, self.helper_hash = True, sha(self.stage[destination])

    def root(self, command):
        self.commands.append(command)
        self.injection(command, self.commands.count(command))
        if command.startswith('id -u; getprop ro.product.device; getprop ro.houji.native_rescue;'):
            return self.identity
        if command == ('id -u; getprop ro.product.device; readlink -f /dev/block/by-name/logfs; '
                       'blockdev --getsize64 /dev/block/by-name/logfs'):
            return b'0\nhouji\n/dev/block/sda13\n8388608\n'
        if command == 'cat /proc/mounts':
            return f'/dev/block/sda13 /dev/logfs vfat {"rw" if self.rw else "ro"},relatime 0 0\n'.encode()
        if command.startswith('sha256sum /dev/block/by-name/'):
            name = command.split('/')[-1]
            return f'{self.boot[name]} /dev/block/by-name/{name}\n'.encode()
        if command.startswith('dd if=/dev/block/sd'):
            fields = dict(part.split('=', 1) for part in command.split()[1:])
            kind = 'primary' if fields['skip'] == '0' else 'backup'
            return self.gpt[fields['if'], kind]
        if command == 'cat /dev/block/by-name/misc':
            return self.misc
        if command == 'cat /dev/logfs/XnuLog.bin':
            return self.xnu
        if command == 'cat /dev/logfs/UniXNU.log':
            if self.deleted:
                raise RuntimeError('file already deleted')
            return self.native_log
        if command == '/tmp/houji-logfs-read':
            return bytes(self.raw)
        if command == 'sha256sum /tmp/houji-logfs-read':
            return f'{self.helper_hash} /tmp/houji-logfs-read\n'.encode()
        if command == 'chmod 755 /tmp/houji-logfs-read' or command == 'sync':
            return b''
        if command.startswith('if [ -e ') or command.startswith('if [ -f '):
            path = command.split()[3]
            present = (self.helper_present if path == '/tmp/houji-logfs-read' else
                       not self.deleted if path == '/dev/logfs/UniXNU.log' else
                       True if path == '/dev/logfs/XnuLog.bin' else path in self.stage)
            affirmative = 'PRESENT' if 'echo PRESENT' in command else 'EXISTS'
            return ((affirmative if present else 'ABSENT') + '\n').encode()
        if command == 'mount -o remount,rw /dev/logfs':
            self.rw = True
            return b''
        if command == 'mount -o remount,ro /dev/logfs':
            self.rw = False
            return b''
        if command.startswith('dd if=/tmp/houji-xnu-log-'):
            assert command.endswith('of=/dev/logfs/XnuLog.bin bs=4096 count=16 conv=notrunc,fsync')
            assert self.rw
            path = command.split()[1][3:]
            self.xnu = self.stage[path]
            assert len(self.xnu) == 65536
            self.raw[7 * 4096:23 * 4096] = self.xnu
            self.reset = True
            self.log_writes += 1
            return b''
        if command.startswith('rm /tmp/houji-xnu-log-'):
            del self.stage[command[3:]]
            return b''
        if command == ('set -e; mount -o remount,rw /dev/logfs; rm /dev/logfs/UniXNU.log; '
                       'sync; mount -o remount,ro /dev/logfs'):
            self.rw = True
            assert not self.deleted
            self.deleted = True
            self.log_writes += 1
            fat_set(self.raw, 18, 0)
            self.raw[12320] = 0xe5
            self.rw = False
            return b''
        raise AssertionError('Unknown command refused: ' + command)

    def subprocess_run(self, command, **kwargs):
        command = list(map(str, command))
        if command[0] == sys.executable:
            assert command[1] == str(self.project / 'scripts/prepare-xnu-log.py')
            assert '--recovery' in command and '--reuse-sha256' in command
            self.before_primitive()
            output = io.StringIO()
            try:
                with patch.object(sys, 'argv', command[1:]), contextlib.redirect_stdout(output):
                    allocator.main()
                self.primitive_after()
                return subprocess.CompletedProcess(command, 0, output.getvalue().encode(), b'')
            except Exception as error:
                return subprocess.CompletedProcess(command, 1, output.getvalue().encode(), str(error).encode())
        assert command[0] == allocator.ADB, 'Real subprocess access is forbidden'
        assert command[1:5] == ['-P', '5038', '-s', 'DEVICE_SERIAL']
        try:
            if command[5] == 'exec-out':
                result = self.root(command[6])
            elif command[5] == 'push':
                self.push(Path(command[6]), command[7])
                result = b'fixture push complete\n'
            else:
                raise AssertionError('Unknown ADB command')
            return subprocess.CompletedProcess(command, 0, result, b'')
        except Exception as error:
            if kwargs.get('check'):
                raise subprocess.CalledProcessError(1, command, output=b'', stderr=str(error).encode()) from error
            return subprocess.CompletedProcess(command, 1, b'', str(error).encode())


cases = 0


def scenario(change=None, ok=False, after=None):
    global cases
    with tempfile.TemporaryDirectory() as temporary:
        project, native = Path(temporary) / 'project', Path(temporary) / 'native'
        project.mkdir()
        peer = Peer(project, native)
        if change:
            change(peer)
        inputs = {path: path.read_bytes() for path in
                  (native / 'native-ios-candidate').rglob('*') if path.is_file()}
        archived = {path: path.read_bytes() for path in
                    (native / 'evidence/logfs-recovery-r137').iterdir()}
        preflight = SimpleNamespace(BOOT=peer.expected_boot,
            expected_gpt=lambda disk, suffix: peer.expected_gpt[disk['device'], suffix])
        with patch.object(runtime, 'HELPER_SHA', sha(HELPER)):
            preparation = runtime.RuntimePreparation(138, 5038, project, native,
                transport=peer, reader=reader, allocator=allocator, preflight=preflight)
            with patch.object(subprocess, 'run', peer.subprocess_run):
                result = preparation.run_preparation()
        assert result['ready_for_assembly'] is ok, result
        assert result['status'] == ('PREPARED_FOR_ASSEMBLY_NOT_BOOTED' if ok else 'FAILED_DO_NOT_BOOT')
        assert result['boot_started'] is False and result['source_or_policy_modified'] is False
        assert all(path.read_bytes() == data for path, data in inputs.items())
        assert all(path.read_bytes() == data for path, data in archived.items())
        assert not (project / 'native').exists(), 'Source tree must not be changed'
        assert json.loads((preparation.receipts / 'receipt.json').read_text()) == result
        assert not any('reboot' in command or 'fastboot' in command or 'of=/dev/block/' in command for command in peer.commands)
        if ok:
            assert peer.log_writes == 2 and peer.deleted and not peer.rw
            assert result['finally_readonly_verified'] is True
            assert result['protected_before'] == result['protected_after']
            final = (preparation.backup / 'logfs.bin').read_bytes()
            assert final == bytes(peer.raw)
            assert reader.decode_xnu_snapshot(peer.xnu, result['new_run_id'])[0]['committed'] is False
            assert result['new_run_id'] != peer.old_id.hex()
            assert result['final_logfs_sha256'] == sha(final)
            assert allocator.layout(final)['lbas'] == peer.allocation['lbas']
            assert (preparation.receipts / 'logfs-before-reset.bin').read_bytes() != final
        else:
            assert not preparation.backup.exists(), 'A failed run published a usable preflight backup'
        if after:
            after(peer, preparation, result)
        # A failed or successful receipt is immutable to a second invocation.
        count = len(peer.commands)
        try:
            runtime.RuntimePreparation(138, 5038, project, native, transport=peer,
                                       reader=reader, allocator=allocator, preflight=preflight)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Existing run destination was reused')
        assert len(peer.commands) == count
        cases += 1


scenario(ok=True)
scenario(lambda p: setattr(p, 'helper_present', False), ok=True,
         after=lambda p, *_: runtime.require(p.pushes.count('/tmp/houji-logfs-read') == 1, 'Helper was not installed exactly once'))


def alter_capture(peer, edit):
    path = peer.native / 'evidence/logfs-recovery-r137/capture.json'
    value = json.loads(path.read_text())
    edit(value)
    dump(path, value)


for edit in (lambda c: c['files'][0].update(stable=False),
             lambda c: c['files'][1].update(stable=False),
             lambda c: c['files'][0].update(sha256='0' * 64),
             lambda c: c['files'][0].update(bytes=1),
             lambda c: c['files'].append(copy.deepcopy(c['files'][0])),
             lambda c: c['native_snapshot_integrity'].update(valid=False),
             lambda c: c['xnu_snapshot_integrity'].update(committed=False)):
    scenario(lambda p, edit=edit: alter_capture(p, edit),
             after=lambda p, *_: runtime.require(not p.commands and p.log_writes == 0, 'Invalid archive reached device'))

for offset in (8, 12, 16, 32, 36, 40, 44, 4096, 65535):
    def corrupt(peer, offset=offset):
        value = bytearray(peer.xnu)
        value[offset] ^= 1
        peer.xnu = bytes(value)
        peer.make_inputs()
    scenario(corrupt, after=lambda p, *_: runtime.require(not p.commands, 'Invalid XNU reached device'))


def bad_native(peer):
    peer.native_log = peer.native_log.replace(b'fixture', b'changed')
    peer.make_inputs()


scenario(bad_native)
scenario(lambda p: setattr(p, 'identity', p.identity.replace(b'houji', b'other')),
         after=lambda p, *_: runtime.require(len(p.commands) == 1 and p.log_writes == 0,
                                             'Foreign device received further commands'))
scenario(lambda p: (setattr(p, 'xnu', xnu_image(bytes(range(2, 18)))), p.make_inputs()))
scenario(lambda p: setattr(p, 'xnu', p.xnu[:-1] + b'Z'))  # Live differs from its archived bytes.
scenario(lambda p: setattr(p, 'native_log', p.native_log + b'Z'))
scenario(lambda p: setattr(p, 'helper_hash', '0' * 64))
scenario(lambda p: setattr(p, 'rw', True), after=lambda p, *_: runtime.require(not p.rw, 'Finally did not restore RO'))
scenario(lambda p: p.boot.update(boot_a='0' * 64))
scenario(lambda p: p.gpt.update({('/dev/block/sdc', 'backup'): bytes(4096)}))
scenario(lambda p: setattr(p, 'misc', bytes(4194304)))
scenario(lambda p: p.raw.__setitem__(4096 + 10, p.raw[4096 + 10] ^ 1))  # FAT copies disagree.
scenario(lambda p: p.raw.__setitem__(7 * 4096 + 100, p.raw[7 * 4096 + 100] ^ 1))


def unstable(peer):
    def inject(command, count):
        if command == '/tmp/houji-logfs-read' and count == 2:
            peer.raw[-1] ^= 1
    peer.injection = inject


scenario(unstable)


def fail_in_rw(peer):
    def inject(command, count):
        if command.startswith('dd if=/tmp/houji-xnu-log-'):
            assert peer.rw
            raise RuntimeError('Injected write failure with FAT mounted RW')
    peer.injection = inject


scenario(fail_in_rw, after=lambda p, prep, r: (
    runtime.require(not p.rw and not p.deleted, 'Failure did not preserve native archive/restore RO'),
    runtime.require((prep.receipts / 'logfs-before-reset.bin').stat().st_size == 8388608, 'Full backup absent'),
    runtime.require(r['protected_before'] == r['protected_after_failure'], 'Failed-path protected verification absent')))


def partial_write_failure(peer):
    def inject(command, count):
        if command.startswith('dd if=/tmp/houji-xnu-log-'):
            peer.xnu = b'P' * 4096 + peer.xnu[4096:]
            peer.raw[7 * 4096:8 * 4096] = b'P' * 4096
            peer.reset, peer.log_writes = True, 1
            raise RuntimeError('Injected partial fixed-file write')
    peer.injection = inject


scenario(partial_write_failure, after=lambda p, prep, r: (
    runtime.require(not p.rw and not p.deleted and p.log_writes == 1, 'Partial failure continued mutation'),
    runtime.require((prep.receipts / 'logfs-before-reset.bin').read_bytes()[7 * 4096:8 * 4096] != p.xnu[:4096],
                    'Prewrite complete backup was not retained')))


def after_primitive(peer, action):
    peer.primitive_after = lambda: action(peer)


scenario(lambda p: after_primitive(p, lambda q: q.raw.__setitem__(-1, 1)))
scenario(lambda p: after_primitive(p, lambda q: (q.native / 'native-ios-candidate/r138-allocation/HoujiLogAllocation.h').write_text('wrong header\n')))
scenario(lambda p: after_primitive(p, lambda q: setattr(q, 'native_log', q.native_log + b'changed')))


for kind in ('boot', 'gpt', 'misc'):
    def post_change(peer, kind=kind):
        def inject(command, count):
            if peer.deleted:
                if kind == 'boot':
                    peer.boot['boot_a'] = '0' * 64
                elif kind == 'gpt':
                    peer.gpt['/dev/block/sdf', 'backup'] = bytes(4096)
                else:
                    peer.misc = peer.misc[:1000] + b'Q' + peer.misc[1001:]
        peer.injection = inject
    scenario(post_change)


def ro_failure(peer):
    def inject(command, count):
        if peer.deleted and command == 'mount -o remount,ro /dev/logfs':
            peer.rw = True
            raise RuntimeError('Injected failed final remount')
    peer.injection = inject


scenario(ro_failure, after=lambda p, prep, r: runtime.require(r['finally_readonly_verified'] is False, 'RO failure accepted'))

# Validate the narrow raw-mutation boundary independently: data/timestamps only.
with tempfile.TemporaryDirectory() as temporary:
    peer = Peer(Path(temporary) / 'p', Path(temporary) / 'n')
    before = bytes(peer.raw)
    for offset, allowed in ((7 * 4096, True), (12288 + 13, True), (12288 + 22, True),
                            (12288 + 11, False), (12288 + 26, False), (4096, False),
                            (12320 + 22, False), (len(before) - 1, False)):
        after = bytearray(before)
        after[offset] ^= 1
        try:
            runtime.validate_in_place(before, bytes(after), peer.allocation)
            actual = True
        except RuntimeError:
            actual = False
        assert actual is allowed, (offset, actual, allowed)
        cases += 1

def history_fixture(peer):
    # Synthetic reviewed anchors exercise the exact real proof function. No
    # artifact hashes from these peers are accepted by the production history.
    # The real full capture-title grammar, distinct from other status labels.
    body = (b'HOUJI LOGFS r136: app diagnostic capture; not full OEM/XNU output\nfixture\n'
            b'r136 snapshot end; app text only; commit/readback follows\n')
    peer.native_log = body + (f'HOUJI LOGFS CHECKSUM: payload-bytes={len(body)} '
                              f'payload-crc32={zlib.crc32(body):08x}\n').encode()
    peer.make_inputs()
    c = peer.native / 'native-ios-candidate'
    frozen = c / 'r137-source'
    source = b'Print (L"HOUJI LOGFS r136: app diagnostic capture; not full OEM/XNU output\\n");\n'
    app = b'PE test owner\0' + ('HOUJI LOGFS r136: app diagnostic capture; not full OEM/XNU output\n\0').encode('utf-16le')
    dll = b'linked DLL peer\0' + app
    frozen.mkdir()
    (frozen / 'HoujiStorageProbe.c').write_bytes(source)
    other = frozen / 'uefi/Application/HoujiStorageProbe/HoujiStorageProbe.c'
    other.parent.mkdir(parents=True);other.write_bytes(source)
    for src, name in ((c / 'r137-policy.json', 'r137-policy.json'),
                      (c / 'r137-allocation/layout.json', 'layout.json')):
        (frozen / name).write_bytes(src.read_bytes())
    manifest = {str(p.relative_to(frozen)): sha(p.read_bytes()) for p in frozen.rglob('*') if p.is_file()}
    dump(frozen / 'source-manifest.json', manifest)
    (c / 'r137-qualified-app.efi').write_bytes(app);(c / 'r137-qualified-app.dll').write_bytes(dll)
    image, payload = b'anchored boot-image peer', b'anchored payload peer'
    images = peer.native / 'images';images.mkdir()
    ip, pp = images / 'houji-native-ios-r137.img', images / 'houji-native-ios-r137-ramdisk.img'
    ip.write_bytes(image);pp.write_bytes(payload)
    dump(ip.with_suffix('.json'), {'status': 'offline-image-checks-passed', 'device': 'houji',
        'sha256': {'image': sha(image)}, 'bytes': len(image), 'ramdisk_sha256': sha(payload),
        'native_storage_policy': peer.policy})
    dump(pp.with_suffix('.json'), {'sha256': sha(payload), 'bytes': len(payload),
        'files': {'Payloads/StorageProbe.efi': sha(app)}, 'native_storage_policy': peer.policy})
    anchor = {'app': sha(app), 'app_dll': sha(dll), 'image': sha(image),
        'source_manifest': sha((frozen / 'source-manifest.json').read_bytes()),
        'image_metadata': sha(ip.with_suffix('.json').read_bytes()),
        'payload_metadata': sha(pp.with_suffix('.json').read_bytes()),
        'native': sha(peer.native_log), 'native_crc32': reader.verify_native_snapshot(peer.native_log)['actual_crc32'],
        'xnu': sha(peer.xnu), 'run_id': peer.old_id.hex()}
    return {'peer': peer, 'anchor': anchor, 'frozen': frozen, 'image': ip,
            'payload': pp, 'app': c / 'r137-qualified-app.efi', 'dll': c / 'r137-qualified-app.dll'}


def history_json(ctx, path, change, repin=None):
    value = json.loads(path.read_text());change(value);dump(path, value)
    if repin:ctx['anchor'][repin] = sha(path.read_bytes())


def history_scenario(change=None, enabled=True, registered=True, ok=False):
    global cases
    with tempfile.TemporaryDirectory() as temporary:
        project, native = Path(temporary) / 'p', Path(temporary) / 'n'
        project.mkdir();peer = Peer(project, native);ctx = history_fixture(peer)
        if change:change(ctx)
        inputs = {p: p.read_bytes() for p in native.rglob('*') if p.is_file()}
        with patch.object(runtime, 'QUALIFIED_NATIVE_LABEL_HISTORY', {137: ctx['anchor']} if registered else {}):
            preparation = runtime.RuntimePreparation(138, 5038, project, native,
                transport=peer, reader=reader, previous_native_label_from_qualified_app=enabled)
            error = None
            try:preparation.archive_inputs();actual = True
            except (RuntimeError, OSError, ValueError) as caught:actual = False;error = str(caught)
        assert actual is ok and not peer.commands and not peer.pushes, error
        assert all(p.read_bytes() == data for p, data in inputs.items())
        proof = preparation.receipts / 'previous-native-label-provenance.json'
        assert proof.exists() is ok
        if ok:
            value = json.loads(proof.read_text())
            assert value['mode'] == 'explicit-qualified-app-history' and value['source_files_verified'] == 4
            assert value['expected_label'] == 'r137' and 'r136:' in value['actual_capture_title']
            assert value == preparation.state['previous_native_label_provenance']
        cases += 1


history_scenario(ok=True)
history_scenario(enabled=False)
history_scenario(registered=False)
for key in ('app', 'dll', 'image', 'payload'):
    history_scenario(lambda c, key=key: c[key].write_bytes(c[key].read_bytes() + b'changed'))
history_scenario(lambda c: (c['frozen'] / 'HoujiStorageProbe.c').write_bytes(b'changed'))
history_scenario(lambda c: (c['frozen'] / 'source-manifest.json').write_text('{}'))
for bad_path in ('../foreign', '/absolute-foreign'):
    history_scenario(lambda c, key=bad_path: history_json(c, c['frozen'] / 'source-manifest.json',
        lambda j: j.update({key: '0' * 64}), 'source_manifest'))
for metadata, field in (('image', 'image_metadata'), ('payload', 'payload_metadata')):
    history_scenario(lambda c, k=metadata: c[k].with_suffix('.json').write_text('{}'))
    history_scenario(lambda c, k=metadata, f=field: history_json(c, c[k].with_suffix('.json'),
        lambda j: j.update(native_storage_policy={}), f))
history_scenario(lambda c: history_json(c, c['payload'].with_suffix('.json'),
    lambda j: j['files'].update({'Payloads/StorageProbe.efi': '0' * 64}), 'payload_metadata'))
history_scenario(lambda c: history_json(c, c['image'].with_suffix('.json'),
    lambda j: j['sha256'].update(image='0' * 64), 'image_metadata'))
history_scenario(lambda c: c['anchor'].update(run_id='f' * 32))
history_scenario(lambda c: c['anchor'].update(native_crc32='0' * 8))
history_scenario(lambda c: c['anchor'].update(xnu='0' * 64))
history_scenario(lambda c: c['anchor'].update(native='0' * 64))


def duplicate_source_title(ctx):
    for name in ('HoujiStorageProbe.c', 'uefi/Application/HoujiStorageProbe/HoujiStorageProbe.c'):
        p = ctx['frozen'] / name;p.write_bytes(p.read_bytes() * 2)
    manifest = ctx['frozen'] / 'source-manifest.json'
    history_json(ctx, manifest, lambda j: j.update({name: sha((ctx['frozen'] / name).read_bytes())
        for name in ('HoujiStorageProbe.c', 'uefi/Application/HoujiStorageProbe/HoujiStorageProbe.c')}), 'source_manifest')


def duplicate_app_title(ctx):
    ctx['app'].write_bytes(ctx['app'].read_bytes() * 2)
    ctx['anchor']['app'] = sha(ctx['app'].read_bytes())


def wrong_native_title(ctx, extra_expected=False):
    peer = ctx['peer']
    body = peer.native_log[:peer.native_log.index(b'HOUJI LOGFS CHECKSUM:')].replace(b'r136', b'r135')
    if extra_expected:body += b'HOUJI LOGFS r137: must not skip explicit provenance\n'
    peer.native_log = body + (f'HOUJI LOGFS CHECKSUM: payload-bytes={len(body)} '
                             f'payload-crc32={zlib.crc32(body):08x}\n').encode()
    peer.make_inputs();ctx['anchor']['native'] = sha(peer.native_log)
    ctx['anchor']['native_crc32'] = reader.verify_native_snapshot(peer.native_log)['actual_crc32']


history_scenario(duplicate_source_title)
history_scenario(duplicate_app_title)
history_scenario(wrong_native_title)
history_scenario(lambda c: wrong_native_title(c, True))
for action in (lambda j: j['native_snapshot_integrity'].update(valid=False),
               lambda j: j['xnu_snapshot_integrity'].update(committed=False),
               lambda j: j['xnu_snapshot_integrity'].update(run_id='f' * 32)):
    history_scenario(lambda c, action=action: history_json(c,
        c['peer'].native / 'evidence/logfs-recovery-r137/capture.json', action))

print(f'PASS: {cases} actual coordinator/primitive/FAT/CRC/qualified-label scenarios; no device subprocess escaped; '
      'committed-only binding, exact file reuse, complete backups, protected-state checks, '
      'failure receipts, finally-RO and immutable run destinations verified.')
