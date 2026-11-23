#!/usr/bin/env python3
"""Offline checks of log-window containment, ring order, and fixed output paths."""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('capture_log', Path(__file__).resolve().parents[1] / 'scripts/capture-android-boot-log.py')
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)
FIRST = 128098299


def fixture_header(**changes):
    h = dict(zip(READER.FIELDS, (b'SHLOG001', 4, 152, 0xcafe, FIRST,
                               8192, 1, 32, 6, 33, 16, 2, 3,
                               30, 3, 0, 0x1234, 0x1234, 2, b'../../escape')))
    h.update(changes)
    data = bytearray(READER.BLOCK)
    READER.HEADER.pack_into(data, 0, *(h[x] for x in READER.FIELDS))
    # These external export lengths must never cause a read or a new local path.
    struct.pack_into('<7I', data, 120, 1, 65536, 0xffffffff, 7, 65536, 2, 0xffffffff)
    return data


class LogReaderChecks(unittest.TestCase):
    def test_supported_header(self):
        h = READER.validate_header(fixture_header(), FIRST)
        self.assertEqual(h['version'], 4)
        self.assertEqual(h['diag_bytes'], 0xffffffff)

    def test_reject_unsafe_header_layouts(self):
        cases = [dict(magic=b'BADMAGIC'), dict(version=5), dict(header_bytes=147),
                 dict(header_bytes=4097), dict(first_lba=FIRST + 1), dict(window_blocks=8193),
                 dict(msg_first=0), dict(msg_blocks=8192), dict(msg_bytes=32 * 4096 + 1),
                 dict(slot_first=32), dict(slot_blocks=0), dict(slot_count=0),
                 dict(slot_count=8192)]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                READER.validate_header(fixture_header(**changes), FIRST)
        with self.assertRaises(ValueError):
            READER.validate_header(b'\0' * 4095, FIRST)

    def test_wrapped_ring_and_no_export_paths(self):
        blob = bytearray(READER.BLOCK * READER.LOG_BLOCKS)
        blob[:READER.BLOCK] = fixture_header()
        blob[4096:4102] = b'HELLO\n'
        first = 33 * 4096
        blob[first:first + 7] = b'NEWEST\0'
        second = (33 + 16) * 4096
        blob[second:second + 9] = b'PREVIOUS\0'
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'capture'
            output.mkdir()
            READER.decode(blob, FIRST, output)
            self.assertEqual((output / 'msgbuf.txt').read_bytes(), b'HELLO\n')
            self.assertEqual((output / 'slots.txt').read_text(), 'PREVIOUS\nNEWEST')
            self.assertEqual((output / 'latest.txt').read_text(), 'NEWEST')
            self.assertEqual(json.loads((output / 'header.json').read_text())['boot_id'], 0xcafe)
            self.assertEqual({p.name for p in output.iterdir()},
                             {'log.bin', 'header.json', 'msgbuf.txt', 'slots.txt', 'latest.txt'})
            self.assertEqual({p.name for p in Path(folder).iterdir()}, {'capture'})

    def test_short_full_window_rejected(self):
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            READER.decode(fixture_header(), FIRST, Path(folder))


if __name__ == '__main__':
    unittest.main()
