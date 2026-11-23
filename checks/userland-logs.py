#!/usr/bin/env python3
"""Exercise offline diagnostic collection with repeated clocks and corrupt IPS."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'tools/capture-userland-logs.py'
spec = importlib.util.spec_from_file_location('capture_userland', TOOL)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory(prefix='houji-userland-logs-') as directory:
    tmp = Path(directory)
    before, after, output = tmp / 'before', tmp / 'after', tmp / 'output'
    relative = Path('private/var/mobile/Library/Logs/CrashReporter')
    for root in (before, after):
        (root / relative).mkdir(parents=True)
        (root / relative / 'unchanged.ips').write_text('old report')
        (root / relative / 'reused-name.ips').write_text('old contents')
        os.utime(root / relative / 'reused-name.ips', (1, 1))
    body = dict(procName='Preferences', faultingThread=0,
                exception=dict(type='EXC_BAD_ACCESS'),
                threads=[dict(frames=[dict(imageIndex=0, symbol='CI::GLContext', imageOffset=12)])],
                usedImages=[dict(name='CoreImage')])
    raw = json.dumps(dict(bug_type='309')) + '\n' + json.dumps(body)
    (after / relative / 'reused-name.ips').write_text(raw)
    os.utime(after / relative / 'reused-name.ips', (1, 1))
    (after / relative / 'incomplete.ips').write_bytes(b'\xffnot JSON')
    power = Path('private/var/log/houji-power.jsonl')
    (after / power).parent.mkdir(parents=True)
    (after / power).write_text('{"low_power_mode":false}\n')
    (after / power).with_name('unrelated.log').write_text('must not be copied')
    apps = relative.parent / 'UniXNU-system-apps.log'
    (after / apps).write_text('FINISHED registered=32 expected=32\n')
    (after / apps).with_name('UniXNU-unrelated.log').write_text('must not be copied')
    command = [sys.executable, str(TOOL), '--root', str(after), '--baseline', str(before),
               '--run-id', '12' * 16, '--output', str(output)]
    subprocess.run(command, check=True, capture_output=True)
    report = json.loads((output / 'capture.json').read_text())
    assert report['status'] == 'PASS' and report['unchanged_files'] == 1
    assert len(report['files']) == 4
    rows = {Path(row['path']).name: row for row in report['files']}
    assert rows['reused-name.ips']['change'] == 'changed'
    assert rows['reused-name.ips']['crash']['frames'][0]['image'] == 'CoreImage'
    assert rows['incomplete.ips']['crash'] is None
    assert (output / 'files' / power).read_text() == '{"low_power_mode":false}\n'
    assert not (output / 'files' / power).with_name('unrelated.log').exists()
    assert (output / 'files' / apps).read_bytes() == (after / apps).read_bytes()
    assert not (output / 'files' / apps).with_name('UniXNU-unrelated.log').exists()
    assert (output / 'files' / relative / 'reused-name.ips').read_text() == raw
    assert (output / 'files' / relative / 'incomplete.ips').read_bytes() == b'\xffnot JSON'
    assert output.stat().st_mode & 0o777 == 0o700
    assert (output / 'capture.json').stat().st_mode & 0o777 == 0o600
    assert subprocess.run(command, capture_output=True).returncode != 0, 'never overwrite evidence'
    assert (before / relative / 'reused-name.ips').read_text() == 'old contents'

    secret = tmp / 'outside.ips'
    secret.write_text('must not be followed')
    (after / relative / 'symlink.ips').symlink_to(secret)
    os.mkfifo(after / relative / 'pipe.ips')
    (after / relative / 'linked-directory').symlink_to(tmp, target_is_directory=True)
    partial = tmp / 'partial'
    partial.mkdir()
    result = module.collect(after, before, partial, '12' * 16)
    assert result['status'] == 'PARTIAL' and len(result['errors']) == 2
    assert not (partial / 'files' / relative / 'symlink.ips').exists()
    assert not (partial / 'files' / relative / 'pipe.ips').exists()
    assert not (partial / 'files' / relative / 'linked-directory').exists()
    limited = tmp / 'limited'
    limited.mkdir()
    module.MAX_TOTAL = 1
    assert module.collect(after, before, limited, '12' * 16)['status'] == 'PARTIAL'
    inside_command = command[:-1] + [str(after / 'nested-output')]
    assert subprocess.run(inside_command, capture_output=True).returncode != 0
    assert not (after / 'nested-output').exists()
print('PASS: content-diff diagnostics, raw invalid IPS, private output, bounds and no symlink/FIFO reads')
