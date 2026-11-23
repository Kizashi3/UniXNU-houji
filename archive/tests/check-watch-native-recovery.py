#!/usr/bin/env python3
"""Check immediate capture, stale-log refusal, and preserved retry evidence."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('watcher',root/'scripts/watch-native-recovery.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
for retry in (False,True):
 with tempfile.TemporaryDirectory() as folder:
  output=Path(folder)/'trial';calls=[];sleeps=[];captures=0
  def run(cmd,**kw):
   global captures
   calls.append(cmd)
   if cmd[0]==w.ADB:
    return subprocess.CompletedProcess(cmd,0,b'0\n1\n',b'')
   assert cmd[1].endswith('/capture-logfs.py')
   captures+=1;output.mkdir()
   (output/'UniXNU.log').write_bytes(b'HOUJI LOGFS r77: app text')
   metadata={'native_snapshot_integrity':{'valid':True},'xnu_snapshot_integrity':{'run_id':('0' if retry and captures==1 else 'a')*32},'files':[{'file':'UniXNU.log','stable':True},{'file':'XnuLog.bin','stable':True}]}
   (output/'capture.json').write_text(json.dumps(metadata))
   return subprocess.CompletedProcess(cmd,0,'captured','')
  argv=['watcher','--run','77','--run-id','a'*32,'--output',str(output)]
  with patch.object(sys,'argv',argv),patch.object(w.subprocess,'run',run),patch.object(w.time,'sleep',lambda n:sleeps.append(n)),contextlib.redirect_stdout(io.StringIO()):
   assert w.main()==0
  status=json.loads(output.with_name('trial-watch.json').read_text())
  assert status['state']=='complete' and status['fixed_grace_sleep'] is False
  assert captures==(2 if retry else 1)
  assert not sleeps  # First capture occurs immediately; no boot grace sleep.
  assert output.with_name('trial-partial-1').exists()==retry
  assert all('kill-server' not in x and 'reboot' not in x for x in calls)
print('PASS: live watcher captures immediately, rejects stale run identity, archives partial capture, never reboots or restarts ADB servers')
with tempfile.TemporaryDirectory() as folder:
 output=Path(folder)/'trial';captures=0
 def stable_invalid(cmd,**kw):
  global captures
  if cmd[0]==w.ADB:return subprocess.CompletedProcess(cmd,0,b'0\n1\n',b'')
  captures+=1;output.mkdir();(output/'UniXNU.log').write_bytes(b'HOUJI LOGFS r77: identical invalid bytes')
  (output/'capture.json').write_text(json.dumps({'native_snapshot_integrity':{'valid':False},'xnu_snapshot_integrity':{'run_id':'a'*32},'files':[{'file':'UniXNU.log','stable':True},{'file':'XnuLog.bin','stable':True}]}))
  return subprocess.CompletedProcess(cmd,0,'captured','')
 with patch.object(sys,'argv',['watcher','--run','77','--run-id','a'*32,'--output',str(output)]),patch.object(w.subprocess,'run',stable_invalid),contextlib.redirect_stdout(io.StringIO()):
  assert w.main()==3
 assert captures==3 and output.exists()
 assert json.loads(output.with_name('trial-watch.json').read_text())['state']=='invalid-stable-snapshot'
print('PASS: three identical stable invalid captures stop instead of looping; latest and previous evidence retained')

# Recovery may return before the native app creates UniXNU.log. Exercise the
# real watcher with completed capture metadata, rather than treating absence
# as either a successful trial or a transport error.
for scenario in ('stable-missing', 'then-valid', 'unstable-xnu', 'changing-xnu',
                 'capture-failed', 'implicit-missing', 'missing-xnu', 'reset-stability'):
 with tempfile.TemporaryDirectory() as folder:
  output=Path(folder)/'trial';captures=0;calls=[]
  expected_captures=3 if scenario=='stable-missing' else 2 if scenario=='then-valid' else 6 if scenario=='reset-stability' else 4
  def missing_native(cmd,**kw):
   global captures
   calls.append(cmd)
   if cmd[0]==w.ADB:return subprocess.CompletedProcess(cmd,0,b'0\n1\n',b'')
   assert cmd[1].endswith('/capture-logfs.py')
   captures+=1
   assert captures<=expected_captures, (scenario, captures)
   output.mkdir()
   if scenario!='stable-missing' and captures==expected_captures:
    (output/'UniXNU.log').write_bytes(b'HOUJI LOGFS r77: app text')
    metadata={'native_snapshot_integrity':{'valid':True},'xnu_snapshot_integrity':{'run_id':'a'*32},'files':[{'file':'UniXNU.log','stable':True},{'file':'XnuLog.bin','stable':True}]}
   else:
    payload=b'uncommitted XNU placeholder'+(str(captures).encode() if scenario=='changing-xnu' else b'')
    if scenario!='missing-xnu':(output/'XnuLog.bin').write_bytes(payload)
    stable=scenario!='unstable-xnu' and not (scenario=='reset-stability' and captures==3)
    metadata={'native_log_file_present':False,'xnu_log_file_present':scenario!='missing-xnu',
              'xnu_snapshot_integrity':{'valid':False,'committed':False,'run_id':'a'*32},
              'files':[{'file':'UniXNU.log','status':'missing'},
                       {'file':'XnuLog.bin','status':'missing' if scenario=='missing-xnu' else 'captured','stable':stable}]}
    if scenario=='implicit-missing':metadata.pop('native_log_file_present')
   (output/'capture.json').write_text(json.dumps(metadata))
   return subprocess.CompletedProcess(cmd,1 if scenario=='capture-failed' and captures<expected_captures else 0,'captured','')
  with patch.object(sys,'argv',['watcher','--run','77','--run-id','a'*32,'--output',str(output)]),patch.object(w.subprocess,'run',missing_native),patch.object(w.time,'sleep',lambda _:None),contextlib.redirect_stdout(io.StringIO()):
   assert w.main()==(3 if scenario=='stable-missing' else 0), scenario
  status=json.loads(output.with_name('trial-watch.json').read_text())
  assert captures==expected_captures and output.exists()
  assert all(output.with_name(f'trial-partial-{i}').exists() for i in range(1,captures))
  assert all('kill-server' not in x and 'reboot' not in x for x in calls)
  if scenario=='stable-missing':
   assert status['state']=='invalid-stable-snapshot' and not (output/'UniXNU.log').exists()
   assert all(r.get('native_log_missing') and r['trial_identity_and_native_crc_valid'] is False and 'error' not in r for r in status['captures'])
  else:
   assert status['state']=='complete' and status['captures'][-1]['trial_identity_and_native_crc_valid'] is True
print('PASS: explicit missing native log stops after three stable XNU captures; transient absence, unstable/changing XNU, incomplete capture and transport failures remain retryable')
