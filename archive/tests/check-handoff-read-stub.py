#!/usr/bin/env python3
"""Execute the compiled diagnostic read stub and its exact abort return site."""
import argparse,re,struct
from pathlib import Path
import pefile
from unicorn import Uc,UcError,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn.arm64_const import UC_ARM64_REG_PC,UC_ARM64_REG_SP,UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X30,UC_ARM64_REG_NZCV
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',type=Path,required=True);p.add_argument('--map',type=Path,required=True);a=p.parse_args()
rva=int(re.search(r'^([0-9a-fA-F]+)\s+[0-9a-fA-F]+\s+\d+\s+HandoffReadStub$',a.map.read_text(),re.M)[1],16)
pe=pefile.PE(str(a.image));mapped=pe.get_memory_mapped_image();assert mapped[rva:rva+8]==struct.pack('<II',0xb9400000,0xd65f03c0)
base,stop,stack,address=0x10000000,0x20000000,0x30000000,0x15000800
for fault in (False,True):
 cpu=Uc(UC_ARCH_ARM64,UC_MODE_ARM);cpu.mem_map(base,(len(mapped)+4095)&~4095);cpu.mem_write(base,mapped);cpu.mem_map(stop,4096);cpu.mem_map(stack,4096)
 if not fault: cpu.mem_map(address&~4095,4096);cpu.mem_write(address,struct.pack('<I',0xfedcba98))
 values={UC_ARM64_REG_SP:stack+0x800,UC_ARM64_REG_X0:address,UC_ARM64_REG_X1:0x11111111,UC_ARM64_REG_X30:stop,UC_ARM64_REG_NZCV:0xa0000000}
 for register,value in values.items():cpu.reg_write(register,value)
 if fault:
  try:cpu.emu_start(base+rva,stop,count=3)
  except UcError:pass
  else:raise AssertionError('Expected unmapped read')
  assert cpu.reg_read(UC_ARM64_REG_PC)==base+rva and cpu.reg_read(UC_ARM64_REG_X0)==address
  cpu.reg_write(UC_ARM64_REG_X0,0);cpu.reg_write(UC_ARM64_REG_PC,base+rva+4)
  cpu.emu_start(base+rva+4,stop,count=2)
 else:cpu.emu_start(base+rva,stop,count=3)
 assert cpu.reg_read(UC_ARM64_REG_PC)==stop
 assert cpu.reg_read(UC_ARM64_REG_X0)==(0 if fault else 0xfedcba98)
 for register,value in values.items():
  if register!=UC_ARM64_REG_X0:assert cpu.reg_read(register)==value
print('PASS: actual built LDR/RET, zero-extended data and failed-read RET site; SP/LR/X1/NZCV unchanged. Hardware external-abort delivery is not emulated.')
