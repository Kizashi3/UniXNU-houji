//! A process-wide ring of the stages each command buffer passes from its commit to its completion,
//! for a host that asks where the time between them goes ([`read`]): when it was committed, left
//! to the lowering thread, run, recorded, handed to the scheduler and taken in, what held its
//! batches, when each was submitted, and when the completion waiter armed, saw it and finished it.
//! The scheduler's and the waiters' own sleeps and wakes are recorded under id 0 and the queue.
//!
//! - **Bounded.** A record tries one slot lock; a collision drops the record without waiting.
//!   Readers use the same slot lock, so a lap cannot mix fields from different records. Nothing allocates. The ring
//!   keeps the newest [`RING`] records; a reader that falls behind loses the oldest.
//! - **One clock.** The host's uptime clock in nanoseconds (`CLOCK_UPTIME_RAW` on Apple
//!   platforms), the one the frontend's trace and the driver's rings use.
//! - **Off unless asked for.** Records are kept only where the host's environment has
//!   `HOUJI_GPU_TRACE=1` ([`diagnostics`]), read once. The frontend enables it only in an explicit
//!   diagnostic build, in backboardd, and stops it at the file/time budget. Default builds keep no trace.
//! - **Ids.** A command buffer's id is the address of its shared state, alive from its commit to
//!   its completion: records of one id between a commit stage and its completion are one command
//!   buffer's.

use std::sync::OnceLock;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

/// The records the ring keeps.
const RING: usize = 1 << 16;

/// What happened, the record's `stage`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u16)]
pub enum Stage {
    /// `commit` was called (`arg`: 0).
    CommitCall = 1,
    /// The commit was left to wait for the lowering thread's end of its last render encoder.
    CommitQueued = 2,
    /// The commit's own work began (`arg`: 0 at the call, 1 queued, 2 refused).
    CommitRun = 3,
    /// Its segments were recorded or prepared for their host steps (`arg`: segments).
    Prepared = 4,
    /// Its batches were handed to the scheduler (`arg`: batches).
    Handed = 5,
    /// The scheduler took its batches into its order (`arg`: batches).
    Taken = 6,
    /// A look of the scheduler's held one of its batches (`arg`: the reason, `HeldFor` + 1, |
    /// batch index << 8); recorded once per reason and batch.
    Held = 7,
    /// A batch's submission began (`arg`: batch index | last << 15).
    SubmitBegin = 8,
    /// A batch's submission returned (`arg`: 0 submitted, 1 grouped, 2 later, 3 after the group,
    /// 4 failed).
    SubmitEnd = 9,
    /// Its host step began recording on the scheduler's thread (`arg`: batch index).
    StepBegin = 10,
    /// Its host step ended (`arg`: batch index).
    StepEnd = 11,
    /// A completion waiter began waiting for its batch (`arg`: queue | slept first << 8).
    PollArmed = 12,
    /// The waiter's wait for its batch returned (`arg`: queue).
    PollDone = 13,
    /// A completion turn saw it complete (`arg`: queue).
    Seen = 14,
    /// Its completion ran (`arg`: 1 on the waiter, 2 posted to its queue's context).
    Finished = 15,
    /// A step inside a batch's submission ended (`arg`: 1 the scrubs and segments placed, 2 its
    /// waits and signals gathered, 3 the driver's `vkQueueSubmit` returned, 4 the submission's
    /// changes made).
    SubmitStep = 16,
    /// The scheduler's thread went to sleep (id 0, `arg`: slice in ms, | 0x8000 on the GPU).
    SchedulerSleep = 20,
    /// Something woke the scheduler's thread (id 0, `arg`: 0 commit, 1 completion, 2 host).
    SchedulerWake = 21,
    /// The scheduler's thread resumed after its sleep (id 0, `arg`: 1 timed out).
    SchedulerResumed = 22,
    /// The scheduler's thread began a pass (id 0).
    PassBegin = 23,
    /// The scheduler's thread ended a pass (id 0, `arg`: batches submitted, capped).
    PassEnd = 24,
    /// Frontend command buffer created.
    FrontCreated = 30,
    /// Frontend commit entered.
    FrontCommit = 31,
    /// Frontend scheduled callback entered.
    FrontScheduled = 32,
    /// Frontend completion callback entered.
    FrontCompleted = 33,
    /// Measured GPU duration in us, saturated at 65535; absent when unavailable.
    GpuMicros = 34,
    /// Driver submit duration in us, saturated at 65535; absent when unavailable.
    SubmitMicros = 35,
    /// Frontend draw API wall time in us, saturated at 65535.
    DrawMicros = 36,
    /// Frontend encoder end wall time in us, saturated at 65535.
    EndMicros = 37,
    /// Frontend render pass creation wall time in us, saturated at 65535.
    PassMicros = 38,
    /// Draw count, saturated at 65535.
    DrawCount = 39,
    /// A frontend wait began; arg 0 completed, 1 scheduled.
    WaitBegin = 40,
    /// That wait ended, same arg.
    WaitEnd = 41,
}

struct Slot {
    busy: AtomicBool,
    sequence: AtomicU64,
    when: AtomicU64,
    id: AtomicU64,
    /// stage | arg << 16 | sequence << 32: a reader takes the slot only where the sequence is the
    /// one it asked for.
    word: AtomicU64,
}

#[allow(clippy::declare_interior_mutable_const)]
const EMPTY: Slot = Slot {
    busy: AtomicBool::new(false),
    sequence: AtomicU64::new(0),
    when: AtomicU64::new(0),
    id: AtomicU64::new(0),
    word: AtomicU64::new(0),
};
static SLOTS: [Slot; RING] = [EMPTY; RING];
static NEXT: AtomicU64 = AtomicU64::new(1);
static DROPPED: AtomicU64 = AtomicU64::new(0);
static STOPPED: AtomicBool = AtomicBool::new(false);

