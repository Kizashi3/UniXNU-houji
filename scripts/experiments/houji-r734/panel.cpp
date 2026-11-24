#include "HoujiBacklightProtocol.h"

extern "C" uintptr_t map_io(uint64_t, uintptr_t);
extern "C" void unmap_io(uintptr_t, uintptr_t);
extern "C" void sleep_ms(unsigned);
extern "C" void trace(const char *, unsigned, unsigned, unsigned);
extern "C" uint64_t absolute_time();
extern "C" void to_nanoseconds(uint64_t, uint64_t *);
extern "C" void terminate_thread() __attribute__((noreturn));

extern "C" int assert_panel_wait(void *, unsigned);
extern "C" int block_panel_thread(void *);
extern "C" int wake_panel_thread(void *, bool, unsigned);
extern "C" int clear_panel_wait(void *, unsigned);
extern "C" void *current_panel_thread();
extern "C" void *current_process();
extern "C" int platform_process(void *);
extern "C" void process_name(char *, int);
extern "C" int compare_names(const char *, const char *, unsigned long);

struct PanelMailbox {
    unsigned enabled;
    unsigned requested;
    uint64_t wakeAt;
    uint64_t readyAt;
};
extern "C" PanelMailbox panel_mailbox;

namespace {
constexpr uintptr_t kDsi0 = 0x0ae94000;
constexpr uintptr_t kMapSize = 0x4000;

uint32_t read(void *cookie, unsigned reg)
{
    const auto value = static_cast<volatile uint32_t *>(cookie)[reg / 4];
    asm volatile("dmb oshld" ::: "memory");
    return value;
}

void write(void *cookie, unsigned reg, uint32_t value)
{
    asm volatile("dmb oshst" ::: "memory");
    static_cast<volatile uint32_t *>(cookie)[reg / 4] = value;
    asm volatile("dsb osh" ::: "memory");
}

uint64_t now()
{
    uint64_t ns = 0;
    to_nanoseconds(absolute_time(), &ns);
    return ns / 1000;
}

uint32_t displayPacket(bool on)
{
    return 0x80050000u | (on ? 0x29u : 0x28u);
}

int sendDisplay(HoujiDsiCommand &command, bool on)
{
    const uint32_t packet = displayPacket(on);
    if (!command.begin(&packet, 1, now())) {
        return -2;
    }
    int result;
    do {
        sleep_ms(1);
        result = command.poll(now());
    } while (result == 0);
    return result;
}
}

extern "C" void panel_observe(unsigned selector, const unsigned char *arguments)
{
    if (selector != 12 || !arguments ||
        !__atomic_load_n(&panel_mailbox.enabled, __ATOMIC_ACQUIRE)) {
        return;
    }
    const auto *scalars = *reinterpret_cast<const uint64_t *const *>(arguments + 0x20);
    const auto count = *reinterpret_cast<const unsigned *>(arguments + 0x28);
    if (count != 1 || !scalars || scalars[0] > 1) return;

    char name[32];
    process_name(name, sizeof(name));
    if (compare_names(name, "backboardd", sizeof("backboardd")) != 0 ||
        !platform_process(current_process())) {
        return;
    }
    // RequestPowerChange uses 0 for off and 1 for on. Zero in the
    // mailbox means the client has not made a supported request yet.
    const unsigned desired = static_cast<unsigned>(scalars[0]) + 1u;
    const unsigned previous = __atomic_load_n(&panel_mailbox.requested, __ATOMIC_ACQUIRE);
    if (desired == previous) return;
    if (desired == 2) {
        __atomic_store_n(&panel_mailbox.wakeAt, absolute_time(), __ATOMIC_RELEASE);
    }
    __atomic_store_n(&panel_mailbox.requested, desired, __ATOMIC_RELEASE);
    wake_panel_thread(&panel_mailbox.requested, true, 0);
    trace("HOUJI-PANEL: backboardd requested on=%u\n", desired - 1, 0, 0);
}

