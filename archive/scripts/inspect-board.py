#!/usr/bin/env python3
"""Extract reproducible, non-identifying board facts. Never accesses a device."""
import argparse
import hashlib
import json
from pathlib import Path
from fdt import cells, embedded, strings


def value(name, data):
    # Binary cells can contain printable bytes and NULs; never infer their type
    # from their content (e.g. a register address containing ASCII 'x').
    if name in {"model", "compatible", "MemLabel", "device_type", "label", "status", "enable-method"}:
        return strings(data)
    if not data:
        return True
    if len(data) == 1:
        return data[0]
    return [hex(x) for x in cells(data)] if len(data) % 4 == 0 else {"hex": data.hex()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"scope": "Source facts only; not a validated boot configuration", "inputs": []}
    for source in args.inputs:
        data = source.read_bytes()
        trees = []
        for offset, size, root in embedded(data):
            nodes = {}
            for path, node in root.walk():
                if any(k in path.lower() for k in ["memorymap", "configurationmap", "reserved-memory", "/memory", "/cpus", "framebuffer", "splash"]):
                    nodes[path] = {k: value(k, v) for k, v in node.properties.items()}
                elif path == "/":
                    nodes[path] = {k: value(k, v) for k, v in node.properties.items() if k in ["model", "compatible", "qcom,msm-id", "qcom,board-id", "#address-cells", "#size-cells"]}
            trees.append({"offset": offset, "bytes": size, "nodes": nodes})
        if not trees:
            raise SystemExit("No valid FDT found: " + str(source))
        report["inputs"].append({"file": source.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "trees": trees})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
