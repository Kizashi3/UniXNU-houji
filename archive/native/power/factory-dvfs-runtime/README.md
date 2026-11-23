# Full factory OPP mapping and controlled follow-up

The read-only houji tuple (GPU bin 5, external SoC feature AB = 2) selects
`gpu-pwrlevels-3` using the pinned Qualcomm selector. Pcode does not enter
the SoC code for this external feature. The 12 OPPs and ARC/MX votes are
generated from the captured phone FDT/AOP, not another board.

r220 advertised and governed the full table. The owner reported continued
lag and purple/text artifacts, plus new pink blocks. Its valid snapshot
found texture/command allocation failures and substantial publish cost; it
does not establish that the higher requests caused the artifacts. The next
diagnostic keeps all advertised entries but caps the load governor at the
500 MHz boot entry while testing the separate Turnip BO lifetime repair.

`HoujiGpuGovernorPolicy.h` has no I/O. The runtime retains the existing issuer
lock, HFI ACK validation and failure-stop path. The initial vote is 500 MHz.
No PLL/voltage register or thermal limit is directly written. Thermal feedback
and measured actual clocks remain unqualified.

Checks: tests/check-factory-gpu-dvfs.cpp and tests/check-factory-gpu-hfi.c.
The compiler, kernel link and hardware trial are recorded separately.
