"""A750 nonsecure register setup derived from pinned vendor gen7_start.
No SMC/ZAP authentication, preemption, LPAC, LLCC, or Metal device publication.
"""
import re,time,hashlib
from gpu_terminal_live import ROOT

class Gen7Config:
 def __init__(self,live,transport,report):
  self.l,self.t,self.r=live,transport,report
  self.source=(ROOT/'.cache/gpu-source/adreno_gen7.c').read_text()
  self.list=(ROOT/'.cache/gpu-source/adreno-gpulist.h').read_text()
  regtext=(ROOT/'.cache/gpu-source/gen7_reg.h').read_text()
  self.regs={n:int(v,0) for n,v in re.findall(r'^#define\s+(GEN7_\w+)\s+(0x[0-9a-fA-F]+|[0-9]+)\b',regtext,re.M)}
  self.r['configuration_sources']={p:hashlib.sha256((ROOT/'.cache/gpu-source'/p).read_bytes()).hexdigest() for p in ('adreno_gen7.c','adreno-gpulist.h','gen7_reg.h','kgsl_util.h')}
 def word(self,name):
  parts=name.split('+');return self.regs[parts[0].strip()]+(int(parts[1]) if len(parts)>1 else 0)
 def rd(self,name):return self.l.read(0x3d00000+4*self.word(name))
 def wr(self,name,value,verify=True):
  self.l.write(0x3d00000+4*self.word(name),value,verify=verify)
  self.r.setdefault('configured_registers',[]).append({'name':name,'value':hex(value),'verified':verify,'observed':hex(self.rd(name))})
 def array(self,name):
  body=re.search(r'static const u32 '+name+r'\[\] = \{(.*?)\};',self.source,re.S)[1]
  return [s.strip() for s in body.split(',') if s.strip()]
 def configure(self):
  assert self.rd('GEN7_GMU_GFX_PWR_CLK_STATUS')&3==0
  self.r['gpu_irq_mask_before']=hex(self.rd('GEN7_RBBM_INT_0_MASK'))
  self.wr('GEN7_RBBM_INT_0_MASK',0)
  for i in range(4):self.wr('GEN7_GBIF_QSB_SIDE'+str(i),0x71620)
  settings=[('RBBM_GBIF_CLIENT_QOS_CNTL',0x2120212),('UCHE_GBIF_GX_CONFIG',0x10240e0),
   ('RBBM_PERFCTR_GPU_BUSY_MASKED',0xffffffff),('UCHE_TRAP_BASE_LO',0xfffff000),('UCHE_TRAP_BASE_HI',0x1ffff),
   ('UCHE_WRITE_THRU_BASE_LO',0xfffff000),('UCHE_WRITE_THRU_BASE_HI',0x1ffff),
   ('UCHE_GMEM_RANGE_MIN_LO',0x1000000),('UCHE_GMEM_RANGE_MIN_HI',0),
   ('UCHE_GMEM_RANGE_MAX_LO',0x12fffff),('UCHE_GMEM_RANGE_MAX_HI',0),('UCHE_CACHE_WAYS',0x800000),
   ('UCHE_CMDQ_CONFIG',0x6690e),('GMU_CX_GMU_POWER_COUNTER_SELECT_1',4),
   ('RB_NC_MODE_CNTL',0x816),('TPL1_NC_MODE_CNTL',6),
   ('TPL1_BICUBIC_WEIGHTS_TABLE_1',0x3fe05ff4),('TPL1_BICUBIC_WEIGHTS_TABLE_2',0x3fa0ebee),
   ('TPL1_BICUBIC_WEIGHTS_TABLE_3',0x3f5193ed),('TPL1_BICUBIC_WEIGHTS_TABLE_4',0x3f0243f0),
   ('SP_NC_MODE_CNTL',0x26),('GRAS_NC_MODE_CNTL',0x60),('UCHE_MODE_CNTL',0x600000),
   ('RBBM_INTERFACE_HANG_INT_CNTL',0x4cfffff),('UCHE_CLIENT_PF',0x81),('TPL1_DBG_ECO_CNTL1',0xc0700),
   ('GPU_GMU_AO_GPU_CX_BUSY_MASK',0xff000000),('GMU_CX_GMU_POWER_COUNTER_ENABLE',1),
   ('CP_PROTECT_CNTL',0xb),('CP_APRIV_CNTL',0x6f),('CP_BV_APRIV_CNTL',0xf),('CP_LPAC_APRIV_CNTL',0xf),('CP_AQE_APRIV_CNTL',1)]
  # Hang interrupt mask is BIT(30) | hang_detect_cycles (0xcfffff).
  settings=[(n,0x40cfffff if n=='RBBM_INTERFACE_HANG_INT_CNTL' else v) for n,v in settings]
  for name,value in settings:
   self.wr('GEN7_'+name,value,verify=name not in ('RBBM_PERFCTR_GPU_BUSY_MASKED','UCHE_GMEM_RANGE_MAX_LO'))
   if name=='UCHE_GMEM_RANGE_MAX_LO':assert self.rd('GEN7_'+name)==(value&~4095)
  self.wr('GEN7_RB_CMP_DBG_ECO_CNTL',self.rd('GEN7_RB_CMP_DBG_ECO_CNTL')|(1<<19))
  self.wr('GEN7_GMU_CX_GMU_POWER_COUNTER_SELECT_0',(self.rd('GEN7_GMU_CX_GMU_POWER_COUNTER_SELECT_0')&~255)|0x20)
  self.wr('GEN7_GBIF_CX_CONFIG',(self.rd('GEN7_GBIF_CX_CONFIG')&~0xe0000000)|0x20000000)
  body=re.search(r'gen7_9_0_protected_regs\[\] = \{(.*?)\};',self.list,re.S)[1]
  entries=re.findall(r'\{ GEN7_CP_PROTECT_REG \+ (\d+), (0x[0-9a-f]+), (0x[0-9a-f]+), ([01]) \}',body)
  assert len(entries)==48
  for index,start,end,deny in entries:
   start,end=int(start,16),int(end,16)
   self.wr('GEN7_CP_PROTECT_REG+'+index,start|((end-start)<<18)|(int(deny)<<31))
  for name,value in (('RBBM_SECVID_TSB_CNTL',0),('RBBM_SECVID_TSB_TRUSTED_BASE_LO',0xf0000000),
     ('RBBM_SECVID_TSB_TRUSTED_BASE_HI',0),('RBBM_SECVID_TSB_TRUSTED_SIZE',0x10000000)):
   self.wr('GEN7_'+name,value)
  for name,value in (('GPU_GMU_AO_GMU_CGC_MODE_CNTL',0x20202),('GPU_GMU_AO_GMU_CGC_DELAY_CNTL',0x10111),('GPU_GMU_AO_GMU_CGC_HYST_CNTL',0x5555)):
   self.wr('GEN7_'+name,value)
  self.wr('GEN7_RBBM_CLOCK_CNTL_GLOBAL',1)
  self.wr('GEN7_RBBM_CGC_GLOBAL_LOAD_CMD',1,False)
  self.wr('GEN7_RBBM_CGC_P2S_TRIG_CMD',1,False)
  deadline=time.monotonic()+.1
  while time.monotonic()<deadline:
   if self.rd('GEN7_RBBM_CGC_P2S_STATUS')&1:break
  else:raise RuntimeError('CGC P2S load handshake failed')
  self.wr('GEN7_RBBM_CLOCK_CNTL_GLOBAL',0)
  first=self.array('gen7_ifpc_pwrup_reglist')+self.array('gen7_9_x_ifpc_pwrup_reglist')
  second=self.array('gen7_pwrup_reglist')
  assert len(first)<256 and len(second)<256
  words=[0,0,0,len(first)|(len(second)<<8)]
  for name in first+second:words.extend((self.word(name),self.rd(name)))
  a=self.t.allocate(4096,4096,0x33f,0);self.t.dev(4,a['offset'],4096)
  self.t.write(a['offset'],words)
  for at in range(0,len(words),32):assert self.t.read(a['offset']+at*4,min(32,len(words)-at))==words[at:at+32]
  self.r['powerup_list']={'allocation':a,'ifpc_pairs':len(first),'preemption_pairs':len(second),'dynamic_triplets':0,'words':len(words),'sha256':hashlib.sha256(b''.join(v.to_bytes(4,'little') for v in words)).hexdigest()}
  self.r['gen7_nonsecure_registers_verified']=True
  return a
