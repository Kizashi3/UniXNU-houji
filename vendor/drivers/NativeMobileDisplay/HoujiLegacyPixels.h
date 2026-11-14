#pragma once
#include <stddef.h>
#include <stdint.h>

namespace HoujiLegacy20H392 {
inline bool pixelExtent(uint64_t bytes, uint64_t stride, uint32_t width, uint32_t height)
{
    if (!width || !height || width > 16384 || height > 16384 ||
        stride < static_cast<uint64_t>(width) * 4 || (stride & 3))
        return false;
    const uint64_t row = static_cast<uint64_t>(width) * 4;
    return height - 1 <= (UINT64_MAX - row) / stride &&
        static_cast<uint64_t>(height - 1) * stride + row <= bytes;
}

inline bool pixelAddress(const void *base, uint64_t bytes)
{
    const uintptr_t address = reinterpret_cast<uintptr_t>(base);
    return address && !(address & 3) && bytes <= UINTPTR_MAX - address;
}

inline bool copyBgra(volatile void *destination, uint64_t destinationBytes,
    uint64_t destinationStride, const void *source, uint64_t sourceBytes,
    uint64_t sourceOffset, uint64_t sourceStride, uint32_t width, uint32_t height)
{
    auto dst = reinterpret_cast<uintptr_t>(destination);
    if (!pixelAddress(const_cast<const void *>(destination), destinationBytes) ||
        !pixelAddress(source, sourceBytes) || sourceOffset > sourceBytes ||
        (sourceOffset & 3) || !pixelExtent(destinationBytes, destinationStride, width, height) ||
        !pixelExtent(sourceBytes - sourceOffset, sourceStride, width, height))
        return false;
    const auto src = reinterpret_cast<uintptr_t>(source) + sourceOffset;
    const uint64_t span = static_cast<uint64_t>(height - 1) * sourceStride + width * 4ULL;
    const uint64_t dstSpan = static_cast<uint64_t>(height - 1) * destinationStride + width * 4ULL;
    if (dst < src + span && src < dst + dstSpan)
        return false;
    for (uint32_t y = 0; y < height; ++y) {
        auto out = reinterpret_cast<volatile uint32_t *>(dst + y * destinationStride);
        auto in = reinterpret_cast<const unsigned char *>(src + y * sourceStride);
        for (uint32_t x = 0; x < width; ++x) {
            uint32_t value;
            __builtin_memcpy(&value, in + x * 4ULL, sizeof(value));
            out[x] = value;
        }
    }
    return true;
}

inline bool fillBgra(volatile void *destination, uint64_t bytes, uint64_t stride,
    uint32_t width, uint32_t height, uint32_t color)
{
    if (!pixelAddress(const_cast<const void *>(destination), bytes) ||
        !pixelExtent(bytes, stride, width, height))
        return false;
    const auto base = reinterpret_cast<uintptr_t>(destination);
    for (uint32_t y = 0; y < height; ++y) {
        auto out = reinterpret_cast<volatile uint32_t *>(base + y * stride);
        for (uint32_t x = 0; x < width; ++x)
            out[x] = color;
    }
    return true;
}
}
