#!/usr/bin/env python3
"""Exercise the upstream-derived room worker's wake/coalesce/teardown with fake allocations."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'graphics/runtime/overlay/crates/metal2vulkan-runtime/src/device/room.rs'
unit = r'''
use std::sync::{Arc,Mutex,Condvar,mpsc,atomic::{AtomicBool,AtomicUsize,Ordering}};
use std::time::Duration;
fn lock<T>(m:&Mutex<T>)->std::sync::MutexGuard<'_,T>{m.lock().unwrap()}
mod exit_guard {
    use super::*;
    pub static FAIL:AtomicBool=AtomicBool::new(false);
    pub fn enter()->Option<()>{Some(())}
    pub fn spawn<F:FnOnce()->T+Send+'static,T:Send+'static>(b:std::thread::Builder,f:F)->std::io::Result<std::thread::JoinHandle<T>>{
        if FAIL.swap(false,Ordering::SeqCst){Err(std::io::Error::other("fixture spawn failure"))}else{b.spawn(f)}
    }
}
struct Gate { permits:Mutex<usize>,wake:Condvar,entered:mpsc::Sender<()>,done:AtomicUsize,ended:mpsc::Sender<()> }
impl Gate {fn allow(&self,n:usize){*lock(&self.permits)+=n;self.wake.notify_all();}}
mod memory {
    use super::*;
    pub struct Memory(pub Arc<Gate>);
    pub fn keep_room(m:&Mutex<Memory>,_:&(),_:&()){
        let g=Arc::clone(&lock(m).0);g.entered.send(()).unwrap();
        let mut permit=lock(&g.permits);
        while *permit==0{permit=g.wake.wait(permit).unwrap();}
        *permit-=1;g.done.fetch_add(1,Ordering::SeqCst);
    }
}
mod device {
    use super::*;
    #[derive(Clone)] pub struct Device(pub Arc<Shared>);
    pub struct WeakDevice(std::sync::Weak<Shared>);
    pub struct Shared{pub memory:Mutex<crate::memory::Memory>,pub counts:(),pub room:room::Room,pub gate:Arc<Gate>}
    impl Shared{pub fn vk(&self)->&(){&self.counts}}
    impl Device{pub fn downgrade(&self)->WeakDevice{WeakDevice(Arc::downgrade(&self.0))}pub fn shared(&self)->&Shared{&self.0}}
    impl WeakDevice{pub fn upgrade(&self)->Option<Device>{self.0.upgrade().map(Device)}}
    impl Drop for Shared{fn drop(&mut self){self.room.stop();self.gate.ended.send(()).unwrap();}}
'''
unit += '#[path="' + str(SOURCE) + '"] pub mod room;\n}\n'
unit += r'''
fn setup()->(device::Device,Arc<Gate>,mpsc::Receiver<()>,mpsc::Receiver<()>){
    let (tx,rx)=mpsc::channel();let (end,ended)=mpsc::channel();
    let g=Arc::new(Gate{permits:Mutex::new(0),wake:Condvar::new(),entered:tx,done:AtomicUsize::new(0),ended:end});
    (device::Device(Arc::new(device::Shared{memory:Mutex::new(memory::Memory(Arc::clone(&g))),counts:(),room:Default::default(),gate:Arc::clone(&g)})),g,rx,ended)
}
fn receive(rx:&mpsc::Receiver<()>){rx.recv_timeout(Duration::from_secs(3)).expect("worker stalled");}
fn main(){
    let (d,g,entered,ended)=setup();
    d.0.room.ask(&d);receive(&entered); // ask returned while allocation is still blocked
    for _ in 0..1000{d.0.room.ask(&d);}
    g.allow(1);receive(&entered);g.allow(1); // burst asks coalesce into one further pass
    drop(d);receive(&ended);assert_eq!(g.done.load(Ordering::SeqCst),2);
    let (d,g,entered,ended)=setup();let weak=d.downgrade();
    d.0.room.ask(&d);receive(&entered);drop(d);g.allow(1);
    receive(&ended);assert!(weak.upgrade().is_none()); // last handle can drop on worker; no self-join
    let (d,g,entered,ended)=setup();g.allow(1);
    exit_guard::FAIL.store(true,Ordering::SeqCst);d.0.room.ask(&d);receive(&entered);
    assert_eq!(g.done.load(Ordering::SeqCst),1);drop(d);receive(&ended); // failed spawn falls back once
    println!("PASS: actual async room worker returns before allocation, coalesces asks, handles last-reference teardown and spawn failure; no GPU");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-room-worker-') as temporary:
    source, binary = Path(temporary) / 'room.rs', Path(temporary) / 'room'
    source.write_text(unit)
    subprocess.run(['rustc', '--edition=2021', '-Dwarnings', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)
