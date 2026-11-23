#!/usr/bin/env python3
"""Collect diagnostics from an already mounted, offline iOS system snapshot.

Reads files only; does not attach images or access a phone. Compare content with
the pre-boot snapshot because the board's clock can repeat across boots. Reports
and raw files stay in a new private directory, with no automatic upload.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat

LOG_ROOTS = ('private/var/mobile/Library/Logs', 'private/var/root/Library/Logs')
MAX_FILE = 16 * 1024**2
MAX_TOTAL = 256 * 1024**2


def fingerprint(st):
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def safe_path(root, relative):
    path = root
    for part in Path(relative).parts:
        if part in ('.', '..', '/'):
            raise ValueError('invalid relative diagnostic path')
        path = path / part
        if path.is_symlink():
            raise ValueError('diagnostic path contains a symlink: ' + relative)
    return path


def read_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE:
            raise ValueError('diagnostic is not a bounded regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(MAX_FILE + 1)
        if len(data) != before.st_size or fingerprint(before) != fingerprint(os.fstat(fd)):
            raise ValueError('diagnostic changed while reading')
        return data
    finally:
        os.close(fd)


def candidates(root):
    # Exact board diagnostic only; do not collect arbitrary system log files.
    for diagnostic in ('private/var/log/houji-power.jsonl',
                       'private/var/mobile/Library/Logs/UniXNU-system-apps.log'):
        if (root / diagnostic).exists() or (root / diagnostic).is_symlink():
            yield diagnostic
    for relative in LOG_ROOTS:
        directory = safe_path(root, relative)
        if not directory.exists():
            continue
        for parent, directories, files in os.walk(directory, followlinks=False):
            directories[:] = sorted(d for d in directories if not (Path(parent) / d).is_symlink())
            for name in sorted(files):
                path = Path(parent) / name
                # Keep crash reports and the board's own bounded diagnostic text.
                # Do not recursively copy caches, app data or the entire volume.
                if (path.suffix in ('.ips', '.crash', '.panic') or
                        (name.startswith('Houji') and path.suffix in ('.log', '.txt'))):
                    yield str(path.relative_to(root))


def crash_summary(data):
    """Summarize the modern two-JSON IPS format without replacing its raw file."""
    try:
        text = data.decode('utf-8')
        header, end = json.JSONDecoder().raw_decode(text.lstrip())
        body = json.loads(text.lstrip()[end:]) if text.lstrip()[end:].strip() else header
        if not isinstance(body, dict):
            return None
        index = body.get('faultingThread')
        frames = []
        if isinstance(index, int) and 0 <= index < len(body.get('threads', [])):
            images = body.get('usedImages', [])
            for frame in body['threads'][index].get('frames', [])[:20]:
                image_index = frame.get('imageIndex')
                image = images[image_index] if isinstance(image_index, int) and 0 <= image_index < len(images) else {}
                frames.append({key: value for key, value in dict(
                    image=image.get('name'), symbol=frame.get('symbol'),
                    symbol_offset=frame.get('symbolLocation'), image_offset=frame.get('imageOffset')).items()
                    if value is not None})
        return dict(process=body.get('procName'), exception=body.get('exception'),
                    termination=body.get('termination'), faulting_thread=index, frames=frames)
    except (UnicodeError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


def collect(root, baseline, output, run_id):
    report = dict(captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  run_id=run_id, run_id_source='operator; IPS files have no trial UUID',
                  comparison='content hashes, not timestamps', source_writes_requested=False,
                  compared_with_baseline=baseline is not None, files=[], errors=[],
                  unchanged_files=0, inspected_bytes=0, copied_bytes=0)
    for relative in candidates(root):
        try:
            path = safe_path(root, relative)
            size = path.lstat().st_size
            if report['inspected_bytes'] + size > MAX_TOTAL:
                raise ValueError('total inspection limit exceeded')
            report['inspected_bytes'] += size
            data = read_file(path)
            digest = hashlib.sha256(data).hexdigest()
            old = safe_path(baseline, relative) if baseline else None
            before = None
            if old and old.exists():
                before = hashlib.sha256(read_file(old)).hexdigest()
            if digest == before:
                report['unchanged_files'] += 1
                continue
            target = output / 'files' / relative
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            target.write_bytes(data)
            entry = dict(path=relative, bytes=len(data), sha256=digest,
                         baseline_sha256=before, change='changed' if before else 'new-or-no-baseline')
            if path.suffix == '.ips':
                entry['crash'] = crash_summary(data)
            report['files'].append(entry)
            report['copied_bytes'] += len(data)
        except (OSError, ValueError) as error:
            report['errors'].append(dict(path=relative, error=str(error)))
    report['status'] = 'PARTIAL' if report['errors'] else 'PASS'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True, help='mounted post-boot snapshot, preferably read-only')
    parser.add_argument('--baseline', type=Path, help='mounted pre-boot snapshot for this trial')
    parser.add_argument('--run-id', required=True, help='trial UUID used to label this collection')
    parser.add_argument('--output', type=Path, required=True, help='new private evidence directory')
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{32}', args.run_id):
        parser.error('--run-id must contain 32 lowercase hex digits')
    root = args.root.resolve(strict=True)
    baseline = args.baseline.resolve(strict=True) if args.baseline else None
    if baseline == root:
        parser.error('post-boot and pre-boot roots must differ')
    output = args.output.resolve()
    for source in (root, baseline):
        if source and (not source.is_dir() or output.is_relative_to(source)):
            parser.error('source must be a directory and output must be outside it')
    os.umask(0o077)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    report = collect(root, baseline, output, args.run_id)
    (output / 'capture.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(dict(status=report['status'], new_or_changed_files=len(report['files']),
                          unchanged_files=report['unchanged_files'], errors=len(report['errors']),
                          output=str(output), source_writes_requested=False), indent=2))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
