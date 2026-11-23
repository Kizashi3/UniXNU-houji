#!/usr/bin/env python3
"""Check persisted diagnostic integrity and damaged/partial snapshot rejection."""
import importlib.util
from pathlib import Path
import zlib
path=Path(__file__).resolve().parents[1]/'scripts/capture-logfs.py'
spec=importlib.util.spec_from_file_location('capture',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
payload=b'HOUJI LOGFS r23: app diagnostic capture\r\nHOUJI LOGFS: r23 snapshot end; app text only; commit/readback follows\r\n'
footer=f'HOUJI LOGFS CHECKSUM: payload-bytes={len(payload)} payload-crc32={zlib.crc32(payload):08x}\r\n'.encode();good=payload+footer
assert m.verify_native_snapshot(good)['valid']
for length,valid in ((150000,True),(524200,True),(524288,False)):
 large=payload+b'x'*(length-len(payload))
 encoded=large+f'HOUJI LOGFS CHECKSUM: payload-bytes={len(large)} payload-crc32={zlib.crc32(large):08x}\r\n'.encode()
 assert m.verify_native_snapshot(encoded)['valid']==valid
for data in (b'',payload,good[:-1],good+b'extra',b'x'+good,good.replace(b'r23:',b'r22:'),good.replace(b'capture',b'corrupt'),good.replace(str(len(payload)).encode(),b'99999999')):
 assert not m.verify_native_snapshot(data)['valid']
print('PASS: exact persisted snapshot footer, byte length and CRC; truncation, corruption, stale version, extra data and wrong length refused.')
