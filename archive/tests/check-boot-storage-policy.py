#!/usr/bin/env python3
"""Ensure writer provenance is rejected before any ADB/fastboot side effect."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

script = Path(__file__).resolve().parents[1] / 'scripts/try-ram-boot.py'
spec = importlib.util.spec_from_file_location('trial', script)
trial = importlib.util.module_from_spec(spec); spec.loader.exec_module(trial)

class DeviceCall(Exception): pass

with tempfile.TemporaryDirectory() as directory:
    image = Path(directory) / 'boot.img'; image.write_bytes(b'local-test-image')
    base = {'device': 'houji', 'physical_storage_drivers': True,
            'test_scope': 'uefi-logfs-file-write-test',
            'storage_write_policy': trial.LOGFS_POLICY,
            'usage': 'fastboot boot only', 'sha256': {'image': hashlib.sha256(image.read_bytes()).hexdigest()}}
    bad = [{**base, 'storage_write_policy': None}, {**base, 'test_scope': 'unknown'},
           {**base, 'device': 'sheng'}, {**base, 'usage': 'flash'}]
    for key in trial.LOGFS_POLICY:
        policy = dict(trial.LOGFS_POLICY)
        policy[key] = 'tampered'
        bad.append({**base, 'storage_write_policy': policy})
    native = {**base, 'test_scope': 'xnu-native-ufs-gpt-read-probe',
              'native_storage_policy': trial.NATIVE_READ_POLICY}
    bad.append({**native, 'native_storage_policy': None})
    for key in trial.NATIVE_READ_POLICY:
        policy = dict(trial.NATIVE_READ_POLICY); policy[key] = 'tampered'
        bad.append({**native, 'native_storage_policy': policy})
    native_log = {**base, 'test_scope': 'xnu-native-fixed-log-test',
                  'native_storage_policy': trial.NATIVE_LOG_POLICY}
    bad.append({**native_log, 'native_storage_policy': None})
    for key in trial.NATIVE_LOG_POLICY:
        policy = dict(trial.NATIVE_LOG_POLICY); policy[key] = 'tampered'
        bad.append({**native_log, 'native_storage_policy': policy})
    valid = [base, native, native_log]
    for metadata in bad + valid:
        image.with_suffix('.json').write_text(json.dumps(metadata))
        with patch.object(sys, 'argv', ['trial', '--image', str(image), '--label', 'policy-offline', '--adb-port', '5037']):
            with patch.object(trial.subprocess, 'run', side_effect=DeviceCall) as call:
                try: trial.main()
                except ValueError:
                    assert metadata not in valid and not call.called
                except DeviceCall:
                    assert metadata in valid and call.call_count == 1
                else: raise AssertionError('Expected rejection or intercepted first device call')
print(f'PASS: {len(bad)} altered provenance cases refused before device call; exact writer/native policies reach only mocked preflight.')
