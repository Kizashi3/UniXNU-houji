#!/usr/bin/env python3
"""Read retained CPU mutex intervals; overlaps are evidence, not causal proof."""
import argparse
import hashlib
import json
from pathlib import Path
import re

FIELDS = ['seq', 'site', 'method', 'client', 'subject', 'request', 'acquired', 'released', 'issued', 'seen']
ROW = re.compile(r'HOUJI LOCK: ' + ' '.join(name + r'=(\d+)' for name in FIELDS) + r'$')


def analyze(log, source=None, stages=None):
    records, incomplete = {}, 0
    for line in log.splitlines():
        if not line.startswith('HOUJI LOCK: '):
            continue
        match = ROW.fullmatch(line)
        if not match:
            incomplete += 1
            continue
        row = dict(zip(FIELDS, map(int, match.groups())))
        if any(value > 2**64-1 for value in row.values()) or not row['seq']:
            raise ValueError('invalid issuer record value')
        if not row['request'] <= row['acquired'] <= row['released']:
            raise ValueError('backwards issuer record clock')
        old = records.get(row['seq'])
        if old is not None and old != row:
            raise ValueError('conflicting sequence: do not mix different boots')
        records[row['seq']] = row
    lines = source.splitlines() if source is not None else []
    for row in records.values():
        row['wait_us'] = row['acquired'] - row['request']
        row['held_us'] = row['released'] - row['acquired']
        row['source_line'] = lines[row['site']-1] if 0 < row['site'] <= len(lines) else None
    rows = sorted(records.values(), key=lambda row: row['acquired'])
    result = dict(status='RETAINED_INTERVALS' if rows else 'NO_ISSUER_RECORDS',
                  clock='mach_absolute_time converted to microseconds; same uptime domain as CLOCK_UPTIME_RAW',
                  scope='Selected long holds/waits and recent intervals only, not the complete lock history. A waiting caller may wait behind several holders. No GPU execution timestamps or FPS.',
                  source_sha256=hashlib.sha256(source.encode()).hexdigest() if source is not None else None,
                  incomplete_rows=incomplete, records=rows)
    if stages is not None:
        matches = []
        for command in stages['slow']:
            start = command['commit_uptime_s']*1e6
            end = start+command['callback_us']
            overlaps = []
            for row in rows:
                duration = min(end, row['released'])-max(start, row['acquired'])
                if duration > 0:
                    overlaps.append(dict(issuer_sequence=row['seq'], held_overlap_us=round(duration, 3)))
            matches.append(dict(command_sequence=command['sequence'], holds=overlaps))
        result['command_overlap_scope'] = ('Inputs must be from the same verified boot; this parser cannot establish their trial identity. '
                                           'Clock overlap alone does not prove the command waited for that holder. Do not add overlapping intervals or infer GPU start/end.')
        result['command_overlaps'] = matches
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--source', type=Path, help='Exact compiled NativeAdrenoPublish.cpp from the trial archive')
    parser.add_argument('--stages', type=Path, help='analyze-gpu-stages JSON from the same verified boot')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.log.stat().st_size > 8*1024**2:
        parser.error('log exceeds 8 MiB analysis budget')
    result = analyze(args.log.read_text(errors='replace'),
                     args.source.read_text() if args.source else None,
                     json.loads(args.stages.read_text()) if args.stages else None)
    text = json.dumps(result, ensure_ascii=False, indent=2)+'\n'
    if args.output:
        args.output.write_text(text)
    else:
        print(text, end='')
