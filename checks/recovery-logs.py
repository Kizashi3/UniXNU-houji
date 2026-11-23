#!/usr/bin/env python3
"""Exercise the public decoder with corrupt/stale evidence and a scoped reader."""
import contextlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/capture-recovery-logs.py'
spec = importlib.util.spec_from_file_location('capture', SCRIPT)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)
RUN = '0123456789abcdef' * 2


def fixture():
    raw = bytearray(capture.PARTITION_BYTES)
    struct.pack_into('<HBHBHHBH', raw, 11, 4096, 1, 1, 2, 512, 1280, 248, 1)
    raw[510:512] = b'\x55\xaa'
    firmware = b'HOUJI LOGFS r237:\r\nHOUJI LOGFS r87:\r\n'
    firmware += b'r87 snapshot end; app text only; commit/readback follows\r\n'
    firmware += ('HOUJI LOGFS CHECKSUM: payload-bytes=%d payload-crc32=%08X\r\n' %
                 (len(firmware), zlib.crc32(firmware))).encode()
    kernel = bytearray(65536)
    kernel[:8] = b'HJXNU001'
    struct.pack_into('<II', kernel, 8, 1, 1)
    kernel[16:32] = bytes.fromhex(RUN)
    text = b'current trial log\n'
    kernel[4096:4096 + len(text)] = text
    struct.pack_into('<II', kernel, 32, len(text), zlib.crc32(text))
    struct.pack_into('<I', kernel, 40, zlib.crc32(kernel[:4096]))
    for entry, (name, data, chain) in enumerate([
        (b'UNIXNU  LOG', firmware, [2]),
        (b'XNULOG  BIN', kernel, list(range(3, 19))),
    ]):
        offset = 3 * 4096 + entry * 32
        raw[offset:offset + 11] = name
        raw[offset + 11] = 32
        struct.pack_into('<HI', raw, offset + 26, chain[0], len(data))
        for at, cluster in enumerate(chain):
            word_at = 4096 + cluster + cluster // 2
            word = struct.unpack_from('<H', raw, word_at)[0]
            following = chain[at + 1] if at + 1 < len(chain) else 4095
            word = ((word & 15) | (following << 4)) if cluster & 1 else ((word & 61440) | following)
            struct.pack_into('<H', raw, word_at, word)
            block = (7 + cluster - 2) * 4096
            part = data[at * 4096:(at + 1) * 4096]
            raw[block:block + len(part)] = part
    raw[8192:12288] = raw[4096:8192]
    return bytes(raw), bytes(kernel), firmware


raw, kernel, firmware = fixture()
files = capture.fat_files(raw)
assert files['XnuLog.bin'][0] == kernel and files['UniXNU.log'][0] == firmware
assert capture.verify_firmware(firmware)['valid']
assert not capture.verify_firmware(firmware.replace(b'r87 snapshot', b'r86 snapshot'))['valid']
assert capture.decode_xnu(kernel, RUN)[1] == b'current trial log\n'
assert not capture.decode_xnu(kernel, 'f' * 32)[0]['valid']
for at in (0, 8, 12, 16, 32, 36, 40, 44, 4096, 65000):
    broken = bytearray(kernel)
    broken[at] ^= 1
    assert not capture.decode_xnu(broken, RUN)[0]['valid'], at
for at in (11, 13, 14, 16, 17, 19, 21, 22, 32, 510, 8198):
    broken = bytearray(raw)
    broken[at] ^= 1
    try:
        capture.fat_files(broken)
        raise AssertionError(('accepted corrupt FAT geometry/copy', at))
    except ValueError:
        pass
# A loop, an overlong chain, premature EOF and an out-of-volume link, in both FATs.
for link in (3, 19, 4095, 1275):
    broken = bytearray(raw)
    cluster = 3 if link != 19 else 18
    at = 4096 + cluster + cluster // 2
    word = struct.unpack_from('<H', broken, at)[0]
    word = ((word & 15) | (link << 4)) if cluster & 1 else ((word & 61440) | link)
    struct.pack_into('<H', broken, at, word)
    broken[8192:12288] = broken[4096:8192]
    try:
        capture.fat_files(broken)
        raise AssertionError('accepted malformed file chain')
    except ValueError:
        pass
broken = bytearray(raw)
struct.pack_into('<H', broken, 3 * 4096 + 32 + 26, 2)
try:
    capture.fat_files(broken)
    raise AssertionError('accepted aliased diagnostic files')
except ValueError:
    pass

# Device commands must stay on the exact selected server/device and read only.
commands = []
def adb_read(argv, **kwargs):
    assert argv[:6] == ['chosen-adb', '-P', '15057', '-s', 'test-target', 'exec-out']
    commands.append(argv[6])
    assert kwargs['env']['ADB_LIBUSB'] == '0'
    if argv[6].startswith('id -u;'):
        value = b'0\nhouji\n1\n/dev/block/sda13\n8388608\n'
    elif argv[6] == 'sha256sum /dev/block/by-name/logfs':
        value = (capture.sha256(raw) + '  /dev/block/by-name/logfs\n').encode()
    else:
        assert argv[6] == 'dd if=/dev/block/by-name/logfs bs=4096 count=2048 status=none'
        value = raw
    return SimpleNamespace(stdout=value, stderr=b'', returncode=0)

with patch.object(capture.socket, 'create_connection', return_value=contextlib.nullcontext()):
    with patch.object(capture.subprocess, 'run', side_effect=adb_read):
        observed, stable = capture.read_recovery('chosen-adb', 15057, 'test-target')
        assert observed == raw and stable and len(commands) == 4

with tempfile.TemporaryDirectory(prefix='houji-recovery-log-') as temporary:
    directory = Path(temporary)
    source = directory / 'raw.bin'
    source.write_bytes(raw)
    for name, expected_run, status in [('valid', RUN, 0), ('stale', 'f' * 32, 1)]:
        output = directory / name
        result = subprocess.run([sys.executable, str(SCRIPT), '--input', str(source),
                                 '--run-id', expected_run, '--output', str(output)],
                                capture_output=True, text=True)
        assert result.returncode == status, result.stdout + result.stderr
        assert (output / 'logfs.bin').read_bytes() == raw
        report = json.loads((output / 'capture.json').read_text())
        assert report['device_writes_requested'] is False
        assert (output / 'XnuLog.txt').exists() == (status == 0)
print('PASS: logfs bounds/chains, CRC and trial binding, stale evidence retained, explicit read-only ADB scope; no device')
