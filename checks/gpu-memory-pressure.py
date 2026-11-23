#!/usr/bin/env python3
"""Execute the runtime's allocation retry policy with a bounded fake GPU heap."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
text = (root / 'graphics/runtime/overlay/crates/metal2vulkan-runtime/src/memory.rs').read_text()
at = text.index('fn make_pressure_block<T>(')
function = text[at:text.index('\n}\n', at) + 3]
at = text.index('    fn release_kept_heap(')
reclaim = text[at:text.index('\n    }\n', at) + 7]
unit = '''
#[derive(Debug, PartialEq)] enum Error { OutOfMemory(u8), DeviceLost }
mod ash { pub struct Device; }
struct MemoryType { heap_index: u32 }
struct Memory { types: Vec<MemoryType>, empty: Vec<usize>, visited: Vec<u32> }
impl Memory {
    fn release_kept(&mut self, _: &ash::Device, index: u32) -> usize {
        self.visited.push(index);
        std::mem::take(&mut self.empty[index as usize])
    }
''' + reclaim + '\n}\n' + function + r'''
fn main() {
    use std::cell::Cell;
    // An empty image pool of another memory type consumes the same heap.
    // Reclaim it, but leave an unrelated heap's cached blocks alone.
    let mut memory=Memory {types:vec![MemoryType{heap_index:0},MemoryType{heap_index:1},MemoryType{heap_index:0}],
                           empty:vec![0,99,2],visited:vec![]};
    assert_eq!(memory.release_kept_heap(&ash::Device,0),2);
    assert_eq!(memory.visited,[0,2]);assert_eq!(memory.empty,[0,99,0]);
    let mut attempts = Vec::new();
    // A 12 MiB image fits the remaining 24 MiB, though a 64 MiB pool does not.
    let made = make_pressure_block(64, 12, false, |bytes| {
        attempts.push(bytes);
        if bytes > 24 { Err(Error::OutOfMemory(1)) } else { Ok(73) }
    }, || false).unwrap();
    assert_eq!(attempts, [64, 12]); assert_eq!(made, (73, 12, true));
    // Empty-block reclamation restores room for the normal reusable block.
    let room = Cell::new(0);
    let freed = Cell::new(0);
    let made = make_pressure_block(64, 12, false, |bytes| {
        if bytes > room.get() { Err(Error::OutOfMemory(1)) } else { Ok(11) }
    }, || { freed.set(freed.get()+1); room.set(128); true }).unwrap();
    assert_eq!(freed.get(), 1); assert_eq!(made, (11, 64, false));
    // A successful pool allocation performs no reclamation.
    assert_eq!(make_pressure_block(64, 12, false, |_| Ok(7), || panic!("unexpected reclaim")).unwrap(), (7,64,false));
    // Device loss is not a memory-pressure signal and must not be hidden.
    assert_eq!(make_pressure_block::<u8>(64, 12, false, |_| Err(Error::DeviceLost), || panic!("unexpected reclaim")), Err(Error::DeviceLost));
    // A dedicated resource cannot be made smaller than its requirements.
    let calls=Cell::new(0);
    assert_eq!(make_pressure_block::<u8>(80, 80, true, |_| {calls.set(calls.get()+1); Err(Error::OutOfMemory(1))}, || false), Err(Error::OutOfMemory(1)));
    assert_eq!(calls.get(), 1);
    // Exhaustion stays an error after bounded retries, without inventing storage.
    let calls=Cell::new(0);
    assert_eq!(make_pressure_block::<u8>(64, 12, false, |_| {calls.set(calls.get()+1); Err(Error::OutOfMemory(1))}, || true), Err(Error::OutOfMemory(1)));
    assert_eq!(calls.get(), 3);
    println!("PASS: actual memory-pressure policy reclaims empty blocks, falls back to exact-size storage, preserves device loss and bounded exhaustion; no GPU");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-memory-') as temporary:
    source = Path(temporary) / 'pressure.rs'
    binary = Path(temporary) / 'pressure'
    source.write_text(unit)
    subprocess.run(['rustc', '--edition=2021', '-Dwarnings', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
