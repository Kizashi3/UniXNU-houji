"""One bounded stock-GMU/HFI polling experiment on the verified HFI boot.

Uses only kernel-owned pinned RAM and idle GPU SMMU bank 0/SID 5. Never
programs PLL/rate/voltage or enables host IRQs. Restores held reset, FAULT
routing, disabled translation, saved config and terminal clock gates.
"""
from gpu_terminal_live import Live,ROOT
from gpu_terminal_nmi import NmiHfi
import hashlib,json,struct,re,time

fw=(ROOT/'out/ios16/gpu-stock-firmware/gmu_gen70900.bin').read_bytes()
assert hashlib.sha256(fw).hexdigest()=='9685f62c42543befcaee68d25355e16bf55cdb0d573bddcc9f6633f59eec3f72'
import argparse
from gpu_terminal_boot import LEASE
parser=argparse.ArgumentParser(description='Bounded terminal HWSCHED experiment; requires a fresh boot lease. Stops at allocation requests.')
parser.add_argument('--execute',action='store_true',help='Perform temporary device writes and reset/cleanup')
parser.add_argument('--stage',choices=('tables','start'),default='tables')
args=parser.parse_args()
if not args.execute:parser.error('Use --execute after binding the current boot; no hardware accessed')
lease=json.loads(LEASE.read_text())
boot_path=__import__('pathlib').Path(lease['boot_log'])
assert hashlib.sha256(boot_path.read_bytes()).hexdigest()==lease['boot_log_sha256']
boot=boot_path.read_text(errors='replace')
roots=set(re.findall(r'build-inactive-tables result=ok code=0 root_pa=(0x[0-9a-f]+).*table_pages=6 leaf_pages=139',boot))
assert len(roots)==1
root_pa=int(roots.pop(),16)
assert root_pa==int(lease['root_pa'],16)
blocks=[];off=0
while off<len(fw):
    address,n,kind,value=struct.unpack_from('<4I',fw,off);off+=16
    if n and (address<0x4000 or 0x10004000<=address<0x10008000):
        pa=0x3d6d000+address if address<0x4000 else 0x3d71000+address-0x10004000
        blocks.append((pa,fw[off:off+n]))
    off+=n
assert sum(len(data) for _,data in blocks)==540
report={'firmware_sha256':hashlib.sha256(fw).hexdigest(),'root_pa':hex(root_pa),
    'stock_fw_ready':False,'hfi_ready':False,'query_ack':False,
    'polling_only':True,'clock_rates_changed':False,'secure_cx_call_executed':False,
    'new_bandwidth_vote':False,'metal_ready':False}
