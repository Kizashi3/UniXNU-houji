#!/usr/bin/env python3
"""Check actual embedded CM3 bytes; external accesses confined to fixed test VAs."""
from pathlib import Path
import hashlib
import re
import struct
import subprocess
p=Path(__file__).resolve().parents[1]
header=(p/'native/gpu/uefi/GpuDmaCode.h').read_text()
words=[int(x,16) for x in re.findall(r'0x([0-9a-f]+)u',header)]
binary=struct.pack('<'+'I'*len(words),*words)
assert len(binary)==176 and hashlib.sha256(binary).hexdigest() in header
assert binary[0x7a:0x7c]==b'\xfe\xe7'
source=(p/'native/gpu/firmware/houji_gmu_dma_probe.S').read_bytes()
subprocess.run(['docker','exec','-i','unixnu-houji-build','clang','--target=arm-none-eabi',
 '-mcpu=cortex-m3','-mthumb','-nostdlib','-fuse-ld=lld','-Wl,--image-base=0,-Ttext=0,-e,vectors',
 '-x','assembler-with-cpp','-','-o','/tmp/houji-dma-check.elf'],input=source,check=True)
subprocess.run(['docker','exec','unixnu-houji-build','llvm-objcopy','-O','binary',
 '/tmp/houji-dma-check.elf','/tmp/houji-dma-check.bin'],check=True)
assert subprocess.check_output(['docker','exec','unixnu-houji-build','cat','/tmp/houji-dma-check.bin'])==binary
program=r'''
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP,UC_ARM_REG_PC,UC_ARM_REG_PRIMASK
import struct
code=bytes.fromhex('''+repr(binary.hex())+r''')
vectors=struct.unpack_from('<16I',code)
assert vectors[:2]==(0x10007f80,0x41)
for fault in (False,True):
 cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
 for at,n in ((0,0x4000),(0x10004000,0x4000),(0x60000000,0x1000),(0x60002000,0x1000),(0xe000e000,0x1000)):cpu.mem_map(at,n)
 cpu.mem_write(0,code);cpu.mem_write(0x60000000,struct.pack('<3I',0x7504cafe,0x86500071,0))
 cpu.mem_write(0xe000ed28,struct.pack('<I',0x8200));cpu.mem_write(0xe000ed38,struct.pack('<I',0x60002000))
 cpu.reg_write(UC_ARM_REG_SP,vectors[0]);reads=[];writes=[]
 def read(uc,kind,address,size,value,cookie):
  assert size==4 and (0<=address<address+size<=len(code) or
    address in (0x60000000,0x60000004,0x60000008,0x60002000,0xe000ed28,0xe000ed38))
  reads.append(address)
 def write(uc,kind,address,size,value,cookie):
  assert size==4 and (0x10004000<=address<0x10004020 or address==0x60000008)
  if address==0x60000008:assert value==0xa750cafe
  writes.append((address,value))
 def instruction(uc,address,size,cookie):
  assert 0x40<=address<0x94
  if address==0x7a:uc.emu_stop()
  if fault and address==0x6e:uc.reg_write(UC_ARM_REG_PC,vectors[3])
 cpu.hook_add(UC_HOOK_MEM_READ,read);cpu.hook_add(UC_HOOK_MEM_WRITE,write);cpu.hook_add(UC_HOOK_CODE,instruction)
 cpu.emu_start(vectors[1],0x94,count=5000)
 mail=struct.unpack('<8I',cpu.mem_read(0x10004000,32))
 assert mail[:5]==(0xa750dead if fault else 0xa7500003,0x7504cafe,0x86500071,0xa750cafe,0)
 assert mail[6:]==((0x8200,0x60002000) if fault else (0,0))
 assert struct.unpack('<3I',cpu.mem_read(0x60000000,12))==(0x7504cafe,0x86500071,0xa750cafe)
 assert [x for x in writes if x[0]>=0x60000000]==[(0x60000008,0xa750cafe)]
 assert cpu.reg_read(UC_ARM_REG_SP)==vectors[0] and cpu.reg_read(UC_ARM_REG_PRIMASK)==1
 assert 0x60002000 in reads if not fault else 0xe000ed38 in reads
print('PASS: actual 176-byte CM3 image; fixed owned-page read/write, one negative read or captured fault, internal idle, masked IRQs, unchanged SP; no other external writes')
'''
subprocess.run(['docker','exec','-i','unixnu-houji-build','/opt/houji-venv/bin/python3','-'],input=program,text=True,check=True)
