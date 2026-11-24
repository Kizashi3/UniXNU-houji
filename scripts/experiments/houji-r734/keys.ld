ENTRY(keys_start_hook)
SECTIONS {
    . = 0xfffffff007a6ca50;
    .payload : {
        *(.text.keys_start_hook)
        *(.text.keys_descriptor_hook)
        *(.text .text.*)
        *(.rodata .rodata.str1.1)
        *(.rodata.descriptor)
    }
    ASSERT(SIZEOF(.payload) <= 0x35b0, "payload outside the verified __TEXT_EXEC tail")
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
native_start_resume = 0xfffffff0079cb708;
native_start_log_page = 0xfffffff00713c000;
native_descriptor_resume = 0xfffffff0079caec0;
io_map_impl = 0xfffffff007403990;
unmap_io = 0xfffffff00740f238;
sleep_ms = 0xfffffff0078ac554;
delay_us = 0xfffffff0078ac56c;
iolog = 0xfffffff0078ac57c;
boot_arg = 0xfffffff00796bf74;
buffer_with_bytes = 0xfffffff0078e8084;
start_thread = 0xfffffff0072e61e4;
release_thread = 0xfffffff0072e45bc;
terminate_thread = 0xfffffff0072e4008;


managed_page = 0xfffffff0073f43b0;
absolute_time = 0xfffffff007413d1c;
to_nanoseconds = 0xfffffff00741413c;
display_observe_resume = 0xfffffff00796b028;
panel_mailbox = 0xfffffff0083febb0;
assert_panel_wait = 0xfffffff0072bfd2c;
block_panel_thread = 0xfffffff0072c0570;
wake_panel_thread = 0xfffffff0072c0658;
clear_panel_wait = 0xfffffff0072c0198;
current_panel_thread = 0xfffffff00740de08;
current_process = 0xfffffff00784eff0;
platform_process = 0xfffffff0076d92e8;
process_name = 0xfffffff007707bac;
compare_names = 0xfffffff007410d50;
present_done_resume = 0xfffffff00796a2a0;
