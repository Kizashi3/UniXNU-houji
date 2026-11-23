#!/usr/bin/env python3
"""Bounded, read-only USB keepalive for this device while a local build runs."""
import subprocess
import time

ADB = '${USER_HOME}/Library/Android/sdk/platform-tools/adb'
SERIAL = 'DEVICE_SERIAL'
deadline = time.monotonic() + 1200
port = None
while time.monotonic() < deadline:
    if port is None:
        for candidate in (5038, 15049, 5037, 5047):
            try:
                r = subprocess.run([ADB, '-P', str(candidate), 'devices'], capture_output=True, timeout=3)
                if (SERIAL + '\trecovery').encode() in r.stdout:
                    port = candidate
                    print('Recovery keepalive connected on ' + str(port), flush=True)
                    break
            except subprocess.TimeoutExpired:
                pass
    if port is not None:
        try:
            r = subprocess.run([ADB, '-P', str(port), '-s', SERIAL, 'exec-out',
                                'getprop ro.houji.native_rescue; getprop ro.product.device'],
                               capture_output=True, timeout=3)
            if r.returncode or r.stderr or r.stdout.splitlines() != [b'1', b'houji']:
                print('Recovery keepalive disconnected', flush=True)
                port = None
        except subprocess.TimeoutExpired:
            port = None
    time.sleep(3)
print('Recovery keepalive ended', flush=True)
