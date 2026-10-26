"""Decode versioned PCIe preparation reports carried in XNU boot arguments."""
import re
import base64
import binascii
import struct

BINARY_FIELDS=('version','stage','detail','error','firmware_status','clock_version',
    'rails','clocks','phy','link','elbi','device','command','bar0','bar1',
    'gpio_before','gpio_after','root_device','retained_rails','pipe_source',
    'cleanup_status','perst','sw_ctrl','wlan_sw_ctrl','ref_clock',
    'port_link_before','port_link_after','link_cap','gen2_ctrl','pipe_gate',
    'phy_common','phy_status2','phy_status3','clkreq',
    'ltssm_seen_lo','ltssm_seen_hi','ltssm_changes')
BINARY_FORMAT=struct.Struct('<4I2Q14IQ16I')
BINARY_V4_FIELDS=BINARY_FIELDS+('pipe_hz','pipe_measure_status')
BINARY_V4_FORMAT=struct.Struct('<4I2Q14IQ18I')

FIELDS=('stage','detail','error','firmware_status','rails','clocks','phy','link',
        'elbi','device','clock_version','cleanup_status','retained_rails','root_device')
STAGES={1:'start',2:'firmware ABI',3:'resolve resources / snapshot votes',4:'map MMIO',
        5:'check pin ownership',6:'power rails',7:'WLAN enable',8:'PCIe power domains',
        9:'PCIe clocks',10:'reset controller and PHY',11:'program PHY',12:'wait for PHY',
        13:'train PCIe link',14:'configure outbound configuration window',
        15:'identify endpoint',16:'endpoint identified',17:'CESTA/CRM D0 resources',
        18:'resources prepared; XNU owns pending link training'}
ERRORS={0:'success',1:'firmware resource error',2:'pin ownership/mux mismatch',
        3:'inherited Wi-Fi or Bluetooth already active',4:'invalid PHY sequence',
        5:'invalid register state',6:'PHY timeout',7:'link timeout',8:'iATU timeout',
        9:'unexpected endpoint ID',10:'endpoint bus mastering unexpectedly enabled'}
RAILS=('ldob15','ldoc3','smpi4','smpc2','smpc3','smpc6','smpc1','ldoi1','ldoi3')
CLOCKS=('gcc_aggre_noc_pcie_axi_clk','gcc_cnoc_pcie_sf_axi_clk','gcc_ddrss_pcie_sf_qtb_clk',
        'gcc_pcie_0_cfg_ahb_clk','gcc_pcie_0_mstr_axi_clk','gcc_pcie_0_slv_axi_clk',
        'gcc_pcie_0_slv_q2a_axi_clk','gcc_pcie_0_aux_clk','gcc_pcie_0_phy_rchng_clk',
        'gcc_cfg_noc_pcie_anoc_ahb_clk','tcsr_pcie_0_clkref_en','gcc_pcie_0_pipe_clk')

