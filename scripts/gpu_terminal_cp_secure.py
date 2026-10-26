"""Stock first-RAW ordering with ABI2 ownership, SCM and bounded kernel watch."""
import hashlib
import struct
import time
from gpu_terminal_live import ROOT
from gpu_terminal_gen7_config import Gen7Config
from gpu_terminal_diagnostics import snapshot


def packet(opcode, count):
    return 0x70000000|count|((1^(count.bit_count()&1))<<15)|(opcode<<16)|((1^(opcode.bit_count()&1))<<23)


def prepare(live, transport, report):
    """Configure and verify firmware without staging or publishing any RAW."""
    if not (transport.platform_enabled and report.get('aqe_feature_enabled') and
            report.get('secure_context_active') and report.get('secure_cx_call_executed') and
            report.get('hwsched_start_accepted') and report.get('oob_ack')):
        raise RuntimeError('Complete platform prerequisites required before CP dispatch')
    config=Gen7Config(live,transport,report)
    record=config.configure()
    for asset,name,prefix in ((1,'gen70900_sqe.fw','GEN7_CP_SQE'),(2,'gen70900_aqe.fw','GEN7_CP_AQE')):
        data=(ROOT/'out/ios16/gpu-stock-firmware'/name).read_bytes()
        allocation=transport.allocate(len(data)+4096,4096,0x301,0)
        transport.dev(7,asset,allocation['offset']+4092)
        payload=data[4:]
        if len(payload)&3:raise RuntimeError('Misaligned CP firmware')
        for at in range(0,len(payload),128):
            block=payload[at:at+128]
            if transport.read(allocation['offset']+4096+at,len(block)//4)!=list(struct.unpack('<'+'I'*(len(block)//4),block)):
                raise RuntimeError('CP firmware copy differs from fixed asset')
        low=prefix+'_INSTR_BASE_LO'+('_0' if asset==2 else '')
        high=prefix+'_INSTR_BASE_HI'+('_0' if asset==2 else '')
        config.wr(low,allocation['gpu']+4096);config.wr(high,0)
        report[name]=dict(gpu=hex(allocation['gpu']+4096),bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest(),full_readback=True)
    if report.get('per_allocation_mapping_enabled'):
        report['firmware_mapping_audit']=transport.dev(16)
        if 'audit_complete=1' not in report['firmware_mapping_audit']:raise RuntimeError('Firmware mapping audit incomplete')
    before=snapshot(live,report,live.capture.root/'result.json','before_stock_cp_init',cx_ready=True,include_gx=True,gx_held=True)
    if before['status']!='complete' or before['gx']['status']!='complete':raise RuntimeError('CP pre-dispatch snapshot incomplete')
    report['cp_firmware_prepared_without_raw']=True
    return config,record


def run_mapped(live, transport, report):
    if getattr(transport,'platform_abi',0)!=3 or not report.get('per_allocation_mapping_enabled'):
        raise RuntimeError('Mapped CP trial requires verified ABI3 mapping policy and RAM-only watcher')
    config,record=prepare(live,transport,report)
    report['pre_dispatch_kernel_snapshot']=transport.dev(14)
    from gpu_terminal_diagnostics import _checkpoint
    _checkpoint(live.capture.root/'result.json',report)

    def submit(label,commands):
        report['pending_cp_operation']=label
        (live.capture.root/'cp-pending.txt').write_text(label+'\n'+repr(commands)+'\n')
        reply=transport.send(131,commands,seconds=2)
        report[label+'_reply']=reply
        if reply['value']!=0 or reply['status'] not in (None,0):raise RuntimeError(label+' rejected')
        until=time.monotonic()+.2
        while time.monotonic()<until:
            if not config.rd('GEN7_GPU_GMU_AO_GPU_CX_BUSY_STATUS')&(1<<23):break
        else:raise RuntimeError(label+' did not idle')
        report[label+'_accepted']=True

    # The first RAW follows gen7_cp_init_cmds, never a pre-init NOP.
    submit('cp_init',[packet(0x17,1),1<<27,packet(0x48,7),0x94b,3,0x20000000,2,record['gpu'],0,1<<31])
    report['zap_reply']=transport.platform(7)
    submit('switch_unsecure',[packet(0x66,1),0])
    report['secvid_trust_control']=config.rd('GEN7_RBBM_SECVID_TRUST_CNTL')
    if report['secvid_trust_control']!=0:raise RuntimeError('Secure mode exit not confirmed')
    fence=transport.allocate(4096,4096,0x33f,2)
    transport.write(fence['offset'],[0])
    submit('cp_mem_write',[packet(0x3d,3),fence['gpu'],0,0xa750cafe])
    report['cp_mem_write_value']=transport.read(fence['offset'])[0]
    if report['cp_mem_write_value']!=0xa750cafe:raise RuntimeError('No observed GPU memory write')
    report['gpu_memory_write_verified']=True
    report.pop('pending_cp_operation',None)
    transport.dev(14)
