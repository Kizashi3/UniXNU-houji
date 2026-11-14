"""Prove the generated 338-slot inheritance header keeps every slot in place.

Run after generate-houji-legacy-abi.py and the probe compile. Parses clang's
-fdump-vtable-layouts output; no kernel or device is touched.
"""
import argparse
import json
import re
from pathlib import Path

EXPECTED_PURE = [211, 212, 242, 243, 292, 293, 321, 322, 329]
NAMED = {246: 'getDisplayDimensions', 274: 'startHardware', 276: 'kickSwapQueue',
         281: 'completeCurrentSwap', 282: 'validateSwap', 283: 'prepareSwap',
         287: 'getRefreshAttributes'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stdout')
    parser.add_argument('audit')
    parser.add_argument('--report')
    args = parser.parse_args()

    audit = json.loads(Path(args.audit).read_text())
    if audit['virtual_entries'] != 338 or audit['legacy_instance_bytes'] != 0x1660:
        raise SystemExit('audit is not the 20H392 338-slot profile')
    if audit['abstract_slots'] != EXPECTED_PURE:
        raise SystemExit('audit abstract slots differ from the checked profile')

    text = Path(args.stdout).read_text()
    header = "Vtable for 'IOMobileFramebufferLegacy'"
    if header not in text:
        raise SystemExit('no legacy vtable dump')
    block = text[text.index(header):text.index("VTable indices for 'IOMobileFramebufferLegacy'")]
    rows = re.findall(r'^\s*(\d+) \| (.*)$', block, re.M)
    if len(rows) != 341:
        raise SystemExit('expected 341 entries, saw %d' % len(rows))
    by_index = {int(n) - 2: name for n, name in rows}

    problems = []
    if sorted(by_index) != list(range(-2, 339)):
        problems.append('index space is not -2..338')
    for index in range(168, 338):
        name = by_index.get(index, '<missing>')
        match = re.search(r'opaque(\d+)', name)
        if index in NAMED:
            if NAMED[index] not in name:
                problems.append('slot %d expected %s, saw %s' % (index, NAMED[index], name))
        elif match:
            if int(match.group(1)) != index:
                problems.append('slot %d carries opaque%s' % (index, match.group(1)))
        else:
            problems.append('slot %d is not opaque/known: %s' % (index, name))
    probe = text[text.index("VTable indices for 'HoujiLegacyABIProbe'"):]
    probe_block = probe[:probe.index('\nVtable for', 1)] if '\nVtable for' in probe else probe
    pure_seen = sorted(int(m.group(1)) for m in
                       re.finditer(r'^\s*(\d+) \| void HoujiLegacyABIProbe::opaque\d+\(\)',
                                   probe_block, re.M))
    if pure_seen != EXPECTED_PURE:
        problems.append('probe pure overrides %s' % pure_seen)

    report = {'entries': len(rows), 'named': {str(k): v for k, v in NAMED.items()},
              'pure_slots': pure_seen, 'problems': problems, 'ok': not problems}
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
    if problems:
        print('FAIL', problems[:8])
        raise SystemExit(1)
    print('PASS: 338 slots, exact opaque index, seven named overrides, nine pure leaves')


if __name__ == '__main__':
    main()
