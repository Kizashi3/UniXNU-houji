#include "houji_native_full_host_graph.h"
#include "houji_hfi_inactive.h"
#include "houji_stock_native.h"
#include <type_traits>
static_assert(std::is_standard_layout<FhgConfig>::value && std::is_trivial<FhgConfig>::value,"config POD");
static_assert(std::is_standard_layout<FhgRequest>::value && std::is_trivial<FhgRequest>::value,"request POD");
static_assert(std::is_standard_layout<FhgBacking>::value && std::is_trivial<FhgBacking>::value,"backing POD");
static_assert(std::is_standard_layout<FhgOps>::value && std::is_trivial<FhgOps>::value,"ops POD");
static_assert(std::is_standard_layout<FhgSummary>::value && std::is_trivial<FhgSummary>::value,"summary POD");
static_assert(sizeof(FhgStorage)==32768 && alignof(FhgStorage)==16,"independent opaque");
static_assert(HHI_ABI_VERSION==1 && sizeof(HhiStorage)==4096,"old HHI unchanged");
static_assert(HSN_ABI_VERSION==2 && sizeof(HsnStorage)==196608,"old HSN unchanged");
int main(){FhgStorage s{};return sizeof(s)!=32768 || fhg_actual_state_size()>sizeof(s) || fhg_actual_state_alignment()!=16;}
