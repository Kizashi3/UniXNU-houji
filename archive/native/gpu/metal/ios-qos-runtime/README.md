# iOS pthread QoS consumer adaptation

Enable the runtime's existing Apple thread roles on iOS as well as macOS. The public pthread QoS APIs are available in the owner-selected iOS 16 shared cache. Requests never bind a CPU or alter clocks. Six process-local counters distinguish requested classes from observed classes and errors; observations do not prove actual CPU scheduling or latency.

The Objective-C telemetry forwards cached counters only. Native 1200x2670 display output, retained iOS16 and ASTC adapters, fences, GPU memory lifetime, and Turnip are unchanged. This is a consumer experiment, not a qualified upstream release. Hardware performance remains unverified until r207 completes.
