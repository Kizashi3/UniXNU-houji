#include "HoujiLegacyPixels.h"
#include <array>
#include <cassert>
#include <limits>

namespace ABI = HoujiLegacy20H392;
int main()
{
    alignas(8) std::array<uint32_t, 20> source{};
    alignas(8) std::array<uint32_t, 20> target{};
    for (unsigned i = 0; i < source.size(); ++i)
        source[i] = 0xff000000U | i;
    target.fill(0xdeadbeefU);
    assert(ABI::copyBgra(target.data(), sizeof(target), 24, source.data(),
                        sizeof(source), 8, 20, 3, 3));
    for (unsigned y = 0; y < 3; ++y) {
        for (unsigned x = 0; x < 3; ++x)
            assert(target[y * 6 + x] == source[2 + y * 5 + x]);
        for (unsigned x = 3; x < 6; ++x)
            assert(target[y * 6 + x] == 0xdeadbeefU);
    }
    auto unchanged = target;
    assert(!ABI::copyBgra(target.data(), sizeof(target), 8, source.data(),
                         sizeof(source), 0, 20, 3, 3));
    assert(target == unchanged);
    assert(!ABI::copyBgra(target.data(), sizeof(target), 24, source.data(),
                         59, 8, 20, 3, 3));
    assert(target == unchanged);
    assert(!ABI::copyBgra(target.data(), sizeof(target), 24, source.data(),
                         sizeof(source), 81, 20, 3, 3));
    assert(target == unchanged);
    assert(!ABI::copyBgra(target.data(), sizeof(target), 24, target.data(),
                         sizeof(target), 0, 24, 3, 3));
    assert(target == unchanged);
    assert(!ABI::fillBgra(target.data(), sizeof(target), 24, 0, 3, 0));
    assert(!ABI::pixelExtent(80, UINT64_MAX - 3, 1, 3));
    assert(!ABI::pixelAddress(reinterpret_cast<const void *>(UINTPTR_MAX - 3), 8));
    assert(ABI::fillBgra(target.data(), sizeof(target), 24, 3, 3, 0xff112233));
    for (unsigned y = 0; y < 3; ++y) {
        for (unsigned x = 0; x < 3; ++x)
            assert(target[y * 6 + x] == 0xff112233);
        for (unsigned x = 3; x < 6; ++x)
            assert(target[y * 6 + x] == 0xdeadbeefU);
    }
    assert(ABI::pixelExtent(12, 16, 3, 1));
    assert(!ABI::pixelExtent(11, 16, 3, 1));
    assert(!ABI::pixelExtent(80, 22, 3, 3));
    assert(!ABI::copyBgra(nullptr, 80, 24, source.data(), 80, 0, 20, 3, 3));
    assert(!ABI::copyBgra(target.data(), 80, 24, source.data(), 80, 2, 20, 3, 3));
}
