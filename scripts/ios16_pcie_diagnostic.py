"""Interpret measured PCIe conditions without inventing an electrical cause."""
import struct

PHASES = (
    '设置 PHY_RCHNG 频率前', 'SetClockFreqHz 返回后', 'EnableClock 返回后',
    '其余时钟启用后、CESTA 请求前', 'CESTA D0 请求完成后',
    'PCIe 核心复位完成后', 'PHY 复位完成后', 'PHY 就绪、PIPE 启用后',
)
FINAL = (
    ('core_power', 0x16b008), ('phy_power', 0x16c004),
    ('core_reset', 0x16b000), ('phy_reset', 0x16c01c),
    ('perst_config', 0xf15e000), ('perst_io', 0xf15e004),
    ('wlan_config', 0xf110000), ('wlan_io', 0xf110004),
    ('ltssm', 0x1c001b0), ('elbi', 0x60000f28), ('link', 0x60000080),
    ('phy_status', 0x1c06214), ('crm_perf', 0x1d0500c),
    ('refclk', 0x1ff1100), ('pipe_cbcr', 0x16b048),
)
STATES = {0: 'Detect.Quiet', 1: 'Detect.Active', 2: 'Polling.Active',
          3: 'Polling.Compliance', 4: 'Polling.Configuration', 17: 'L0',
          18: 'L0s', 20: 'L1.Idle', 21: 'L2.Idle'}
SOURCES = {
    'gcc': 'drivers/clk/qcom/gcc-pineapple.c',
    'rcg': 'drivers/clk/qcom/clk-rcg2.c',
    'gdsc': 'drivers/clk/qcom/gdsc-regulator.c',
    'pcie': 'drivers/pci/controller/pci-msm.c',
    'gpio': 'drivers/pinctrl/qcom/pinctrl-msm.c',
}


