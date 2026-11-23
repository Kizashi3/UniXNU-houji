#!/usr/bin/env python3
"""Extract register facts from fixed vendor sources; emit no vendor algorithm.

The independently implemented consumer stays at disabled SQE. Source files are
local evidence, not build-time network inputs. A750v2's gen7_9_1 profile matters:
it uses gen7_0_0 GBIF and has AO HWCG only, unlike several nearby profiles.
"""
import argparse, hashlib, json, re
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('sources',type=Path);p.add_argument('--fdt',type=Path,required=True)
p.add_argument('--linux-host',type=Path,metavar='A6XX_GPU_C',help='use the hash-bound Linux host CP_AHB and untrusted TSB initialization facts')
a=p.parse_args()
root=Path(__file__).resolve().parents[1];out=root/'native/gpu/uefi'
linux_host=None
if a.linux_host is not None:
 linux_bytes=a.linux_host.read_bytes();linux_hash=hashlib.sha256(linux_bytes).hexdigest()
 if linux_hash!='3ba0192acb394ace2f7058c9c6b884c83c1763da49067f97201dad606bb3d109':
  p.error('--linux-host must match pinned Linux a6xx_gpu.c SHA256 3ba0192acb394ace2f7058c9c6b884c83c1763da49067f97201dad606bb3d109')
 linux_text=linux_bytes.decode()
 statements=[('gpu_write','REG_A6XX_CP_AHB_CNTL','0x1'),
  ('gpu_write64','REG_A6XX_RBBM_SECVID_TSB_TRUSTED_BASE','0x00000000'),
  ('gpu_write','REG_A6XX_RBBM_SECVID_TSB_TRUSTED_SIZE','0x00000000')]
 for function,register,value in statements:
  pattern=rf'\b{function}\s*\(\s*gpu\s*,\s*{register}\s*,\s*{value}\s*\)\s*;'
  if not re.search(pattern,linux_text):p.error(f'--linux-host missing pinned statement: {function}(gpu, {register}, {value});')
 linux_host={'source_commit':'21a7f44fd0765fcc5194130b28767786eba1d1e7',
  'source_file':'drivers/gpu/drm/msm/adreno/a6xx_gpu.c','source_sha256':linux_hash,
  'validated_statements':[f'{function}(gpu, {register}, {value});' for function,register,value in statements]}
files={name:(a.sources/('OnePlus453d-'+name)).read_text() for name in ('adreno_gen7.c','adreno-gpulist.h','gen7_reg.h','kgsl_util.h')}
hashes={name:hashlib.sha256(text.encode()).hexdigest() for name,text in files.items()}
assert hashes['adreno_gen7.c']=='1d63fca08e1d45428b80342d3d35a8c4166ad93c74ade6d125d2b3f9f4267d5d'
assert hashes['adreno-gpulist.h']=='08293f60e0be8b3a16ec0b800588d700f54b34d2e9e32e64aac115f05548c8f3'
assert hashes['kgsl_util.h']=='e7b8c1a8fc598987a0f1b81279e7f06e6ee2b6d6f1be417f9d7dd8417124c18d'
assert hashes['gen7_reg.h']=='5da9d8b167c5edb1e2225878461a0b2cbaaae1d1680f2eff467c0b95a78f7a48'
fdt=a.fdt.read_text()
for text in ('qcom,ubwc-mode = <0x04>', 'qcom,min-access-length = <0x20>', 'qcom,gpu-model = "Adreno750v2"', 'qcom,adreno-gpu-gen7-9-1'):
 assert text in fdt,text
regs={k:int(v,0) for k,v in re.findall(r'^#define\s+(GEN7_\w+)\s+(0x[0-9a-fA-F]+|[0-9]+)\b',files['gen7_reg.h'],re.M)}
profile=re.search(r'adreno_gpu_core_gen7_9_1 = \{(.*?)\n\};',files['adreno-gpulist.h'],re.S)[1]
for text in ('.gbif = gen7_0_0_gbif_regs', '.highest_bank_bit = 16', '.gmem_size = 3 * SZ_1M', '.ao_hwcg = gen7_2_0_ao_hwcg_regs'):
 assert text in profile,text
assert not re.search(r'\.hwcg\s*=',profile)
ops=[]
def address(name):
 parts=name.split('+');return 0x3d00000+4*(regs['GEN7_'+parts[0]]+(int(parts[1]) if len(parts)>1 else 0))
