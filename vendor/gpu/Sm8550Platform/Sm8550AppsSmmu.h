/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* A translating domain on the firmware-managed apps SMMU (0x15000000) for masters with several stream IDs: a free context bank, an
 * ASID no enabled bank uses and one free stream-match slot per SID, chosen by the rules Sm8550QupDma.c applies on this board, and the
 * stream routes to the bank once the caller has programmed and enabled it (ArmSmmu4KProgramDisabledContext). Page tables are the
 * caller's (ArmSmmu4KLive). The caller holds sm8550_apps_smmu_lock from the pick through the route, and the master stays idle. */
#ifndef SM8550_APPS_SMMU_H
#define SM8550_APPS_SMMU_H
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define SM8550_APPS_SMMU_BASE 0x15000000ULL
/* sm8550.dtsi apps_smmu reg: 2 x 128 register pages of 4 KiB, the size the SMMU architecture defines (the banks implemented end at
 * 0xd0000) */
#define SM8550_APPS_SMMU_SIZE 0x00100000ULL
#define SM8550_APPS_SMMU_MAX_STREAMS 8u

struct sm8550_apps_smmu_io {
    void *context;
    uint32_t (*read)(void *context, uint32_t offset);
    void (*write)(void *context, uint32_t offset, uint32_t value);   /* completes the store */
};
struct sm8550_apps_smmu_domain {
    unsigned bank, asid, pages, count;
    unsigned slots[SM8550_APPS_SMMU_MAX_STREAMS];
    uint16_t sids[SM8550_APPS_SMMU_MAX_STREAMS];
    uint32_t id0, id1, id2;
    /* exhausted: 1 stream slots, 2 context banks, 3 ASIDs */
    unsigned free_slots, unused_banks, exhausted;
    bool routed;
};
/* Chooses the bank, ASID and slots. Errno-style: -EINVAL arguments, -ENOTSUP an SMMU this does not drive, -EBUSY a SID already routed,
 * -ENOSPC nothing free. Nothing is written. */
int sm8550_apps_smmu_pick(const struct sm8550_apps_smmu_io *, const uint16_t *sids, unsigned count, struct sm8550_apps_smmu_domain *);
/* Routes every SID to the bank (S2CR before SMR, each read back); on a mismatch the slots written so far fault again. */
int sm8550_apps_smmu_route(const struct sm8550_apps_smmu_io *, struct sm8550_apps_smmu_domain *);
/* The SIDs fault again and their slots are free (S2CR fault type, SMR invalid). The bank is the caller's to disable. */
void sm8550_apps_smmu_unroute(const struct sm8550_apps_smmu_io *, struct sm8550_apps_smmu_domain *);
#ifdef __cplusplus
}
#endif
#endif
