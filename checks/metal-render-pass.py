#!/usr/bin/env python3
"""Exercise the actual render-pass bridge conversion and C/Rust ABI; no GPU."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1] / 'graphics/metal/AdrenoMetal'
text = (ROOT / 'bridge/NativeMetalObjects.rs').read_text()


def function(name):
    at = text.index(name)
    return text[at:text.index('\n}\n', at) + 3]


cpp = '#include <cstdio>\n#include "' + str(ROOT / 'bridge/NativeMetalObjects.h') + '"\n'
cpp += r'''
int main(){
 NmbRenderPassDescriptor d={};
 for(unsigned i=0;i<10;i++){
  auto &a=i<8?d.colors[i]:(i==8?d.depth:d.stencil);
  a.texture=(NmbTexture *)(uintptr_t)(i+1);a.resolve_texture=(NmbTexture *)(uintptr_t)(i+101);
  a.level=2+i;a.slice=3+i;a.depth_plane=4+i;a.load=1;a.store=2;
  a.resolve_level=5+i;a.resolve_slice=6+i;a.resolve_depth_plane=7+i;a.resolve_filter=i%2;
  for(unsigned n=0;n<4;n++)a.clear[n]=i+n/4.0;
 }
 d.width=320;d.height=240;d.array_length=3;d.samples=4;d.visibility=(NmbBuffer *)(uintptr_t)42;
 return fwrite(&d,sizeof d,1,stdout)==1?0:1;
}
'''
rust = r'''
use std::io::Read;
#[derive(Clone,Debug,PartialEq)] struct Texture(u64);
#[derive(Clone,Debug,PartialEq)] struct Buffer(u64);
pub struct NmbTexture(Texture);pub struct NmbBuffer(Buffer);
#[derive(Clone,Copy,Default,Debug,PartialEq)] struct Choice(u64);
impl Choice {fn from_raw(v:u64)->Result<Self,()>{if v<=3{Ok(Self(v))}else{Err(())}}}
type LoadAction=Choice;type StoreAction=Choice;
type MultisampleDepthResolveFilter=Choice;type MultisampleStencilResolveFilter=Choice;
#[derive(Default)] struct ClearColor([f64;4]);
impl ClearColor{fn new(r:f64,g:f64,b:f64,a:f64)->Self{Self([r,g,b,a])}}
#[derive(Default)] struct Attachment {
 texture:Option<Texture>,resolve_texture:Option<Texture>,level:u64,slice:u64,depth_plane:u64,
 resolve_level:u64,resolve_slice:u64,resolve_depth_plane:u64,load_action:Choice,store_action:Choice,
 clear_color:ClearColor,clear_depth:f64,clear_stencil:u32,depth_resolve_filter:Choice,stencil_resolve_filter:Choice,
}
#[derive(Default)] struct RenderPassDescriptor {
 color_attachments:[Attachment;8],depth_attachment:Attachment,stencil_attachment:Attachment,
 render_target_width:u64,render_target_height:u64,render_target_array_length:u64,default_raster_sample_count:u64,
 visibility_result_buffer:Option<Buffer>,
}
impl RenderPassDescriptor{fn new()->Self{Self::default()}}
'''
for name in ['pub struct NmbPassAttachment {', 'pub struct NmbRenderPassDescriptor {']:
    rust += '#[repr(C)]\n' + function(name)
for name in ["fn get<'a, T>(", "fn optional<'a, T>(", 'fn e<E:', 'fn texture_of(']:
    rust += function(name)
# Extract the live conversion up to encoder creation, supplying only a fake API destination.
body = function('pub extern "C" fn nmb_render_encoder_new(')
body = body[body.index('        let d = get(descriptor)?;'):body.index('        let encoder = get(command_buffer)?;') if '        let encoder = get(command_buffer)?;' in body else body.index('        let encoder = get(command_buffer)?.0')]
rust += 'fn convert(descriptor:*const NmbRenderPassDescriptor)->Result<RenderPassDescriptor,String>{\n' + body + '\nOk(pass)\n}\n'
rust += r'''
fn main(){
 let mut bytes=Vec::new();std::io::stdin().read_to_end(&mut bytes).unwrap();
 assert_eq!(bytes.len(),std::mem::size_of::<NmbRenderPassDescriptor>());
 let mut wire=unsafe{std::ptr::read_unaligned(bytes.as_ptr().cast::<NmbRenderPassDescriptor>())};
 let mut textures:Vec<_>=(0..10).map(|i|NmbTexture(Texture(i+1))).collect();
 let mut resolves:Vec<_>=(0..10).map(|i|NmbTexture(Texture(i+101))).collect();
 let buffer=NmbBuffer(Buffer(42));
 for i in 0..10 {
  let a=if i<8{&mut wire.colors[i]}else if i==8{&mut wire.depth}else{&mut wire.stencil};
  assert_eq!(a.texture as usize,i+1);assert_eq!(a.resolve_texture as usize,i+101);
  a.texture=&mut textures[i];a.resolve_texture=&mut resolves[i];
 }
 assert_eq!(wire.visibility as usize,42);wire.visibility=&buffer;
 let converted=convert(&wire).unwrap();
 drop(textures);drop(resolves); // bridge destination owns cloned handles
 for i in 0..10 {
  let a=if i<8{&converted.color_attachments[i]}else if i==8{&converted.depth_attachment}else{&converted.stencil_attachment};
  let n=i as u64;
  assert_eq!(a.texture,Some(Texture(n+1)));assert_eq!(a.resolve_texture,Some(Texture(n+101)));
  assert_eq!((a.level,a.slice,a.depth_plane),(n+2,n+3,n+4));
  assert_eq!((a.resolve_level,a.resolve_slice,a.resolve_depth_plane),(n+5,n+6,n+7));
  assert_eq!((a.load_action.0,a.store_action.0),(1,2));
  if i<8{assert_eq!(a.clear_color.0,[i as f64,i as f64+0.25,i as f64+0.5,i as f64+0.75]);}
 }
 assert_eq!(converted.depth_attachment.clear_depth,8.0);assert_eq!(converted.stencil_attachment.clear_stencil,9);
 assert_eq!(converted.depth_attachment.depth_resolve_filter.0,0);assert_eq!(converted.stencil_attachment.stencil_resolve_filter.0,1);
 assert_eq!((converted.render_target_width,converted.render_target_height,converted.render_target_array_length,converted.default_raster_sample_count),(320,240,3,4));
 assert_eq!(converted.visibility_result_buffer,Some(Buffer(42)));
 // Missing attachments are valid; unknown filters must refuse the request.
 for a in wire.colors.iter_mut().chain([&mut wire.depth,&mut wire.stencil]){a.texture=std::ptr::null_mut();a.resolve_texture=std::ptr::null_mut();}
 assert!(convert(&wire).unwrap().color_attachments[0].resolve_texture.is_none());
 wire.depth.resolve_filter=99;assert!(convert(&wire).is_err());wire.depth.resolve_filter=0;
 wire.stencil.resolve_filter=99;assert!(convert(&wire).is_err());
 assert!(convert(std::ptr::null()).is_err());
 println!("PASS: actual C/Rust render-pass ABI and conversion retains resolve handles, indices, filters, clears and visibility; no GPU");
}
'''
with tempfile.TemporaryDirectory(prefix='houji-render-pass-') as temporary:
    tmp = Path(temporary)
    for ext, unit, compiler in [('cpp', cpp, ['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined']),
                                ('rs', rust, ['rustc', '--edition=2021', '-Dwarnings'])]:
        source = tmp / ('pass.' + ext)
        source.write_text(unit)
        subprocess.run([*compiler, str(source), '-o', str(tmp / ext)], check=True)
    subprocess.run([str(tmp / 'rs')], input=subprocess.check_output([str(tmp / 'cpp')]), check=True, timeout=10)
