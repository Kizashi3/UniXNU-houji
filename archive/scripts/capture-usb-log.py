#!/usr/bin/env python3
"""Capture an explicitly selected CDC ACM serial port on macOS; no disk commands."""
import argparse
import array
import fcntl
import os
from pathlib import Path
import select
import sys
import termios
import time


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=Path, help='e.g. /dev/cu.usbmodemHOUJIUEFI001')
    p.add_argument('--output', type=Path)
    p.add_argument('--seconds', type=int, default=300)
    p.add_argument('--replay', action='store_true', help='request retained RAM logs from a compatible console')
    a = p.parse_args()
    if a.port is None:
        print('\n'.join(str(x) for x in sorted(Path('/dev').glob('cu.usbmodem*'))) or 'No CDC ACM serial device is currently connected.')
        return
    if a.output is None:
        p.error('--output is required when opening a port')
    if not str(a.port).startswith('/dev/cu.usbmodem'):
        p.error('select an explicit macOS CDC ACM cu.usbmodem port')
    if not 1 <= a.seconds <= 3600:
        p.error('--seconds must be between 1 and 3600')
    fd = os.open(a.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    original = termios.tcgetattr(fd)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attrs[4] = attrs[5] = termios.B115200
        attrs[6][termios.VMIN] = 0
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        fcntl.ioctl(fd, termios.TIOCMBIS, array.array('i', [termios.TIOCM_DTR]))
        if a.replay:
            os.write(fd, b'replay\n')
        a.output.parent.mkdir(parents=True, exist_ok=True)
        end = time.monotonic() + a.seconds
        with a.output.open('ab', buffering=0) as log:
            while time.monotonic() < end:
                if not select.select([fd], [], [], max(0, min(1, end - time.monotonic())))[0]:
                    continue
                data = os.read(fd, 65536)
                if not data:
                    time.sleep(0.02)
                    continue
                log.write(data)
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSANOW, original)
        except OSError:
            pass
        os.close(fd)


if __name__ == '__main__':
    main()
