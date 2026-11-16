#include "HoujiLegacySwapRequest.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>

namespace ABI = HoujiLegacy20H392;

static void put(uint8_t *buf, size_t off, uint32_t v) { std::memcpy(buf + off, &v, 4); }

int main()
{
    std::vector<uint8_t> req(ABI::swapRequestBytes, 0);
    ABI::SwapLayers view{};

    // Short buffer is refused.
    assert(!ABI::parseSwapRequest(req.data(), ABI::swapRequestBytes - 1, &view));

    // Layer 1 enabled only: id and rect come from the second slot.
    put(req.data(), 0x50, 0x1234);
    put(req.data(), 0x54, 0);              // layer 0 disabled, id may be zero
    put(req.data(), 0x54 + 0x60, 77);      // layer 1 surface id
    put(req.data(), 0x64 + 0x60 + 0, 0);
    put(req.data(), 0x64 + 0x60 + 4, 0);
    put(req.data(), 0x64 + 0x60 + 8, 1200);
    put(req.data(), 0x64 + 0x60 + 12, 2670);
    put(req.data(), 0x104, 0x2);
    assert(ABI::parseSwapRequest(req.data(), req.size(), &view));
    assert(view.sequence == 0x1234);
    assert(view.mask == 0x2);
    assert(view.surfaceId[1] == 77);
    assert(view.rect[1][2] == 1200 && view.rect[1][3] == 2670);
    assert(view.enabledCount == 1 && view.firstLayer == 1);

    // Enabled layer with a zero id is refused.
    put(req.data(), 0x54 + 0x60, 0);
    assert(!ABI::parseSwapRequest(req.data(), req.size(), &view));
    put(req.data(), 0x54 + 0x60, 77);

    // Empty mask and out-of-range mask bits are refused.
    put(req.data(), 0x104, 0);
    assert(!ABI::parseSwapRequest(req.data(), req.size(), &view));
    put(req.data(), 0x104, 0x10);
    assert(!ABI::parseSwapRequest(req.data(), req.size(), &view));

    // All four layers enabled.
    for (size_t layer = 0; layer < 4; ++layer)
        put(req.data(), 0x54 + 0x60 * layer, 100 + layer);
    put(req.data(), 0x104, 0xf);
    assert(ABI::parseSwapRequest(req.data(), req.size(), &view));
    assert(view.enabledCount == 4 && view.firstLayer == 0);
    assert(view.surfaceId[3] == 103);

    std::puts("SWAP_REQUEST_TESTS_OK");
}