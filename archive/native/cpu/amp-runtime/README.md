# Houji two-class scheduler trial

The current eight-core image put every CPU in one SMP class. This trial classifies CPU0-1 (A520) as E and CPU2-7 (A720/X4) as P, enables the existing XNU AMP scheduler and raises only this board maximum to two clusters. HAS_CLUSTER remains zero so Qualcomm per-core Aff1 IDs use generic E/P grouping instead of Apple hardware cluster numbering. Physical affinities, GIC routing, CPU initialization, frequency domains and frequency/voltage tables stay as before. Native 1200x2670 rendering is unchanged.

This is coarse P/E scheduling; it does not rank X4 separately from A720. Host ADT verification restores every edited property and requires the original byte stream; actual scheduling, startup and responsiveness require r209 hardware evidence. Terminal telemetry reports the real scheduler name and kernel topology.
