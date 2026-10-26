"""Bounded NMI transport for terminal experiments, not a runtime driver."""
import hashlib, struct, time
from gpu_terminal_live import ROOT

class NmiHfi:
    def __init__(self,live,report):
        self.l=live;self.report=report;self.saved=[];self.seq=0
        self.base=0x3d73ec0;self.cfg=0x3d7e0b4
        self.code=(ROOT/'.cache/gmu-hfi-mailbox.bin').read_bytes()
        assert len(self.code)==140 and hashlib.sha256(self.code).hexdigest()=='4f9058cf0cba12edbfaf2945b23be4e39b51f13efde9c90f231677c0f71ef910'
        self.header_seq=0x800
    def install(self):
        assert self.l.read(0x3d7e000)==0
        self.original_cfg=self.l.read(self.cfg)
        assert self.original_cfg in (0x4012,0x4052)
        assert self.l.read(0x3d7e648)&0x8000==0
        vector=self.l.read(0x3d6e008)
        assert vector&1 and 0x200<=vector<0x3a3c,hex(vector)
        for start,size in ((0x3d70a40,len(self.code)),(self.base,220),(0x3d6e008,4)):
            for a in range(start,start+size,4):self.saved.append((a,self.l.read(a)))
        self.report['nmi_transport']={'code_sha256':hashlib.sha256(self.code).hexdigest(),
            'original_vector':hex(vector),'patched_vector':'0x3a41',
            'firmware_parser_modified':False,'temporary_nmi_vector_modified':True}
        for i in range(0,len(self.code),4):self.l.write(0x3d70a40+i,struct.unpack_from('<I',self.code,i)[0])
        self.l.write(0x3d6e008,0x3a41)
    def transaction(self,op,address=0,count=0,data=(),expect=0xa750600d):
        assert len(data)<=48
        self.seq+=1
        assert self.l.read(self.cfg)&0x200==0
        for i,v in enumerate((0,op,address,count,self.seq,0,0,*data)):self.l.write(self.base+4*i,v)
        current_cfg=self.l.read(self.cfg)
        self.l.write(self.cfg,current_cfg|0x200)
        try:
            end=time.monotonic()+.5
            result=0
            while time.monotonic()<end:
                result=self.l.read(self.base)
                if result:break
            if result!=expect:raise RuntimeError(f'NMI result {result:#x}, expected {expect:#x}')
            assert self.l.read(self.base+20)==self.seq
            assert self.l.read(self.base+24)==0x1000
            return [self.l.read(self.base+28+4*i) for i in range(count)] if expect==0xa750600d else []
        finally:self.l.write(self.cfg,current_cfg)
    def read(self,address,count=1):return self.transaction(1,address,count)
    def write(self,address,data):
        assert 0<len(data)<=48
        observed=self.transaction(2,address,len(data),data)
        assert observed==list(data),(hex(address),observed,data)
    def ring_read(self,base,index,count):
        result=[]
        while count:
            n=min(count,48,1024-index)
            result+=self.read(base+index*4,n)
            index=(index+n)%1024;count-=n
        return result
    def ring_write(self,base,index,data):
        while data:
            n=min(len(data),48,1024-index)
            self.write(base+index*4,data[:n])
            data=data[n:];index=(index+n)%1024
    def queue(self,q):
        h=0x60010000+24+48*q
        values=self.read(h,12)
        assert values[:4]==[1,0x60010350+4096*q,q,1024]
        r,w=values[10:12]
        assert r<1024 and w<1024 and not (r|w)&3
        return h,values[1],r,w
    def receive(self,q):
        h,base,r,w=self.queue(q)
        if r==w:return None
        header=self.read(base+4*r)[0];n=(header>>8)&255
        padded=(n+3)&~3
        assert n and padded<=(w-r)%1024
        words=self.ring_read(base,r,n)
        self.write(h+40,[(r+padded)%1024])
        self.report.setdefault('hfi_packets',[]).append({'queue':q,'words':[hex(x) for x in words]})
        return words
    def send(self,msg_id,payload,seconds=2):
        self.header_seq+=1
        assert self.header_seq<4096
        n=len(payload)+1;padded=(n+3)&~3
        assert n<=255
        header=(self.header_seq<<20)|(n<<8)|msg_id
        h,base,r,w=self.queue(0)
        assert r==w, 'Refuse to overwrite a pending command'
        self.ring_write(base,w,[header,*payload]+[0xfafafafa]*(padded-n))
        self.write(h+44,[(w+padded)%1024])
        self.l.write(0x3d7e650,1,verify=False)
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if self.l.read(0x3d7e648)&0x8000:raise RuntimeError('CM3 fault')
            self.receive(2)
            words=self.receive(1)
            if words is None:continue
            if len(words)>=3 and ((words[0]>>16)&15)==1 and words[1]==header:
                reply={'id':msg_id,'payload':payload,'header':hex(header),'value':words[2],
                    'status':words[3] if len(words)>=4 else None}
                self.report.setdefault('transactions',[]).append(reply)
                self.l.write(0x3d7e644,1,verify=False)
                return reply
            if words[0]&255==20 and len(words)==11 and words[1]==1:
                names=('gpu_address_low','gpu_address_high','flags','kind','host_handle','gmu_handle','gmu_address','bytes','alignment')
                self.report.setdefault('allocation_requests',[]).append(dict(zip(names,words[2:])))
            raise RuntimeError('Asynchronous HFI request; an owned allocation/handler is required')
        raise RuntimeError('HFI response timeout')
    def restore(self):
        if not self.saved:return
        assert self.l.read(0x3d7e000)==1
        self.l.write(self.cfg,self.l.read(self.cfg)&~0x200)
        for address,value in reversed(self.saved):self.l.write(address,value)
        self.report['nmi_restored']=True
