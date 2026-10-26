"""Verify the captured Ace 5 GPU board, pinned vendor sources and local firmware."""
import argparse
import json
from pathlib import Path
from ios16_gpu import verify_inputs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dts', type=Path, required=True)
    p.add_argument('--source-dir', type=Path, required=True)
    p.add_argument('--firmware-dir', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    report = verify_inputs(a.dts, a.source_dir, a.firmware_dir)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2) + '\n')
    print('Ace 5 A750 inputs verified; hardware initialization and Metal remain unverified')


if __name__ == '__main__':
    main()
