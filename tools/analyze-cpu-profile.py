#!/usr/bin/env python3
"""Read a bounded compositor stack profile, optionally within an animation window.

Samples perturb the target; counts are neither CPU percentages nor display FPS.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

MAX_BYTES = 4 * 1024**2
PHASES = ['gap', 'encoding', 'pass_creation', 'draw', 'encoder_end', 'binding', 'commit', 'wait']


def analyze(data, start=None, end=None):
    if len(data) > MAX_BYTES or not data.startswith(b'HOUJI_CPU_PROFILE_V1\t'):
        raise ValueError('invalid or oversized profile')
    lines = data.decode('utf-8').splitlines()
    truncated = not data.endswith(b'\n')
    if truncated:
        lines = lines[:-1]
    definitions, samples, errors = {}, [], []
    previous = 0
    for line in lines[1:]:
        row = line.split('\t')
        if row[0] == 'A' and len(row) == 5:
            address, offset = int(row[1], 16), int(row[2], 16)
            if address in definitions or len(definitions) >= 4096:
                raise ValueError('duplicate or excessive address definitions')
            definitions[address] = dict(image=row[3], symbol=row[4], offset=hex(offset))
        elif row[0] == 'S' and len(row) == 17:
            sequence, when, pause, phase, state, suspend, registers, resume = map(int, row[1:9])
            if sequence != previous + 1 or min(when, pause, state) < 0 or not 0 <= phase < len(PHASES):
                raise ValueError('invalid sequence, time or phase')
            previous = sequence
            if (start is None or when >= start*1e6) and (end is None or when <= end*1e6):
                samples.append(dict(when=when, pause=pause, phase=PHASES[phase], state=state,
                                    suspend=suspend, registers=registers, resume=resume,
                                    frames=[int(v, 16) for v in row[9:]]))
        elif row[0] == 'E' and len(row) == 2:
            errors.append(row[1])
        else:
            raise ValueError('invalid profile row')
    def name(address):
        d = definitions.get(address)
        if not d:
            return 'unknown@' + hex(address)
        # dyld may return the same redaction marker for many private functions.
        # Keep their image offsets distinct for offline symbolication.
        return d['image'] + '`' + (d['offset'] if d['symbol'] in ('?', '<redacted>', '') else d['symbol'])
    phases = defaultdict(lambda: dict(samples=0, leaf=Counter(), inclusive=Counter(), states=Counter()))
    valid = [s for s in samples if s['suspend'] == s['registers'] == s['resume'] == 0 and s['frames'][0]]
    for s in valid:
        group = phases[s['phase']]
        group['samples'] += 1
        group['leaf'][name(s['frames'][0])] += 1
        group['inclusive'].update(set(name(f) for f in s['frames'] if f))
        group['states'][s['state']] += 1
    return dict(scope='Periodic stack observations, not CPU percentages or FPS; suspension perturbs timing. State was read before suspend.',
                total_records=previous, selected_samples=len(samples), valid_samples=len(valid),
                failed_samples=len(samples)-len(valid), truncated_tail=truncated, errors=errors,
                first_uptime_s=samples[0]['when']/1e6 if samples else None,
                last_uptime_s=samples[-1]['when']/1e6 if samples else None,
                pause_total_us=sum(s['pause'] for s in samples),
                pause_max_us=max((s['pause'] for s in samples), default=0),
                phases={p:dict(samples=v['samples'], states=dict(v['states']),
                               leaf=v['leaf'].most_common(20), inclusive=v['inclusive'].most_common(30))
                        for p, v in phases.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile', type=Path)
    parser.add_argument('--from-uptime', type=float)
    parser.add_argument('--to-uptime', type=float)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.profile.stat().st_size > MAX_BYTES:
        parser.error('profile exceeds budget')
    result = json.dumps(analyze(args.profile.read_bytes(), args.from_uptime, args.to_uptime), ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end='')