def op(name,value,mask=0xffffffff,verify=0xffffffff,kind=0):
 ops.append(dict(name=name,address=address(name),value=value,mask=mask,verify=verify,kind=kind))
op('RBBM_INT_0_MASK',0)
for i in range(4):op('GBIF_QSB_SIDE'+str(i),0x71620)
for name,val in [('RBBM_GBIF_CLIENT_QOS_CNTL',0x2120212),('UCHE_GBIF_GX_CONFIG',0x10240e0),
 ('RBBM_PERFCTR_GPU_BUSY_MASKED',0xffffffff),('UCHE_TRAP_BASE_LO',0xfffff000),('UCHE_TRAP_BASE_HI',0x1ffff),
 ('UCHE_WRITE_THRU_BASE_LO',0xfffff000),('UCHE_WRITE_THRU_BASE_HI',0x1ffff),
 ('UCHE_GMEM_RANGE_MIN_LO',0x1000000),('UCHE_GMEM_RANGE_MIN_HI',0),('UCHE_GMEM_RANGE_MAX_LO',0x12fffff),('UCHE_GMEM_RANGE_MAX_HI',0),
 ('UCHE_CACHE_WAYS',0x800000),('UCHE_CMDQ_CONFIG',0x6690e),('GMU_CX_GMU_POWER_COUNTER_SELECT_1',4),
 ('RB_NC_MODE_CNTL',0x816),('TPL1_NC_MODE_CNTL',6),('TPL1_BICUBIC_WEIGHTS_TABLE_1',0x3fe05ff4),
 ('TPL1_BICUBIC_WEIGHTS_TABLE_2',0x3fa0ebee),('TPL1_BICUBIC_WEIGHTS_TABLE_3',0x3f5193ed),('TPL1_BICUBIC_WEIGHTS_TABLE_4',0x3f0243f0),
 ('SP_NC_MODE_CNTL',0x26),('GRAS_NC_MODE_CNTL',0x60),('UCHE_MODE_CNTL',0x600000),('RBBM_INTERFACE_HANG_INT_CNTL',0x40cfffff),('UCHE_CLIENT_PF',0x81)]:
 op(name,val,verify=0 if name=='RBBM_PERFCTR_GPU_BUSY_MASKED' else 0xfffff000 if name=='UCHE_GMEM_RANGE_MAX_LO' else 0xffffffff)
op('RB_CMP_DBG_ECO_CNTL',1<<19,1<<19,kind=1)
op('TPL1_DBG_ECO_CNTL1',0xc0700)
op('GPU_GMU_AO_GPU_CX_BUSY_MASK',0xff000000)
op('GMU_CX_GMU_POWER_COUNTER_SELECT_0',0x20,255,kind=1)
op('GMU_CX_GMU_POWER_COUNTER_ENABLE',1)
if linux_host is not None:op('CP_AHB_CNTL',1)
op('CP_PROTECT_CNTL',0xb)
body=re.search(r'gen7_9_0_protected_regs\[\] = \{(.*?)\};',files['adreno-gpulist.h'],re.S)[1]
entries=re.findall(r'\{ GEN7_CP_PROTECT_REG \+ (\d+), (0x[0-9a-f]+), (0x[0-9a-f]+), ([01]) \}',body)
assert len(entries)==48
for index,start,end,deny in entries:
 start,end=int(start,16),int(end,16);assert 0<=end-start<8192 and start<262144
 op('CP_PROTECT_REG+'+index,start|((end-start)<<18)|(int(deny)<<31))
for name,value in [('CP_APRIV_CNTL',0x6f),('CP_BV_APRIV_CNTL',15),('CP_LPAC_APRIV_CNTL',15),('CP_AQE_APRIV_CNTL',1)]:op(name,value)
op('GBIF_CX_CONFIG',0x20000000,0xe0000000,kind=1)
for name,value in [('RBBM_SECVID_TSB_CNTL',0),('RBBM_SECVID_TSB_TRUSTED_BASE_LO',0 if linux_host is not None else 0xf0000000),('RBBM_SECVID_TSB_TRUSTED_BASE_HI',0),('RBBM_SECVID_TSB_TRUSTED_SIZE',0 if linux_host is not None else 0x10000000),
 ('GPU_GMU_AO_GMU_CGC_MODE_CNTL',0x20202),('GPU_GMU_AO_GMU_CGC_DELAY_CNTL',0x10111),('GPU_GMU_AO_GMU_CGC_HYST_CNTL',0x5555),('RBBM_CLOCK_CNTL_GLOBAL',1)]:op(name,value)
