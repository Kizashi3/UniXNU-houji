#if defined(SWEET)
// PSCI CPU_ON enters with MMU/caches off and x0 = cpu_data physical address.
// XNU's normal start_cpu label expects x20/x21 already established.
    .align 4
    .globl EXT(houji_secondary_entry)
LEXT(houji_secondary_entry)
    msr     DAIFSet, #(DAIFSC_ALL)
    msr     OSLAR_EL1, xzr
    mov     x21, x0
    adrp    x1, EXT(LowExceptionVectorBase)@page
    add     x1, x1, EXT(LowExceptionVectorBase)@pageoff
    msr     VBAR_EL1, x1
    adrp    x20, EXT(const_boot_args)@page
    add     x20, x20, EXT(const_boot_args)@pageoff
    adrp    lr, EXT(arm_init_cpu)@page
    add     lr, lr, EXT(arm_init_cpu)@pageoff
    isb
    b       start_cpu
#endif
