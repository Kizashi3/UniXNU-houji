#!/usr/bin/env python3
"""Execute the pinned CM3 image with an explicit architectural entry peer.

Unicorn does not deliver this device's NVIC exception. Its real unmapped-read
failure supplies the register state; the peer stacks the documented eight
words, then executes the unchanged handler. This is not hardware validation.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import struct
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=Path('/tmp/houji-gmu-negative-frame.json'))
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
words = [int(x, 16) for x in re.findall(r'0x([0-9a-f]+)u', (root / 'native/gpu/uefi/GpuDmaCode.h').read_text())]
blob = struct.pack('<44I', *words)
assert hashlib.sha256(blob).hexdigest() == 'b3a876b2a2a6aed251b824ba412fdf9e1d1f4c340a8093868e63c3bba721e076'
program = r'''
import json,struct
from unicorn import Uc,UcError,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_HOOK_CODE,UC_ERR_READ_UNMAPPED
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R12,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_ARM_REG_SP,UC_ARM_REG_XPSR,UC_ARM_REG_PRIMASK
code=bytes.fromhex(BLOB)
vectors=struct.unpack_from('<16I',code)
assert vectors[:2]==(0x10007f80,0x41) and code[0x6e:0x70]==bytes.fromhex('1368')
records=[]
for flags in range(32):
 cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
 for address,size in ((0,0x4000),(0x10004000,0x4000),(0x60000000,0x1000),(0xe000e000,0x1000)):
  cpu.mem_map(address,size)
 cpu.mem_write(0,code)
 cpu.mem_write(0x60000000,struct.pack('<3I',0x7504cafe,0x86500071,0))
 guards=struct.pack('<8I',*[0x12340000+i for i in range(8)])
 cpu.mem_write(0x10007f40,guards)
 cpu.reg_write(UC_ARM_REG_SP,vectors[0])
 cpu.reg_write(UC_ARM_REG_R12,0x12abc000+flags)
 cpu.reg_write(UC_ARM_REG_LR,0xe1230000+flags)
 cpu.reg_write(UC_ARM_REG_XPSR,0x01000000|(flags<<27))
 reads=[];writes=[];instructions=[]
 def read(uc,kind,address,size,value,cookie):
  assert size==4 and (0<=address<address+size<=len(code) or address in (0x60000000,0x60000004,0x60000008,0x60002000,0xe000ed28,0xe000ed38))
  reads.append(address)
 def write(uc,kind,address,size,value,cookie):
  assert size==4 and (0x10004000<=address<0x10004020 or address==0x60000008)
  writes.append((address,value))
 def instruction(uc,address,size,cookie):
  assert 0x40<=address<0x94
  instructions.append(address)
  if address==0x7a:uc.emu_stop()
 cpu.hook_add(UC_HOOK_MEM_READ,read)
 cpu.hook_add(UC_HOOK_MEM_WRITE,write)
 cpu.hook_add(UC_HOOK_CODE,instruction)
 try:cpu.emu_start(vectors[1],0x94,count=1000)
 except UcError as error:assert error.errno==UC_ERR_READ_UNMAPPED
 else:raise AssertionError('negative address unexpectedly returned')
 assert cpu.reg_read(UC_ARM_REG_PC)==0x6e and cpu.reg_read(UC_ARM_REG_SP)==0x10007f80
 regs=(UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_R12,UC_ARM_REG_LR,UC_ARM_REG_PC,UC_ARM_REG_XPSR)
 frame=tuple(cpu.reg_read(reg) for reg in regs)
 assert frame[:4]==(0x10004000,0xa7500001,0x60002000,0xa750cafe)
 assert frame[4:7]==(0x12abc000+flags,0xe1230000+flags,0x6e)
 assert frame[7]&~0xf8000000==0x01000000
 assert 0x60 in instructions and 0x68 in instructions
 # Explicit architectural exception-entry peer; not Unicorn NVIC emulation.
 cpu.mem_write(0x10007f60,struct.pack('<8I',*frame))
 cpu.reg_write(UC_ARM_REG_SP,0x10007f60)
 cpu.reg_write(UC_ARM_REG_LR,0xfffffff9)
 cpu.reg_write(UC_ARM_REG_XPSR,(frame[7]&~0x1ff)|3)
 cpu.mem_write(0xe000ed28,struct.pack('<I',0x8200))
 cpu.mem_write(0xe000ed38,struct.pack('<I',0x60002000))
 cpu.emu_start(vectors[3],0x94,count=1000)
 mail=struct.unpack('<8I',cpu.mem_read(0x10004000,32))
 assert mail==(0xa750dead,0x7504cafe,0x86500071,0xa750cafe,0,0,0x8200,0x60002000)
 assert cpu.mem_read(0x10007f40,32)==guards
 assert struct.unpack('<8I',cpu.mem_read(0x10007f60,32))==frame
 assert cpu.reg_read(UC_ARM_REG_SP)==0x10007f60 and cpu.reg_read(UC_ARM_REG_PRIMASK)==1
 assert [entry for entry in writes if entry[0]>=0x60000000]==[(0x60000008,0xa750cafe)]
 assert instructions[-1]==0x7a and 0x8e in instructions
 assert struct.unpack('<3I',cpu.mem_read(0x60000000,12))==(0x7504cafe,0x86500071,0xa750cafe)
 records.append({'flags':flags,'frame':frame,'mailbox':mail,'external_writes':[entry for entry in writes if entry[0]>=0x60000000]})
print(json.dumps({'status':'PASS','cases':len(records),'hardware_tested':False,'exception_entry':'explicit architecture peer after actual Unicorn unmapped read, not hardware/NVIC delivery','records':records}))
'''.replace('BLOB', repr(blob.hex()))
result = subprocess.run(['docker', 'exec', '-i', 'unixnu-houji-build', '/opt/houji-venv/bin/python3', '-'],
                        input=program, text=True, capture_output=True, check=True)
data = json.loads(result.stdout)
args.output.write_text(json.dumps(data, indent=2) + '\n')
print(f"PASS: {data['cases']} actual pinned-payload executions with explicit exception-entry peer; no hardware qualification; {args.output}")
