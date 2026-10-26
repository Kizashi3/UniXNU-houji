"""Read-only USB acceptance check for the HFI host-preparation stage.

Never starts GMU, pins memory, rings a doorbell, reboots, or flashes. Passing
proves only that the running kernel prepared the expected owned buffers.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time

from debug_terminal import matching_ports, wire_command


def evaluate(text):
    status = re.findall(
        r'command=gpu.status stage=host-memory-prepared mode=3 '
        r'firmware_verified=1 host_prepared=1 reservations=8 table_pages=6 leaf_pages=139', text)
    table = re.findall(
        r'GIULIA GPU HFI: table_iova=0x60010000 log_iova=0x60030000 '
        r'vrb_iova=0x60040000 cpu_cache=normal-nc pinned=0', text)
    queues = re.findall(r'GIULIA GPU HFI: queue=(\d+) code=(\d+) read=(\d+) write=(\d+)', text)
    observed = {int(q): (int(code), int(read), int(write)) for q, code, read, write in queues}
    checks = {
        'expected_running_service': len(status) == 1,
        'expected_owned_buffer_layout': len(table) == 1,
        'all_17_queues_empty_and_valid': len(queues) == 17 and
            observed == {q: (0, 0, 0) for q in range(17)},
        'no_panic_in_capture': not re.search(r'panic\(cpu|Unaligned kernel data abort', text),
    }
    passed = all(checks.values())
    return {'scope': 'hfi-host-preparation-only', 'passed': passed, 'checks': checks,
            'stock_gmu_execution_verified': False, 'hfi_handshake_verified': False,
            'gpu_submission_verified': False, 'metal_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', help='Exact ACE5DBG001 CDC port, auto-detected by default')
    parser.add_argument('--seconds', type=float, default=8)
    parser.add_argument('--output', type=Path, required=True, help='New result directory')
    args = parser.parse_args()
    if not 2 <= args.seconds <= 60:
        parser.error('--seconds must be 2..60')
    import serial
    from serial.tools import list_ports
    ports = matching_ports(list_ports.comports())
    if args.port:
        if args.port not in ports:
            parser.error('Requested port is not the identified ACE5DBG001 device')
        port = args.port
    elif len(ports) == 1:
        port = ports[0]
    else:
        parser.error('Expected exactly one ACE5DBG001 device; use --port when ambiguous')
    args.output.mkdir(parents=True, exist_ok=False)
    raw = bytearray()
    error = None
    try:
        with serial.Serial(port, 115200, timeout=.05, write_timeout=2) as connection:
            # Discard buffered history before requesting fresh read-only records.
            connection.reset_input_buffer()
            for command in ('gpu.status', 'gpu.hfi.status'):
                wire = wire_command(command)
                if connection.write(wire) != len(wire):
                    raise OSError('Incomplete diagnostic command write')
                time.sleep(.1)
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                data = connection.read(min(max(connection.in_waiting, 1), 16384))
                raw.extend(data)
                if len(raw) > 4 * 1024 * 1024:
                    raise RuntimeError('Capture exceeded 4 MiB bound')
    except (OSError, RuntimeError) as exception:
        error = str(exception)
    report = evaluate(raw.decode('utf-8', errors='replace'))
    report.update(port=port, captured_at=datetime.now(timezone.utc).isoformat(),
                  log_sha256=hashlib.sha256(raw).hexdigest(), error=error)
    if error:
        report['passed'] = False
    (args.output/'device.log').write_bytes(raw)
    (args.output/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