extern "C" void panel_frame_presented(uint64_t startedAt, uint64_t copiedBytes)
{
    constexpr uint64_t canvasBytes = 1200ull * 2670 * 4;
    if (copiedBytes < canvasBytes ||
        !__atomic_load_n(&panel_mailbox.enabled, __ATOMIC_ACQUIRE) ||
        __atomic_load_n(&panel_mailbox.requested, __ATOMIC_ACQUIRE) != 2) {
        return;
    }
    const uint64_t wakeAt = __atomic_load_n(&panel_mailbox.wakeAt, __ATOMIC_ACQUIRE);
    if (!wakeAt || startedAt <= wakeAt ||
        __atomic_load_n(&panel_mailbox.readyAt, __ATOMIC_ACQUIRE) == wakeAt) {
        return;
    }
    __atomic_store_n(&panel_mailbox.readyAt, wakeAt, __ATOMIC_RELEASE);
    wake_panel_thread(&panel_mailbox.requested, true, 0);
}

extern "C" void panel_probe(void *, int)
{
    const uintptr_t mapped = map_io(kDsi0, kMapSize);
    if (!mapped) {
        trace("HOUJI-PANEL: DSI0 map failed\n", 0, 0, 0);
        terminate_thread();
    }
    auto *registers = reinterpret_cast<void *>(mapped);
    const unsigned revision = read(registers, 0);
    const unsigned control = read(registers, 4);
    const unsigned clock = read(registers, 0x11c);
    trace("HOUJI-PANEL: DSI0 revision=%x control=%x clock=%x\n", revision, control, clock);
    if (revision != 0x20080000u || (control & 5) != 5 || !clock) {
        trace("HOUJI-PANEL: unsupported DSI handoff, skipping writes\n", 0, 0, 0);
        unmap_io(mapped, kMapSize);
        terminate_thread();
    }

    HoujiDsiCommand command = {{registers, read, write}, false, false, 0, 0, 0, 0, 0};
    unsigned handled = 0;
    bool panelOn = true;
    __atomic_store_n(&panel_mailbox.enabled, 1u, __ATOMIC_RELEASE);
    for (;;) {
        // Publish the wait before rereading the mailbox. This avoids
        // sleeping through a request published before thread_block().
        assert_panel_wait(&panel_mailbox.requested, 0);
        const unsigned desired = __atomic_load_n(&panel_mailbox.requested, __ATOMIC_ACQUIRE);
        const bool awaitingFrame = desired == 2 && !panelOn &&
            __atomic_load_n(&panel_mailbox.readyAt, __ATOMIC_ACQUIRE) !=
            __atomic_load_n(&panel_mailbox.wakeAt, __ATOMIC_ACQUIRE);
        if (desired == handled || awaitingFrame) {
            block_panel_thread(nullptr);
            continue;
        }
        clear_panel_wait(current_panel_thread(), 0);
        handled = desired;
        const bool nextOn = desired == 2;
        if (nextOn == panelOn) continue;

        if (nextOn) trace("HOUJI-PANEL: waking after a post-request framebuffer copy\n", 0, 0, 0);
        int result = -2;
        for (unsigned retry = 0; retry < 4 && result == -2; ++retry) {
            if (__atomic_load_n(&panel_mailbox.requested, __ATOMIC_ACQUIRE) != desired) break;
            result = sendDisplay(command, nextOn);
            if (result == -2) sleep_ms(10);
        }
        trace("HOUJI-PANEL: applied on=%u DCS=%x result=%d\n",
              nextOn, nextOn ? 0x29u : 0x28u, result);
        if (result == 1) {
            panelOn = nextOn;
        } else if (command.failed) {
            break;
        }
    }
    __atomic_store_n(&panel_mailbox.enabled, 0u, __ATOMIC_RELEASE);
    unmap_io(mapped, kMapSize);
    terminate_thread();
}
