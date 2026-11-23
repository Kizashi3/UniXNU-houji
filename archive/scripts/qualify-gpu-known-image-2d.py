#!/usr/bin/env python3
"""Offline qualification, never a driver/device operation.

Compile the unchanged selected Mesa functions and same-pin generated packers.
Minimal host objects replace Vulkan lifetime/bookkeeping; every selected device
property/magic value comes from the generated FD750 record. Fixed RGBA8 format
helpers select the audited linear UNORM8 branch. Border storage is an owned
zero BO, autotune/preemption latency instrumentation and debug stomps are off.
This is a controlled CP_BLIT probe, not byte equivalence to VkCmdClearColorImage
on A750 (the default API branch can use generic event clear instead).
"""
from pathlib import Path
import argparse, hashlib, re, subprocess, json, tempfile
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mesa-source',type=Path,required=True)
parser.add_argument('--mesa-build-freedreno',type=Path,required=True)
args=parser.parse_args()
S=args.mesa_source; B=args.mesa_build_freedreno
PIN='85fda3b36405bcaea8bffc64aa4f2651dc90770d'
if subprocess.check_output(['git','-C',str(S),'rev-parse','HEAD'],text=True).strip()!=PIN:
 raise SystemExit('Mesa source HEAD differs from the fixed qualification commit')
plan=json.loads((Path(__file__).resolve().parents[1]/'native/gpu/known-image-2d-source-plan.json').read_text())
for item in plan['sources']:
 if hashlib.sha256((S/item['path']).read_bytes()).hexdigest()!=item['sha256']:
  raise SystemExit('Changed pinned input: '+item['path'])

for item in plan['cold_context_candidate']['generated_inputs']:
 if hashlib.sha256((B/item['path']).read_bytes()).hexdigest()!=item['sha256']:
  raise SystemExit('Changed pinned generated input: '+item['path'])
cs=(S/'src/freedreno/vulkan/tu_cs.h').read_text();cb=(S/'src/freedreno/vulkan/tu_cmd_buffer.cc').read_text()
def fn(text,name,template=True):
 pos=text.index('\n'+name+'(');start=text.rfind('template <chip CHIP>',0,pos) if template else text.rfind('\n',0,pos)+1
 b=text.index('{',pos);n=1;i=b+1
 while n:
  if text[i]=='{':n+=1
  if text[i]=='}':n-=1
  i+=1
 return text[start:i]
def body(text,start,end):return text[text.index(start):text.index(end)]
devices=(B/'common/freedreno_devices.h').read_text()
target=re.search(r'\{ \{0, 0x43051401\}, "FD750", &(__info\d+) \}',devices).group(1)
info=re.search(r'static const struct fd_dev_info '+target+r' = (.*?);',devices).group(1)
assert '.num_ccu=6,' in info and '.has_generic_clear=True,' in info
assert '.magic={.RB_DBG_ECO_CNTL=1,.RB_DBG_ECO_CNTL_blit=1,.RB_RBP_CNTL=0,}' in info
props=re.search(r'\.props=\{(.*?)\},\.magic=',info).group(1)
magic=re.search(r'\.magic_raw=\{(.*)\},',info).group(1)
decl=''.join(('unsigned ' if k=='gmem_ccu_color_cache_fraction' else 'bool ')+k+';' for k in ['blit_wfi_quirk','is_a702','has_gmem_fast_clear','supports_linear_mipmap_threshold_in_blocks','enable_tp_ubwc_flag_hint','has_eolm_eogm','has_attachment_shading_rate','has_early_preamble','has_gmem_vpc_attr_buf','gmem_ccu_color_cache_fraction','concurrent_resolve','cmdbuf_start_a725_quirk'])
prop_init=','.join('.'+k+'='+v.replace('True','1').replace('False','0') for k,v in re.findall(r'\.(\w+)=([^,]+)',props) if k in decl)
prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <bit>
#include <type_traits>
#include <iterator>

