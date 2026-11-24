#include <stdbool.h>
#include <stdint.h>

extern uintptr_t map_io(uint64_t, uintptr_t);
extern uintptr_t map_ro(uint64_t, uintptr_t, unsigned);
extern void unmap_io(uintptr_t, uintptr_t);
extern void sleep_ms(unsigned);
extern void delay_us(unsigned);
extern bool boot_arg(const char *, void *, int);
extern void *buffer_with_bytes(const void *, unsigned long, unsigned, bool);
extern int start_thread(void (*)(void *, int), void *, void **);
extern void release_thread(void *);
extern void trace(const char *, unsigned, unsigned, unsigned);
extern void panel_probe(void *, int);
extern void terminate_thread(void) __attribute__((noreturn));

enum {
    kCore = 0x0c400000, kConfig = 0x0c42d000, kObserver = 0x0c440000,
    kCoreSize = 0x4000, kConfigBase = 0x0c42c000, kConfigSize = 0x4000, kObserverSize = 0x8000,
    kPonPpid = 0x013, kGpioPpid = 0x18d,
    kPower = 1, kVolumeUp = 2, kVolumeDown = 4,
    kConsumerReport = 2,
    kGuidedSamples = 11000, kPeriodMs = 20
};

static unsigned find_apid(volatile uint32_t *core, volatile uint32_t *config,
                          unsigned apids, unsigned ppid)
{
    unsigned result = apids;
    for (unsigned i = 0; i < apids; ++i) {
        const unsigned map = core[0x2000 / 4 + i];
        if ((map & 0x010fff00) == (0x01000000 | (ppid << 8)) &&
            (config[i] & 7) == 0) {
            if (result != apids) {
                return apids;
            }
            result = i;
        }
    }
    return result;
}

static int read_status(volatile uint32_t *observer, unsigned apid)
{
    volatile uint32_t *channel = observer + 8 * apid;
    // EE0 observer EXT_READL, one byte of INT_RT_STS. No PMIC register writes.
    channel[0] = (1u << 27) | (0x10 << 4);
    __asm__ volatile("dsb sy" ::: "memory");
    for (unsigned i = 0; i < 100; ++i) {
        const unsigned status = channel[2];
        if (status & 1) {
            return (status & 0xe) ? -1 : (int)(channel[6] & 0xff);
        }
        delay_us(2);
    }
    return -2;
}

static unsigned publish_report(void *device, unsigned mask)
{
    const uint8_t report[2] = {kConsumerReport, mask};
    void *buffer = buffer_with_bytes(report, sizeof(report), 0, false);
    if (!buffer) {
        return 0xe00002bdu;
    }
    const uintptr_t *hid_vtable = *(const uintptr_t **)device;
    const uintptr_t *buffer_vtable = *(const uintptr_t **)buffer;
    unsigned (*handle_report)(void *, void *, unsigned, unsigned) =
        (void *)hid_vtable[0x5a8 / 8];
    void (*release_buffer)(void *) = (void *)buffer_vtable[0x28 / 8];
    const unsigned status = handle_report(device, buffer, 0, 0);
    release_buffer(buffer);
    return status;
}

static void sample_keys(void *device, int wait_result)
{
    (void)wait_result;
    sleep_ms(20000);
    uintptr_t core = map_ro(kCore, kCoreSize, 1);
    uintptr_t config = map_ro(kConfigBase, kConfigSize, 1);
    uintptr_t observer = 0;
    if (!core || !config) {
        trace("HOUJI-PMICBTN: core/config mapping failed\n", 0, 0, 0);
        goto cleanup;
    }
    volatile uint32_t *hw = (void *)core;
    const unsigned version = hw[0];
    const unsigned apids = hw[1] & 0x7ff;
    if (version < 0x70000000u || version >= 0x80000000u || apids == 0 || apids > 1024) {
        trace("HOUJI-PMICBTN: unexpected arbiter version=%x apids=%u\n", version, apids, 0);
        goto cleanup;
    }
    volatile uint32_t *mapping = (void *)(config + kConfig - kConfigBase);
    const unsigned pon = find_apid(hw, mapping, apids, kPonPpid);
    const unsigned gpio = find_apid(hw, mapping, apids, kGpioPpid);
    trace("HOUJI-PMICBTN: count=%u pon-apid=%u gpio-apid=%u\n", apids, pon, gpio);
    if (pon == apids || gpio == apids) {
        goto cleanup;
    }
    observer = map_io(kObserver, kObserverSize);
    if (!observer) {
        trace("HOUJI-PMICBTN: observer mapping failed\n", 0, 0, 0);
        goto cleanup;
    }
    unsigned previous = 0, repeats = 0, reported = 0;
    bool armed = false;
    for (unsigned i = 0; i < kGuidedSamples; ++i) {
        const int pon_status = read_status((void *)observer, pon);
        const int gpio_status = pon_status < 0 ? -3 : read_status((void *)observer, gpio);
        if (pon_status < 0 || gpio_status < 0) {
            trace("HOUJI-PMICBTN: observer error pon=%d gpio=%d\n", pon_status, gpio_status, 0);
            break;
        }
        const unsigned state = ((pon_status & 0x80) ? kPower : 0) |
            ((gpio_status & 1) ? 0 : kVolumeUp) |
            ((pon_status & 0x40) ? kVolumeDown : 0);
        if (previous != state) {
            previous = state;
            repeats = 0;
        } else if (repeats < 2) {
            ++repeats;
        }
        if (repeats == 2) {
            if (!armed && state == 0) {
                armed = true;
                trace("HOUJI-PMICBTN: ready, kPower=1 kVolumeUp=2 kVolumeDown=4\n", 0, 0, 0);
            }
            if (armed && reported != state) {
                const unsigned status = publish_report(device, state);
                trace("HOUJI-PMICBTN: old=%x new=%x HID-return=%x\n", reported, state, status);
                if (status != 0) {
                    break;
                }
                reported = state;
            }
        }
        sleep_ms(kPeriodMs);
    }
    if (reported && publish_report(device, 0) != 0) {
        trace("HOUJI-PMICBTN: final key release failed\n", 0, 0, 0);
    }
cleanup:
    if (observer) unmap_io(observer, kObserverSize);
    if (config) unmap_io(config, kConfigSize);
    if (core) unmap_io(core, kCoreSize);
    trace("HOUJI-PMICBTN: sampling ended\n", 0, 0, 0);
    terminate_thread();
}

__attribute__((section(".text.keys_start")))
void panel_probe_start(void);

void keys_start(void *device)
{
    panel_probe_start();
    unsigned enabled = 0;
    if (!boot_arg("houji-pmic-buttons", &enabled, sizeof(enabled)) || enabled != 1) {
        return;
    }
    void *thread = 0;
    const int result = start_thread(sample_keys, device, &thread);
    trace("HOUJI-PMICBTN: thread=%d\n", result, 0, 0);
    if (result == 0 && thread) {
        release_thread(thread);
    }
}



void panel_probe_start(void)
{
    unsigned enabled = 0;
    if (!boot_arg("houji-panel-power", &enabled, sizeof(enabled)) || enabled != 1) {
        return;
    }
    void *thread = 0;
    const int result = start_thread(panel_probe, 0, &thread);
    trace("HOUJI-PANEL: probe thread=%d\n", result, 0, 0);
    if (result == 0 && thread) {
        release_thread(thread);
    }
}
