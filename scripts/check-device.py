"""Compare selected hardware properties with the upstream giulia DTB (needs fdtget)."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

def get(dtb, node, prop, fmt):
    return subprocess.check_output(['fdtget', '-t', fmt, str(dtb), node, prop], text=True).strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('runtime_dtb', type=Path)
    parser.add_argument('upstream_dtb', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    values = []
    for node, prop, fmt in [('/', 'model', 's'), ('/', 'compatible', 's'),
                            ('/', 'qcom,msm-id', 'x'), ('/', 'qcom,board-id', 'x'),
                            ('/memory', 'reg', 'x'), ('/reserved-memory/splash_region', 'reg', 'x')]:
        actual = get(args.runtime_dtb, node, prop, fmt)
        expected = get(args.upstream_dtb, node, prop, fmt)
        values.append({'node': node, 'property': prop, 'runtime': actual,
                       'upstream': expected, 'matches': actual == expected})
    passed = all(item['matches'] for item in values)
    report = {'selected_properties_match': passed, 'checks': values,
              'runtime_sha256': hashlib.sha256(args.runtime_dtb.read_bytes()).hexdigest(),
              'upstream_sha256': hashlib.sha256(args.upstream_dtb.read_bytes()).hexdigest(),
              'note': 'Matching selected DT properties does not prove firmware or hardware compatibility.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if not passed:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
