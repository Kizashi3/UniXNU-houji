"""Reserve the explicit GPU mode 3 firmware report in a new GUI ADT."""
import argparse
import hashlib
import json
from pathlib import Path

from ios16_gpu_power import add_request, check_request


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--adt', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    report_path = a.out.with_suffix('.gpu-power.json')
    if a.out.exists() or report_path.exists():
        p.error('Output already exists')
    before = a.adt.read_bytes()
    after = add_request(before)
    report = {'input_sha256': hashlib.sha256(before).hexdigest(),
              'output_sha256': hashlib.sha256(after).hexdigest(),
              'only_added_property': '/device-tree/chosen/giulia-gpu-power',
              'request': check_request(after, 3), 'hardware_tested': False}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_bytes(after)
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
