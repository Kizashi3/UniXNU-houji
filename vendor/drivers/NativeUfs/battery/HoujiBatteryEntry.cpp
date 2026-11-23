#include <IOKit/IOLib.h>
#include <mach/vm_param.h>
#include <mach/vm_types.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#include <stdint.h>

#include "HoujiSpi.h"

extern "C" boolean_t pmap_valid_page(ppnum_t page);
extern "C" int houji_modem_partition(uint64_t *blocks);
extern "C" int houji_adsp_preflight(void);
extern "C" void houji_adsp_run(void);
extern "C" int armcpu_spi_attach(uint32_t intid, bool edge, void (*handler)(void *),
                                 void *context, uint32_t *readback, uint64_t *router);

extern "C" int houji_spi_attach(uint32_t intid, int edge, void (*handler)(void *),
                                void *context, uint32_t *readback, uint64_t *router)
{
    if (edge != 0 && edge != 1) {
        return HoujiSpiArgument;
    }
    return armcpu_spi_attach(intid, edge == 1, handler, context, readback, router);
}

extern "C" void houji_ufs_checkpoint(const char *stage, unsigned stopId)
{
    // The existing houji recovery log worker snapshots the kernel message buffer.
    IOLog("HOUJI-BATTERY: %s stage=%u\n", stage, stopId);
}

namespace {
enum {kReadiness = 1, kPublish = 2};
unsigned started;

bool carveoutUnmanaged(uint64_t start, uint64_t size)
{
    const unsigned pageBytes = 1u << PAGE_SHIFT;
    if ((start & (pageBytes - 1)) || (size & (pageBytes - 1))) {
        return false;
    }
    for (uint64_t address = start; address < start + size; address += pageBytes) {
        if (pmap_valid_page(static_cast<ppnum_t>(address >> PAGE_SHIFT))) {
            IOLog("HOUJI-BATTERY: carveout page owned by XNU %llx\n", address);
            return false;
        }
    }
    return true;
}

void batteryThread(void *argument, wait_result_t)
{
    const auto mode = static_cast<unsigned>(reinterpret_cast<uintptr_t>(argument));
    IOSleep(30000);
    uint64_t modemBlocks = 0;
    if (!houji_modem_partition(&modemBlocks)) {
        IOLog("HOUJI-BATTERY: modem_a unavailable\n");
    } else if (carveoutUnmanaged(0x9de80000, 0x80000) &&
               carveoutUnmanaged(0x9df00000, 0x4680000) &&
               houji_adsp_preflight() && mode == kPublish) {
        houji_adsp_run();
    }
    thread_terminate(current_thread());
}
}

extern "C" void houji_battery_board_start(void)
{
    unsigned enabled = 0;
    if (!PE_parse_boot_argn("houji-battery-mode", &enabled, sizeof(enabled)) ||
        (enabled != kReadiness && enabled != kPublish) ||
        __atomic_exchange_n(&started, 1, __ATOMIC_ACQ_REL)) {
        return;
    }
    thread_t thread = THREAD_NULL;
    const kern_return_t status = kernel_thread_start(batteryThread,
        reinterpret_cast<void *>(static_cast<uintptr_t>(enabled)), &thread);
    if (status == KERN_SUCCESS) {
        thread_deallocate(thread);
    } else {
        __atomic_store_n(&started, 0, __ATOMIC_RELEASE);
        IOLog("HOUJI-BATTERY: worker launch failed 0x%x\n", status);
    }
}
