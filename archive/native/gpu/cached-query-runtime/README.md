# Nonmutating query dispatch

Query, GetStatus, GetDeviceInfo, SetMetadata and GetMetadata access the connection host bookkeeping under the existing lock. GetTimestamp reads the original board-guarded CP counter with the original high-low-high rollover check. These six methods need no drain of unrelated GPU work. The live and ABI checks remain in the original core. All BO, VM, queue, submission, close and fence paths retain their original synchronization, checks and completion requirements. Unknown methods retain the quiesce path. Per-method counters record elapsed time and actual no-drain dispatches.

Sandbox counters observe the original syscall result, including ENOPOLICY, without altering policy registration, authorization or return values. Hardware performance pending r208.
