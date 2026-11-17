# Sweet display bring-up, 2026-11-17 evening

Device: houji (SM8650), iOS 16.7.16 userland, Sweet stack in kernel.

## Confirmed working

- One AppleCLCD instance owns IOMobileFramebuffer (`SWEET FB: AppleCLCD 1200x2670 ... default surface 2`).
- backboardd drives it through the user client; every call returns success.
- SpringBoard no longer trips `FBSDisplayMode cannot be configured as requested`.
- Runs ~500-600 s, then launchd panics because watchdogd keeps asserting.

## Selector sequence backboardd issues (run 487)

    57                     -> 0
    15  [0, 0x10]          -> 0
    22  [0]                -> 0
    29  (8-byte out)       -> 0
    33  [0]                -> 0
    79  [0x4d]  (1580 out) -> 0
    74  [0]    count,64B   -> count 1 after the fix below
    72  [fn, refcon, 3]    -> registers notification type 3
    73  [3]                -> 0
    12  [1]                -> 0
    79  [0x40] (40 out)    -> 0
    6   [0, 0x80000003]    -> 0
    27  (3084 out)         -> 0
    17  (3084 in)          -> 0
    84  (4 in)             -> 0
    50  [0x10000]          -> 0

Then it stops. `sel 3` never arrives.

## Two findings from this round

1. `sel 74` (SupportedFrameInfo) was a gate. The framework at
   `_IOMobileFramebufferSupportedFrameInfo` (0x1af226350) returns a cached array
   that is only allocated when the record count is non-zero:

       cmp w0,#0 ; ccmp w8,#0,eq ; b.eq <return null>
       str w8,[x19,#1532]
       add w0,w8,#1 ; calloc(count+1, 8)
       copy the 64-byte record into array[0]

   Returning `count=1` plus one record made backboardd register notification
   type 3 and call `sel 73`; before that it stopped at 74.

2. Delivering a type-3 notification right after registration did not move the
   sequence further. Still no `sel 3`.

## Watchdog

`IOWatchdog` as a class name already exists in this kernel (string present in
the baseline image). Defining it again panics; allocating it by name returns
null, so the class is not instantiable here. Attempts to compile the Sweet
watchdog unit also broke the link (`arm64_platform_sleep_hook` came from an
ArmCpu drift, since pinned) and, once, NativeAES allocation. The watchdog path
is parked.

## Next candidates

- Identify what `sel 79` and `sel 50` carry. `79` takes a selector-like input
  (`0x4d`, `0x40`) with 1580- and 40-byte outputs; `50` takes `0x10000`. These
  look like display configuration reads, not pixel traffic.
- Check whether the framework requires a successful "set display mode" step
  before it asks for the layer surface, and which selector carries it.
- Keep the frame-info record values under review: the layout of the 64-byte
  record is still a guess (width, height, dot pitch at offsets 0/4/8).
