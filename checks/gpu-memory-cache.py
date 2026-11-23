#!/usr/bin/env python3
"""Run the actual allocator bookkeeping with fake device-memory handles; no GPU."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'graphics/runtime/overlay/crates/metal2vulkan-runtime/src'
text = (BASE / 'memory.rs').read_text()


def method(name):
    start = text.index('    fn ' + name + '(') if name != 'release_spare' else text.index('    pub(super) fn release_spare(')
    return text[start:text.index('\n    }\n', start) + 7]


constants = '\n'.join(re.findall(r'^pub\(super\) const (?:BLOCK_BYTES|FIRST_BLOCK_BYTES|KEPT_EMPTY_BLOCKS|KEPT_EMPTY_FOR|SPARE_FOR|SPARE_BYTES|SPARE_COUNT):.*;', text, re.M))
pool = text[text.index('#[derive(Debug)]\npub(super) struct Pool<T>'):text.index('/// A host pointer the runtime may send')]
plain = text[text.index('    fn plain(&self)'):text.index('\n    }\n', text.index('    fn plain(&self)')) + 7]
unit = '#![allow(dead_code)]\n#[path="' + str(BASE / 'range.rs') + '"] mod range;\n'
unit += r'''
mod model {
use crate::range::RangeAllocator;
use std::time::{Instant, Duration};
mod ash { pub struct Device; }
''' + constants + '\n' + pool + r'''
#[derive(Debug)]
struct Block { id:u64, size:u64, imported:bool, pages:Option<()>, view:Option<()> }
impl Block {
''' + plain + r'''
}
struct Spare {pool:(Holds,u32),block:Block,since:Instant}
#[derive(Clone,Copy,PartialEq,Eq)] enum Holds { Buffers, Images }
struct MemoryType {heap_index:u32}
struct Memory {pools:Vec<Pool<Block>>,spare:Vec<Spare>,block_bytes:u64,types:Vec<MemoryType>,freed:Vec<u64>}
impl Memory {
    fn pool(&mut self,h:Holds,t:u32)->&mut Pool<Block>{&mut self.pools[t as usize*2+usize::from(h==Holds::Images)]}
    fn pool_ref(&self,h:Holds,t:u32)->&Pool<Block>{&self.pools[t as usize*2+usize::from(h==Holds::Images)]}
    fn say_block(&self,_:&str,_:&Block){}
    unsafe fn let_go(&mut self,_:&ash::Device,block:Block,_:FreeCause,after:Option<Box<dyn Send>>)->Option<Box<dyn Send>>{
        assert!(!self.freed.contains(&block.id),"double free");self.freed.push(block.id);after
    }
''' + '\n'.join(method(n) for n in ['next_block_bytes', 'release_range', 'release_kept', 'can_keep_spare', 'age_spare', 'take_spare', 'release_spare', 'release_kept_heap']) + r'''
}
const M:u64=1<<20;
fn block(id:u64,size:u64)->Block{Block{id,size,imported:false,pages:None,view:None}}
fn memory()->Memory{Memory{pools:(0..4).map(|_|Pool::default()).collect(),spare:vec![],block_bytes:BLOCK_BYTES,
    types:vec![MemoryType{heap_index:0},MemoryType{heap_index:0}],freed:vec![]}}
fn retire(m:&mut Memory,id:u64,h:Holds,size:u64){
    let index=m.pool(h,0).add(size,true,block(id,size),size);
    drop(m.release_range(&ash::Device,(h,0),index,0,size,None));
}
pub fn run(){
    let d=ash::Device;let mut m=memory();
    assert_eq!(m.next_block_bytes((Holds::Images,0),1),4*M);
    for (n,expected) in [4,4,8,16,32,64,64].into_iter().enumerate(){
        let bytes=m.next_block_bytes((Holds::Images,0),1);assert_eq!(bytes,expected*M);
        m.pool(Holds::Images,0).add(bytes,false,block(100+n as u64,bytes),1);
    }
    assert_eq!(m.next_block_bytes((Holds::Buffers,0),9*M),16*M); // independent type/usage pools
    m.pool(Holds::Buffers,0).add(112*M,true,block(200,112*M),112*M);
    assert_eq!(m.next_block_bytes((Holds::Buffers,0),1),4*M); // dedicated blocks do not grow pools
    let mut m=memory();
    let index=m.pool(Holds::Images,0).add(40*M,true,block(1,40*M),40*M);
    drop(m.release_range(&d,(Holds::Images,0),index,0,20*M,None));
    assert!(m.spare.is_empty() && m.freed.is_empty()); // cannot cache a live allocation
    drop(m.release_range(&d,(Holds::Images,0),index,20*M,20*M,None));
    assert_eq!(m.spare.len(),1);
    retire(&mut m,2,Holds::Images,48*M);
    assert!(m.take_spare(&d,(Holds::Images,1),39*M).is_none()); // memory type must match
    assert!(m.take_spare(&d,(Holds::Images,0),29*M).is_none()); // refuse >25% waste
    let spare=m.take_spare(&d,(Holds::Images,0),39*M).unwrap();assert_eq!(spare.id,1);
    assert_eq!(m.spare.len(),1); // removed from cache exactly once
    unsafe{drop(m.let_go(&d,spare,FreeCause::Dedicated,None));}
    retire(&mut m,3,Holds::Buffers,40*M);assert!(m.freed.contains(&3));
    for (id,imported,pages,view) in [(4,true,None,None),(5,false,Some(()),None),(6,false,None,Some(()))]{
        let b=Block{id,size:40*M,imported,pages,view};let at=m.pool(Holds::Images,0).add(40*M,true,b,40*M);
        drop(m.release_range(&d,(Holds::Images,0),at,0,40*M,None));assert!(m.freed.contains(&id));
    }
    retire(&mut m,7,Holds::Images,80*M);assert_eq!(m.spare.iter().map(|s|s.block.size).sum::<u64>(),128*M);
    retire(&mut m,8,Holds::Images,M);assert!(m.freed.contains(&8)); // byte limit
    retire(&mut m,9,Holds::Images,129*M);assert!(m.freed.contains(&9));
    m.spare[0].since=Instant::now()-SPARE_FOR; m.age_spare(&d,Instant::now());
    assert_eq!(m.spare.len(),1);assert!(m.freed.contains(&2));
    m.pool(Holds::Buffers,1).add(4*M,false,block(10,4*M),0);
    let live=m.pool(Holds::Images,1).add(4*M,false,block(11,4*M),M);
    assert_eq!(m.release_kept_heap(&d,0),2); // reclaim other memory types on the same heap
    assert!(m.spare.is_empty());assert!(m.pool_ref(Holds::Images,1).payload(live).is_some());
    for id in 12..16{retire(&mut m,id,Holds::Images,M);}
    retire(&mut m,16,Holds::Images,M);assert!(m.freed.contains(&16)); // count limit
    assert_eq!(m.release_spare(&d),4);assert_eq!(m.release_spare(&d),0);
    assert!(m.pool_ref(Holds::Images,1).payload(live).is_some()); // pressure preserves live memory
}
}
fn main(){model::run();println!("PASS: actual growing pools, retirement, spare bounds/best-fit/expiry, import exclusion and pressure reclaim; fake memory handles, no GPU");}
'''
with tempfile.TemporaryDirectory(prefix='houji-memory-cache-') as temporary:
    source, binary = Path(temporary) / 'cache.rs', Path(temporary) / 'cache'
    source.write_text(unit)
    subprocess.run(['rustc', '--edition=2021', '-Dwarnings', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
