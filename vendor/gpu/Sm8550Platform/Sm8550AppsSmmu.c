/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include "Sm8550AppsSmmu.h"
#ifdef KERNEL
#include <sys/errno.h>
#else
#include <errno.h>
#endif

#define S2CR_FAULT (2u << 16)
#define SMR_VALID (1u << 31)

static uint32_t rd(const struct sm8550_apps_smmu_io *io, uint32_t o) {return io->read(io->context, o);}
static void wr(const struct sm8550_apps_smmu_io *io, uint32_t o, uint32_t v) {io->write(io->context, o, v);}

int sm8550_apps_smmu_pick(const struct sm8550_apps_smmu_io *io, const uint16_t *sids, unsigned count, struct sm8550_apps_smmu_domain *d)
{
    if (!io || !io->read || !io->write || !sids || !d || !count || count > SM8550_APPS_SMMU_MAX_STREAMS) return -EINVAL;
    for (unsigned i = 0; i < count; ++i) {
        if (sids[i] > 0x7fff) return -EINVAL;
        for (unsigned j = 0; j < i; ++j) if (sids[i] == sids[j]) return -EINVAL;
    }
    *d = (struct sm8550_apps_smmu_domain){0};
    const uint32_t id0 = rd(io, 0x20), id1 = rd(io, 0x24), id2 = rd(io, 0x28);
    d->id0 = id0; d->id1 = id1; d->id2 = id2;
    const unsigned slots = id0 & 255, banks = id1 & 255, pages = 1u << (((id1 >> 28) & 7) + 1);
    /* stage 1, stream matching, no extended IDs, AArch64 4K tables; 4 KiB register pages */
    if (!(id0 & (1u << 30)) || !(id0 & (1u << 27)) || (id0 & (1u << 8)) || !(id2 & (1u << 12)) || !slots || slots > 128 || banks < 2 ||
        banks > 128 || (id1 >> 31) || (pages + banks) * 4096u > SM8550_APPS_SMMU_SIZE)
        return -ENOTSUP;
    const uint32_t scr0 = rd(io, 0);
    if ((scr0 & 1) || !(scr0 & (1u << 10))) return -ENOTSUP;   /* enabled, unmatched streams fault */
    bool used[128] = {false};
    unsigned found = 0;
    for (unsigned i = 0; i < slots; ++i) {
        const uint32_t smr = rd(io, 0x800 + i * 4), s2cr = rd(io, 0xc00 + i * 4);
        if (!(smr & SMR_VALID)) {
            d->free_slots++;
            if (found < count) d->slots[found++] = i;
            continue;
        }
        if (((s2cr >> 16) & 3) == 0 && (s2cr & 255) < banks) used[s2cr & 255] = true;
        for (unsigned k = 0; k < count; ++k)
            if (!((smr ^ sids[k]) & 0x7fff & ~((smr >> 16) & 0x7fff))) return -EBUSY;
    }
    if (found < count) {d->exhausted = 1; return -ENOSPC;}
    unsigned bank = banks;
    for (unsigned i = 1; i < banks; ++i) {
        if (used[i]) continue;
        d->unused_banks++;
        const unsigned cb = (pages + i) * 4096;
        if (rd(io, 0x1000 + i * 4) || rd(io, 0x1800 + i * 4) || (rd(io, cb) & 1) || (rd(io, cb + 0x58) & 0xc00001feu)) continue;
        bank = i;
        break;
    }
    if (bank == banks) {d->exhausted = 2; return -ENOSPC;}
    unsigned asid = 0;
    for (unsigned candidate = 1; candidate < 256 && !asid; ++candidate) {
        bool taken = false;
        for (unsigned i = 0; i < banks && !taken; ++i) {
            const unsigned cb = (pages + i) * 4096;
            if (!used[i] && !(rd(io, cb) & 1)) continue;
            taken = (rd(io, cb + 0x24) >> 16) == candidate || (rd(io, cb + 0x2c) >> 16) == candidate;
        }
        if (!taken) asid = candidate;
    }
    if (!asid) {d->exhausted = 3; return -ENOSPC;}
    d->bank = bank; d->asid = asid; d->pages = pages; d->count = count;
    for (unsigned k = 0; k < count; ++k) d->sids[k] = sids[k];
    return 0;
}

int sm8550_apps_smmu_route(const struct sm8550_apps_smmu_io *io, struct sm8550_apps_smmu_domain *d)
{
    if (!io || !d || !d->count || d->routed) return -EINVAL;
    for (unsigned k = 0; k < d->count; ++k) {
        const unsigned slot = d->slots[k];
        wr(io, 0xc00 + slot * 4, d->bank);
        if (rd(io, 0xc00 + slot * 4) != d->bank) {d->count = k + 1; sm8550_apps_smmu_unroute(io, d); return -EIO;}
        wr(io, 0x800 + slot * 4, SMR_VALID | d->sids[k]);
        if (rd(io, 0x800 + slot * 4) != (SMR_VALID | d->sids[k])) {d->count = k + 1; sm8550_apps_smmu_unroute(io, d); return -EIO;}
    }
    d->routed = true;
    return 0;
}

void sm8550_apps_smmu_unroute(const struct sm8550_apps_smmu_io *io, struct sm8550_apps_smmu_domain *d)
{
    if (!io || !d) return;
    for (unsigned k = 0; k < d->count; ++k) {
        wr(io, 0xc00 + d->slots[k] * 4, S2CR_FAULT);
        wr(io, 0x800 + d->slots[k] * 4, 0);
    }
    d->routed = false;
}