saved=[];maps=[];modified=False;attached=False
with Live('gpu-hwsched-start-terminal') as live:
    from gpu_terminal_boot import validate
    assert int(validate(live)["root_pa"],16)==root_pa
    transport=NmiHfi(live,report)
    def rw(a,v,width=32,verify=True):live.write(a,v,width,verify)
    def config(a,v,verify=True):
        saved.append((a,live.read(a)));rw(a,v,verify=verify)
        if not verify:
            report.setdefault('unverified_config_readbacks',[]).append({'address':hex(a),'requested':hex(v),'observed':hex(live.read(a))})
    def reg(word):return 0x3d00000+4*word
    def poll(a,mask,expected,seconds=3):
        end=time.monotonic()+seconds;seen=[]
        while time.monotonic()<end:
            value=live.read(a)
            if not seen or seen[-1]!=value:seen.append(value)
            if value&mask==expected:return True,seen
        return False,seen
    try:
        for base,size in ((0x3d90000,0x10000),(0x170000,0x4000),(0x3da0000,0x4000),(0x3d7c000,0x4000)):
            maps.append(live.map(base,size))
        rw(0x171004,live.read(0x171004)&~2,verify=False)
        rw(0x171010,live.read(0x171010)&~2,verify=False)
        rw(0x3d97000,live.read(0x3d97000)|1,verify=False)
        # The bus gates were explicitly enabled and surveyed immediately before
        # this experiment; no RCG/PLL/source-rate registers are changed here.
        for a in (0x171004,0x171010,0x171018,0x3d97000):assert live.read(a)&0x80000001==1
        assert live.read(0x3d7e000)==1 and live.read(0x3d7e070)==0
        assert live.read(0x3da0020)==0x4c017e18 and live.read(0x3da0048)==0
        for base,size in ((0x3dc0000,0x10000),(0x3dd0000,0x8000),
            (0x3d6c000,0x4000),(0x3d70000,0x4000),(0x3d74000,0x4000),(0x3d50000,0x4000),
            (0xb284000,0x4000),(0x3d0c000,0x4000),(0x3d8c000,0x4000)):
            maps.append(live.map(base,size))
        for i in range(24):
            assert live.read(0x3da0800+4*i)==0 and live.read(0x3da0c00+4*i)==0x20000
        for i in range(22):assert not live.read(0x3dc0000+0x1000*i)&1
        assert not live.read(0x3dc0058)&0xc00001fe
        report['hfi_status_before']=live.read(reg(0x1f980))
        live.command('gpu.hfi.pin',r'GIULIA GPU HFI: memory_pinned_until_reboot=1')
        modified=True
        # Use the same native4K format already validated by actual CM3 DMA.
        rw(0x3da1800,1);rw(0x3da1000,0x1f300)
        rw(0x3dc0010,0x38011,verify=False);assert live.read(0x3dc0010)==0x38071
        rw(0x3dc0030,0x80802020)
        rw(0x3dc0020,(0x750<<48)|root_pa,64);rw(0x3dc0028,0x750<<48,64)
        rw(0x3dc0038,0xff44);rw(0x3dc003c,0)
        rw(0x3dc0058,0xffffffff,verify=False)
        rw(0x3dc0618,0,verify=False);rw(0x3dc07f0,0xffffffff,verify=False)
        assert live.read(0x3dc07f4)==0
        for pa,data in blocks:
            assert live.read(0x3d7e000)==1
            for i in range(0,len(data),4):rw(pa+i,struct.unpack_from('<I',data,i)[0])
        assert live.read(0x3d74ff0)==0x20060001
        # PDC and the Gen7.2-family RSC layout used by Gen7.9.1.
        config(0xb280000+4*0x1148,0);config(0xb280000+4*0x1140,0x80000001)
        rsc=[(4,1<<24),(0xb,1),(0xe,0),(0xd,0),(0x10,0),(0xf,0),
             (0x12,0x80000021),(0x11,0),(0x100,0),(8,0x4520),(9,0x4510),(10,0x4514)]
        rsc += [(0x154+i,v) for i,v in enumerate((0xeaaae5a0,0xe1a1ebab,0xa2e0a581,0xecac82e2,0x0020edad))]
        for word,value in rsc:
            # Hidden TCS address/data fields can retain hardware/firmware-owned
            # routing. Vendor writes have no readback contract. Record these
            # differences explicitly; this polling trial does not exercise sleep.
            config(0x3d50000+4*word,value,verify=not 0xd<=word<=0x12)
        for word,value in ((0x1f8f1,1),(0x1f8f0,1),(0x1f81c,0),(0x1f801,2),
            (0x1f985,0x60010000),(0x1f984,1),(0x23b11,0x80c808a0),
            (0x1f82d,0x4052),(0x3c45,0),(0x1f9d0,0x60040000),
            (0x1f9ce,0),(0x1f9cf,0x07090100),(0x1f9cd,0x6003000f),
            (0x1f40f,1),(0x1f400,1),(0x1f401,1),
            (0x1f993,0xffffffff),(0x23b06,0xffffffff),(0x1f986,0)):
            config(reg(word),value,verify=word!=0x23b06)
            if word==0x23b06:assert live.read(reg(word))&0x7f==0x7f
        rw(reg(0x1f991),0xffffffff,verify=False);rw(reg(0x23b04),0xffffffff,verify=False)
        report['counter_before']=live.read(reg(0x1f880))
        report['counter_after']=live.read(reg(0x1f880))
        assert report['counter_before']!=report['counter_after']
        rw(0x3dc0000,0x1027,verify=False);assert live.read(0x3dc0000)==0x27
        attached=True;rw(0x3da0800,0x80000005);rw(0x3da0c00,0)
        print('Stock TCM/config verified; starting bounded GMU polling experiment',flush=True)
        rw(0x3d7e000,0)
        report['stock_fw_ready'],report['fw_states']=poll(0x3d7e070,0x1ff,0x100)
        print('Firmware ready: '+str(report['stock_fw_ready'])+' '+str(report['fw_states']),flush=True)
        if report['stock_fw_ready']:
            rw(reg(0x1f986),1)
            report['hfi_ready'],report['hfi_states']=poll(reg(0x1f980),1,1)
            if report['hfi_ready']:
                transport.install()
                transport.transaction(0)
                report['nmi_read_header']=transport.read(0x60010000,6)
                assert report['nmi_read_header']==[0,210,6,12,17,17]
                transport.transaction(1,0x60000000,1,expect=0xa750bad0)
                report['nmi_range_rejection']=True
                from gpu_terminal_stock_tables import tables
                perf,bw,metadata=tables()
                assert perf[7]==0x340201 and perf[14]==0x400202 and perf[16]==0x800303
                report['offline_table_sources']=metadata
                reply=transport.send(12,[125,0])
                assert reply['value']==1 and reply['status']==0
                report['query_ack']=True
                for msg,payload in ((15,perf),(3,bw),(11,[1,1,0]),(11,[16,1,0])):
                    reply=transport.send(msg,payload)
                    print('INIT ACK id='+str(reply['id'])+' value='+str(reply['value'])+' status='+str(reply['status']),flush=True)
                    assert reply['value']==0 and reply['status'] in (0,None)
                report['performance_and_bandwidth_tables_accepted']=True
                report['hwsched_feature_enabled']=True
                if args.stage=='start':
                    reply=transport.send(14,[0])
                    print('CORE FW START '+str(reply),flush=True)
                    assert reply['value']==0 and reply['status'] in (0,None)
                    report['core_fw_start_accepted']=True
                    reply=transport.send(12,[121,0])
                    report['context_queue_capability']=reply
                    print('CONTEXT QUEUE '+str(reply),flush=True)
                    reply=transport.send(10,[])
                    report['start_reply']=reply
                    assert reply['value']==0 and reply['status'] in (0,None)
                    report['hwsched_start_accepted']=True
        report.update(smmu_fsr=live.read(0x3dc0058),smmu_far=live.read(0x3dc0060,64),
            global_fault=live.read(0x3da0048),gmu_irq=live.read(reg(0x1f992)),ao_irq=live.read(reg(0x23b05)))
        live.command('gpu.hfi.log',r'GIULIA GPU HFI: log_word=63 value=')
        print(json.dumps(report,indent=2),flush=True)
    except Exception as error:
        import traceback
        report['error']=traceback.format_exc();print(report['error'],flush=True)
        report['smmu_fsr']=live.read(0x3dc0058)
        report['global_fault']=live.read(0x3da0048)
        report['gmu_irq']=live.read(reg(0x1f992))
    finally:
        try:
            if modified:
                rw(0x3d7e000,1)
                rw(0x3da0c00,0x20000);rw(0x3dc0000,0)
                rw(0x3dc0618,0,verify=False);rw(0x3dc07f0,0xffffffff,verify=False)
                assert poll(0x3dc07f4,1,0)[0]
                rw(0x3da0800,0);rw(0x3dc0020,0,64);rw(0x3dc0028,0,64)
                rw(0x3dc0058,0xffffffff,verify=False)
                transport.restore()
                for a,v in reversed(saved):rw(a,v,verify=False)
                assert live.read(0x3d7e000)==1 and live.read(0x3dc0000)==0
                assert live.read(0x3da0800)==0 and live.read(0x3da0c00)==0x20000
                report['cleanup']={'reset_held':True,'stream_faulted':True,'context_disabled':True,
                    'tlb_synced':True,'stock_tcm_retained':True,'owned_ram_pinned_until_reboot':True}
            # Restore the three bus gate changes made in this terminal turn.
            rw(0x3d97000,live.read(0x3d97000)&~1,verify=False)
            rw(0x171010,live.read(0x171010)|2,verify=False)
            rw(0x171004,live.read(0x171004)|2,verify=False)
            for slot in reversed(maps):live.unmap(slot)
        except Exception as error:
            report['cleanup_error']=str(error)
        (live.capture.root/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        print('RESULT '+str(live.capture.root/'result.json'),flush=True)

if report.get('error') or report.get('cleanup_error') or not report.get('nmi_restored'):
    raise SystemExit(1)