/// The host's uptime clock in nanoseconds.
pub fn now_nanos() -> u64 {
    #[cfg(any(target_os = "macos", target_os = "ios"))]
    {
        let mut spec = libc::timespec {
            tv_sec: 0,
            tv_nsec: 0,
        };
        // SAFETY: a valid clock id and an owned timespec.
        if unsafe { libc::clock_gettime(libc::CLOCK_UPTIME_RAW, &mut spec) } == 0 {
            return spec.tv_sec as u64 * 1_000_000_000 + spec.tv_nsec as u64;
        }
        0
    }
    #[cfg(not(any(target_os = "macos", target_os = "ios")))]
    {
        crate::gpu_time::host_nanos()
    }
}

/// Whether the host asked for the runtime's diagnostics: `HOUJI_GPU_TRACE=1`, read
/// once.
pub(crate) fn diagnostics() -> bool {
    static ON: OnceLock<bool> = OnceLock::new();
    !STOPPED.load(Ordering::Relaxed)
        && *ON.get_or_init(|| std::env::var("HOUJI_GPU_TRACE").is_ok_and(|v| v == "1"))
}

/// Stop further recording when the frontend reaches its budget or cannot write the trace.
pub fn stop() {
    STOPPED.store(true, Ordering::Relaxed);
}

/// Dropped producers and the next sequence. Reader gaps additionally include lapped slots.
pub fn statistics() -> [u64; 2] {
    [
        DROPPED.load(Ordering::Relaxed),
        NEXT.load(Ordering::Relaxed),
    ]
}

/// Frontend stages only. Unknown values are ignored, never converted to an invalid enum.
pub fn frontend(id: usize, kind: u16, arg: u64) {
    let stage = match kind {
        30 => Stage::FrontCreated,
        31 => Stage::FrontCommit,
        32 => Stage::FrontScheduled,
        33 => Stage::FrontCompleted,
        34 => Stage::GpuMicros,
        35 => Stage::SubmitMicros,
        36 => Stage::DrawMicros,
        37 => Stage::EndMicros,
        38 => Stage::PassMicros,
        39 => Stage::DrawCount,
        40 => Stage::WaitBegin,
        41 => Stage::WaitEnd,
        _ => return,
    };
    mark(id, stage, arg.min(u16::MAX as u64) as u32);
}

/// Record `stage` of `id` with `arg`, now, where the diagnostics are on ([`diagnostics`]).
pub(crate) fn mark(id: usize, stage: Stage, arg: u32) {
    if !diagnostics() {
        return;
    }
    let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
    let slot = &SLOTS[(sequence as usize) & (RING - 1)];
    if slot
        .busy
        .compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
        .is_err()
    {
        DROPPED.fetch_add(1, Ordering::Relaxed);
        return;
    }
    // A preempted producer may resume after a newer producer has already lapped it.
    if slot.sequence.load(Ordering::Relaxed) >= sequence {
        slot.busy.store(false, Ordering::Release);
        DROPPED.fetch_add(1, Ordering::Relaxed);
        return;
    }
    slot.when.store(now_nanos(), Ordering::Relaxed);
    slot.id.store(id as u64, Ordering::Relaxed);
    let word = stage as u64 | ((arg as u64 & 0xffff) << 16) | ((sequence & 0xffff_ffff) << 32);
    slot.word.store(word, Ordering::Relaxed);
    slot.sequence.store(sequence, Ordering::Relaxed);
    slot.busy.store(false, Ordering::Release);
}

/// One record as [`read`] gives it.
#[derive(Clone, Copy, Debug, Default)]
#[repr(C)]
pub struct StageRecord {
    /// Host uptime nanoseconds.
    pub when: u64,
    /// The command buffer's id (0: the scheduler's thread).
    pub id: u64,
    /// Its place among all records.
    pub sequence: u32,
    /// [`Stage`] as its number.
    pub stage: u16,
    /// The stage's argument.
    pub arg: u16,
}

/// The records from sequence `from` on (the oldest kept where `from` fell out of the ring), at most
/// `out.len()`, oldest first: how many, and the sequence to ask for next. Busy, missing and
/// overwritten slots are skipped, never waited for; sequence gaps must be kept in analysis.
pub fn read(from: u64, out: &mut [StageRecord]) -> (usize, u64) {
    let newest = NEXT.load(Ordering::Acquire);
    let mut sequence = from.max(1).max(newest.saturating_sub(RING as u64 - 1024));
    let mut written = 0;
    while sequence < newest && written < out.len() {
        let slot = &SLOTS[(sequence as usize) & (RING - 1)];
        if slot
            .busy
            .compare_exchange(false, true, Ordering::Acquire, Ordering::Relaxed)
            .is_err()
        {
            sequence += 1;
            continue;
        }
        let word = slot.word.load(Ordering::Relaxed);
        if slot.sequence.load(Ordering::Relaxed) == sequence && word & 0xffff != 0 {
            let when = slot.when.load(Ordering::Relaxed);
            let id = slot.id.load(Ordering::Relaxed);
            out[written] = StageRecord {
                when,
                id,
                sequence: sequence as u32,
                stage: (word & 0xffff) as u16,
                arg: ((word >> 16) & 0xffff) as u16,
            };
            written += 1;
        }
        slot.busy.store(false, Ordering::Release);
        sequence += 1;
    }
    (written, sequence)
}
