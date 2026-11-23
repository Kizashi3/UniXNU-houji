# Stock iPhone X canvas comparison

The rendering canvas is 1125×2436 pixels, corresponding to 375×812 points at
scale 3 for the owner's iPhone X iOS 16.7.16 root. A separate, budget-accounted
IOSurface holds the rendering canvas. Cached row buffers scale completed
frames to the verified 1200×2670 firmware scanout. The GPU fence and ownership
gate cover the source acquisition and copy, as before.

The physical framebuffer address, pitch and geometry guards remain active.
Touch events retain their physical-panel normalization to 0…1. The panel is
filled, with a small aspect-ratio stretch. Rendering resolution is lower than
the native-panel comparison, which used a custom 400×890 logical layout.

This is a hardware comparison, not a qualified keyboard or performance fix.
The nearest-neighbour scaler can affect image quality and add CPU cost.
`HOUJI DISPLAY PERF` counts source bytes and CPU presents, not panel refresh.
`HOUJI GPU ALLOC` reports existing client allocation/window failure counters;
it does not turn GPU address high-water values into physical RAM usage.

Apply `scripts/apply-stock-canvas.py --xnu <source>` after the display-refresh
layer. The helper refuses any input other than the pinned before/after hashes.
