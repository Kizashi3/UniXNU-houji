#!/usr/bin/env python3
"""Archive/bind a committed XNU run and prepare its next fixed log allocation.

This tool never builds, changes policy/source, arms BCB, boots, or restores a raw
partition. Failed preparation is terminal for that run number: retain its
receipt and all backups, investigate, and do not boot the candidate.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import zlib

P = Path('${HOUJI_PORT_ROOT}')
N = Path('${HOUJI_ARTIFACTS}/native-port')
ADB = '${USER_HOME}/Library/Android/sdk/platform-tools/adb'
SERIAL = 'DEVICE_SERIAL'
HELPER_SHA = '716048584c1c6e85e64335e9528704f0e80c46a893f0e3e5d723bb3bd778b6a0'
LOGFS_BYTES = 8388608
MISC_BYTES = 4194304

# r200 stopped at the first live/archive comparison, before the reset primitive.
# Exact receipt retained; its failed state is never reused or marked successful.
QUALIFIED_READONLY_PREPARATION_FAILURES = {
    200: '185920c2e2e5188a13b1716ac49cfec6a7216ccde8fee61e73a9e9faba6793e5',
}

# Explicit historical exception, independently qualified BEFORE this option
# existed. No label supplied by a caller or a mutable metadata file is trusted.
# A later exception needs its own reviewed immutable artifact anchors.
QUALIFIED_NATIVE_LABEL_HISTORY = {140: {
    'app': '96434567134854b6e26ecb83e85eac9ce3fff033654d93eb9f608c124ce46246',
    'app_dll': '526985b6335b383d967bcd3dff392bf86d18c64d0a3585560d53d892a860d30e',
    'image': '038d1d4439eea3ab86735421f5801aab2d73b8cb6fbea78f2bbaa8fb636d09ea',
    'source_manifest': 'c9b0c569fc0643c4f3fdaf7d0f00ab7d27b3427d0202c907d8d20655c706e984',
    'image_metadata': 'cea198aa8857d2d96ad1707fa89e6d6ecbbf02e940633d8159814f7ec25361f6',
    'payload_metadata': '90774df3d2e863ae52b490b522d5d85aa3792042e4fbc71af8646137fb3ad07c',
    'native': '12059f012e3a9ce7f03da6dcc750801435a63421992363c5665af280f77b97d0',
    'native_crc32': 'e099019c',
    'xnu': '688a822a14d730dca0f1fb7de34c0b504e3cbefd74bf36f3880af33942866b3b',
    'run_id': '53b2d349a87d41fd8066478fc9556b6f',
}}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def write_new(path, data):
    with path.open('xb') as stream:
        stream.write(data)


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def qualified_previous_native_label(native_root, previous, policy_bytes, allocation_bytes,
                                    native_bytes, xnu_bytes, native_integrity, xnu_integrity):
    """Offline proof of a known historical title bug, never an arbitrary override.

    The source freeze and qualified app/image/metadata are anchored separately;
    self-consistent edited manifests cannot approve a different artifact set.
    CRC-valid native and committed XNU files must be this exact captured run.
    """
    anchor = QUALIFIED_NATIVE_LABEL_HISTORY.get(previous)
    require(anchor is not None, 'No reviewed qualified-App native label exception for this previous run')
    n = Path(native_root)
    c = n / 'native-ios-candidate'
    frozen = c / f'r{previous}-source'
    manifest_bytes = (frozen / 'source-manifest.json').read_bytes()
    require(digest(manifest_bytes) == anchor['source_manifest'], 'Previous source freeze anchor differs')
    manifest = json.loads(manifest_bytes)
    require(isinstance(manifest, dict) and 0 < len(manifest) <= 10000, 'Previous source freeze is invalid')
    for name, expected in manifest.items():
        relative = Path(name)
        require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected) and
                not relative.is_absolute() and '..' not in relative.parts and
                (frozen / relative).resolve().is_relative_to(frozen.resolve()),
                'Unsafe previous source freeze entry')
        require(digest((frozen / relative).read_bytes()) == expected, 'Frozen source differs: ' + name)
    require((frozen / f'r{previous}-policy.json').read_bytes() == policy_bytes and
            (frozen / 'layout.json').read_bytes() == allocation_bytes,
            'Previous policy/allocation is not the qualified source freeze')
    app = (c / f'r{previous}-qualified-app.efi').read_bytes()
    require(digest(app) == anchor['app'] and
            digest((c / f'r{previous}-qualified-app.dll').read_bytes()) == anchor['app_dll'],
            'Previous qualified App/DLL differs')
    source = (frozen / 'HoujiStorageProbe.c').read_bytes()
    require(source == (frozen / 'uefi/Application/HoujiStorageProbe/HoujiStorageProbe.c').read_bytes(),
            'Frozen App source copies disagree')
    titles = re.findall(rb'Print\s*\(\s*L"(HOUJI LOGFS r[0-9]+: app diagnostic capture; not full OEM/XNU output\\n)"\s*\);', source)
    require(len(titles) == 1, 'Qualified source has no unique native capture title')
    title = titles[0].replace(b'\\n', b'\n')
    app_titles = re.findall(re.escape('HOUJI LOGFS r'.encode('utf-16le')) +
        rb'(?:[0-9]\x00){1,4}' + re.escape(': app diagnostic capture; not full OEM/XNU output\n\0'.encode('utf-16le')), app)
    require(len(app_titles) == 1 and app_titles[0] == (title + b'\0').decode().encode('utf-16le'),
            'Qualified App has no unique matching native capture title')
    native_titles = re.findall(rb'^HOUJI LOGFS r[0-9]+: app diagnostic capture; not full OEM/XNU output\r?$', native_bytes, re.M)
    require(len(native_titles) == 1 and native_bytes.splitlines()[0] == native_titles[0].rstrip(b'\r') and
            native_titles[0].rstrip(b'\r') + b'\n' == title,
            'Captured native title is not the qualified App title')
    image_bytes = (n / f'images/houji-native-ios-r{previous}.img').read_bytes()
    image_metadata_bytes = (n / f'images/houji-native-ios-r{previous}.json').read_bytes()
    payload_bytes = (n / f'images/houji-native-ios-r{previous}-ramdisk.img').read_bytes()
    payload_metadata_bytes = (n / f'images/houji-native-ios-r{previous}-ramdisk.json').read_bytes()
    require(digest(image_bytes) == anchor['image'] and digest(image_metadata_bytes) == anchor['image_metadata'] and
            digest(payload_metadata_bytes) == anchor['payload_metadata'], 'Previous image/metadata anchors differ')
    image, payload, policy = map(json.loads, (image_metadata_bytes, payload_metadata_bytes, policy_bytes))
    require(image.get('status') == 'offline-image-checks-passed' and image.get('device') == 'houji' and
            image.get('sha256', {}).get('image') == anchor['image'] and image.get('bytes') == len(image_bytes) and
            image.get('ramdisk_sha256') == payload.get('sha256') == digest(payload_bytes) and
            payload.get('bytes') == len(payload_bytes) and payload.get('files', {}).get('Payloads/StorageProbe.efi') == anchor['app'] and
            image.get('native_storage_policy') == payload.get('native_storage_policy') == policy,
            'Previous app/image/payload/policy binding differs')
    require(policy.get('log_run_id') == anchor['run_id'] and digest(native_bytes) == anchor['native'] and
            digest(xnu_bytes) == anchor['xnu'] and native_integrity.get('valid') is True and
            native_integrity.get('actual_crc32') == native_integrity.get('expected_crc32') == anchor['native_crc32'] and
            xnu_integrity.get('valid') is True and xnu_integrity.get('committed') is True and
            xnu_integrity.get('expected_run_id_matches') is True and xnu_integrity.get('run_id') == anchor['run_id'],
            'Historical exception is not the exact CRC-valid committed captured run')
    return {'mode': 'explicit-qualified-app-history', 'previous_run': previous,
            'expected_label': f'r{previous}', 'actual_capture_title': title.decode().rstrip(),
            'reviewed_artifact_anchors': dict(anchor), 'source_files_verified': len(manifest),
            'policy_sha256': digest(policy_bytes), 'allocation_sha256': digest(allocation_bytes),
            'native_integrity': native_integrity, 'xnu_integrity': xnu_integrity}


def mounted_logfs(raw, require_ro=False):
    rows = [line.split() for line in raw.decode().splitlines()
            if len(line.split()) >= 4 and line.split()[1] == '/dev/logfs']
    require(len(rows) == 1 and rows[0][0] in (
        '/dev/block/sda13', '/dev/block/by-name/logfs',
        '/dev/block/bootdevice/by-name/logfs') and rows[0][2] == 'vfat',
        'Expected unique OEM FAT mount absent')
    options = rows[0][3].split(',')
    if require_ro:
        require('ro' in options and 'rw' not in options, 'logfs is not read-only')
    return rows[0]


def file_from_raw(raw, allocation):
    return b''.join(raw[(lba - 4096) * 4096:(lba - 4096 + 1) * 4096]
                    for lba in allocation['lbas'])


def validate_in_place(before, after, allocation):
    """The reuse primitive may change file bytes and its FAT timestamps only."""
    require(len(before) == len(after) == LOGFS_BYTES, 'Raw partition size differs')
    a, b = bytearray(before), bytearray(after)
    for lba in allocation['lbas']:
        offset = (lba - 4096) * 4096
        a[offset:offset + 4096] = b'\0' * 4096
        b[offset:offset + 4096] = b'\0' * 4096
    entries = [offset for offset in range(3 * 4096, 7 * 4096, 32)
               if before[offset:offset + 11] == b'XNULOG  BIN']
    require(len(entries) == 1, 'Unique XnuLog directory entry absent')
    # Creation/access/write timestamps may be updated by the mounted FAT driver.
    for lo, hi in ((13, 20), (22, 26)):
        offset = entries[0]
        a[offset + lo:offset + hi] = b'\0' * (hi - lo)
        b[offset + lo:offset + hi] = b'\0' * (hi - lo)
    require(a == b, 'Reuse changed bytes outside XnuLog data/timestamps')


class AdbTransport:
    def __init__(self, port, event):
        self.port, self.event = port, event

    def root(self, command):
        ports = [self.port] + [p for p in (5037, 5038, 5047, 15049) if p != self.port]
        for port in ports:
            result = subprocess.run([ADB, '-P', str(port), '-s', SERIAL,
                                     'exec-out', command], capture_output=True, timeout=40)
            self.event('adb', command=command, port=port, code=result.returncode,
                       bytes=len(result.stdout), sha256=digest(result.stdout),
                       stderr=result.stderr.decode(errors='replace'))
            missing = result.returncode and any(marker in result.stderr for marker in
                (b'not found', b'device offline', b'no devices/emulators'))
            if missing:
                continue
            require(result.returncode == 0 and not result.stderr,
                    'ADB operation failed; do not boot: ' + command)
            self.port = port
            return result.stdout
        raise RuntimeError('No existing ADB server has the verified rescue device')

    def push(self, source, destination):
        result = subprocess.run([ADB, '-P', str(self.port), '-s', SERIAL, 'push',
                                 str(source), destination], capture_output=True, timeout=40)
        self.event('adb-push', source=str(source), destination=destination,
                   code=result.returncode, source_sha256=digest(source.read_bytes()))
        require(result.returncode == 0, 'Helper transfer failed')


def validate_uncommitted_snapshot(capture, policy, allocation, data, initial):
    """No result is inferred: accept only the exact never-committed trial marker."""
    run_id=policy.get('log_run_id')
    require(isinstance(run_id,str) and re.fullmatch('[0-9a-f]{32}',run_id), 'Uncommitted run UUID invalid')
    require(allocation.get('run_id')==run_id and len(data)==65536 and data==initial and
            digest(data)==policy.get('log_initial_sha256')==allocation.get('initial_sha256') and
            data[:8]==b'HJXNU001' and struct.unpack_from('<II',data,8)==(0,1) and
            data[16:32].hex()==run_id and not any(data[32:]),
            'Previous snapshot is not the exact pristine allocation marker')
    native=[r for r in capture.get('files',[]) if r.get('file')=='UniXNU.log']
    xnu=[r for r in capture.get('files',[]) if r.get('file')=='XnuLog.bin']
    require(len(native)==1 and native[0].get('status')=='missing' and
            capture.get('native_log_file_present') is False and len(xnu)==1 and
            xnu[0].get('status')=='captured' and xnu[0].get('stable') is True and
            xnu[0].get('bytes')==65536 and xnu[0].get('sha256')==digest(data),
            'Pristine snapshot capture/absence proof differs')
    return {'scope':'No committed UEFI/XNU result; not a GPU success or proof of no execution',
            'pristine_marker_sha256':digest(data),'run_id':run_id,'native_log_absent':True}

class RuntimePreparation:
    def __init__(self, run, port, project=P, native=N, transport=None,
                 reader=None, allocator=None, preflight=None, primitive=None,
                 previous_native_label_from_qualified_app=False, previous_uncommitted_snapshot=False,
                 previous_run=None, previous_native_only=False, previous_capture=None):
        require(138 <= run <= 9999 and port in (5037, 5038, 5047, 15049), 'Invalid run/port')
        self.run, self.previous = run, run - 1 if previous_run is None else previous_run
        require(137 <= self.previous < run, 'Invalid previous run')
        if self.previous != run - 1:
            for skipped in range(self.previous + 1, run):
                receipt_path = Path(native) / f'evidence/xnu-runtime-prepare-r{skipped}/receipt.json'
                receipt_bytes = receipt_path.read_bytes()
                receipt = json.loads(receipt_bytes)
                reviewed_readonly = (digest(receipt_bytes) == QUALIFIED_READONLY_PREPARATION_FAILURES.get(skipped)
                    and receipt.get('status') == 'FAILED_DO_NOT_BOOT'
                    and receipt.get('stage') == 'archived-inputs-validated'
                    and receipt.get('raw_partition_writes') is False
                    and receipt.get('source_or_policy_modified') is False
                    and receipt.get('finally_readonly_verified') is True
                    and receipt.get('error') == 'Live file differs from archived evidence: XnuLog.bin'
                    and not (Path(native) / f'native-ios-candidate/r{skipped}-allocation').exists()
                    and not (Path(native) / f'logfs-backup-before-native-ios-r{skipped}').exists())
                # Archiving input files is offline. A missing rescue connection
                # before identity validation cannot have reached a phone write.
                # Retain that failed run and start a new one from the last boot.
                pre_device_connection_failure = (
                    receipt.get('status') == 'FAILED_DO_NOT_BOOT'
                    and receipt.get('stage') == 'archived-inputs-validated'
                    and receipt.get('device_identity_verified') is False
                    and receipt.get('raw_partition_writes') is False
                    and receipt.get('source_or_policy_modified') is False
                    and receipt.get('finally_readonly_verified') is None
                    and 'protected_before' not in receipt
                    and receipt.get('error') == 'No existing ADB server has the verified rescue device'
                    and not (Path(native) / f'native-ios-candidate/r{skipped}-allocation').exists()
                    and not (Path(native) / f'logfs-backup-before-native-ios-r{skipped}').exists())
                require(receipt.get('boot_started') is False and receipt.get('ready_for_assembly') is False and
                        (receipt.get('stage') == 'created' or reviewed_readonly or pre_device_connection_failure) and
                        not (Path(native) / f'images/houji-native-ios-r{skipped}.img').exists(),
                        'Skipped run is not a failed pre-device preparation')
        self.previous_native_only = previous_native_only
        self.previous_native_label_from_qualified_app = previous_native_label_from_qualified_app
        self.previous_uncommitted_snapshot = previous_uncommitted_snapshot
        self.p, self.n = Path(project), Path(native)
        self.previous_capture = Path(previous_capture).resolve() if previous_capture else None
        if self.previous_capture:
            require(self.previous_capture.is_relative_to((self.n / 'evidence').resolve()) and
                    self.previous_capture.is_dir(), 'Previous capture must be an archived local evidence directory')
        self.c = self.n / 'native-ios-candidate'
        self.output = self.c / f'r{run}-allocation'
        self.backup = self.n / f'logfs-backup-before-native-ios-r{run}'
        self.receipts = self.n / f'evidence/xnu-runtime-prepare-r{run}'
        for path in (self.output, self.backup, self.receipts):
            require(not path.exists(), 'Destination exists; retain it and do not reuse this run: ' + str(path))
        self.receipts.mkdir(parents=True, mode=0o700)
        write_new(self.receipts / 'events.jsonl', b'')
        self.state = {'run': f'r{run}', 'previous_run': f'r{self.previous}',
                      'status': 'INCOMPLETE_DO_NOT_BOOT', 'stage': 'created',
                      'boot_started': False, 'source_or_policy_modified': False,
                      'ready_for_assembly': False, 'raw_partition_writes': False,
                      'device_identity_verified': False, 'finally_readonly_verified': None,
                      'coordinator_sha256': digest(Path(__file__).read_bytes()),
                      'direct_read_helper_sha256': HELPER_SHA,
                      'previous_native_label_from_qualified_app_requested': bool(previous_native_label_from_qualified_app),
                      'paths': {'allocation': str(self.output), 'backup': str(self.backup)}}
        self.transport = transport or AdbTransport(port, self.event)
        self.reader, self.allocator, self.preflight = reader, allocator, preflight
        self.primitive = primitive or self.run_primitive
        self.verified_device = False
        self.save()

    def event(self, kind, **fields):
        record = {'time': datetime.datetime.now().astimezone().isoformat(),
                  'kind': kind, **fields}
        with (self.receipts / 'events.jsonl').open('ab') as stream:
            stream.write((json.dumps(record, ensure_ascii=False) + '\n').encode())

    def save(self, **fields):
        self.state.update(fields)
        self.state['updated_at'] = datetime.datetime.now().astimezone().isoformat()
        temp = self.receipts / 'receipt.json.new'
        write_new(temp, json_bytes(self.state))
        temp.replace(self.receipts / 'receipt.json')

    def root(self, command):
        return self.transport.root(command)

    def stable_raw(self):
        first, second = self.root('/tmp/houji-logfs-read'), self.root('/tmp/houji-logfs-read')
        require(len(first) == LOGFS_BYTES and first == second,
                'Complete O_DIRECT logfs reads are not stable; do not boot')
        return first

    def archive_inputs(self):
        capture_dir = self.previous_capture or self.n / f'evidence/logfs-recovery-r{self.previous}'
        capture_bytes = (capture_dir / 'capture.json').read_bytes()
        policy_bytes = (self.c / f'r{self.previous}-policy.json').read_bytes()
        allocation_bytes = (self.c / f'r{self.previous}-allocation/layout.json').read_bytes()
        capture, policy, allocation = map(json.loads, (capture_bytes, policy_bytes, allocation_bytes))
        run_id = policy.get('log_run_id')
        require(policy.get('log_file') == 'XnuLog.bin' and
                isinstance(run_id, str) and re.fullmatch('[0-9a-f]{32}', run_id), 'Previous policy log identity invalid')
        require(allocation.get('run_id') == run_id and
                allocation.get('lbas') == policy.get('log_data_lbas') and
                allocation.get('file_bytes') == 65536 and
                allocation.get('physical_lun') == 0, 'Previous allocation/policy identity differs')
        if self.previous_native_only:
            require(not self.previous_uncommitted_snapshot and not self.previous_native_label_from_qualified_app,
                    'Conflicting previous-evidence modes')
            files = {name:(capture_dir/name).read_bytes() for name in ('XnuLog.bin','UniXNU.log')}
            initial=(self.c/f'r{self.previous}-allocation/XnuLog.initial.bin').read_bytes()
            require(files['XnuLog.bin']==initial and digest(initial)==allocation['initial_sha256']==policy['log_initial_sha256'],
                    'Native-only XNU is not the exact pristine marker')
            for name,data in files.items():
                rows=[row for row in capture['files'] if row.get('file')==name]
                require(len(rows)==1 and rows[0].get('stable') is True and rows[0].get('status')=='captured' and
                        rows[0].get('sha256')==digest(data) and rows[0].get('bytes')==len(data), 'Native-only capture differs')
            integrity=self.reader.verify_native_snapshot(files['UniXNU.log'])
            require(integrity.get('valid') is True and f'HOUJI LOGFS r{self.previous}:'.encode() in files['UniXNU.log'],
                    'Native-only CRC/title differs')
            for name,data in (('previous-capture.json',capture_bytes),('previous-policy.json',policy_bytes),
                              ('previous-allocation.json',allocation_bytes),*files.items()):write_new(self.receipts/name,data)
            self.save(stage='archived-native-only-inputs-validated',previous_run_id=run_id,
                      native_integrity=integrity,xnu_integrity={'valid':False,'committed':False,'run_id':run_id},
                      evidence_scope='Valid UEFI checkpoint; no committed XNU snapshot, no GPU/CPU success inferred')
            return policy,allocation,files
        if self.previous_uncommitted_snapshot:
            require(not self.previous_native_label_from_qualified_app,'Conflicting previous-evidence modes')
            data=(capture_dir/'XnuLog.bin').read_bytes()
            initial=(self.c/f'r{self.previous}-allocation/XnuLog.initial.bin').read_bytes()
            proof=validate_uncommitted_snapshot(capture,policy,allocation,data,initial)
            require(not (capture_dir/'UniXNU.log').exists(),'Unexpected native evidence must be retained and decoded')
            files={'XnuLog.bin':data}
            for name,b in (('previous-capture.json',capture_bytes),('previous-policy.json',policy_bytes),
                           ('previous-allocation.json',allocation_bytes),('XnuLog.bin',data)):
                write_new(self.receipts/name,b)
            write_new(self.receipts/'previous-uncommitted-proof.json',json_bytes(proof))
            self.save(stage='archived-uncommitted-inputs-validated',previous_run_id=run_id,
                      previous_uncommitted_proof=proof,previous_inputs={'capture.json':digest(capture_bytes),
                      'policy.json':digest(policy_bytes),'layout.json':digest(allocation_bytes),'XnuLog.bin':digest(data)},
                      native_integrity=None,xnu_integrity={'valid':False,'committed':False,'run_id':run_id})
            return policy,allocation,files
        files = {}
        for name in ('XnuLog.bin', 'UniXNU.log'):
            matches = [x for x in capture.get('files', []) if x.get('file') == name]
            require(len(matches) == 1, 'Captured file absent/duplicated: ' + name)
            row, data = matches[0], (capture_dir / name).read_bytes()
            require(row.get('status') == 'captured' and row.get('stable') is True and
                    row.get('bytes') == len(data) and row.get('sha256') == digest(data),
                    'Archived file is not a stable exact capture: ' + name)
            files[name] = data
        native = self.reader.verify_native_snapshot(files['UniXNU.log'])
        xnu, payload = self.reader.decode_xnu_snapshot(files['XnuLog.bin'], run_id)
        require(native.get('valid') is True, 'Previous native CRC/run identity invalid')
        require(xnu.get('valid') is True and xnu.get('committed') is True and
                xnu.get('expected_run_id_matches') is True and payload is not None,
                'Previous XNU is not a CRC-valid committed snapshot of the expected run')
        require(capture.get('native_snapshot_integrity') == native and
                capture.get('xnu_snapshot_integrity') == xnu,
                'Capture receipt disagrees with re-decoded snapshots')
        if self.previous_native_label_from_qualified_app is True:
            proof = qualified_previous_native_label(self.n, self.previous, policy_bytes, allocation_bytes,
                files['UniXNU.log'], files['XnuLog.bin'], native, xnu)
            write_new(self.receipts / 'previous-native-label-provenance.json', json_bytes(proof))
            self.save(previous_native_label_provenance=proof)
        else:
            require(f'HOUJI LOGFS r{self.previous}:'.encode() in files['UniXNU.log'],
                    'Previous native CRC/run identity invalid; qualified-App history override is not enabled')
        for name, data in (('previous-capture.json', capture_bytes), ('previous-policy.json', policy_bytes),
                           ('previous-allocation.json', allocation_bytes), *files.items()):
            write_new(self.receipts / name, data)
        write_new(self.receipts / 'XnuLog.txt', payload)
        self.save(stage='archived-inputs-validated', previous_run_id=run_id,
                  previous_inputs={name: digest(data) for name, data in
                      (('capture.json', capture_bytes), ('policy.json', policy_bytes),
                       ('layout.json', allocation_bytes), *files.items())},
                  native_integrity=native, xnu_integrity=xnu)
        return policy, allocation, files

    def protected(self, label):
        folder = self.receipts / label
        folder.mkdir(mode=0o700)
        boot = self.preflight.BOOT
        require(len(boot) == 5 and all(re.fullmatch('[a-z0-9_]+', n) and
                re.fullmatch('[0-9a-f]{64}', s) for n, s in boot.items()), 'Pinned boot policy differs')
        for name, expected in boot.items():
            require(self.root('sha256sum /dev/block/by-name/' + name).split() ==
                    [expected.encode(), ('/dev/block/by-name/' + name).encode()],
                    'Protected boot partition differs: ' + name)
        disks = json.loads((self.n / 'partition-backup-20261024/manifest.json').read_text())['disks']
        require(len(disks) == 6 and len({d['device'] for d in disks}) == 6, 'Expected six physical LUNs')
        gpt = []
        for index, disk in enumerate(disks):
            require(re.fullmatch('/dev/block/sd[a-f]', disk['device']), 'Unexpected pinned GPT device')
            for suffix, skip in (('primary', 0), ('backup', disk['backup_start_lba'])):
                require(isinstance(skip, int) and skip >= 0, 'Invalid GPT backup offset')
                expected = self.preflight.expected_gpt(disk, suffix)
                require(expected and len(expected) % 4096 == 0, 'Pinned GPT extent differs')
                actual = self.root(f'dd if={disk["device"]} bs=4096 skip={skip} count={len(expected) // 4096} status=none')
                require(actual == expected, 'Protected GPT differs: ' + disk['device'] + '-' + suffix)
                write_new(folder / f'gpt-{index}-{suffix}.bin', actual)
                gpt.append({'device': disk['device'], 'kind': suffix,
                            'bytes': len(actual), 'sha256': digest(actual)})
        misc = self.root('cat /dev/block/by-name/misc')
        require(len(misc) == MISC_BYTES and misc == self.root('cat /dev/block/by-name/misc'), 'misc is not stable')
        baseline = (self.n / f'device-baseline/misc-before-native-ios-r{self.previous}.bin').read_bytes()
        require(len(baseline) == MISC_BYTES and misc[864:] == baseline[864:], 'misc reserved/A-B bytes differ')
        write_new(folder / 'misc.bin', misc)
        state = {'boot': dict(boot), 'gpt': gpt, 'misc_bytes': len(misc),
                 'misc_sha256': digest(misc), 'misc_reserved_sha256': digest(misc[864:])}
        write_new(folder / 'state.json', json_bytes(state))
        return state

    def run_primitive(self, command):
        result = subprocess.run(command, capture_output=True, timeout=240)
        write_new(self.receipts / 'primitive.stdout.log', result.stdout)
        write_new(self.receipts / 'primitive.stderr.log', result.stderr)
        self.event('prepare-fixed-file', command=command, code=result.returncode,
                   stdout_sha256=digest(result.stdout), stderr_sha256=digest(result.stderr))
        require(result.returncode == 0, 'Fixed-file reset primitive failed; do not boot')

    def run_preparation(self):
        error = None
        before = None
        pending_backup = None
        try:
            self.reader = self.reader or module(self.p / 'scripts/capture-logfs.py', 'runtime_capture')
            self.allocator = self.allocator or module(self.p / 'scripts/prepare-xnu-log.py', 'runtime_allocator')
            self.preflight = self.preflight or module(self.p / 'scripts/try-native-userland-boot.py', 'runtime_preflight')
            self.state['dependency_sha256'] = {
                label: digest(Path(dependency.__file__).read_bytes())
                for label, dependency in (('capture', self.reader), ('allocation', self.allocator),
                                          ('protected_policy', self.preflight))
                if getattr(dependency, '__file__', None)}
            policy, previous_allocation, files = self.archive_inputs()
            identity = self.root('id -u; getprop ro.product.device; getprop ro.houji.native_rescue; '
                                 'readlink -f /dev/block/by-name/logfs; blockdev --getsize64 /dev/block/by-name/logfs')
            require(identity.splitlines() == [b'0', b'houji', b'1', b'/dev/block/sda13', b'8388608'],
                    'Verified root houji rescue identity absent')
            mounts = self.root('cat /proc/mounts')
            mounted_logfs(mounts)
            self.verified_device = True
            self.state['device_identity_verified'] = True
            mounted_logfs(mounts, require_ro=True)
            before = self.protected('protected-before')
            for name, data in files.items():
                require(self.root('cat /dev/logfs/' + name) == data, 'Live file differs from archived evidence: ' + name)
            helper = self.n / 'native-log-candidate/logfs-direct-read'
            require(digest(helper.read_bytes()) == HELPER_SHA, 'Local O_DIRECT helper differs')
            exists = self.root('if [ -e /tmp/houji-logfs-read ]; then echo PRESENT; else echo ABSENT; fi').strip()
            if exists == b'ABSENT':
                self.transport.push(helper, '/tmp/houji-logfs-read')
                self.root('chmod 755 /tmp/houji-logfs-read')
            else:
                require(exists == b'PRESENT', 'Helper existence response invalid')
            require(self.root('sha256sum /tmp/houji-logfs-read').split() ==
                    [HELPER_SHA.encode(), b'/tmp/houji-logfs-read'], 'Remote O_DIRECT helper differs')
            raw_before = self.stable_raw()
            actual_allocation = self.allocator.layout(raw_before)
            require(all(actual_allocation[k] == previous_allocation[k] for k in
                        ('clusters', 'lbas', 'file_bytes', 'physical_lun', 'short_name')),
                    'Actual fixed FAT allocation differs from previous run')
            require(file_from_raw(raw_before, actual_allocation) == files['XnuLog.bin'],
                    'Raw XnuLog differs from the archived mounted file')
            write_new(self.receipts / 'logfs-before-reset.bin', raw_before)
            self.save(stage='prewrite-proof-complete', protected_before=before,
                      complete_before_sha256=digest(raw_before), device_log_write_attempted=True)
            header = self.output / 'HoujiLogAllocation.h'
            command = [sys.executable, str(self.p / 'scripts/prepare-xnu-log.py'),
                       '--adb-port', str(self.transport.port), '--recovery',
                       '--reuse-sha256', digest(files['XnuLog.bin']),
                       '--output', str(self.output), '--header', str(header)]
            self.primitive(command)
            initial = (self.output / 'XnuLog.initial.bin').read_bytes()
            layout = json.loads((self.output / 'layout.json').read_text())
            require(len(initial) == 65536 and initial[:8] == b'HJXNU001' and
                    struct.unpack_from('<II', initial, 8) == (0, 1) and not any(initial[32:]) and
                    initial[16:32].hex() == layout['run_id'] != policy['log_run_id'] and
                    digest(initial) == layout['initial_sha256'] and header.is_file(),
                    'New initial marker/header qualification failed')
            crc = zlib.crc32(initial)
            expected_header = ('// Generated from verified FAT allocation; one explicitly bound trial.\n'
                'static const uint8_t kHoujiLogRunId[16] = {' + ','.join(str(x) for x in initial[16:32]) + '};\n'
                'static const uint16_t kHoujiLogClusters[16] = {' + ','.join(map(str, layout['clusters'])) + '};\n'
                'static const uint32_t kHoujiLogLbas[16] = {' + ','.join(map(str, layout['lbas'])) + '};\n'
                f'static const uint32_t kHoujiLogInitialCrc = 0x{crc:08x}U;\n')
            require(layout['initial_crc32'] == f'{crc:08x}' and header.read_text() == expected_header,
                    'New allocation header is not exactly bound to the initial marker')
            require(all(layout[k] == actual_allocation[k] for k in
                        ('clusters', 'lbas', 'file_bytes', 'physical_lun', 'short_name')),
                    'In-place reset changed the fixed file allocation')
            child_before = (self.output / 'logfs-before.bin').read_bytes()
            child_after = (self.output / 'logfs-after.bin').read_bytes()
            require(child_before == raw_before and digest(child_before) == layout['backup_before_sha256'] and
                    digest(child_after) == layout['backup_after_sha256'], 'Primitive full backups differ')
            validate_in_place(child_before, child_after, actual_allocation)
            require(file_from_raw(child_after, layout) == initial and self.stable_raw() == child_after and
                    self.root('cat /dev/logfs/XnuLog.bin') == initial, 'Reset raw/mounted readback differs')
            if 'UniXNU.log' in files:
                require(self.root('cat /dev/logfs/UniXNU.log') == files['UniXNU.log'], 'Native archive binding changed before deletion')
            else:
                require(self.root('if [ -e /dev/logfs/UniXNU.log ]; then echo PRESENT; else echo ABSENT; fi').strip()==b'ABSENT','Unexpected unarchived native log')
            self.save(stage='fixed-log-reset-verified', allocation=layout,
                      header_sha256=digest(header.read_bytes()))
            if 'UniXNU.log' in files:
                self.root('set -e; mount -o remount,rw /dev/logfs; rm /dev/logfs/UniXNU.log; sync; mount -o remount,ro /dev/logfs')
            mounted_logfs(self.root('cat /proc/mounts'), require_ro=True)
            require(self.root('if [ -e /dev/logfs/UniXNU.log ]; then echo PRESENT; else echo ABSENT; fi').strip() == b'ABSENT',
                    'Archived native log was not removed')
            final = self.stable_raw()
            final_layout = self.allocator.layout(final)
            require(final_layout == actual_allocation and file_from_raw(final, final_layout) == initial and
                    self.root('cat /dev/logfs/XnuLog.bin') == initial, 'Final fixed allocation/marker differs')
            # Keep even a failed post-check's complete bytes, but withhold the
            # canonical preflight backup path until every check/finally passed.
            pending_backup = self.receipts / 'final-backup.pending'
            pending_backup.mkdir(mode=0o700)
            write_new(pending_backup / 'logfs.bin', final)
            write_new(pending_backup / 'manifest.json', json_bytes({'bytes': len(final), 'sha256': digest(final),
                'run': f'r{self.run}', 'initial_sha256': digest(initial), 'run_id': layout['run_id'],
                'source_receipt': str(self.receipts / 'receipt.json')}))
            after = self.protected('protected-after')
            require(after == before, 'Protected boot/GPT/misc changed during log preparation')
            self.save(stage='postwrite-proof-complete', protected_after=after,
                      final_logfs_sha256=digest(final), new_run_id=layout['run_id'],
                      new_initial_sha256=digest(initial))
        except Exception as caught:
            error = caught
            self.event('failure', error_type=type(caught).__name__, error=str(caught))
        finally:
            if self.verified_device:
                try:
                    self.root('mount -o remount,ro /dev/logfs')
                    mounted_logfs(self.root('cat /proc/mounts'), require_ro=True)
                    self.state['finally_readonly_verified'] = True
                except Exception as caught:
                    self.state['finally_readonly_verified'] = False
                    self.event('readonly-failure', error_type=type(caught).__name__, error=str(caught))
                    if error is None:
                        error = caught
                if before is not None and 'protected_after' not in self.state:
                    try:
                        after_failure = self.protected('protected-after-failure')
                        self.state['protected_after_failure'] = after_failure
                        require(after_failure == before, 'Protected state changed on the failed preparation path')
                    except Exception as caught:
                        self.event('protected-after-failure-unverified',
                                   error_type=type(caught).__name__, error=str(caught))
                        if error is None:
                            error = caught
        if error is None:
            try:
                require(pending_backup is not None and pending_backup.is_dir(), 'Final complete backup absent')
                require(not self.backup.exists(), 'Final backup destination appeared; refusing overwrite')
                pending_backup.rename(self.backup)
                self.event('publish-final-backup', path=str(self.backup),
                           sha256=self.state['final_logfs_sha256'])
            except Exception as caught:
                error = caught
                self.event('publication-failure', error_type=type(caught).__name__, error=str(caught))
        if error is not None:
            self.save(status='FAILED_DO_NOT_BOOT', ready_for_assembly=False,
                      error_type=type(error).__name__, error=str(error))
        else:
            self.save(status='PREPARED_FOR_ASSEMBLY_NOT_BOOTED', ready_for_assembly=True,
                      note='New run ID/header must enter the next kernel and policy; no source/policy/build/BCB/boot performed')
        return self.state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=int, required=True)
    parser.add_argument('--adb-port', type=int, choices=(5037, 5038, 5047, 15049), required=True)
    parser.add_argument('--previous-run',type=int,help='Skip only failed pre-device preparations, never a built/booted run')
    parser.add_argument('--previous-capture',type=Path,help='Exact archived replay capture; all identity, CRC and live-byte checks remain')
    parser.add_argument('--previous-native-only',action='store_true',help='Archive CRC-valid native checkpoint plus exact pristine XNU marker')
    parser.add_argument('--previous-uncommitted-snapshot',action='store_true',help='Archive exact pristine marker plus missing native log without claiming a completed result')
    parser.add_argument('--previous-native-label-from-qualified-app', action='store_true',
                        help='Explicitly allow only a reviewed historical title mismatch after frozen App/image/source and exact captured-run proof')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        result = RuntimePreparation(args.run, args.adb_port,
            previous_native_label_from_qualified_app=args.previous_native_label_from_qualified_app,
        previous_uncommitted_snapshot=args.previous_uncommitted_snapshot,
        previous_run=args.previous_run,previous_native_only=args.previous_native_only,
        previous_capture=args.previous_capture).run_preparation()
    except Exception as error:
        print('FAILED_DO_NOT_BOOT: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ready_for_assembly'] else 1


if __name__ == '__main__':
    sys.exit(main())
