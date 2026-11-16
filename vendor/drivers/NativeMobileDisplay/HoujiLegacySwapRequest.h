#pragma once
#include <stddef.h>
#include <stdint.h>

// 20H392 IOMobileFramebufferSwapEnd carries a 1132 (0x46c) byte request:
//   +0x50  swap sequence
//   +0x54  per-layer surface id, stride 0x60 (layer 0..3)
//   +0x64  per-layer rectangle {x, y, w, h}, same stride
//   +0x104 layer mask
// Only the shape verified against the device binary is read here; every field
// stays inside the caller-provided size.
namespace HoujiLegacy20H392 {
constexpr size_t swapRequestBytes = 0x46c;
constexpr size_t swapRequestLayers = 4;
constexpr size_t swapLayerStride = 0x60;

inline uint32_t swapWord(const void *request, size_t offset, size_t bytes)
{
    if (request == nullptr || offset + 4 > bytes)
        return 0;
    uint32_t value;
    __builtin_memcpy(&value, static_cast<const unsigned char *>(request) + offset, sizeof(value));
    return value;
}

struct SwapLayers {
    uint32_t sequence;
    uint32_t mask;
    uint32_t surfaceId[swapRequestLayers];
    uint32_t rect[swapRequestLayers][4];
    uint32_t enabledCount;
    uint32_t firstLayer;
};

// Returns false when the buffer is too small or names a layer the mask does not enable.
inline bool parseSwapRequest(const void *request, size_t bytes, SwapLayers *out)
{
    if (request == nullptr || out == nullptr || bytes < swapRequestBytes)
        return false;
    SwapLayers view = {};
    view.sequence = swapWord(request, 0x50, bytes);
    view.mask = swapWord(request, 0x104, bytes);
    if (view.mask == 0 || (view.mask & ~((1U << swapRequestLayers) - 1U)))
        return false;
    view.enabledCount = 0;
    view.firstLayer = swapRequestLayers;
    for (size_t layer = 0; layer < swapRequestLayers; ++layer) {
        const size_t idOffset = 0x54 + swapLayerStride * layer;
        const size_t rectOffset = 0x64 + swapLayerStride * layer;
        view.surfaceId[layer] = swapWord(request, idOffset, bytes);
        for (size_t i = 0; i < 4; ++i)
            view.rect[layer][i] = swapWord(request, rectOffset + i * 4, bytes);
        if (view.mask & (1U << layer)) {
            if (view.surfaceId[layer] == 0)
                return false;
            if (view.firstLayer == swapRequestLayers)
                view.firstLayer = static_cast<uint32_t>(layer);
            view.enabledCount++;
        }
    }
    if (view.enabledCount == 0)
        return false;
    *out = view;
    return true;
}
}