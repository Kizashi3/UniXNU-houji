#!/usr/bin/env python3
"""Read a bounded houji GPU timeline. Command buffers are not display frames/FPS."""
import argparse
import json
import math
from pathlib import Path
import struct

HEADER = struct.Struct('<8sQQQ')
RECORD = struct.Struct('<QQIHH')
MAX_BYTES = 16 * 1024**2
CHAIN = [31, 3, 4, 5, 6, 8, 9, 14, 15, 33]
CHAIN_NAMES = ['commit_to_prepare', 'prepare', 'prepared_to_handed',
               'scheduler_inbox', 'taken_to_submit', 'driver_submission',
               'submit_return_to_observed', 'observed_to_dispatched', 'dispatched_to_callback']


def command_chain(frame):
    """Disjoint phases of ONE complete, ordered, successfully submitted batch.

    Do not combine the first submit of a multibatch buffer with its final wait,
    or treat the GPU duration as a host-clock interval. Missing records remain
    missing evidence, rather than zero-duration work.
    """
    events = frame['events']
    if len(events.get(8, [])) != 1 or len(events.get(9, [])) != 1:
        return None, 'missing_or_multibatch'
    if events[9][0][1] != 0:
        return None, 'grouped_or_not_submitted'
    if any(len(events.get(stage, [])) != 1 for stage in CHAIN):
        return None, 'missing_or_duplicate_stage'
    times = [events[stage][0][0] for stage in CHAIN]
    if any(b < a for a, b in zip(times, times[1:])):
        return None, 'out_of_order'
    return {name: round((b-a)/1000, 3)
            for name, a, b in zip(CHAIN_NAMES, times, times[1:])}, None


def summarize(values):
    ordered = sorted(v for v in values if v is not None and v >= 0)
    if not ordered:
        return {'count': 0}
    return dict(count=len(ordered), mean_us=round(sum(ordered)/len(ordered), 3),
                p95_us=ordered[math.ceil(len(ordered)*.95)-1], max_us=ordered[-1])


def analyze(data):
    if len(data) < HEADER.size or len(data) > MAX_BYTES:
        raise ValueError('invalid trace size')
    magic, began, size, limit = HEADER.unpack_from(data)
    if magic != b'HJGPU01\n' or size != RECORD.size or limit != MAX_BYTES:
        raise ValueError('unsupported trace header')
    tail = (len(data)-HEADER.size) % RECORD.size
    rows = [RECORD.unpack_from(data, at) for at in range(HEADER.size, len(data)-tail, RECORD.size)]
    gaps, previous = 0, 0
    for _, _, seq, _, _ in rows:
        if seq <= previous:
            raise ValueError('duplicate or reordered trace sequence')
        gaps += seq - previous - 1
        previous = seq
    # Sequence reserves a slot before reading the clock; concurrent producers can finish out of order.
    rows.sort(key=lambda r: (r[0], r[2]))
    buffers, frames = {}, []
    for when, identity, seq, stage, arg in rows:
        if not identity:
            continue
        if stage == 30:
            frame = dict(id=identity, created_ns=when, sequence=seq, stages={}, values={}, events={})
            frames.append(frame)
            buffers[identity] = frame  # addresses can be reused after completion
        frame = buffers.get(identity)
        if frame is None:
            continue
        frame['stages'].setdefault(stage, []).append(when)
        frame['events'].setdefault(stage, []).append((when, arg))
        if 34 <= stage <= 39:
            frame['values'][stage] = arg
    def first(frame, stage):
        return next(iter(frame['stages'].get(stage, [])), None)
    def span(frame, a, b):
        start, end = first(frame, a), first(frame, b)
        return round((end-start)/1000, 3) if start is not None and end is not None and end >= start else None
    complete = [f for f in frames if span(f, 31, 33) is not None]
    paths, excluded = [], {}
    for frame in complete:
        path, reason = command_chain(frame)
        frame['chain_us'], frame['chain_exclusion'] = path, reason
        if path is not None:
            paths.append(path)
        else:
            excluded[reason] = excluded.get(reason, 0) + 1
    metrics = {
        'creation_to_commit_including_caller_idle': (30, 31),
        'commit_to_scheduled_callback': (31, 32),
        'commit_to_completed_callback': (31, 33),
        'runtime_prepare': (3, 4),
        'scheduler_inbox': (5, 6),
        'runtime_poll_to_seen': (12, 14),
    }
    timings = {name: summarize(span(f, a, b) for f in complete) for name, (a, b) in metrics.items()}
    for name, stage in [('gpu_span', 34), ('driver_submit_span', 35), ('draw_api_wall', 36),
                        ('encoder_end_wall', 37), ('pass_creation_wall', 38)]:
        timings[name] = summarize(f['values'].get(stage) for f in complete)
    slow = sorted(complete, key=lambda f: span(f, 31, 33), reverse=True)[:20]
    return dict(records=len(rows), sequence_gaps=gaps, incomplete_tail_bytes=tail,
                header_created_uptime_s=began/1e9,
                first_record_uptime_s=rows[0][0]/1e9 if rows else None,
                last_record_uptime_s=rows[-1][0]/1e9 if rows else None,
                created_buffers=len(frames), complete_buffers=len(complete),
                incomplete_buffers=len(frames)-len(complete), clock='CLOCK_UPTIME_RAW nanoseconds',
                scope='Command buffers, not display frames or panel FPS. Creation includes caller idle; sequence gaps mean missing evidence. Duration values of 65535 are saturated.',
                single_batch_chain=dict(count=len(paths), excluded=excluded,
                    scope='Adjacent non-overlapping host intervals of the same command buffer only. Submit return to observed includes GPU queueing, execution and host observation; GPU duration alone cannot separate them.',
                    phases={name: summarize(path[name] for path in paths) for name in CHAIN_NAMES}),
                timings=timings,
                slow=[dict(sequence=f['sequence'], commit_uptime_s=first(f, 31)/1e9,
                           callback_us=span(f, 31, 33), prepare_us=span(f, 3, 4), inbox_us=span(f, 5, 6),
                           gpu_us=f['values'].get(34), draw_us=f['values'].get(36),
                           end_us=f['values'].get(37), chain_us=f['chain_us'],
                           chain_exclusion=f['chain_exclusion'], held_reasons=[r[4] for r in rows
                            if r[1] == f['id'] and r[3] == 7 and f['created_ns'] <= r[0] <= first(f, 33)])
                      for f in slow])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.trace.stat().st_size > MAX_BYTES:
        parser.error('trace exceeds its budget')
    result = json.dumps(analyze(args.trace.read_bytes()), ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(result)
    else:
        print(result, end='')
