/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* PMIC GLINK read protocol. Property IDs/units follow the pinned MiCode houji
 * driver; message framing follows UniXNU-sheng. No charger SET operation. */
#ifndef HOUJI_BATTMGR_H
#define HOUJI_BATTMGR_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
enum {
    HoujiBmCapacity, HoujiBmPresent, HoujiBmStatus, HoujiBmUsbOnline,
    HoujiBmVoltage, HoujiBmTemperature, HoujiBmCurrent,
    HoujiBmCharge, HoujiBmFull, HoujiBmDesign, HoujiBmCycles, HoujiBmFields
};
#define HOUJI_BM_REQUIRED ((1u << HoujiBmCapacity) | (1u << HoujiBmPresent) | (1u << HoujiBmStatus) | (1u << HoujiBmUsbOnline))
#define HOUJI_BM_OWNER 32778u
#define HOUJI_BM_REQUEST_BYTES 24u
#define HOUJI_BM_FRESH_MS 15000u
enum {HoujiBmIgnored=0, HoujiBmAnswer=1, HoujiBmCycleDone=2, HoujiBmNotification=4};
typedef struct {
    int32_t value[HoujiBmFields], pending[HoujiBmFields];
    uint32_t valid, pending_valid, cursor;
    uint64_t sampled_ms, pending_first_ms;
    uint8_t active, awaiting;
    uint32_t responses, errors, ignored, timeouts, cycles, notifications;
} HoujiBattmgr;
void houji_battmgr_init(HoujiBattmgr *b);
/* A new cycle is refused while one is active. Old readings are never mixed
 * with new replies to manufacture a complete cycle. */
int houji_battmgr_begin(HoujiBattmgr *b);
uint32_t houji_battmgr_request(HoujiBattmgr *b, uint8_t out[HOUJI_BM_REQUEST_BYTES]);
/* Register notifications only, without changing charge/current settings. */
uint32_t houji_battmgr_subscribe(uint8_t out[28]);
int houji_battmgr_receive(HoujiBattmgr *b, const uint8_t *data, uint32_t length, uint64_t now_ms);
int houji_battmgr_timeout(HoujiBattmgr *b, uint64_t now_ms);
/* A timed-out optional property must not be requested again in this channel
 * generation: the wire format has no transaction ID for a delayed reply. */
int houji_battmgr_skip_optional(HoujiBattmgr *b, uint64_t now_ms);
void houji_battmgr_disconnect(HoujiBattmgr *b);
int houji_battmgr_fresh(const HoujiBattmgr *b, uint64_t now_ms);
#ifdef __cplusplus
}
#endif
#endif
