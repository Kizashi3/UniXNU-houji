"""Send DCS display off/on through the live DSI0 FIFO; no image rebuild."""
import json,time,sys
from gpu_terminal_live import Live
assert len(sys.argv)==2 and sys.argv[1] in ('off','on')
command=0x28 if sys.argv[1]=='off' else 0x29
report={'requested':sys.argv[1],'dcs':hex(command),'completed':False}
base=0xae94000
with Live('panel-display-terminal') as live:
    slot=live.map(base,0x4000);saved={};started=False
    try:
        def rd(off):return live.read(base+off)
        def wr(off,value,verify=True):return live.write(base+off,value,verify=verify)
        report['controller']=hex(rd(4));report['status_before']=hex(rd(8))
        assert rd(4)==0x1f5 and rd(0x15c)==0
        assert not rd(8)&2,'Command DMA busy'
        for off in (0x3c,0x4c,0x84,0x15c):saved[off]=rd(off)
        assert saved[0x84]&15==4,'Expected software DMA trigger'
        # DSI status bits are W1C, interrupt enable fields are retained.
        interrupts=rd(0x110)
        wr(0x110,(interrupts&~0x01000000)|1,False)
        assert not rd(0x110)&1,'Old completion did not clear'
        wr(0x1ec,1,False);wr(0x1ec,0,False)
        wr(0x15c,0x30006)
        wr(0x17c,0x80050000|command,False);wr(0x17c,0,False)
        wr(0x3c,(saved[0x3c]&~0xc0000000)|0x14000000)
        wr(0x4c,4)
        started=True;wr(0x90,1,False)
        deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            status=rd(0x110)
            if status&1:report['completed']=True;break
        report['interrupt_status']=hex(status)
        report['ack_error']=hex(rd(0x68));report['status_after']=hex(rd(8))
        if not report['completed']:raise RuntimeError('No new DSI command completion')
        wr(0x110,(status&~0x01000000)|1,False)
    except Exception as error:report['error']=str(error)
    finally:
        if saved:
            live.write(base+0x15c,0)
            live.write(base+0x1ec,1,verify=False);live.write(base+0x1ec,0,verify=False)
            for off,value in saved.items():live.write(base+off,value)
        live.unmap(slot)
        (live.capture.root/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
if not report['completed'] or 'error' in report:sys.exit(1)
