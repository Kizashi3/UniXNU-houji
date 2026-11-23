# Native runtime performance: r208

This report distinguishes confirmed behavior from pending work. The owner's iOS 16.7.16 build remains at native 1200×2670 pixels with a separate owned render surface and exact CPU copy to scanout. The owner confirmed clear text and no flicker in r206/r207. Smooth desktop operation, keyboard geometry and Photos remain unresolved.

## Hardware findings

r208's first attempt stopped in the unchanged OEM UEFI SCM driver before XNU. Its uncommitted XNU file, screen photo, full direct logfs image and recovery captures were retained. The same firmware bytes subsequently entered the desktop. The recovery reader is now restaged and SHA-verified by the boot guard on every attempt; a missing tmpfs helper is no longer misreported as a changed partition. UEFI log rotation was independently compared and restored only in eight identified logfs blocks, with full direct readback and protected partition checks.

The owner reported slow app opening, a brief black initial view, dropped frames when scrolling and slow response. The no-drain query changes did not visibly improve this behavior. A different interaction workload prevents treating aggregate differences between r207 and r208 as a controlled performance regression.

| r208 native method | Calls | Total time, ms | Mean time, ms |
|---|---:|---:|---:|
| BO allocate | 1592 | 1874.153 | 1.177 |
| BO map | 2796 | 1636.171 | 0.585 |
| BO free | 1493 | 6442.930 | 4.315 |
| Submit | 3632 | 28096.367 | 7.736 |
| Timestamp read | 2452 | 674.534 | 0.275 |
| Cached status | 2296 | 1.160 | 0.000505 |

These are cumulative method wall times, not independent additive costs or panel frame rates. The renderer recorded 2250 completed command buffers at a 25.074 ms mean from commit to callback. Its scheduled waits totalled 34.224 seconds. The gate's wait-for-jobs time was 12.711 seconds within its 17.324-second total; it overlaps the method times above.

The principal remaining synchronous path is:

```
AGXDeviceUserClient::runCore(Submit)
  -> native_adreno_board_quiesce()
  -> NativeAdrenoSubmit::waitAll()
  -> NativeAdrenoUserClient::dispatch()/submit()
  -> NativeAdrenoSubmit::submit()
  -> NativeAdrenoVm::publishMapped()
  -> NativeAdrenoRing::submitFramed()
```

It is unsafe to delete the wait and call the result qualified: the board publication callback admits one pending publish, the submission path maintains mapped CPU caches, and presentation requires a completed GPU source. A future pipelined implementation must reconcile these ownership rules, retain real references until observed fences, preserve VM mutation checks, handle queue pressure and avoid starving presentation. r208 retains that synchronization.

## CPU scheduling follow-up

The actual r208 ADT put all eight cores into cluster 0 with cluster-type 0. The board maximum was one cluster, which undefines ARM AMP. The A520 frequency domain repeatedly recorded full load while faster domains were less utilized. This does not by itself prove why the UI is slow.

r209 confirmed eight active CPUs with XNU's Edge scheduler: CPU0–1 in E cluster 0, CPU2–7 in P cluster 1. Qualcomm physical affinities and four DVFS domains stayed unchanged. A720 and X4 share the P group in this experiment. The owner reported only a slight possible improvement; short black views and scrolling lag persisted.

The run-bound, CRC-valid r209 log recorded GPU HFI requests changing between nominal 231 and 500 MHz 85 times, with no vote failures or invalid busy-counter samples. GPU XO busy time was 8.364 seconds across 145.986 seconds of valid samples; nominal level residency was 75.940 seconds at 231 and 70.046 seconds at 500. This is acknowledged level residency, not measured core frequency. CPU controller-state samples did reach the four validated minimum states, so failure to downshift is not established. Late samples showed the E domain busy and P domains quiet; those samples alone do not describe the full interaction workload.

Source inspection found a concrete placement gap: `sched_clutch_bucket_group_init` initializes every QoS bucket's preference to the boot E cluster. Edge's default E-to-P migration and steal edges are disabled, and this board has no CLPC updating those preferences. Classifying the cores therefore did not itself direct foreground work to P cores.

r210 changes the board-specific initial preference for fixed-priority, foreground, initiated and default buckets to P, retaining utility/background preference for E. It falls back to the boot pset until the preferred pset is registered, preserving Edge's normal handling of registered-but-offline processors, explicit binding and later preference updates. It also adapts sheng's interactive governor policy within the existing houji frequency caps: P touch boost, render activity retention, quiet downshift and a short GPU wake hold. Five-second append-only histories record all eight CPU loads, requests/controller states, GPU busy time and acknowledged level residency. The r210 trial completed and its final log was captured automatically on port 5038 with a matching run UUID and CRC. The owner reported basically no improvement. Neither the framebuffer nor the userland Metal plugin changed.

The 5-second histories confirm foreground work on all six P CPUs, with touch-window mean requested frequencies of approximately 2.904, 2.992 and 3.093 GHz in the three P frequency domains. All four domains subsequently reached their validated minimum controller states; no invalid state readbacks occurred. During the interaction window the GPU spent 94.44% of sampled time at the nominal 500 MHz request, yet its XO busy counter indicated 16.63% activity. There were 83 level changes, zero vote failures and zero invalid samples. These are controller requests and acknowledged levels, not an independent GPU clock measurement or thermal qualification.

Renderer command buffers averaged 37.409 ms from commit to completion in this different, uncontrolled workload; submit methods averaged 9.605 ms and the global gate spent 9.797 seconds waiting for outstanding work. The owner feedback and these measurements do not support attributing the remaining lag solely to frequency. Further work must examine serialized submission, cache ownership and presentation without removing fence/reference protections. Evidence: `evidence/native-ios-r210-result.json`, `evidence/r210-power-result.json`, and the run-bound `evidence/logfs-recovery-r210/` capture.

The r209 host watcher missed recovery because USB was owned by an existing ADB server on port 15049. The same final log was subsequently captured on that port without another iOS trial; its final timestamp was 189.44 seconds. This does not prove an automatic reset failure. The port is now included in preparation, boot, capture, recovery polling and protected-storage verification.

## Other confirmed issues

- The current-boot Photos log shows TCC granting access through the app's existing entitlement, then failing to issue its sandbox extension, followed by PhotoLibrary error 45002. The existing `bsd/kern/sweet_amfi.c` stand-in explicitly returns `ENOENT` for extension issue/consume. r208 counted 8564 failed Sandbox calls out of 30397, with zero `ENOPOLICY` results. This is an unimplemented return-data interface; policy registration is present. No authorization or Sandbox behavior was changed by r208.
- `MainScreenStaticInfo` reports native 1200×2670 and scale 3. UIKit reports 400×890 points. The Settings keyboard logs show a 375-point `UIKeyboardAutomatic` within a 400-point host. More layout/resource investigation is needed; the rejected CPU-resampled canvas is not an accepted fix.

Evidence: `native-port/evidence/r208-result.json`, the run-bound `logfs-recovery-r208/capture.json` and `XnuLog.txt`, current-boot r207 Photos/TCC extracts, and `native/cpu/amp-runtime/manifest.json`. Raw images, userland snapshots and Apple binaries remain local, outside this document.