def decode_reports(data):
    reports=[]
    seen=set()
    for match in re.finditer(rb'\bgiulia_wifi([2345p]?)=([^\s\x00]+)',data):
        pending=match[1]==b'p'
        version=5 if pending else int(match[1]) if match[1] else 1
        token=match[2]
        key=(version,pending,token)
        if key in seen:continue
        seen.add(key)
        if version>=3:
            try:raw=base64.b64decode(token,validate=True)
            except binascii.Error as e:raise ValueError('Malformed PCIe base64 report') from e
            binary_format=BINARY_FORMAT if version==3 else BINARY_V4_FORMAT
            binary_fields=BINARY_FIELDS if version==3 else BINARY_V4_FIELDS
            if len(raw)!=binary_format.size or base64.b64encode(raw)!=token:
                raise ValueError('Malformed/truncated PCIe binary report')
            r=dict(zip(binary_fields,binary_format.unpack(raw)))
            if r.pop('version')!=version:raise ValueError('PCIe binary report version mismatch')
        else:
            items=token.split(b',')
            lengths=(14,17) if version==1 else (21,)
            if len(items) not in lengths or any(not re.fullmatch(rb'[0-9a-fA-F]{1,16}',i) for i in items):
                raise ValueError('Malformed/truncated PCIe report')
            fields=FIELDS if len(items)==len(FIELDS) else FIELDS+('gpio_before','gpio_after','pipe_source')
            if version==2:fields+=('perst','sw_ctrl','wlan_sw_ctrl','ref_clock')
            r=dict(zip(fields,(int(i,16) for i in items)))
        if r['stage'] not in STAGES or r['error'] not in ERRORS:
            raise ValueError('Unsupported PCIe report schema')
        for name,value in r.items():
            if name not in ('firmware_status','clock_version','cleanup_status') and value>0xffffffff:
                raise ValueError('PCIe report field overflow')
        rail_count=9 if version>=5 else 7
        all_rails=(1<<rail_count)-1
        if r['rails']>all_rails or r['clocks']>4095 or r['retained_rails']>all_rails:
            raise ValueError('Unknown PCIe resource bits')
        ready=(r['stage']==16 and r['error']==0 and r['firmware_status']==0 and
               r['device']==0x110717cb and r['rails']==all_rails and r['clocks']==4095 and
               r['phy']!=0xffffffff and not r['phy']&64 and
               r['link']!=0xffffffff and bool(r['link']&(1<<29)) and
               r['elbi']!=0xffffffff and bool(r['elbi']&1024) and
               r['cleanup_status']==0 and r['retained_rails']==0)
        prepared=(pending and r['stage']==18 and r['detail']==0x584e554c and r['error']==0 and
                  r['firmware_status']==0 and r['rails']==511 and r['clocks']==4095 and
                  r['phy']!=0xffffffff and not r['phy']&64 and r['root_device']&65535==0x17cb and
                  r['device']==0 and r['command']==0 and r['gpio_after']&3==3 and
                  (r['perst']>>16)&0x23c==0x200 and not r['perst']&3 and r['ref_clock']==1)
        if pending and not prepared:raise ValueError('Invalid prepared PCIe handoff')
        if not prepared and (r['stage']==16 or r['error']==0) and not ready:
            raise ValueError('Inconsistent PCIe success claim')
        if version>=2 and ready and (r['ref_clock']==0xffffffff or not r['ref_clock']&1):
            raise ValueError('PCIe success report lacks an enabled reference clock')
        r['report_version']=version
        if version>=2:
            r['pin_readback']={k:{'config':r[k]>>16,'io':r[k]&0xffff} for k in ('perst','sw_ctrl','wlan_sw_ctrl')}
            if r['stage']==13 and r['error']==7:r['ltssm_enable_readback']=bool(r['detail']&256)
        if version>=3:
            r['pin_readback']['clkreq']={'config':r['clkreq']>>16,'io':r['clkreq']&0xffff}
            states=r['ltssm_seen_lo'] | (r['ltssm_seen_hi']<<32)
            r['ltssm_states_seen']=[i for i in range(64) if states&(1<<i)]
            r['last_ltssm_state']=None if r['elbi']==0xffffffff else (r['elbi']>>12)&63
            r['core_x1_configured']=(r['port_link_after']!=0xffffffff and
                r['port_link_after']&0x3f00a0==0x10020 and
                r['gen2_ctrl']!=0xffffffff and r['gen2_ctrl']&0x1f00==0x100 and
                r['link_cap']!=0xffffffff and r['link_cap']&0x3f0==0x10)
            r['core_x2_configured']=(r['port_link_after']!=0xffffffff and
                r['port_link_after']&0x3f00a0==0x30020 and
                r['gen2_ctrl']!=0xffffffff and r['gen2_ctrl']&0x1f00==0x200 and
                r['link_cap']!=0xffffffff and r['link_cap']&0x3f0==0x20)
            r['core_stock_initial_training']=(r['port_link_after']!=0xffffffff and
                r['port_link_after']&0x3f00a0==0x30020 and
                r['gen2_ctrl']!=0xffffffff and r['gen2_ctrl']&0x1f00==0x100 and
                r['link_cap']!=0xffffffff and r['link_cap']&0x3f0==0x20)
            if ready and (not (r['core_x1_configured'] or r['core_x2_configured'] or r['core_stock_initial_training']) or
                          not states&(1<<17) or r['command']&4):
                raise ValueError('PCIe success contradicts lane configuration, L0, or disabled DMA')
        if version>=4:
            names=('not run','measured','counter already active','invalid register',
                   'counter clear timeout','counter completion timeout','debug state restore failed')
            if r['pipe_measure_status']>=len(names):raise ValueError('Unknown clock measurement status')
            r['pipe_measure_name']=names[r['pipe_measure_status']]
            r['pipe_frequency_measured']=r['pipe_measure_status']==1
            if not r['pipe_frequency_measured'] and r['pipe_hz']:
                raise ValueError('Failed measurement cannot claim a frequency')
        r.update(stage_name=STAGES[r['stage']],error_name=ERRORS[r['error']],
                 xnu_link_pending=prepared,
                 endpoint_identified=ready,firmware_loaded=False,scan_supported=False,
                 observation_scope='UEFI before ExitBootServices; not an XNU runtime link test',
                 retained_rail_names=[n for i,n in enumerate(RAILS) if r['retained_rails']&(1<<i)])
        if prepared:
            r['endpoint_registers_sampled']=False
            r['pin_readback'].pop('sw_ctrl',None);r['pin_readback'].pop('wlan_sw_ctrl',None)
            r['pdc_wake_routes']={'before_sw_ctrl_intr_cfg':r['sw_ctrl'],'before_wlan_sw_ctrl_intr_cfg':r['wlan_sw_ctrl'],
                'sw_ctrl_intr_cfg':r['bar0'],'wlan_sw_ctrl_intr_cfg':r['bar1'],
                'both_enabled':r['bar0']!=0xffffffff and r['bar1']!=0xffffffff and (r['bar0']&192)==192 and (r['bar1']&192)==192}
        if r['stage']==5 and r['detail'] in (0x5008,0x6008):
            r['resource']='GPIO18 SW_CTRL PDC wake route' if r['detail']==0x5008 else 'GPIO19 WLAN_SW_CTRL PDC wake route'
            r['wake_intr_cfg_readback']=r['bar0'] if r['detail']==0x5008 else r['bar1']
            r['endpoint_registers_sampled']=False
        if version>=5 and not r['device'] and r['error'] and r.get('command',0)&0xffffff00==0xce570000:
            r['cesta_cleanup_failure']={'error':r['command']&255,'region':r['bar0']>>24,
                'offset':hex(r['bar0']&65535),'value':hex(r['bar1'])}
            r['endpoint_registers_sampled']=False
        if r['stage']==3:
            d=r['detail']
            if d<rail_count:r['resource']=RAILS[d]
            elif 0x100<=d<0x100+12:r['resource']=CLOCKS[d-0x100]
            elif 0x200<=d<0x202:r['resource']=('gcc_pcie_0_gdsc','gcc_pcie_0_phy_gdsc')[d-0x200]
            elif 0x300<=d<0x300+rail_count*3:r['resource']=RAILS[(d-0x300)//3]
            elif 0x400<=d<0x406:r['resource']=('MC0','SH0','SH1','SN4','IP0','ACV')[d-0x400]
        if r['stage']==6 and r['detail']<rail_count:r['resource']=RAILS[r['detail']]
        if r['stage']==9 and r['detail']<12:r['resource']=CLOCKS[r['detail']]
        if r['stage']==17:
            d=r['detail']
            r['cesta_failure']={'region':d>>24,'error':(d>>16)&255,'offset':hex(d&65535)}
            r['resource']='PCIe0 CESTA/CRM'
        reports.append(r)
    return reports
