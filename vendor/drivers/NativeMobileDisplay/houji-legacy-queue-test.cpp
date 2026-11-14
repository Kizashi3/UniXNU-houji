#include "HoujiLegacyQueue.h"
#include <array>
#include <cassert>

namespace ABI = HoujiLegacy20H392;
using Display = std::array<unsigned char, 5728>;
using Request = std::array<unsigned char, 2424>;

int main()
{
    assert(!ABI::activatePendingSwap(nullptr, nullptr));
    for (size_t count = 0; count <= 4; ++count) {
        Display display{};
        std::array<Request, 4> requests{};
        auto headLink = display.data() + ABI::pendingHead;
        ABI::storePointer(display.data(), ABI::pendingHead,
                          count ? requests[0].data() : nullptr);
        ABI::storePointer(display.data(), ABI::pendingTail,
                          count ? requests[count - 1].data() + ABI::requestNext : headLink);
        for (size_t i = 0; i < count; ++i) {
            ABI::storePointer(requests[i].data(), ABI::requestNext,
                              i + 1 < count ? requests[i + 1].data() : nullptr);
            ABI::storePointer(requests[i].data(), ABI::requestPreviousLink,
                              i ? requests[i - 1].data() + ABI::requestNext : headLink);
        }
        Display unchanged = display;
        auto originalRequests = requests;
        assert(!ABI::activatePendingSwap(display.data(), nullptr));
        assert(display == unchanged && requests == originalRequests);
        if (!count) {
            assert(!ABI::activatePendingSwap(display.data(), requests[0].data()));
            assert(display == unchanged);
            continue;
        }
        if (count > 1) {
            assert(!ABI::activatePendingSwap(display.data(), requests[1].data()));
            assert(display == unchanged && requests == originalRequests);
        }
        ABI::storePointer(requests[0].data(), ABI::requestPreviousLink, nullptr);
        Display brokenDisplay = display;
        auto brokenRequests = requests;
        assert(!ABI::activatePendingSwap(display.data(), requests[0].data()));
        assert(display == brokenDisplay && requests == brokenRequests);
        requests = originalRequests;
        if (count > 1) {
            ABI::storePointer(requests[1].data(), ABI::requestPreviousLink, nullptr);
            brokenRequests = requests;
            assert(!ABI::activatePendingSwap(display.data(), requests[0].data()));
            assert(display == brokenDisplay && requests == brokenRequests);
            requests = originalRequests;
        }
        ABI::storePointer(display.data(), ABI::pendingTail, nullptr);
        brokenDisplay = display;
        brokenRequests = requests;
        assert(!ABI::activatePendingSwap(display.data(), requests[0].data()));
        assert(display == brokenDisplay && requests == brokenRequests);
        display = unchanged;
        ABI::storePointer(requests[0].data(), ABI::requestNext, requests[0].data());
        brokenRequests = requests;
        assert(!ABI::activatePendingSwap(display.data(), requests[0].data()));
        assert(display == unchanged && requests == brokenRequests);
        requests = originalRequests;
        ABI::storePointer(display.data(), ABI::pendingTail,
                          requests[0].data() + ABI::requestNext + 1);
        brokenDisplay = display;
        if (count == 1) {
            assert(!ABI::activatePendingSwap(display.data(), requests[0].data()));
            assert(display == brokenDisplay && requests == originalRequests);
        }
        display = unchanged;
        for (size_t i = 0; i < count; ++i) {
            assert(ABI::activatePendingSwap(display.data(), requests[i].data()));
            assert(ABI::loadPointer(display.data(), ABI::currentSwap) == requests[i].data());
            Display busy = display;
            auto busyRequests = requests;
            assert(!ABI::activatePendingSwap(display.data(), requests[i].data()));
            assert(display == busy && requests == busyRequests);
            ABI::storePointer(display.data(), ABI::currentSwap, nullptr);
        }
        assert(!ABI::loadPointer(display.data(), ABI::pendingHead));
        assert(ABI::loadPointer(display.data(), ABI::pendingTail) == headLink);
    }
}
