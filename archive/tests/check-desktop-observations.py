#!/usr/bin/env python3
"""Regression: unavailable snapshots and restarted clients must not imply zero GPU work."""
import importlib.util
from pathlib import Path

p=Path(__file__).resolve().parents[1]/'scripts/collect-native-desktop-result.py'
s=importlib.util.spec_from_file_location('collector',p)
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
text='''[  157.979836]: HOUJI DESKTOP: observed=0 backboard-submits=2975 real-completed=3061 jobs=0
[  162.992143]: HOUJI DESKTOP: observed=e00002d5 backboard-submits=0 real-completed=0 jobs=0
'''
rows=m.desktop_samples(text)
assert len(rows)==2 and rows[0]['observation_available']
assert rows[0]['real-completed']==3061 and rows[0]['uptime_seconds']==157.979836
assert rows[1]['observation_status']==0xe00002d5 and not rows[1]['observation_available']
assert next(r for r in reversed(rows) if r['observation_available'])['real-completed']==3061
reset=m.desktop_samples('HOUJI DESKTOP: observed=0 backboard-submits=4 real-completed=10 jobs=0')
assert reset[0]['backboard-submits']==4 and reset[0]['uptime_seconds'] is None
assert m.desktop_samples('HOUJI DESKTOP: not a sample')==[]
hex_error=m.desktop_samples('HOUJI DESKTOP: observed=80000001 backboard-submits=0')
assert hex_error[0]['observation_status']==0x80000001 and not hex_error[0]['observation_available']
print('PASS: success, unavailable, successful-history, client restart, absent data, hex status')
