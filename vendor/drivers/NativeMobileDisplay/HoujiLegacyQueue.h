#pragma once
#include <stddef.h>
#include <stdint.h>

namespace HoujiLegacy20H392 {
static_assert(sizeof(void *) == 8, "20H392 requires 64-bit pointers");
constexpr size_t currentSwap = 4872;
constexpr size_t pendingHead = 4880;
constexpr size_t pendingTail = 4888;
constexpr size_t requestNext = 2408;
constexpr size_t requestPreviousLink = 2416;
constexpr size_t vsyncHead = 4992;
constexpr size_t commandGate = 5040;
constexpr size_t workLoop = 5048;

inline void *loadPointer(const void *object, size_t offset)
{
    void *value;
    __builtin_memcpy(&value, static_cast<const unsigned char *>(object) + offset, sizeof(value));
    return value;
}

inline void storePointer(void *object, size_t offset, const void *value)
{
    __builtin_memcpy(static_cast<unsigned char *>(object) + offset, &value, sizeof(value));
}

// The original workloop gate must remain held through activation and completion.
inline bool activatePendingSwap(void *display, void *request)
{
    if (!display || !request || loadPointer(display, currentSwap) ||
        loadPointer(display, pendingHead) != request)
        return false;
    auto headLink = static_cast<unsigned char *>(display) + pendingHead;
    auto requestLink = static_cast<unsigned char *>(request) + requestNext;
    if (loadPointer(request, requestPreviousLink) != headLink)
        return false;
    void *next = loadPointer(request, requestNext);
    void *tail = loadPointer(display, pendingTail);
    if (!tail)
        return false;
    if (next) {
        if (next == request || tail == requestLink ||
            loadPointer(next, requestPreviousLink) != requestLink)
            return false;
    } else if (tail != requestLink) {
        return false;
    }
    if (next)
        storePointer(next, requestPreviousLink, headLink);
    else
        storePointer(display, pendingTail, headLink);
    storePointer(display, pendingHead, next);
    storePointer(display, currentSwap, request);
    return true;
}
}
