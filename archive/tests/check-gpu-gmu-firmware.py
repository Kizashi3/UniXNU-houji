#!/usr/bin/env python3
"""Execute the exact embedded diagnostic as Cortex-M3; no external accesses."""
from pathlib import Path
import hashlib
import re
import struct
import subprocess
p=Path(__file__).resolve().parents[1]
header=(p/'native/gpu/uefi/GpuGmuCode.h').read_text()
words=[int(x,16) for x in re.findall(r'0x([0-9a-f]+)u',header)]
binary=struct.pack('<'+'I'*len(words),*words)
assert binary[0x62:0x64]==b'\xfe\xe7','diagnostic idle must busy-loop in ITCM, never WFI'
assert hashlib.sha256(binary).hexdigest() in header
source=(p/'native/gpu/firmware/houji_gmu_tcm_probe.S').read_bytes()
subprocess.run(['docker','exec','-i','unixnu-houji-build','clang','--target=arm-none-eabi',
 '-mcpu=cortex-m3','-mthumb','-nostdlib','-fuse-ld=lld',
 '-Wl,--image-base=0,-Ttext=0,-e,vectors','-x','assembler-with-cpp','-',
 '-o','/tmp/houji-gmu-probe-check.elf'],input=source,check=True)
subprocess.run(['docker','exec','unixnu-houji-build','llvm-objcopy','-O','binary',
 '/tmp/houji-gmu-probe-check.elf','/tmp/houji-gmu-probe-check.bin'],check=True)
rebuilt=subprocess.check_output(['docker','exec','unixnu-houji-build','cat','/tmp/houji-gmu-probe-check.bin'])
assert rebuilt==binary,'embedded CM3 diagnostic differs from actual assembly source'
subprocess.run(['docker','exec','unixnu-houji-build','rm','-f','/tmp/houji-gmu-probe-check.elf','/tmp/houji-gmu-probe-check.bin'],check=True)
program=r'''
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP
import struct
code=bytes.fromhex('''+repr(binary.hex())+r''')
vectors=struct.unpack_from('<16I',code)
assert vectors[:2]==(0x10007f80,0x41)
for fault in (False,True):
 cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
 cpu.mem_map(0,0x4000);cpu.mem_write(0,code)
 cpu.mem_map(0x10004000,0x4000)
 cpu.reg_write(UC_ARM_REG_SP,vectors[0])
 reads=[];writes=[]
 def read(uc,kind,address,size,value,cookie):
  assert 0<=address<address+size<=len(code) or 0x10004000<=address<address+size<=0x10004020
  reads.append((address,size))
 def write(uc,kind,address,size,value,cookie):
  assert 0x10004000<=address<address+size<=0x1000400c
  writes.append((address,size,value))
 def instruction(uc,address,size,cookie):
  assert 0x40<=address<0x74
  if address==0x62:uc.emu_stop()
 cpu.hook_add(UC_HOOK_MEM_READ,read);cpu.hook_add(UC_HOOK_MEM_WRITE,write);cpu.hook_add(UC_HOOK_CODE,instruction)
 cpu.emu_start(vectors[3] if fault else vectors[1],0x74,count=5000)
 mailbox=struct.unpack('<3I',cpu.mem_read(0x10004000,12))
 assert mailbox==(0xa750dead,0,0) if fault else mailbox==(0xa7500002,0x750c0de0,128)
 assert cpu.reg_read(UC_ARM_REG_SP)==vectors[0]
 assert writes and reads
print('PASS: actual CM3 embedded bytes execute normal/fault entries, touch only ITCM/DTCM, preserve SP, and produce expected completion')
'''
subprocess.run(['docker','exec','-i','unixnu-houji-build','/opt/houji-venv/bin/python3','-'],input=program,text=True,check=True)
