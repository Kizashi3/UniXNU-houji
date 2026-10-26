"""Native kernel transport for owned buffers and unmodified stock HFI."""
import re,time,secrets

def start_hwsched(transport, report, *, aqe=True):
    """Cold start for the captured gen7-9-1, including its required AQE feature.

    Pinned vendor adreno_gen7_hwsched_hfi.c enables AQE (feature 29) after
    CORE_FW_START and before START. This does not start the command processor.
    """
    def accepted(reply):
        if reply['value'] != 0 or reply['status'] not in (None, 0):
            raise RuntimeError('HWSCHED initialization rejected: '+str(reply))
    reply=transport.send(14,[0])
    report['core_fw_start_reply']=reply
    accepted(reply)
    report['core_fw_start_accepted']=True
    print('CORE FW START '+str(reply),flush=True)
    reply=transport.send(12,[121,0])
    report['context_queue_capability']=reply
    print('CONTEXT QUEUE '+str(reply),flush=True)
    if aqe:
        # This single-context diagnostic has no preemption implementation.
        # FEATURE_CTRL supports disable; test the explicit setting before AQE.
        # An ACK does not imply secure allocations will no longer be requested.
        reply=transport.send(11,[2,0,0])
        report['preemption_disable_reply']=reply
        accepted(reply)
        report['preemption_explicitly_disabled']=True
        reply=transport.send(11,[29,1,0])
        report['aqe_feature_reply']=reply
        accepted(reply)
        report['aqe_feature_enabled']=True
        print('AQE FEATURE '+str(reply),flush=True)
    else:
        report['aqe_feature_enabled']=False
        report['incomplete_vendor_startup']='AQE omitted for register-only baseline'
    reply=transport.send(10,[])
    report['start_reply']=reply
    accepted(reply)
    report['hwsched_start_accepted']=True

