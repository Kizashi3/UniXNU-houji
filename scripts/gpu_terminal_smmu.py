"""Owned PRR marker for the captured SM8650 SMMU; no translation activation.

The pinned kgsl_iommu.c _iommu_context_set_prr writes a zero page's physical
address to global +0x6008/+0x600c before enabling ACTLR.PRR (bit 5).
Caller maps 0x3da4000..0x3da7fff and restores saved configuration only after
its contexts are disabled and TLB invalidations have completed.
"""

PRR_LOW = 0x3da6008
PRR_HIGH = 0x3da600c


def prepare_prr(live, transport, report, write_saved):
    # The marker is global to this SMMU. Refuse to change it under any bank.
    for bank in range(22):
        if live.read(0x3dc0000 + 0x1000 * bank) & 1:
            raise RuntimeError('PRR setup requires all SMMU context banks disabled')
    allocation = transport.allocate(4096, 4096, 0x33f, 0)
    transport.dev(4, allocation['offset'], 4096)
    for at in range(0, 4096, 128):
        if transport.read(allocation['offset'] + at, 32) != [0] * 32:
            raise RuntimeError('PRR marker page is not zero')
    physical = transport.physical(allocation['offset'])
    if not 0 < physical < (1 << 36) or physical & 4095:
        raise RuntimeError('PRR requires an owned aligned 36-bit physical address')
    record = dict(allocation=allocation, physical=hex(physical), bytes=4096,
                  register_low=hex(PRR_LOW), register_high=hex(PRR_HIGH),
                  prepared=False, retained_until_reboot=True)
    report['prr_marker'] = record
    # Use the native physical address, never an IOVA or a page-number shift.
    write_saved(PRR_LOW, physical & 0xffffffff)
    write_saved(PRR_HIGH, physical >> 32)
    record['prepared'] = True
    return allocation
