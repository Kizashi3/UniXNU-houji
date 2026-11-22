#pragma once

#include <stdint.h>

struct HoujiTouchContact {
    uint8_t identifier;
    uint16_t x;
    uint16_t y;
};

constexpr unsigned kHoujiTouchContacts = 10;

inline bool decodeHoujiTouchReport(const uint8_t *frame, unsigned size,
    HoujiTouchContact (&contacts)[kHoujiTouchContacts], unsigned &count)
{
    constexpr unsigned headerBytes = 4;
    constexpr unsigned prefixBytes = 18;
    constexpr unsigned objectBytes = 9;
    if (!frame || size < headerBytes + prefixBytes || frame[0] != 0xa5 || frame[1] != 0x11) {
        return false;
    }
    const unsigned payloadBytes = frame[2] | (static_cast<unsigned>(frame[3]) << 8);
    const unsigned active = frame[headerBytes + prefixBytes - 1];
    if (active > kHoujiTouchContacts || payloadBytes != prefixBytes + active * objectBytes ||
        payloadBytes > size - headerBytes) {
        return false;
    }
    uint16_t seen = 0;
    const uint8_t *item = frame + headerBytes + prefixBytes;
    for (unsigned i = 0; i < active; ++i, item += objectBytes) {
        const uint8_t id = item[0] & 0x0f;
        const unsigned bit = 1u << id;
        if (seen & bit) {
            return false;
        }
        seen |= bit;
        contacts[i] = {id, static_cast<uint16_t>(item[1] | (item[2] << 8)),
            static_cast<uint16_t>(item[3] | (item[4] << 8))};
    }
    count = active;
    return true;
}
