#!/usr/bin/env python3
"""Encode the captured houji SKU's complete factory GPU OPP table, offline."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

P = Path(__file__).resolve().parents[1]
N = Path('${HOUJI_ARTIFACTS}/native-port')


def node(text, start):
    begin = text.index('{', start) + 1
    at, depth = begin, 1
    while depth:
        assert at < len(text)
        depth += (text[at] == '{') - (text[at] == '}')
        at += 1
    return text[begin:at - 1]


def property_values(text, name):
    match = re.search(re.escape(name) + r' = <([^>]+)>;', text)
    return [int(x, 0) for x in match[1].split()] if match else None


def select(dts, speed_bin, soc_code):
    bins = []
    for match in re.finditer(r'qcom,gpu-pwrlevels-[0-9]+ \{', dts):
        body = node(dts, match.start())
        speed = property_values(body, 'qcom,speed-bin')
        sku = property_values(body, 'qcom,sku-codes')
        if speed is not None and speed != [speed_bin]:
            continue
        matches = (0 in sku or soc_code in sku) if sku else speed == [speed_bin]
        if not matches:
            continue
        for row in re.finditer(r'qcom,gpu-pwrlevel@\w+ \{', body):
            values = node(body, row.start())
            get = lambda k: property_values(values, k)[0]
            bins.append(dict(hz=get('qcom,gpu-freq'), arc=get('qcom,level'),
                             bw=get('qcom,bus-freq'), register=get('reg')))
        return match.group().split()[0], sorted(bins, key=lambda x: x['hz'])
    raise ValueError('No matching captured factory bin')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--facts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    facts = json.loads(args.facts.read_text())
    assert facts['device'] == 'houji' and facts['native_rescue'] == '1'
    assert facts['feature_code'] == 'AB' and facts['gpu_speed_bin'] == 5
    # SOCINFO_FC_AB == 2. KGSL uses pcode only for internal Y* feature codes.
    assert facts['gpu_soc_code'] == 2
    dts = N / 'device-baseline/live-fdt.dts'
    text = dts.read_text()
    assert hashlib.sha256(dts.read_bytes()).hexdigest() == facts['dts_sha256']
    selected, points = select(text, facts['gpu_speed_bin'], facts['gpu_soc_code'])
    assert selected == 'qcom,gpu-pwrlevels-3' and 1 < len(points) < 16
    assert points[0]['hz'] == 231000000 and points[-1]['hz'] == 903000000
    spec = importlib.util.spec_from_file_location('hfi_tables', P / 'scripts/make-gpu-hfi-tables.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    aop = N.parent / 'native-research/houji-aop-20261025/aop_a.bin'
    _, _, meta = module.tables(aop.read_bytes(), text)
    rails = meta['rails']
    for point in points:
        gx = next(i for i, value in enumerate(rails['gfx.lvl']) if value >= point['arc'])
        mx = next(i for i, value in enumerate(rails['mx.lvl']) if value >= rails['gfx.lvl'][gx])
        point['vote'] = (rails['gfx.lvl'][gx] << 16) | (mx << 8) | gx
        assert point['hz'] % 1000 == 0 and 0 < point['bw'] < len(meta['ddr_levels'])
    boot = next(i + 1 for i, point in enumerate(points) if point['hz'] == 500000000)
    lines = ['/* SPDX-License-Identifier: BSD-2-Clause-Patent',
             ' * Generated from this houji FDT/AOP and read-only SKU evidence.',
             ' * HFI ACKs are requests, not measured core frequencies. */',
             '#ifndef HOUJI_GPU_FACTORY_OPP_H', '#define HOUJI_GPU_FACTORY_OPP_H',
             '#include <stdint.h>',
             f'enum {{ HCO_COUNT={len(points)}, HCO_BOOT_LEVEL={boot} }};',
             'struct HoujiGpuOpp {uint32_t khz,arc_vote,bw_index;};',
             'static const struct HoujiGpuOpp houjiGpuOpps[HCO_COUNT]={']
    for point in points:
        lines.append(f' {{{point["hz"] // 1000}u,0x{point["vote"]:08x}u,{point["bw"]}u}},')
    lines += ['};',
              'static inline const struct HoujiGpuOpp *hco_opp(unsigned level) {',
              ' return level && level<=HCO_COUNT ? &houjiGpuOpps[level-1] : 0;', '}',
              'static inline unsigned hco_at_least(uint64_t khz,unsigned cap) {',
              ' if(!cap || cap>HCO_COUNT)return 0;',
              ' unsigned level=1;while(level<cap && houjiGpuOpps[level-1].khz<khz)++level;',
              ' return level;', '}', '#endif']
    args.output.mkdir(parents=True, exist_ok=True)
    header = args.output / 'HoujiGpuFactoryOpp.h'
    header.write_text('\n'.join(lines) + '\n')
    (args.output / 'factory-opps.json').write_text(json.dumps(dict(
        selected_node=selected, points=points, boot_level=boot,
        dts_sha256=facts['dts_sha256'], aop_sha256=hashlib.sha256(aop.read_bytes()).hexdigest(),
        facts_sha256=hashlib.sha256(args.facts.read_bytes()).hexdigest(),
        header_sha256=hashlib.sha256(header.read_bytes()).hexdigest(),
        hardware_qualified=False, thermal_feedback_qualified=False), indent=2) + '\n')
    print(f'{selected}: {len(points)} factory levels, {points[0]["hz"] // 1000000}..{points[-1]["hz"] // 1000000} MHz; boot level {boot}')


if __name__ == '__main__':
    main()
