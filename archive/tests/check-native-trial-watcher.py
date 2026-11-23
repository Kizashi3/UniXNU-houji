#!/usr/bin/env python3
"""Validate boot-to-background-watcher dispatch without phone access."""
from pathlib import Path
import importlib.util
import json
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('trial',root/'scripts/try-native-userland-boot.py')
trial=importlib.util.module_from_spec(spec);spec.loader.exec_module(trial)
with tempfile.TemporaryDirectory() as directory:
 evidence=Path(directory)
 watch=trial.recovery_watch_spec('native-ios-r900',5047,'a'*32,evidence)
 assert watch['command'][2:]==['--run','900','--run-id','a'*32,'--output',str(evidence/'logfs-recovery-r900'),'--first-port','5047','--timeout','600']
 with patch.object(trial.subprocess,'Popen',return_value=SimpleNamespace(pid=12345)) as launch:
  assert trial.start_recovery_watch(watch)==12345
  args,kwargs=launch.call_args;assert args==(watch['command'],)
  assert kwargs['start_new_session'] and kwargs['close_fds'] and kwargs['stdin']==subprocess.DEVNULL
  assert kwargs['stderr']==subprocess.STDOUT and kwargs['stdout'].name==str(watch['console'])
 data=json.loads(watch['pid'].read_text());assert data['pid']==12345 and data['fixed_grace_sleep'] is False
 for action in (lambda:trial.start_recovery_watch(watch),lambda:trial.recovery_watch_spec('native-ios-r900',5047,'a'*32,evidence)):
  try:action()
  except FileExistsError:pass
  else:raise AssertionError('Duplicate watcher/capture accepted')
 for label,port,run_id in [('bad',5047,'a'*32),('native-ios-r900',5000,'a'*32),('native-ios-r900',5047,'bad')]:
  try:trial.recovery_watch_spec(label,port,run_id,evidence)
  except ValueError:pass
  else:raise AssertionError('Invalid watcher identity accepted')
source=(root/'scripts/try-native-userland-boot.py').read_text()
assert source.index('watch=recovery_watch_spec')<source.index("root('dd if=/tmp/houji-gpu-recovery-request")
assert source.index('watcher_pid=start_recovery_watch(watch)')>source.index("Fastboot did not confirm Booting OKAY")
print('PASS: boot success dispatches one detached watcher with redirected logs and exact run identity; duplicates rejected before phone mutation; no fixed wait')
