#!/usr/bin/env python3
"""Classify the verified native eight-core ADT into two scheduler groups."""
from pathlib import Path
import argparse,hashlib,json,sys,copy,struct
P=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(P/'.cache/ios16-reference/vermeer/tools'))
import adt
BASE='b7cf540fd9d06e0f511ce38ece6513f5db8f996821be5e23a2dd294a02129f1e'
def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--input',type=Path,required=True);a.add_argument('--output',type=Path,required=True);v=a.parse_args()
 raw=v.input.read_bytes();assert hashlib.sha256(raw).hexdigest()==BASE and not v.output.exists()
 tree,used=adt.parse(raw);assert used==len(raw) and adt.serialize(tree)==raw
 cpus=next(n for n in tree.children if n.name=='cpus');assert len(cpus.children)==8
 records=[];original=[]
 for i,cpu in enumerate(cpus.children):
  assert cpu.name==f'cpu{i}' and int.from_bytes(cpu.prop('reg'),'little')==i*0x100 and cpu.prop('cluster-type')==bytes(4) and cpu.prop('cluster-id')==bytes(4)
  original.append(copy.deepcopy(cpu.props));values={'cluster-type':ord('E') if i<2 else ord('P'),'cluster-id':int(i>=2),'cluster-core-id':i if i<2 else i-2}
  assert all(sum(k==name for k,_,_ in cpu.props)==1 for name in values)
  cpu.props=[(k,f,struct.pack('<I',values[k]) if k in values else b) for k,f,b in cpu.props]
  records.append(dict(logical=i,physical_affinity=i*0x100,**values))
 result=adt.serialize(tree)
 for cpu,props in zip(cpus.children,original):cpu.props=props
 assert adt.serialize(tree)==raw,'Non-topology input changed'
 v.output.write_bytes(result);v.output.with_suffix('.topology.json').write_text(json.dumps(dict(before=BASE,after=hashlib.sha256(result).hexdigest(),physical_affinities_unchanged=True,native_display_unchanged=True,E=[0,1],P=[2,3,4,5,6,7],cpus=records,hardware_qualified=False),indent=2)+'\n');print(hashlib.sha256(result).hexdigest())
if __name__=='__main__':main()
