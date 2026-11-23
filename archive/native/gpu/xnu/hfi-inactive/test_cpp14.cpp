/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include "houji_hfi_inactive.h"
#include <cassert>
#include <type_traits>
static_assert(std::is_standard_layout<HhiCallbacks>::value && std::is_trivial<HhiCallbacks>::value,"C callbacks POD");
static_assert(std::is_standard_layout<HhiSummary>::value && std::is_trivial<HhiSummary>::value,"C summary POD");
static_assert(std::is_standard_layout<HhiRow>::value && std::is_trivial<HhiRow>::value,"C row POD");
static_assert(sizeof(HhiStorage)==HHI_STORAGE_BYTES && alignof(HhiStorage)==HHI_STORAGE_ALIGNMENT,"fixed caller storage");
static int allocate(void *,uint32_t,uint64_t *,void **) {return 1;}
static int validate(void *,uint64_t,void *,uint32_t,uint32_t) {return 1;}
static int publish(void *,const HhiAllocation *) {return 1;}
static int release(void *,uint64_t,void *,uint32_t) {return 1;}
int main() {
    HhiStorage storage{};HhiCallbacks io{HHI_ABI_VERSION,0,nullptr,allocate,validate,publish,release};
    assert(hhi_init(&storage,sizeof storage,&io,sizeof io)==HHI_OK);
    HhiSummary s{};assert(hhi_summary(&storage,sizeof storage,&s,sizeof s)==HHI_OK && s.abi_version==HHI_ABI_VERSION && !s.prepare_called);
    HhiRow row{};assert(hhi_row(&storage,sizeof storage,8,&row,sizeof row)==HHI_OK && row.index==8 && !row.allocated);
    uint32_t code=99;
    assert(hhi_verify_contents(&storage,sizeof storage,nullptr,0,&code)==HHI_ARGUMENT && code==99);
    assert(hhi_actual_state_size()<=sizeof storage && hhi_actual_state_alignment()==alignof(HhiStorage));
}
