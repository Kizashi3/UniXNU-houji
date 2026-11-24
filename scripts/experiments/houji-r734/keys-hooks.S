.section .text.keys_start_hook,"ax"
.global keys_start_hook
keys_start_hook:
    // Native-touch registration just published the retained touchDevice.
    mov x0, x20
    bl keys_start
    adrp x0, native_start_log_page
    b native_start_resume

.section .text.keys_descriptor_hook,"ax"
.global keys_descriptor_hook
keys_descriptor_hook:
    adr x0, combined_descriptor
    mov w1, #COMBINED_DESCRIPTOR_SIZE
    b native_descriptor_resume

.text
.global display_observe_hook
display_observe_hook:
    stp x28, x27, [sp, #-0x40]!
    sub sp, sp, #64
    stp x0, x1, [sp]
    stp x2, x3, [sp, #16]
    stp x4, x5, [sp, #32]
    str x30, [sp, #48]
    mov w0, w1
    mov x1, x2
    bl panel_observe
    ldr x30, [sp, #48]
    ldp x4, x5, [sp, #32]
    ldp x2, x3, [sp, #16]
    ldp x0, x1, [sp]
    add sp, sp, #64
    b display_observe_resume

// Successful AppleCLCD::present, immediately after the final store barrier.
.global present_done_hook
present_done_hook:
    dsb sy
    sub sp, sp, #32
    stp x13, x30, [sp]
    ldur x0, [x29, #-0xb8]
    mov x1, x19
    bl panel_frame_presented
    ldp x13, x30, [sp]
    add sp, sp, #32
    b present_done_resume

.global trace
trace:
    // Darwin arm64 passes variadic arguments on the stack even in the kernel.
    sub sp, sp, #32
    stp x1, x2, [sp]
    stp x3, x30, [sp, #16]
    bl iolog
    ldr x30, [sp, #24]
    add sp, sp, #32
    ret

.section .rodata.descriptor,"a"
combined_descriptor:
    .incbin "descriptor.bin"
combined_descriptor_end:
    .equ COMBINED_DESCRIPTOR_SIZE, combined_descriptor_end - combined_descriptor



.text
.global map_io
map_io:
    mov w2, #3
    b map_ro
.global map_ro
map_ro:
    // io_map(physical, bytes, VM_WIMG_IO, prot, unmappable=true).
    mov w3, w2
    mov w2, #7
    mov w4, #1
    b io_map_impl