class NativeHfi:
    def __init__(self,live,report):
        self.l=live;self.report=report;self.token=secrets.randbits(30);self.sequence=0x900;self.pending=[]
        self.allocations={}
        self.platform_enabled=False
        self.info=self.dev(0)
        m=re.search(r'abi=1 gmu_root=(0x[0-9a-f]+) gpu_root=(0x[0-9a-f]+)',self.info)
        if not m:raise RuntimeError('Native GPU development ABI is unavailable')
        self.gmu_root=int(m[1],16);self.gpu_root=int(m[2],16)
    def platform(self,action):
        text=self.dev(11,action)
        if action==0:
            m=re.search(r'GIULIA GPU PLATFORM: abi=(\d+)\b',text)
            if not m or int(m[1]) not in (2,3):raise RuntimeError('Supported platform ABI is unavailable')
            self.platform_abi=int(m[1]);self.report['platform_abi']=self.platform_abi
        return text
    def _mapping_reply_error(self,message):
        # The kernel may already have published the mapping. A corrupt or
        # incomplete success record must not lead into raw-MMIO cleanup.
        if hasattr(self,'l'):self.l.io_stopped=True
        self.report['mapping_completion_unconfirmed']=True
        raise RuntimeError(message)
    def secure_allocate(self,bytes,align,flags,kind):
        if (any(type(v) is not int or not 0<=v<=0xffffffff for v in (bytes,align,flags,kind)) or
                not 0<bytes<=0x400000 or align>16384 or (align and align&(align-1)) or
                flags!=0x1007 or kind!=5):
            raise RuntimeError('Invalid secure allocation descriptor')
        text=self.dev(12,bytes,align,flags,kind)
        records=[line for line in text.splitlines() if line.startswith('GIULIA GPU SECURE: allocation=')]
        m=re.fullmatch(r'GIULIA GPU SECURE: allocation=(\d+) bytes=(0x[0-9a-f]+) gpu=(0x[0-9a-f]+) gmu=0 flags=(0x[0-9a-f]+) kind=(\d+) owned=1 mapped=1 cpu_access=0',records[0]) if len(records)==1 else None
        if not m:self._mapping_reply_error('Secure allocation lacks ownership/mapping completion')
        allocation=dict(handle=int(m[1]),bytes=int(m[2],0),gpu=int(m[3],0),gmu=0,flags=int(m[4],0),kind=int(m[5]),secure=True)
        if (allocation['handle']>=8 or allocation['bytes']!=bytes or allocation['flags']!=flags or
                allocation['kind']!=kind or allocation['gpu']!=0xf0000000+allocation['handle']*0x400000):
            self._mapping_reply_error('Secure allocation record does not match owned slot')
        return allocation
    def _memstore_capability(self):
        if not re.search(r'^GIULIA GPU DEV: resources_abi=1 memstore=1(?: |$)',getattr(self,'info',''),re.M):
            raise RuntimeError('Native memstore resource ABI is unavailable')
    def ipc_allocate(self,bytes,align,flags,kind=19):
        # Fixed qcom,ipc-core provider. It has no CPU offset or GPU alias and
        # cannot honor HOST_INIT, HOST_ACC, secure or GMU cacheable requests.
        if (any(type(v) is not int or not 0<=v<=0xffffffff for v in (bytes,align,flags,kind)) or
                kind!=19 or not 0<bytes<=0x140000 or flags&~0x78 or not flags&8 or
                align>>16 or (align&255)>22 or ((align>>8)&255)>18):
            raise RuntimeError('Invalid IPC_CORE allocation descriptor')
        va_align=1<<(align&255);size_align=1<<((align>>8)&255)
        if 0x67000000&(va_align-1) or (bytes+size_align-1)&~(size_align-1)>0x140000:
            raise RuntimeError('Invalid IPC_CORE allocation alignment')
        capabilities=[line for line in getattr(self,'info','').splitlines()
            if line.startswith('GIULIA GPU DEV: ipc_core=')]
        if capabilities!=['GIULIA GPU DEV: ipc_core=1 ipc_host_arbitration=1 ipc_retained_until_reboot=1']:
            raise RuntimeError('Native IPC_CORE resource ABI and host arbitration are unavailable')
        previous=getattr(self,'ipc_resource',None)
        if previous is not None and previous['flags']!=flags:
            raise RuntimeError('Conflicting singleton IPC_CORE permissions')
        text=self.dev(19,bytes,align,flags,kind)
        records=[line for line in text.splitlines() if line.startswith('GIULIA GPU IPC:')]
        m=re.fullmatch(r'GIULIA GPU IPC: bytes=(0x[0-9a-f]+) gpu=0 gmu=(0x[0-9a-f]+) flags=(0x[0-9a-f]+) kind=(\d+) reused=([01]) cpu_offset=none mapped=1 host_excluded=1',records[0]) if len(records)==1 else None
        if not m:self._mapping_reply_error('Missing dedicated IPC_CORE mapping and host exclusion record')
        size,gmu,actual_flags=(int(v,0) for v in m.groups()[:3])
        actual_kind,reused=int(m[4]),int(m[5])
        if (size!=0x140000 or gmu!=0x67000000 or actual_flags!=flags or actual_kind!=kind or
                (previous is not None and reused!=1)):
            self._mapping_reply_error('IPC_CORE record does not match requested dedicated mapping')
        allocation=dict(bytes=size,gpu=0,gmu=gmu,flags=flags,kind=kind,reused=bool(reused),
            ipc_core=True,cpu_offset=None,mapped=True,host_excluded=True)
        self.ipc_resource=allocation
        return allocation
    def fence_allocate(self,bytes,align,flags,kind=23):
        # Import a registered provider's existing GPU client queues. This
        # capability only advertises the import interface; the kernel must
        # verify live ownership and its immutable provider epoch every time.
        if (any(type(v) is not int or not 0<=v<=0xffffffff for v in (bytes,align,flags,kind)) or
                kind!=23 or not bytes or flags&~0x178 or not flags&8 or
                align>>16 or (align&255)>22 or ((align>>8)&255)>22):
            raise RuntimeError('Invalid hardware fence allocation descriptor')
        capabilities=[line for line in getattr(self,'info','').splitlines()
            if line.startswith('GIULIA GPU DEV: fence_import_abi=')]
        if capabilities!=['GIULIA GPU DEV: fence_import_abi=1 fence_completion=0']:
            raise RuntimeError('Native hardware fence import ABI is unavailable')
        previous=getattr(self,'fence_resource',None)
        if previous is not None and previous['flags']!=flags:
            raise RuntimeError('Conflicting singleton hardware fence permissions')
        text=self.dev(20,bytes,align,flags,kind)
        records=[line for line in text.splitlines() if line.startswith('GIULIA GPU FENCE:')]
        m=re.fullmatch(r'GIULIA GPU FENCE: bytes=(0x[0-9a-f]+) gpu=0 gmu=(0x[0-9a-f]+) flags=(0x[0-9a-f]+) kind=(\d+) epoch=(0x[0-9a-f]+) reused=([01]) cpu_offset=none mapped=1 completion_verified=0',records[0]) if len(records)==1 else None
        if not m:self._mapping_reply_error('Missing dedicated hardware fence mapping record')
        size,gmu,actual_flags=(int(v,0) for v in m.groups()[:3])
        actual_kind,epoch,reused=int(m[4]),int(m[5],0),int(m[6])
        va_align=1<<(align&255);size_align=1<<((align>>8)&255)
        if (size not in (0x1a000,0x1c000,0x20000) or gmu!=0x68000000 or
                actual_flags!=flags or actual_kind!=kind or not 0<epoch<=0xffffffffffffffff or
                gmu&(va_align-1) or ((bytes+size_align-1)&~(size_align-1))>size or
                (previous is not None and
                    (reused!=1 or previous['epoch']!=epoch or previous['bytes']!=size))):
            self._mapping_reply_error('Hardware fence record does not match requested dedicated mapping and provider epoch')
        allocation=dict(bytes=size,gpu=0,gmu=gmu,flags=flags,kind=kind,epoch=epoch,
            reused=bool(reused),hardware_fence=True,cpu_offset=None,mapped=True,completion_verified=False)
        self.fence_resource=allocation
        return allocation
    def memstore_allocate(self,bytes,align,flags,kind=22):
        # This is a dedicated provider, outside the generic CPU-accessible RAM
        # pool. Preserve wire alignment and independently requested GMU rights.
        if (any(type(v) is not int or not 0<=v<=0xffffffff for v in (bytes,align,flags,kind)) or
                kind!=22 or not 0<bytes<=0x8000 or flags&~0x37f or flags&7!=7 or
                align>>16 or (align&255)>22 or ((align>>8)&255)>15):
            raise RuntimeError('Invalid memstore allocation descriptor')
        self._memstore_capability()
        previous=getattr(self,'memstore_resource',None)
        if previous is not None and previous['flags']!=flags:
            raise RuntimeError('Conflicting singleton memstore permissions')
        text=self.dev(17,bytes,align,flags,kind)
        records=[line for line in text.splitlines() if line.startswith('GIULIA GPU MEMSTORE:')]
        m=re.fullmatch(r'GIULIA GPU MEMSTORE: bytes=(0x[0-9a-f]+) gpu=(0x[0-9a-f]+) gmu=(0x[0-9a-f]+|0) flags=(0x[0-9a-f]+) kind=(\d+) reused=([01]) cpu_offset=none mapped=1',records[0]) if len(records)==1 else None
        if not m:self._mapping_reply_error('Missing dedicated memstore mapping record')
        size,gpu,gmu,actual_flags=(int(v,0) for v in m.groups()[:4])
        actual_kind,reused=int(m[5]),int(m[6])
        if (size!=0x8000 or gpu!=0x66000000 or gmu!=(gpu if flags&8 else 0) or
                actual_flags!=flags or actual_kind!=kind or (previous is not None and reused!=1)):
            self._mapping_reply_error('Memstore record does not match requested dedicated mapping')
        allocation=dict(bytes=size,gpu=gpu,gmu=gmu,flags=flags,kind=kind,reused=bool(reused),
            memstore=True,cpu_offset=None,mapped=True)
        self.memstore_resource=allocation
        return allocation
    def memstore_read(self,context):
        # 819 complete 40-byte records, less two reserved and four ringbuffer
        # slots. Matching timestamp observations alone never establish a fence.
        if type(context) is not int or not 0<=context<813:
            raise RuntimeError('Invalid memstore context')
        self._memstore_capability()
        text=self.dev(18,context,0,0,0)
        records=[line for line in text.splitlines() if line.startswith('GIULIA GPU MEMSTORE:')]
        m=re.fullmatch(r'GIULIA GPU MEMSTORE: context=(\d+) sop=(0x[0-9a-f]+|0) eop=(0x[0-9a-f]+|0) stable=([01]) completion_verified=0',records[0]) if len(records)==1 else None
        if not m:raise RuntimeError('Missing memstore timestamp observation')
        actual_context,sop,eop,stable=int(m[1]),int(m[2],0),int(m[3],0),int(m[4])
        if actual_context!=context or sop>0xffffffff or eop>0xffffffff:
            raise RuntimeError('Memstore observation does not match requested context')
        observation=dict(context=context,sop=sop,eop=eop,stable=bool(stable),completion_verified=False)
        self.report.setdefault('memstore_observations',[]).append(observation)
        return observation
    def dev(self,op,a=0,b=0,c=0,d=0):
        self.token+=1
        vals=(self.token,op,a,b,c,d)
        line='gpu.dev '+' '.join(hex(x) for x in vals)
        assert len(line)<=63
        m=self.l.command(line,rf'GIULIA GPU DEV: done token={self.token} op={op} code=(\d+)',timeout=45 if op==11 else 8)
        if int(m[1]):
            scm_returns=re.findall(r'GIULIA GPU SCM: return a0=(0x[0-9a-f]+|0)\b',m.string)
            if scm_returns and int(scm_returns[-1],0) in (1,2,3):
                self.l.io_stopped=True
                self.report['scm_pending_quarantined']=True
            if op==13:
                self.l.io_stopped=True
                self.report['raw_watch_quarantined']=True
            if int(m[1])==8:
                self.l.io_stopped=True
                self.report['kernel_state_unconfirmed']=True
                self.report['mapping_completion_unconfirmed']=True
            raise RuntimeError('Native GPU command failed: '+line+' '+m[0])
        return '\n'.join(line for line in m.string.splitlines()
            if re.match(r'^GIULIA GPU (?:DEV|PLATFORM|SECURE|SCM|WATCH|ZAP|SNAPSHOT|MAPPING|MEMSTORE|IPC|FENCE):',line))+'\n'
    def allocate(self,bytes,align,flags,kind):
        text=self.dev(1,bytes,align,flags,kind)
        m=re.search(r'allocation=(\d+) offset=(0x[0-9a-f]+|0) bytes=(0x[0-9a-f]+) flags=(0x[0-9a-f]+) kind=(\d+) gpu=(0x[0-9a-f]+|0) gmu=(0x[0-9a-f]+|0)',text)
        if not m:self._mapping_reply_error('Missing allocation record')
        names=('handle','offset','bytes','flags','kind','gpu','gmu')
        allocation=dict(zip(names,(int(x,0) for x in m.groups())))
        offset=allocation['offset'];size=allocation['bytes']
        cache=bool(flags&0x80);lower=0 if cache else 0x400000;limit=0x400000 if cache else 0x4000000
        gpu=0x61000000+offset;gmu=(0x800000 if cache else 0x61000000)+offset
        managed=self.report.get('per_allocation_mapping_enabled',False)
        if (allocation['handle']>=128 or allocation['flags']!=flags or allocation['kind']!=kind or
                not bytes or size!=((bytes+4095)&~4095) or not lower<=offset<limit or size>limit-offset or
                offset%max(4096,align) or
                allocation['gpu'] not in ((gpu,) if flags&1 else ((0,) if managed else (0,gpu))) or
                allocation['gmu'] not in ((gmu,) if flags&8 else ((0,) if managed else (0,gmu)))):
            self._mapping_reply_error('Allocation record does not match requested owned mapping')
        return allocation
    def read(self,offset,count=1):
        text=self.dev(2,offset,count)
        words=[int(v,0) for _,v in re.findall(r'word=(\d+) value=(0x[0-9a-f]+|0)',text)]
        assert len(words)==count
        return words
    def write(self,offset,words):
        for i,v in enumerate(words):self.dev(3,offset+4*i,v)
    def physical(self,offset):
        text=self.dev(9,offset)
        match=re.search(r'GIULIA GPU DEV: offset=(0x[0-9a-f]+|0) pa=(0x[0-9a-f]+)',text)
        if not match or int(match[1],0)!=offset:
            raise RuntimeError('Missing owned physical-address response')
        return int(match[2],0)
    def packet(self,msg_id,payload,msg_type=0):
        self.sequence+=1;n=len(payload)+1
        assert n<=255 and self.sequence<4096
        header=(self.sequence<<20)|(msg_type<<16)|(n<<8)|msg_id
        self.dev(10)
        for i,v in enumerate([header,*payload]):self.dev(5,i,v)
        if msg_id==131 and self.platform_enabled:
            attempt={'header':hex(header),'status':'pending','queue_publication_confirmed':False}
            self.report.setdefault('raw_submission_attempts',[]).append(attempt)
            self.report['raw_cp_submitted']=None
            watched=self.dev(13,n,1000)
            attempt.update(status='watch_returned',reply=watched,
                queue_publication_confirmed=('stage=queue_committed header='+hex(header)) in watched)
            self.report['raw_cp_submitted']=attempt['queue_publication_confirmed']
        else:
            self.dev(6,n)
            self.l.write(0x3d7e650,1,verify=False)
        return header
    def poll(self):
        text=self.l.command('gpu.hfi.poll',r'GIULIA GPU HFI: poll queue=2 code=1',timeout=8).string
        parts=re.split(r'GIULIA GPU HFI: received queue=(\d+) words=(\d+) header=[^\r\n]+',text)
        for i in range(1,len(parts),3):
            q,n=int(parts[i]),int(parts[i+1])
            words=[int(v,0) for _,v in re.findall(r'GIULIA GPU HFI: word=(\d+) value=(0x[0-9a-f]+|0)',parts[i+2])]
            assert len(words)==n
            self.report.setdefault('hfi_packets',[]).append({'queue':q,'words':[hex(v) for v in words]})
            if q==1:self.pending.append(words)
    def request(self,words):
        if (not words or any(type(word) is not int or not 0<=word<=0xffffffff for word in words) or
                ((words[0]>>8)&255)!=len(words) or ((words[0]>>16)&15)!=0):
            raise RuntimeError('Malformed firmware request')
        msg=words[0]&255
        if msg==20 and len(words)==11 and words[1]==1:
            desc=words[2:];flags,kind,handle,bytes,align=desc[2],desc[3],desc[5],desc[7],desc[8]
            request=dict(flags=hex(flags),kind=kind,gmu_handle=handle,bytes=bytes,alignment=hex(align),
                raw_words=[hex(v) for v in words])
            self.report.setdefault('memory_requests',[]).append(request)
            if not bytes or flags&~0x13ff or kind>=26:
                raise RuntimeError('Invalid memory allocation descriptor')
            key=(kind,handle)
            signature=(flags,bytes,align)
            # The vendor lookup is keyed by kind and GMU handle. Repeated
            # requests reuse their backing and must never zero live data.
            if key in self.allocations:
                a=self.allocations[key]
                if a['request_signature']!=signature:
                    raise RuntimeError('Conflicting repeated allocation request')
                # Fence ownership can change independently of the HFI key.
                # A matching signature still requires a live OP20 recheck.
                if kind!=23:
                    desc[0]=a['gpu'] if flags&1 else 0
                    desc[1]=0;desc[4]=handle
                    desc[6]=a['gmu'] if (a.get('gmu_only_sysram',False) or flags&8) else 0
                    if 'request_flags' in a:request['effective_flags']=hex(a['flags'])
                    request['reused']=True
                    self.packet(20,[words[0],*desc],1)
                    return
            elif len(self.allocations)>=64:raise RuntimeError('Bounded allocation limit exceeded')
            if flags&0x1000 or kind==5:
                if getattr(self,'platform_enabled',False) and flags==0x1007 and kind==5 and align==0:
                    a=self.secure_allocate(bytes,4096,flags,kind)
                    desc[0]=a['gpu'];desc[1]=0;desc[4]=handle;desc[6]=0
                    a['request_signature']=signature;self.allocations[key]=a
                    self.report.setdefault('secure_allocations',[]).append(dict(a,gmu_handle=handle))
                    self.packet(20,[words[0],*desc],1)
                    print('Secure allocation kind='+str(kind)+' bytes='+str(bytes),flush=True)
                    return
                request['blocked_reason']='Secure GPU allocation and secure context mapping are not implemented'
                self.report['blocked_memory_request']=request
                raise RuntimeError(request['blocked_reason'])
            if kind==23:
                a=self.fence_allocate(bytes,align,flags,kind)
                desc[0]=0;desc[1]=0;desc[4]=handle;desc[6]=a['gmu']
                # The reply preserves logical size and exposes no CPU pool
                # handle. Importing queues does not enable hardware fences or
                # establish that any payload represents completed work.
                a=dict(a,request_signature=signature);self.allocations[key]=a
                request['reused']=a['reused']
                self.report.setdefault('fence_allocations',[]).append(dict(a,gmu_handle=handle))
                self.packet(20,[words[0],*desc],1)
                return
            if kind==19:
                # This local resource contract implements the fixed GMU-only
                # IPC_CORE form. Do not route unsupported GFX variants to RAM.
                a=self.ipc_allocate(bytes,align,flags,kind)
                desc[0]=0;desc[1]=0;desc[4]=handle;desc[6]=a['gmu']
                # Return the requested logical size; the fixed provider owns
                # the complete resource and never initializes its contents.
                a=dict(a,request_signature=signature);self.allocations[key]=a
                request['reused']=a['reused']
                self.report.setdefault('ipc_allocations',[]).append(dict(a,gmu_handle=handle))
                self.packet(20,[words[0],*desc],1)
                return
            if kind==22:
                # This local memstore backend requires its existing GFX
                # descriptor. A GMU-only request is not a generic pool alias.
                a=self.memstore_allocate(bytes,align,flags,kind)
                desc[0]=a['gpu'];desc[1]=0;desc[4]=handle;desc[6]=a['gmu'] if flags&8 else 0
                # Logical request size remains unchanged; the provider owns a
                # complete 32 KiB singleton and never re-zeroes live records.
                a=dict(a,request_signature=signature);self.allocations[key]=a
                request['reused']=a['reused']
                self.report.setdefault('memstore_allocations',[]).append(dict(a,gmu_handle=handle))
                self.packet(20,[words[0],*desc],1)
                return
            va_align=align&255;size_align=(align>>8)&255
            if va_align>22 or size_align>22 or align>>16:raise RuntimeError('Unsupported alignment')
            alignment=max(4096,1<<va_align);rounded=(bytes+(1<<size_align)-1)&~((1<<size_align)-1)
            if rounded>0x4000000:raise RuntimeError('Allocation exceeds the owned RAM pool')
            # Fixed gen7 branches by GFX_ACC, not the enum's MMIO name. With
            # no GFX access, gen7_reserve_gmu_kernel_block allocates SYSRAM
            # and hard-codes IOMMU_READ|WRITE|PRIV even without GMU_ACC in the
            # request. Keep the raw debug mapping API unchanged: normalize
            # only this HFI request's effective mapping flags. CACHEABLE still
            # selects its separate GMU VA region. GFX buffers keep get_attrs.
            gmu_only_sysram=not flags&1
            effective_flags=flags|0x38 if gmu_only_sysram else flags
            request['effective_flags']=hex(effective_flags)
            a=self.allocate(rounded,alignment,effective_flags,kind)
            self.dev(4,a['offset'],a['bytes'])
            assert self.read(a['offset'])==[0]
            # Vendor process_mem_alloc updates addresses/host handle only.
            # Reply preserves the requested logical size (e.g. SMMU_INFO 24B),
            # even when the owned backing allocation occupies complete pages.
            desc[0]=a['gpu'] if flags&1 else 0
            desc[1]=0;desc[4]=handle
            desc[6]=a['gmu'] if (gmu_only_sysram or flags&8) else 0
            a=dict(a,request_flags=flags,effective_flags=effective_flags,
                gmu_only_sysram=gmu_only_sysram,request_signature=signature)
            self.allocations[key]=a
            self.report.setdefault('memory_allocations',[]).append(dict(a,gmu_handle=handle))
            self.packet(20,[words[0],*desc],1)
            print('Allocated kind='+str(kind)+' bytes='+str(a['bytes']),flush=True)
            return
        if msg==110 and len(words)==3:
            self.packet(110,[words[0],words[1],words[2],0,0],1)
            self.report['optional_counter_declined']=True;return
        raise RuntimeError('Unhandled firmware request '+str([hex(x) for x in words]))
    def send(self,msg_id,payload,seconds=10):
        try:return self._send(msg_id,payload,seconds)
        except Exception:
            if msg_id==131:
                self.l.io_stopped=True
                self.report['raw_response_unconfirmed']=True
            raise
    def _send(self,msg_id,payload,seconds=10):
        header=self.packet(msg_id,payload);deadline=time.monotonic()+seconds;requests=0
        while time.monotonic()<deadline:
            if not self.pending:self.poll()
            if not self.pending:continue
            words=self.pending.pop(0)
            if len(words)>=3 and (words[0]>>16)&15==1 and words[1]==header:
                reply={'id':msg_id,'value':words[2],'status':words[3] if len(words)>3 else None,'header':hex(header)}
                self.report.setdefault('transactions',[]).append(reply)
                return reply
            requests+=1
            if requests>128:raise RuntimeError('Bounded firmware request limit exceeded')
            self.request(words)
            deadline=time.monotonic()+seconds
            if len(self.allocations)>64:raise RuntimeError('Bounded allocation limit exceeded')
        raise RuntimeError('HFI response timeout')
