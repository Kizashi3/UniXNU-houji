#include "HoujiLegacyRequest.h"
#include <array>
#include <cassert>

namespace ABI = HoujiLegacy20H392;
int main()
{
    std::array<unsigned char, 2424> request{};
    auto set = [&](size_t offset, uint32_t value) {
        __builtin_memcpy(request.data() + offset, &value, sizeof(value));
    };
    assert(!ABI::fullFrameRequest(nullptr, 1200, 2670));
    assert(!ABI::fullFrameRequest(request.data(), 1200, 2670));
    set(792, 1);
    set(816, 1200);
    set(820, 2670);
    for (size_t offset : {size_t(17), size_t(81)}) {
        set(offset + 8, 1200);
        set(offset + 12, 2670);
    }
    assert(ABI::fullFrameRequest(request.data(), 1200, 2670));
    for (auto bad : {4U, 3U, 0U, 0x40000001U}) {
        set(792, bad);
        assert(!ABI::fullFrameRequest(request.data(), 1200, 2670));
    }
    set(792, 1);
    set(796, 1);
    assert(!ABI::fullFrameRequest(request.data(), 1200, 2670));
    set(796, 0);
    for (size_t offset : {size_t(17), size_t(81), size_t(804), size_t(808), size_t(812)}) {
        set(offset, 1);
        assert(!ABI::fullFrameRequest(request.data(), 1200, 2670));
        set(offset, 0);
    }
    set(792, 0x80000001U);
    set(796, 0x80000000U);
    set(800, 0xff000000U);
    assert(ABI::fullFrameRequest(request.data(), 1200, 2670));
    set(800, 0xffffffffU);
    assert(!ABI::fullFrameRequest(request.data(), 1200, 2670));
    assert(!ABI::fullFrameRequest(request.data(), 0, 2670));
}