def decode_trace(raw):
    if len(raw) != 168:
        raise ValueError('PCIe trace must contain exactly 168 bytes')
    words = struct.unpack('<42I', raw)
    magic, stage_mask, error = words[:3]
    if magic != 0x32535047 or stage_mask & 0xffff != 13 or not error:
        raise ValueError('Not a v2 link-failure trace')
    mask = stage_mask >> 16
    if mask & ~255:
        raise ValueError('Unsupported phase validity bits')
    phases = []
    changes = []
    for i, name in enumerate(PHASES):
        cfg, cmd, aux = words[3+i*3:6+i*3]
        present = bool(mask & (1 << i))
        phases.append({'phase': i, 'name': name, 'captured': present,
                       'rchng_cfg': hex(cfg) if present else None,
                       'rchng_cmd': hex(cmd) if present else None,
                       'aux_cfg': hex(aux) if present else None})
        if i and present and mask & (1 << (i-1)):
            old = words[3+(i-1)*3]
            if old != 0xffffffff and cfg != 0xffffffff and old != cfg:
                changes.append({'after': name, 'before': hex(old), 'after_value': hex(cfg),
                                'xor': hex(old ^ cfg),
                                'rate_fields_changed': bool((old ^ cfg) & 0x371f),
                                'hw_control_changed': bool((old ^ cfg) & (1 << 20))})
    values = dict(zip((n for n, _ in FINAL), words[27:]))
    registers = [{'name': n, 'address': hex(a), 'value': hex(values[n])} for n, a in FINAL]
    checks = []

    def check(label, keys, predicate, expected, source):
        observed = [values[k] for k in keys]
        valid = all(v != 0xffffffff for v in observed)
        checks.append({'condition': label, 'result': ('pass' if predicate(*observed) else 'fail') if valid else 'unknown',
                       'expected': expected, 'observed': {k: hex(values[k]) for k in keys},
                       'source': SOURCES[source]})

    check('核心电源域完成上电', ['core_power'], lambda v: bool(v & 0x10000), 'CFG_GDSCR bit16=1', 'gdsc')
    check('PHY 电源域完成上电', ['phy_power'], lambda v: bool(v & 0x10000), 'CFG_GDSCR bit16=1', 'gdsc')
    check('核心复位已释放', ['core_reset'], lambda v: not v & 1, 'BCR bit0=0', 'gcc')
    check('PHY 复位已释放', ['phy_reset'], lambda v: not v & 1, 'BCR bit0=0', 'gcc')
    for name, prefix in [('PERST 已配置输出且回读为高', 'perst'), ('WLAN_EN 已配置输出且回读为高', 'wlan')]:
        check(name, [prefix+'_config', prefix+'_io'],
              lambda c, v: bool(c & 512) and c & 60 == 0 and v & 3 == 3,
              'GPIO mux=0, OE=1, OUT=1, IN=1', 'gpio')
    check('LTSSM 已启用', ['ltssm'], lambda v: bool(v & 256), 'PARF_LTSSM bit8=1', 'pcie')
    check('PHY ready 条件通过', ['phy_status'], lambda v: not v & 64, 'DT phy-status-bit6=0', 'pcie')
    check('CESTA 达到训练请求级别', ['crm_perf'], lambda v: 4 <= v <= 5, 'CURR_PERF_OL >= max Gen3 D0 level 4', 'pcie')
    check('参考时钟门已启用', ['refclk'], lambda v: bool(v & 1), 'CLKREF_EN bit0=1; does not measure waveform', 'gcc')
    check('PIPE 时钟未报告停止', ['pipe_cbcr'], lambda v: not v & (1 << 31), 'CBCR CLK_OFF bit31=0; does not measure frequency', 'gcc')
    for i in (3, 4, 5, 6, 7):
        cfg, cmd, aux = words[3+i*3:6+i*3]
        valid = bool(mask & (1 << i)) and cfg != 0xffffffff and cmd != 0xffffffff
        checks.append({'condition': PHASES[i]+'：RCHNG 硬件控制已启用且更新已完成',
                       'result': ('pass' if cfg & (1 << 20) and not cmd & 1 else 'fail') if valid else 'unknown',
                       'expected': 'CFG bit20=1, CMD_UPDATE bit0=0',
                       'observed': {'cfg': hex(cfg) if valid else None, 'cmd': hex(cmd) if valid else None},
                       'source': SOURCES['rcg']})
    valid_link = values['elbi'] != 0xffffffff and values['link'] != 0xffffffff
    state = (values['elbi'] >> 12) & 63 if valid_link else None
    up = bool(values['elbi'] & (1 << 10) and values['link'] & (1 << 29)) if valid_link else None
    failures = [c['condition'] for c in checks if c['result'] == 'fail']
    unknown = [c['condition'] for c in checks if c['result'] == 'unknown']
    if failures:
        conclusion = '超时时确认以下启动条件不满足：' + '；'.join(failures)
    elif unknown:
        conclusion = '启动条件存在缺失或无效回读，不能判断全部条件已满足。'
    else:
        conclusion = '已采集的启动条件均通过，但链路未建立；这些寄存器没有给出唯一电气根因。'
    if up:
        conclusion = '报告标记超时，但最终 XMLH_LINK_UP 和 DLL_ACTIVE 均为 1；记录存在矛盾，需核对采样时序。'
    return {'format': 2, 'stage': 13, 'error': error, 'phase_valid_mask': hex(mask),
            'phases': phases, 'clock_changes': changes, 'registers': registers, 'checks': checks,
            'confirmed_failures': failures, 'unknown_conditions': unknown,
            'final_ltssm': {'code': state, 'name': STATES.get(state, 'unknown'), 'link_up': up},
            'conclusion': conclusion,
            'not_measured': ['芯片引脚处实际电压与参考时钟波形', 'PCIe 对端接收终端电阻及 PIPE 接收检测握手'],
            'scope': 'UEFI timeout snapshot before cleanup; phase boundaries are measured, causal attribution is not inferred'}


def render_trace(report):
    lines = [report['conclusion'],
             '采样地址：RCHNG_CFG=0x16b05c，CMD=0x16b058，AUX_CFG=0x16b078', '', '分阶段时钟回读：']
    for row in report['phases']:
        lines.append(f"{row['phase']}. {row['name']}: RCHNG_CFG={row['rchng_cfg']} CMD={row['rchng_cmd']} AUX_CFG={row['aux_cfg']}")
    lines += ['', '检测到的配置变化：']
    for row in report['clock_changes']:
        lines.append(f"{row['after']}: {row['before']} -> {row['after_value']}；XOR={row['xor']}；速率位变化={row['rate_fields_changed']}；硬件控制位变化={row['hw_control_changed']}")
    if not report['clock_changes']:
        lines.append('相邻有效采样点之间未检测到 RCHNG_CFG 变化。')
    lines += ['', '条件检查：']
    for row in report['checks']:
        lines.append(f"[{row['result']}] {row['condition']}: {row['observed']}；期望 {row['expected']}；依据 {row['source']}")
    lines += ['', '失败清理前原始寄存器：']
    for row in report['registers']:
        lines.append(f"{row['name']} [{row['address']}] = {row['value']}")
    lines += ['', f"最终 LTSSM：{report['final_ltssm']}", '尚未测量：'+'；'.join(report['not_measured'])]
    return '\n'.join(lines)+'\n'
