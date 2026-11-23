# Resource and scope-barrier forwarding

This consumer adapter uses metal2vulkan `0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35`.
The bridge forwards compute/render resource residency and scope barriers to the
runtime instead of silently accepting them. Only native buffer and texture
handles are accepted. Unknown handles, enum values and encoder kinds fail the
command buffer through the existing frontend error path.

Declared resources are retained for the command buffer. Imported IOSurface
textures also use the existing surface cache-acquisition path. Completion,
frame retirement and GPU fence handling are unchanged.

The `A residency` telemetry reports compute/render declarations, compute/render
scope barriers and bridge refusals. These counts establish whether a workload
uses the changed calls. They do not establish visual correctness. In particular,
a scope barrier on the existing serial compute encoder generally adds no
ordering beyond serial dispatches; it must not be reported as a flicker fix
without hardware evidence.

The r201 hardware baseline reached the desktop using the refreshed runtime but
retained flicker, low responsiveness and keyboard clipping. Its display timer
reported 60 Hz and every tick eligible for a copy. The last active 5.025-second
window copied 115 frames, about 22.9 copies/s. This is a CPU presentation count,
not a measured panel refresh rate or GPU-only execution time.