#define CONCAT2(a,b) a##b
#define ALWAYS_INLINE inline
#define chip_range_support chip CHIP, typename Enable = void
#define chip_range(range) CHIP, typename std::enable_if<(range)>::type
constexpr uint32_t fui(float f){return std::bit_cast<uint32_t>(f);}
struct tu_reg_value {uint32_t reg;uint64_t value;bool is_address;};
#define fd_reg_pair tu_reg_value
#define TU_CS_H
#include "adreno_pm4.xml.h"
#include "adreno_common.xml.h"
#include "a6xx_enums.xml.h"
#include "a7xx_enums.xml.h"
#include "a6xx.xml.h"
#include "a6xx-pack.xml.h"
#include "adreno_pm4.xml.h"
#include "adreno-pm4-pack.xml.h"
#include "freedreno_pm4.h"
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define STATIC_ASSERT(x) static_assert(x)
#define TU_DEBUG(x) 0
#define ASSERTED
#define TU_COND_EXEC_STACK_SIZE 8
#define TU_CS_MODE_GROW 1
struct tu_device;
struct tu_pkt;
struct tu_cs {tu_device*device;uint32_t words[2048],*cur,*end;unsigned cond_stack_depth=0,mode=0;uint32_t cond_flags[8],*cond_dwords[8];tu_pkt*pkt=nullptr;};
void init(tu_cs*cs){cs->cur=cs->words;cs->end=cs->words+2048;}
void tu_cs_reserve(tu_cs*cs,unsigned n){assert(cs->cur+n<=cs->end);}
void tu_cs_emit(tu_cs*cs,uint32_t w){assert(cs->cur<cs->end);*cs->cur++=w;}
void tu_cs_emit_array(tu_cs*cs,const uint32_t*p,unsigned n){for(unsigned i=0;i<n;i++)tu_cs_emit(cs,p[i]);}
void tu_cs_emit_pkt7(tu_cs*cs,enum adreno_pm4_type3_packets op,unsigned n){tu_cs_emit(cs,pm4_pkt7_hdr(op,n));}
void tu_cs_emit_pkt4(tu_cs*cs,unsigned reg,unsigned n){tu_cs_emit(cs,pm4_pkt4_hdr(reg,n));}
uint64_t tu_cs_get_cur_iova(tu_cs*cs){return 0x62084000+(cs->cur-cs->words)*4;}
'''
prefix+=body(cs,'#define __assert_eq','#define tu_cs_emit_regs')
prefix+=body(cs,'#define tu_cs_emit_regs','/**\n * Helper base class')
prefix+=body(cs,'struct tu_pkt {','#define with_crb')
for name in ['tu_cs_emit_wfi','tu_cs_emit_qw','tu_cs_emit_write_reg','tu_cond_exec_start','tu_cond_exec_end','tu7_thread_control','tu7_set_pred_mask']:
 prefix+='\n'+fn(cs,name,False)+'\n'
prefix+=r'''
struct gpu_props {PROPDECL};
struct gpu_info {gpu_props props;struct{uint32_t reg,value;}magic_raw[128];struct{unsigned RB_DBG_ECO_CNTL,RB_RBP_CNTL,RB_DBG_ECO_CNTL_blit;}magic;};
struct fd6_gmem_config {unsigned color_ccu_offset,depth_ccu_offset,vpc_attr_buf_size,vpc_attr_buf_offset,vpc_pos_buf_size,vpc_pos_buf_offset,vpc_bv_pos_buf_size,vpc_bv_pos_buf_offset,depth_cache_fraction,color_cache_fraction;};
struct tu_physical_device {gpu_info*info;fd6_gmem_config config_gmem,config_sysmem;};
struct tu_bo {uint64_t iova;unsigned size;};
struct tu_cs_entry {tu_bo*bo;unsigned size,offset;};
struct autotune {bool emit_preempt_latency_tracking_setup(void*,tu_cs*){return false;}};
struct tu_device {tu_physical_device*physical_device;struct{struct{struct{bool use_tex_coord_round_nearest_even_mode;}misc;}drirc;}*instance;tu_bo*global_bo;tu_cs_entry bin_preamble_entry,bin_preamble_bv_entry,switch_back_amble_entry,switch_away_amble_entry,cmdbuf_start_a725_quirk_entry;void*dbg_cmdbuf_stomp_cs=nullptr;void*dbg_renderpass_stomp_cs=nullptr;autotune*autotune;};
struct tu_vis_stream_patchpoint {uint32_t*data;uint64_t iova;};
struct tu_cb_control_point {unsigned type;uint32_t*patchpoint;uint32_t patch_value,original_value;};
enum {TU_CMD_CCU_SYSMEM=1,TU_CMD_FLAG_WAIT_FOR_IDLE=1,TU_CMD_FLAG_CACHE_INVALIDATE=2,TU_CMD_DIRTY_DRAW_STATE=1,TU_CB_CONTROL_TYPE_PATCHPOINT=1,TU_PREDICATE_VTX_STATS_RUNNING=3,TU_PREDICATE_VTX_STATS_NOT_RUNNING=4,VK_COMMAND_BUFFER_USAGE_SIMULTANEOUS_USE_BIT=1};
struct tu_cmd_buffer {tu_device*device;struct{struct{unsigned pending_flush_bits;}cache;unsigned ccu_state,dirty;bool pass;}state;unsigned usage_flags=0;tu_vis_stream_patchpoint vis_stream_count_patchpoint;unsigned cb_control_points;};
#define util_dynarray_append(...) ((void)0)
#define gb_offset(x) 0
template<chip C>struct TU_TESS{static const unsigned PARAM_SIZE=128*1024,FACTOR_SIZE=8*1024;};
void tu_cs_emit_call(tu_cs*,void*){assert(false);}
void tu_cs_set_writeable(tu_cs*,bool){}
void tu_cs_sanity_check(tu_cs*cs){assert(!cs->cond_stack_depth && !cs->pkt);}
void tu_cs_emit_ib(tu_cs*,tu_cs_entry*){assert(false);}
uint64_t global_iova(tu_cmd_buffer*,unsigned){assert(false);return 0;}
enum {seqno_dummy=0};
'''.replace('PROPDECL',decl)
vrs=(S/'src/freedreno/common/freedreno_vrs.h').read_text()
prefix+=body(vrs,'enum fd_shading_rate {','/* The value provided to the FS')
prefix+=fn(vrs,'fd_gras_shading_rate_lut',False)+'\n'
events=(S/'src/freedreno/common/freedreno_gpu_event.h').read_text()
prefix+=body(events,'enum fd_gpu_event :','#endif')
for name in ['tu_emit_raw_event_write','tu_emit_event_write','emit_vpc_attr_buf','emit_rb_ccu_cntl','tu7_emit_tile_render_begin_regs','tu6_init_static_regs','tu_init_hw_rp','tu_emit_bin_preamble','tu_init_hw']:
 prefix+='\n'+fn(cb,name)+'\n'
prefix+='\n'+fn(cb,'tu_disable_draw_states',False).replace(fn(cb,'tu_disable_draw_states',False).split('{')[0],'void tu_disable_draw_states(tu_cmd_buffer *cmd,tu_cs *cs)')+'\n'
# These declarations precede the extracted definitions that call them.
prefix=prefix.replace('template <chip CHIP>\nstatic void\ntu_init_hw(', 'void tu_disable_draw_states(tu_cmd_buffer*,tu_cs*);\nvoid tu7_set_thread_br_patchpoint(tu_cmd_buffer*,tu_cs*,bool);\ntemplate <chip CHIP>\nstatic void\ntu_init_hw(')
prefix+='\n'+fn(cb,'tu7_set_thread_br_patchpoint',False).replace(fn(cb,'tu7_set_thread_br_patchpoint',False).split('{')[0],'void tu7_set_thread_br_patchpoint(tu_cmd_buffer *cmd,tu_cs *cs,bool force_disable_cb)')+'\n'
blit=(S/'src/freedreno/vulkan/tu_clear_blit.cc').read_text()
prefix+=r'''
enum pipe_format{PIPE_FORMAT_R8G8B8A8_UNORM,PIPE_FORMAT_Z24_UNORM_S8_UINT,PIPE_FORMAT_R11G11B10_FLOAT};
typedef unsigned VkImageAspectFlags;enum{VK_IMAGE_ASPECT_DEPTH_BIT=1,VK_IMAGE_ASPECT_STENCIL_BIT=2};
struct VkOffset2D{int32_t x,y;};struct VkExtent2D{uint32_t width,height;};static const VkOffset2D blt_no_coord={-1,-1};
/* Fixed linear RGBA8 selected format; fd6_format_table.c maps it to 0x30. */
template<chip C> a6xx_format blit_base_format(pipe_format f,bool ubwc,bool){assert(f==PIPE_FORMAT_R8G8B8A8_UNORM && !ubwc);return FMT6_8_8_8_8_UNORM;}
void fixup_dst_format(pipe_format src,pipe_format*dst,a6xx_format*f){assert(src==PIPE_FORMAT_R8G8B8A8_UNORM && *dst==src && *f==FMT6_8_8_8_8_UNORM);}
a6xx_2d_ifmt format_to_ifmt(pipe_format f){assert(f==PIPE_FORMAT_R8G8B8A8_UNORM);return R2D_UNORM8;}
bool util_format_is_srgb(pipe_format f){assert(f==PIPE_FORMAT_R8G8B8A8_UNORM);return false;}
bool util_format_is_pure_uint(pipe_format){return false;}bool util_format_is_pure_sint(pipe_format){return false;}bool util_format_is_float16(pipe_format){return false;}
'''
for name in ['r2d_setup_common','r2d_coords']:prefix+='\n'+fn(blit,name)+'\n'
prefix+='\n'+fn(blit,'r2d_run',False)+'\n'
prefix+='''
int main(){
 gpu_info info={.props={PROPINIT},.magic_raw={MAGIC},.magic={1,0,1}};
 tu_physical_device phys={.info=&info,.config_gmem={.color_ccu_offset=0x2ac000,.vpc_attr_buf_size=0xc000,.vpc_attr_buf_offset=0x2b8000},.config_sysmem={.color_ccu_offset=0x180000,.vpc_attr_buf_size=0x20000,.vpc_attr_buf_offset=0x1e0000}};
 tu_device dev={.physical_device=&phys};
 std::remove_reference_t<decltype(*dev.instance)> instance={};dev.instance=&instance;
 tu_bo border={0x62081000,4096},brbo={0x62082000,4096},bvbo={0x62083000,4096};dev.global_bo=&border;
 struct autotune tune;dev.autotune=&tune;
 tu_cs br={},bv={},maincs={};init(&br);init(&bv);init(&maincs);
 tu_emit_bin_preamble<A7XX>(&dev,&br,false);tu_emit_bin_preamble<A7XX>(&dev,&bv,true);
 dev.bin_preamble_entry={&brbo,unsigned((br.cur-br.words)*4),0};dev.bin_preamble_bv_entry={&bvbo,unsigned((bv.cur-bv.words)*4),0};
 tu_cmd_buffer cmd={.device=&dev};tu_init_hw<A7XX>(&cmd,&maincs);
 tu_cs bodycs={};init(&bodycs);
 r2d_setup_common<A7XX>(&cmd,&bodycs,PIPE_FORMAT_R8G8B8A8_UNORM,PIPE_FORMAT_R8G8B8A8_UNORM,0,0,true,false,false);
 tu_cs_emit_pkt4(&bodycs,REG_A6XX_RB_A2D_CLEAR_COLOR_DW0,4);tu_cs_emit(&bodycs,255);tu_cs_emit(&bodycs,0);tu_cs_emit(&bodycs,0);tu_cs_emit(&bodycs,255);
 tu_cs_emit_regs(&bodycs,A6XX_RB_A2D_DEST_BUFFER_INFO(.color_format=FMT6_8_8_8_8_UNORM),A6XX_RB_A2D_DEST_BUFFER_BASE(.qword=0x62085000),A6XX_RB_A2D_DEST_BUFFER_PITCH(128));
 tu_cs_emit_regs(&bodycs,A6XX_RB_A2D_DEST_FLAG_BUFFER_BASE(.qword=0),A6XX_RB_A2D_DEST_FLAG_BUFFER_PITCH());
 r2d_coords<A7XX>(&cmd,&bodycs,{0,0},blt_no_coord,{32,32});r2d_run(&cmd,&bodycs);
 tu_emit_event_write<A7XX>(&cmd,&bodycs,FD_CCU_CLEAN_COLOR);tu_emit_event_write<A7XX>(&cmd,&bodycs,FD_CACHE_CLEAN);tu_cs_emit_wfi(&bodycs);
 tu_cs ib={};init(&ib);tu_cs_emit_pkt7(&ib,CP_INDIRECT_BUFFER,3);tu_cs_emit_qw(&ib,0x62084000);tu_cs_emit(&ib,unsigned(maincs.cur-maincs.words+bodycs.cur-bodycs.words));
 const char*names[]={"br","bv","main","body","ib"};tu_cs*streams[]={&br,&bv,&maincs,&bodycs,&ib};
 printf("{");for(int n=0;n<5;n++){printf("%s\\"%s\\":[",n?",":"",names[n]);for(auto*q=streams[n]->words;q<streams[n]->cur;q++)printf("%s%u",q==streams[n]->words?"":",",*q);printf("]");}printf("}\\n");
}
'''.replace('PROPINIT',prop_init).replace('MAGIC',magic)
with tempfile.TemporaryDirectory(prefix='houji-2d-source-') as td:
 cpp=Path(td)/'source.cc';exe=Path(td)/'source';cpp.write_text(prefix)
 subprocess.run(['clang++','-std=c++20','-fsanitize=address,undefined','-fno-omit-frame-pointer','-Wno-c++11-narrowing','-Wno-array-bounds','-Wno-c99-designator','-Wno-reorder-init-list','-I',str(B/'registers/adreno'),'-I',str(B/'registers'),'-I',str(S/'src/freedreno/common'),str(cpp),'-o',str(exe)],check=True)
 streams=json.loads(subprocess.check_output([str(exe)],text=True))
 print(json.dumps(streams,separators=(',',':')))
