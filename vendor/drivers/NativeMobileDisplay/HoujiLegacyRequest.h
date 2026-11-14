#pragma once
#include <stddef.h>
#include <stdint.h>

namespace HoujiLegacy20H392 {
inline uint32_t requestWord(const void *request, size_t offset)
{
    uint32_t value;
    __builtin_memcpy(&value, static_cast<const unsigned char *>(request) + offset, sizeof(value));
    return value;
}

inline bool fullFrameRequest(const void *request, uint32_t width, uint32_t height)
{
    if (!request || !width || !height || width > 16384 || height > 16384)
        return false;
    const uint32_t updated = requestWord(request, 792);
    const uint32_t disabled = requestWord(request, 796);
    if ((updated | disabled) & ~0x8000000fU || disabled & ~updated ||
        (updated & ~disabled) != 1 ||
        ((updated & 0x80000000U) ? (!(disabled & 0x80000000U) ||
                                  requestWord(request, 800) != 0xff000000U)
                               : requestWord(request, 800) != 0))
        return false;
    const size_t rectangles[] = {17, 81};
    for (size_t offset : rectangles) {
        if (requestWord(request, offset) || requestWord(request, offset + 4) ||
            requestWord(request, offset + 8) != width ||
            requestWord(request, offset + 12) != height)
            return false;
    }
    return !requestWord(request, 804) && !requestWord(request, 808) &&
        !requestWord(request, 812) && requestWord(request, 816) == width &&
        requestWord(request, 820) == height;
}
}
