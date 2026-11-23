#!/usr/bin/env python3
"""Run the actual preparation main with a FAT atime/cache peer; no device I/O."""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_xnu_log', ROOT / 'scripts/prepare-xnu-log.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)
ENTRY, DATA = 3 * 4096, 7 * 4096


class FatPeer:
    def __init__(self):
        self.disk = bytearray(8388608)
        self.disk[510:512] = b'\x55\xaa'
        struct.pack_into('<HBHBHHBHHH', self.disk, 11, 4096, 1, 1, 2, 512, 1280, 248, 1, 1, 1)
        fat = bytearray(4096)
        for cluster in range(2, 18):
            value = cluster + 1 if cluster < 17 else 0xfff
            offset = cluster + cluster // 2
            pair = int.from_bytes(fat[offset:offset + 2], 'little')
            pair = (pair & 0x000f) | (value << 4) if cluster & 1 else (pair & 0xf000) | value
            fat[offset:offset + 2] = pair.to_bytes(2, 'little')
        self.disk[4096:8192] = self.disk[8192:12288] = fat
        self.disk[ENTRY:ENTRY + 11] = b'XNULOG  BIN'
        self.disk[ENTRY + 11] = 0x20
        struct.pack_into('<H', self.disk, ENTRY + 18, 0x5858)
        struct.pack_into('<HI', self.disk, ENTRY + 26, 2, 65536)
        self.original = b'archived-r143'.ljust(65536, b'\0')
        self.disk[DATA:DATA + 65536] = self.original
        self.commands, self.remote = [], {}
        self.written = False
        self.pending_access_date = None
        self.raw_reads = 0

    def flush(self):
        if self.pending_access_date is not None:
            struct.pack_into('<H', self.disk, ENTRY + 18, self.pending_access_date)
            self.pending_access_date = None

    def run(self, argv, **kwargs):
        assert argv[:5] == [prepare.ADB, '-P', '5047', '-s', prepare.SERIAL]
        if argv[5] == 'push':
            assert len(argv) == 8
            self.remote[argv[7]] = Path(argv[6]).read_bytes()
            return subprocess.CompletedProcess(argv, 0)
        assert len(argv) == 7 and argv[5] == 'exec-out'
        command = argv[6]
        self.commands.append(command)
        if command.startswith('id -u; '):
            out = b'0\nhouji\n/dev/block/sda13\n8388608\n'
        elif command == 'cat /proc/mounts':
            out = b'/dev/block/sda13 /dev/logfs vfat ro 0 0\n'
        elif command == 'if [ -e /dev/logfs/XnuLog.bin ]; then echo EXISTS; else echo ABSENT; fi':
            out = b'EXISTS\n'
        elif command.startswith('if [ -e /tmp/houji-xnu-log-'):
            out = b'ABSENT\n'
        elif command == 'cat /dev/logfs/XnuLog.bin':
            # Simulate a date change specifically at post-write mounted readback.
            if self.written:
                self.pending_access_date = 0x5859
            out = bytes(self.disk[DATA:DATA + 65536])
        elif command == 'sync':
            self.flush()
            out = b''
        elif command == '/tmp/houji-logfs-read':
            self.raw_reads += 1
            out = bytes(self.disk)  # O_DIRECT does not flush mounted FAT metadata.
        elif command == 'mount -o remount,rw /dev/logfs':
            out = b''
        elif command == 'mount -o remount,ro /dev/logfs':
            self.flush()
            out = b''
        elif command.startswith('dd '):
            match = re.fullmatch(r'dd if=(/tmp/houji-xnu-log-[0-9a-f]+\.bin) of=/dev/logfs/XnuLog.bin bs=4096 count=16 conv=notrunc,fsync', command)
            assert match, 'Only the existing mounted file may be written'
            self.disk[DATA:DATA + 65536] = self.remote[match[1]]
            self.written = True
            out = b''
        elif command.startswith('rm /tmp/houji-xnu-log-'):
            del self.remote[command[3:]]
            out = b''
        else:
            raise AssertionError('Unexpected command: ' + command)
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr=b'')


peer = FatPeer()
with tempfile.TemporaryDirectory(prefix='houji-log-atime-') as directory:
    output, header = Path(directory) / 'receipt', Path(directory) / 'log.h'
    argv = ['prepare-xnu-log.py', '--adb-port', '5047', '--output', str(output),
            '--header', str(header), '--recovery', '--reuse-sha256', hashlib.sha256(peer.original).hexdigest()]
    with mock.patch.object(sys, 'argv', argv), mock.patch.object(prepare.subprocess, 'run', peer.run), \
            mock.patch.object(prepare.os, 'umask', return_value=0o022), contextlib.redirect_stdout(io.StringIO()):
        prepare.main()
    after = (output / 'logfs-after.bin').read_bytes()
    assert after == peer.disk, 'RO remount must not reveal a deferred FAT date mutation'
    assert struct.unpack_from('<H', after, ENTRY + 18)[0] == 0x5859
    assert after[DATA:DATA + 65536] == (output / 'XnuLog.initial.bin').read_bytes()
    readback = max(i for i, command in enumerate(peer.commands) if command == 'cat /dev/logfs/XnuLog.bin')
    raw_backup = next(i for i in range(readback + 1, len(peer.commands)) if peer.commands[i] == '/tmp/houji-logfs-read')
    remount_ro = peer.commands.index('mount -o remount,ro /dev/logfs')
    assert peer.commands[readback + 1] == 'sync' and readback < raw_backup < remount_ro
    assert peer.raw_reads == 4 and header.exists() and not peer.remote
    before = (output / 'logfs-before.bin').read_bytes()
    allowed = set(range(DATA, DATA + 65536)) | {ENTRY + 18, ENTRY + 19}
    assert all(a == b or i in allowed for i, (a, b) in enumerate(zip(before, after)))

print('PASS: actual prepare main mounted-readback -> sync -> O_DIRECT backup -> RO; cross-day FAT access date stable, one existing file only, no device I/O')
