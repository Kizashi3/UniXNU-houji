/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * CM3 execution test using ITCM and DTCM only. No external loads, GPU writes,
 * HFI or DMA. All interrupts disabled; host returns CM3 to reset afterwards.
 */
.syntax unified
.cpu cortex-m3
.thumb
.section .text,"ax",%progbits
.global vectors
vectors:
  .word 0x10007f80
  .word reset_handler
  .rept 14
  .word fault_handler
  .endr
.thumb_func
reset_handler:
  cpsid i
  ldr r0, =0x10004000
  ldr r1, =0xa7500001
  str r1, [r0]
  ldr r1, =0x750c0de0
  str r1, [r0, #4]
  movs r2, #0
count:
  adds r2, #1
  cmp r2, #128
  bne count
  str r2, [r0, #8]
  dsb
  ldr r1, =0xa7500002
  str r1, [r0]
  dsb
idle:
  /* Low-power entry is not qualified yet. Stay in ITCM until host reset. */
  b idle
.thumb_func
fault_handler:
  cpsid i
  ldr r0, =0x10004000
  ldr r1, =0xa750dead
  str r1, [r0]
  dsb
  b idle
.ltorg
