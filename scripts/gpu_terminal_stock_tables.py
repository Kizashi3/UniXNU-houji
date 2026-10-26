"""Minimal-rate test tables derived offline from this board's stock AOP and DT.

Both embedded ARC variants agree on all three rails. These are parser-test
tables, not live cmd-db verification or proof that voltage/frequency votes run.
"""
from pathlib import Path
import struct,re,hashlib
from gpu_terminal_live import ROOT

def tables():
    aop=(ROOT/'.cache/stock-boot-16.0.3.500/aop.mbn').read_bytes()
    assert hashlib.sha256(aop).hexdigest()=='7e2f6fb6939ab20c28b7189aaead6f1b60a1f7b2c608244f90d606e7bf4df6dd'
    dt=(ROOT.parent/'ace5-analysis/running-device.dts').read_text()
    rails=[]
    for base in (0x1e5a0,0x1eb70):
        out={}
        for i in range(28):
            name,_,_,addr,n,offset=struct.unpack_from('<8sIIIHH',aop,base+i*24)
            name=name.rstrip(b'\0')
            if name not in (b'cx.lvl',b'mx.lvl',b'gfx.lvl'):continue
            assert n==32 and addr in (0x30000,0x30010,0x30050)
            vals=list(struct.unpack_from('<16H',aop,base-0x1c0+offset))
            while len(vals)>1 and vals[-1]==0:vals.pop()
            assert vals[0]==0 and vals==sorted(set(vals))
            out[name.decode()]=vals
        assert len(out)==3;rails.append(out)
    assert rails[0]==rails[1]
    rail=rails[0]
    def vote(primary,level):
        vals=rail[primary];i=next(i for i,v in enumerate(vals) if v>=level)
        j=next(j for j,v in enumerate(rail['mx.lvl']) if v>=vals[i])
        return (vals[i]<<16)|(j<<8)|i
    # Lowest nonzero frequency/voltage in every board speed-bin.
    assert 'qcom,gpu-freq = <0xdc4c7c0>' in dt and 'qcom,level = <0x34>' in dt
    assert 'qcom,gmu-freq-table = <0xf7f4900 0x40 0x2540be40 0x80>' in dt
    perf=[0,1,2,3,0,0xffffffff,0,vote('gfx.lvl',52),0xffffffff,231000,
          3,2,0,0,vote('cx.lvl',64),260000,vote('cx.lvl',128),625000]
    entries={}
    for i in range(31):
        name,_,_,addr,n,off=struct.unpack_from('<8sIIIHH',aop,0x1e0f8+24*i)
        name=name.rstrip(b'\0').decode()
        assert n==8 and off==i*8
        if name in ('SH0','MC0','ACV','CN0'):
            unit,width,vcd,res=struct.unpack_from('<IHBB',aop,0x1e000+off)
            entries[name]=(addr,unit,width,vcd)
    assert set(entries)=={'SH0','MC0','ACV','CN0'}
    levels=[int(x,16) for x in re.search(r'qcom,bus-table-ddr = <([^>]+)>',dt)[1].split()]
    assert len(levels)==10 and levels[0]==0
    bcm=lambda commit,valid,x,y:(int(commit)<<30)|(int(valid)<<29)|(min(x,0x3fff)<<14)|min(y,0x3fff)
    bw=[len(levels),1,3,1,7]+[entries['CN0'][0]]+[0]*5
    cnoc=[]
    for level in (0,100):
        _,unit,width,_=entries['CN0'];v=level*width//4*1000//unit
        v=max(v,1) if level else 0
        cnoc += [bcm(True,bool(v),v,v)]+[0]*5
    bw+=cnoc+[entries[k][0] for k in ('SH0','MC0','ACV')]+[0]*5
    for level in levels+[0]*(16-len(levels)):
        vals=[]
        for name,buswidth in (('SH0',16),('MC0',4),('ACV',0)):
            if name=='ACV':vals.append(bcm(True,bool(level),0,4 if level>=2736*1000*4 else 0));continue
            _,unit,width,_=entries[name];v=level*width//buswidth*1000//unit
            v=max(v,1) if level else 0
            vals.append(bcm(True,bool(v),v,v))
        bw+=vals+[0]*5
    assert len(bw)==159
    return perf,bw,{'aop_sha256':hashlib.sha256(aop).hexdigest(),'arc_variants_identical':True,
        'rail_values':rail,'bcm':entries,'gpu_test_frequency_khz':231000,'live_cmd_db_verified':False}
