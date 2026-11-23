#!/usr/bin/env python3
"""Check the opt-in marker boundary and cache identity, without GPU execution."""
from pathlib import Path
import importlib.util
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'graphics/runtime/overlay/crates/metal2vulkan-runtime/src/texture.rs').read_text()


def function(start):
    at = source.index(start)
    return source[at:source.index('\n}\n', at) + 3]


unit = r'''
use std::sync::atomic::{AtomicU64, Ordering};
#[derive(Clone,Copy)]
enum PixelFormat {RGBA8Unorm,RGBA8UnormSRGB,BGRA8Unorm,BGRA8UnormSRGB,R8Unorm,RGBA16Float,Depth32Float}
mod heap_tiled {
    #[derive(Clone,Debug,PartialEq)]
    pub enum FreshPattern {Color{texel:&'static [u8],color:Option<[f64;4]>},DepthStencil}
}
static HOUJI_PATTERN_PROBE_PLANS: AtomicU64 = AtomicU64::new(0);
'''
for start in ['fn houji_pattern_probe_enabled(', 'fn houji_pattern_probe(', 'pub(crate) fn houji_pattern_probe_statistics(']:
    unit += function(start)
unit += r'''
fn main(){
    use PixelFormat::*;
    use heap_tiled::FreshPattern;
    let enabled=std::env::args().nth(1).unwrap()=="green";
    assert_eq!(houji_pattern_probe_statistics(),[enabled as u64,0]);
    for (index,pf) in [RGBA8Unorm,RGBA8UnormSRGB,BGRA8Unorm,BGRA8UnormSRGB,R8Unorm,RGBA16Float,Depth32Float].into_iter().enumerate(){
        for levels in [0,1,3] {
            let original=if index==6 {FreshPattern::DepthStencil} else {
                FreshPattern::Color{texel:&[0xab,0xcd,0xef,0x12],color:Some([0.3,0.4,0.5,0.6])}
            };
            let actual=houji_pattern_probe(pf,levels,original.clone());
            if enabled && index<4 && levels>0 {
                assert_eq!(actual,FreshPattern::Color{texel:&[0,255,0,255],color:Some([0.0,1.0,0.0,1.0])});
            }else{assert_eq!(actual,original);}
        }
    }
    assert_eq!(houji_pattern_probe_statistics(),[enabled as u64,if enabled{8}else{0}]);
}
'''
with tempfile.TemporaryDirectory(prefix='houji-texture-init-') as directory:
    tmp = Path(directory)
    rust = tmp / 'probe.rs'
    rust.write_text(unit)
    for marker in [None, 'green', 'invalid']:
        env = dict(os.environ)
        env.pop('HOUJI_DIAGNOSTIC_FRESH_PATTERN', None)
        if marker:
            env['HOUJI_DIAGNOSTIC_FRESH_PATTERN'] = marker
        binary = tmp / (marker or 'default')
        subprocess.run(['rustc', '--edition=2021', '-Dwarnings', str(rust), '-o', str(binary)], env=env, check=True)
        subprocess.run([str(binary), marker or 'default'], check=True)

spec = importlib.util.spec_from_file_location('metal_builder', ROOT / 'tools/build-metal.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
identity = '0123456789abcdef' * 2
assert builder.runtime_variant_id(identity, None) == identity
assert builder.runtime_variant_id(identity, 'green') != identity
assert builder.runtime_variant_id(identity, 'green') == builder.runtime_variant_id(identity, 'green')
try:
    builder.runtime_variant_id(identity, 'invalid')
except ValueError:
    pass
else:
    raise AssertionError('unknown diagnostic variant was accepted')
print('PASS: default texture patterns unchanged; opt-in green marker limited to patterned 8-bit colour formats with distinct cache identity; no GPU')
