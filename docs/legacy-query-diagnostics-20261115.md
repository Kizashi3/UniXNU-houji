# Legacy query diagnostics

The 09:39 capture retains only the end of the boot. It shows an FBSDisplayMode
configuration assertion and APFS ENOSPC, but no retained early Legacy checkpoint.
These are separate observations; neither establishes a single root cause.

The pinned user-client dispatch table at 0x5decb58 routes selector 27 to
0x4c00950, then 0x4bfe704, and finally slot 199. Its output buffer is 3084 bytes.
The original slot at 0x4c1adbc returns Unsupported without writing the buffer.
The meaning of that buffer and its relation to mode configuration are not yet
qualified. Do not synthesize a mode record from its size.

The derived queryBackendRecord override calls the unchanged original slot and
records its return code. The ABI generator binds its qualified base call to
slot 199; static instruction checks cover the complete dispatch chain.

With houji-legacy-diag=1, the existing hardware timer emits a summary every
300 fixed-60-Hz periods. record27 and record27-rc report this query; backend212
counts the previous backend query; frames counts completed CPU presentations.
The counters are atomic across callers and the work loop. Diagnostics are off
by default and do not enable CPU presentation.

The last capture did not preserve early query results. No runtime result for
this change is available. Static ABI qualification passed; no driver/kernel
compilation or image packaging was run for this change.
