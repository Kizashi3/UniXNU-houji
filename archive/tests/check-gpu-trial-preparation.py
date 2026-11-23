#!/usr/bin/env python3
"""Exercise the exceptional pre-logfs failure gate without accessing a device."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare', root / 'scripts/prepare-gpu-only-trial.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class Reader:
    @staticmethod
    def verify_native_snapshot(data):
        return {'valid': data == b'HOUJI LOGFS r127: verified test snapshot'}


with tempfile.TemporaryDirectory() as directory:
    cap = Path(directory) / 'logfs-recovery-r127'
    cap.mkdir()
    xnu = b'unchanged initial XNU asset; not a committed boot log'
    (cap / 'XnuLog.bin').write_bytes(xnu)
    (cap / 'photo.png').write_bytes(b'archived failure photo')
    captured = {
        'native_log_file_present': False,
        'files': [
            {'file': 'UniXNU.log', 'status': 'missing'},
            {'file': 'XnuLog.bin', 'stable': True, 'sha256': hashlib.sha256(xnu).hexdigest()},
        ],
    }
    result = {
        'run': 'r127', 'phase': 'OEM-foundation-before-logfs-and-GPU',
        'manual_recovery': True, 'native_snapshot_present': False,
        'boot_partitions_unchanged': True, 'all_12_gpt_ranges_unchanged': True,
        'misc_reserved_unchanged': True, 'GPU_CP_execution_proven': False,
        'GPU_writeback_proven': False, 'photo': 'logfs-recovery-r127/photo.png',
    }

    def verify(metadata=captured, evidence=result, exceptional=True):
        (cap / 'capture.json').write_text(json.dumps(metadata))
        return prepare.verify_previous_evidence(cap, evidence, 127, exceptional, Reader)

    def rejected(**kwargs):
        try:
            verify(**kwargs)
        except (AssertionError, KeyError, FileNotFoundError, TypeError):
            return
        raise AssertionError('unsafe or incomplete evidence accepted')

    _, native, integrity = verify()
    assert native is None and integrity['valid'] is False
    rejected(exceptional=False)
    for key in result:
        bad = copy.deepcopy(result)
        bad.pop(key)
        rejected(evidence=bad)
    for value in ('../outside.png', 'logfs-recovery-r126/photo.png'):
        bad = copy.deepcopy(result)
        bad['photo'] = value
        rejected(evidence=bad)
    for key, value in (('stable', False), ('sha256', '0' * 64)):
        bad = copy.deepcopy(captured)
        bad['files'][1][key] = value
        rejected(metadata=bad)
    for key, value in (('native_log_file_present', True), ('files', [])):
        bad = copy.deepcopy(captured)
        bad[key] = value
        rejected(metadata=bad)
    (cap / 'UniXNU.log').write_bytes(b'unexpected live native snapshot')
    rejected()
    # Ordinary mode still requires actual native validation, stability and hash.
    native = b'HOUJI LOGFS r127: verified test snapshot'
    (cap / 'UniXNU.log').write_bytes(native)
    normal = copy.deepcopy(captured)
    normal['native_log_file_present'] = True
    normal['files'][0] = {'file': 'UniXNU.log', 'stable': True,
                          'sha256': hashlib.sha256(native).hexdigest()}
    assert verify(normal, exceptional=False)[1] == native
    bad = copy.deepcopy(normal)
    bad['files'][0]['stable'] = False
    rejected(metadata=bad, exceptional=False)
    (cap / 'UniXNU.log').write_bytes(native + b'corruption')
    rejected(metadata=normal, exceptional=False)
print('PASS: confirmed pre-logfs failure stays failed; missing proof, stale/mutated files and unarchived native logs are rejected; no device accessed')
