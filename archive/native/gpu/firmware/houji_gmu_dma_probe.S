/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Bounded GMU test for one owned native4K mapping. All interrupts masked.
 * Reads two known words, writes only mapped offset 8, then tries one unmapped
 * read. Host confirms the SMMU fault, holds reset, detaches DMA and invalidates
 * its CPU cache before accepting the device-written marker. No GPU commands.
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
  dsb
  ldr r2, =0x60000000
  ldr r3, [r2]
  str r3, [r0, #4]
  ldr r3, [r2, #4]
  str r3, [r0, #8]
  ldr r3, [r2, #8]
  str r3, [r0, #16]
  ldr r3, =0xa750cafe
  str r3, [r2, #8]
  dsb
  ldr r3, [r2, #8]
  str r3, [r0, #12]
  dsb
  ldr r2, =0x60002000
  ldr r3, [r2]
  str r3, [r0, #20]
  ldr r1, =0xa7500003
  str r1, [r0]
  dsb
idle:
  b idle
.thumb_func
fault_handler:
  cpsid i
  ldr r0, =0x10004000
  ldr r2, =0xe000ed28
  ldr r3, [r2]
  str r3, [r0, #24]
  ldr r3, [r2, #16]
  str r3, [r0, #28]
  ldr r1, =0xa750dead
  str r1, [r0]
  dsb
  b idle
.ltorg