op('RBBM_CGC_GLOBAL_LOAD_CMD',1,verify=0,kind=2)
op('RBBM_CGC_P2S_TRIG_CMD',1,verify=0,kind=2)
op('RBBM_CGC_P2S_STATUS',1,verify=1,kind=3)
op('RBBM_CLOCK_CNTL_GLOBAL',0)
def powerlist(name):
 body=re.search(r'static const u32 '+name+r'\[\] = \{(.*?)\};',files['adreno_gen7.c'],re.S)[1]
 return [s.strip().removeprefix('GEN7_') for s in body.split(',') if s.strip()]
first=powerlist('gen7_ifpc_pwrup_reglist')+powerlist('gen7_9_x_ifpc_pwrup_reglist');second=powerlist('gen7_pwrup_reglist')
assert len(first)<256 and len(second)<256 and (4+2*(len(first)+len(second)))*4<=4096
assert all(x['address']!=address('CP_SQE_CNTL') and x['address']!=address('RBBM_SECVID_TRUST_CNTL') for x in ops)
head='/* SPDX-License-Identifier: BSD-2-Clause-Patent\n * Register facts: OnePlus graphics-kernel 453d8875, gen7_9_1; generated.\n'
if linux_host is not None:head+=' * Linux host CP_AHB / untrusted TSB facts: 21a7f44fd0765fcc5194130b28767786eba1d1e7.\n'
head+=' */\n#ifndef HOUJI_GPU_GEN7_TABLE_H\n#define HOUJI_GPU_GEN7_TABLE_H\n#include <stdint.h>\n#define H7C_LINUX_HOST %d\nstruct h7c_op {const char *name;uint32_t address,value,mask,verify;unsigned kind;};\n'%int(linux_host is not None)
head+='static const struct h7c_op h7c_ops[]={\n'+''.join(' {"%(name)s",0x%(address)08xu,0x%(value)08xu,0x%(mask)08xu,0x%(verify)08xu,%(kind)u},\n'%x for x in ops)+'};\n'
head+='struct h7c_power_reg {const char *name;uint32_t address;};\nstatic const struct h7c_power_reg h7c_power_regs[]={\n'+''.join(' {"%s",0x%08xu},\n'%(name,address(name)) for name in first+second)+'};\n'
head+='enum {H7C_OPS=%d,H7C_IFPC=%d,H7C_PREEMPT=%d,H7C_PAIRS=%d,H7C_WORDS=%d,H7C_POLLS=1000};\n#endif\n'%(len(ops),len(first),len(second),len(first+second),4+2*len(first+second))
(out/'GpuGen7Table.h').write_text(head)
evidence={'source_commit':'453d8875f815bf9dfad9035982861226a4823a6c','source_hashes':hashes,'profile':'gen7_9_1','own_FDT':{'UBWC':4,'MAL':32,'highest_bank_bit':16,'dts_sha256':hashlib.sha256(fdt.encode()).hexdigest()},'operations':ops,'powerup_IFPC':first,'powerup_preempt':second,'scope':'disabled SQE, no CP command/RAW/PAS/trust bypass; no LLCC/LPAC/preemption enable; IRQ stays masked'}
if linux_host is not None:
 evidence['profile']='gen7_9_1-linux-host';evidence['linux_host_source']=linux_host
 evidence['host_overrides']={'CP_AHB_CNTL':{'operation':'add','value':1,'kind':0,'verify':0xffffffff},
  'RBBM_SECVID_TSB_TRUSTED_BASE_LO':{'operation':'replace-value','vendor_value':0xf0000000,'value':0},
  'RBBM_SECVID_TSB_TRUSTED_SIZE':{'operation':'replace-value','vendor_value':0x10000000,'value':0}}
(out/'gen7-register-facts.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(f'{len(ops)} fixed operations, {len(first)} IFPC + {len(second)} preemption pairs; {evidence["profile"]} source facts bound')
