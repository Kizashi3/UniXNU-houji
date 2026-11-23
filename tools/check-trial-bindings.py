#!/usr/bin/env python3
"""Reject mismatched generated XNU log and GPU handoff trial identities."""
import argparse
from pathlib import Path
import re


def read_identity(path, symbol):
    match = re.search(r'\b' + symbol + r'\s*\[\s*16\s*\]\s*=\s*\{([^}]+)\}', path.read_text())
    if not match:
        raise ValueError(f'{path.name}: missing fixed 16-byte trial identity')
    identity = bytes(int(value.strip(), 0) for value in match[1].split(',') if value.strip())
    if len(identity) != 16:
        raise ValueError(f'{path.name}: invalid trial identity length')
    return identity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('xnu', type=Path, help='prepared XNU source tree')
    args = parser.parse_args()
    directory = args.xnu / 'iokit/Kernel/houji-ufs-root'
    try:
        log = read_identity(directory / 'HoujiLogAllocation.h', 'kHoujiLogRunId')
        handoff = read_identity(directory / 'HoujiZapTrial.h', 'kHoujiZapTrial')
        if log != handoff:
            raise ValueError('log and GPU handoff trial identities differ; regenerate both before building')
    except (OSError, ValueError) as error:
        parser.exit(1, f'Trial binding check failed: {error}\n')
    print('PASS: generated log and GPU handoff trial identities match')


if __name__ == '__main__':
    main()
