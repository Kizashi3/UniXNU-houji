extern "C" {
/* Weak fallbacks for the device entry points the XNU patches reference. The
 * bootstrap pass links the kernel before the driver archives are built; a weak
 * definition lets that pass succeed, and the archive's strong definition wins
 * the final link. C linkage means the linker matches by name only. */
__attribute__((weak)) void houji_fb_bootstrap(void) {}
__attribute__((weak)) int native_ufs_fill2(unsigned long, unsigned long) { return 1; }
__attribute__((weak)) int native_ufs_fill_ramdisk(unsigned long, unsigned long) { return 1; }
__attribute__((weak)) int native_ufs_fill_report(void) { return 0; }
__attribute__((weak)) int native_ufs_md_init(void) { return -1; }
__attribute__((weak)) int native_ufs_md_read(const char *, unsigned long, void *, unsigned long) { return 0; }
__attribute__((weak)) int native_ufs_md_write(const char *, unsigned long, const void *, unsigned long) { return -1; }
__attribute__((weak)) void native_ufs_boot_progress(void) {}
__attribute__((weak)) void native_ufs_heartbeat(void) {}
__attribute__((weak)) unsigned long long native_ufs_md_window_bytes(const char *) { return 0; }
__attribute__((weak)) unsigned char native_ram_block_volume_seed[8] = {0};
}
