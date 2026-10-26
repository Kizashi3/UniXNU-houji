"""Audit that an instrumented kernel changed only qualified probe sites/padding."""
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import argparse

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('original',type=Path)
parser.add_argument('patched',type=Path)
parser.add_argument('report',type=Path)
parser.add_argument('--post-mmu-marker',action='store_true')
parser.add_argument('--arm-init-marker',action='store_true')
args=parser.parse_args()
if args.post_mmu_marker and args.arm_init_marker:parser.error('Choose one stopping probe')
original,patched,report=args.original,args.patched,args.report
spec=importlib.util.spec_from_file_location('entry_probe',Path(__file__).with_name('patch-xnu-entry-probe.py'))
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
before=original.read_bytes();after=patched.read_bytes()
if len(before)!=len(after):raise SystemExit('Probe changed kernel length')
p.load_segments(before);symbols=p.rebase(original,before)
sites=[p.ENTRY_VA,p.MMU_ENABLE_VA]
sites += ([symbols['_arm_init']] if args.arm_init_marker else
          [p.AFTER_MMU_VA] if args.post_mmu_marker else [p.PANIC_VA,symbols['_panic_trap_to_debugger']])
padding_start=min(p.CAVES.values());padding_size=p.PANIC_CAVE_END-padding_start
if not p.is_padding(before,padding_start,padding_size):raise SystemExit('Probe region is not verified alignment padding')
allowed=set(range(p.file_offset(padding_start),p.file_offset(padding_start)+padding_size))
for va in sites:allowed.update(range(p.file_offset(va),p.file_offset(va)+4))
changed=[i for i,(a,b) in enumerate(zip(before,after)) if a!=b]
if not changed or any(i not in allowed for i in changed):raise SystemExit('Change outside qualified diagnostic sites')
for va in sites:
    word=struct.unpack_from('<I',after,p.file_offset(va))[0]
    if word>>26!=0b000101:raise SystemExit('Probe entry is not a direct branch')
    delta=word&0x3ffffff
    if delta&(1<<25):delta-=1<<26
    target=va+delta*4
    if not padding_start<=target<p.PANIC_CAVE_END:raise SystemExit('Probe branch leaves the padding region')
r={'original_sha256':hashlib.sha256(before).hexdigest(),'patched_sha256':hashlib.sha256(after).hexdigest(),
   'bytes_changed':len(changed),'sites':[hex(x) for x in sites],
   'entry_marker':'blue second band','pre_mmu_marker':'magenta third band',
   'panic_screen':not (args.post_mmu_marker or args.arm_init_marker),'automatic_reset':False,'hardware_tested':False,
   'post_mmu_marker':'yellow then park' if args.post_mmu_marker else None,
   'arm_init_marker':'yellow then park' if args.arm_init_marker else None}
report.write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
