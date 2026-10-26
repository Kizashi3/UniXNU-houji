#!/usr/bin/env python3
"""Inspect explicitly supplied stock files; never contact a device or enable a provider."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import stat
import struct
import sys
import zlib


MANIFEST = Path(__file__).resolve().parents[1] / "hardware" / "gpu-fence-stock.json"
ELF_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
SECTION_HEADER = struct.Struct("<IIQQQQIIQQ")
SYMBOL = struct.Struct("<IBBHQQ")


class EvidenceError(ValueError):
    """A file does not establish the requested pinned evidence."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


def span(data: bytes, offset: int, size: int, label: str) -> bytes:
    require(offset >= 0 and size >= 0 and offset <= len(data)
            and size <= len(data) - offset, f"{label}: out of file bounds")
    return data[offset:offset + size]


def cstring(data: bytes, offset: int, label: str) -> str:
    require(0 <= offset < len(data), f"{label}: invalid string offset")
    end = data.find(b"\0", offset)
    require(end >= 0, f"{label}: unterminated string")
    try:
        return data[offset:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise EvidenceError(f"{label}: non-ASCII string") from exc


def verify_pin(data: bytes, spec: dict, label: str) -> str:
    require(len(data) == spec["bytes"], f"{label}: size does not match pinned artifact")
    digest = hashlib.sha256(data).hexdigest()
    require(digest == spec["sha256"], f"{label}: SHA-256 does not match pinned artifact")
    return digest


def inspect_module(data: bytes, spec: dict) -> dict:
    """Validate ELF semantics as well as provenance; spec is the trusted manifest entry."""
    digest = verify_pin(data, spec, "module")
    h = ELF_HEADER.unpack(span(data, 0, ELF_HEADER.size, "ELF header"))
    require(h[0][:7] == b"\x7fELF\x02\x01\x01", "module: expected ELF64 little endian")
    require(h[1] == 1 and h[2] == 183 and h[3] == 1,
            "module: expected AArch64 relocatable ELF")
    require(h[8] == ELF_HEADER.size and h[11] == SECTION_HEADER.size,
            "module: unexpected ELF header/section entry size")
    count = h[12]
    require(count > 0 and 0 < h[13] < count, "module: invalid section table")
    raw_sections = span(data, h[6], count * SECTION_HEADER.size, "section table")
    sections = list(SECTION_HEADER.iter_unpack(raw_sections))
    names_section = sections[h[13]]
    require(names_section[1] == 3, "module: section names are not a string table")
    names = span(data, names_section[4], names_section[5], "section names")
    section_names = [cstring(names, s[0], "section name") for s in sections]
    elf = spec["elf"]
    matching_sections = [i for i, name in enumerate(section_names) if name == elf["section"]]
    require(len(matching_sections) == 1, "module: missing or ambiguous text section")
    text_index = matching_sections[0]
    text = sections[text_index]
    require(text[1] == 1 and text[2] & 6 == 6 and text[3] == 0,
            "module: text section must be allocated executable PROGBITS at address zero")
    require(text[4] == int(elf["section_file_offset"], 0), "module: text offset differs")
    text_bytes = span(data, text[4], text[5], "text section")
    matches = []
    for section in sections:
        if section[1] != 2:
            continue
        require(section[9] == SYMBOL.size and section[5] % SYMBOL.size == 0,
                "module: malformed symbol table")
        require(0 < section[6] < count, "module: invalid symbol string table link")
        strings_section = sections[section[6]]
        require(strings_section[1] == 3, "module: symbol names are not a string table")
        strings = span(data, strings_section[4], strings_section[5], "symbol strings")
        for sym in SYMBOL.iter_unpack(span(data, section[4], section[5], "symbol table")):
            if cstring(strings, sym[0], "symbol name") == elf["symbol"]:
                matches.append(sym)
    require(len(matches) == 1, "module: missing or ambiguous allocator symbol")
    sym = matches[0]
    require(sym[1] & 15 == 2 and sym[3] == text_index,
            "module: allocator symbol must be a function in the executable text section")
    require(sym[4] == int(elf["symbol_value"], 0) and sym[5] == elf["symbol_bytes"],
            "module: allocator symbol range differs")
    span(text_bytes, sym[4], sym[5], "allocator function")
    for check in spec["instruction_checks"]:
        offset = int(check["text_offset"], 0)
        require(offset % 4 == 0 and sym[4] <= offset and offset + 4 <= sym[4] + sym[5],
                "module: instruction outside allocator function")
        require(text[4] + offset == int(check["file_offset"], 0),
                "module: instruction file offset differs")
        word = struct.unpack("<I", span(text_bytes, offset, 4, "instruction"))[0]
        require(word == int(check["word"], 0),
                f"module: allocator instruction differs at {check['text_offset']}")
    modinfo_indices = [i for i, name in enumerate(section_names) if name == ".modinfo"]
    require(len(modinfo_indices) == 1, "module: missing or ambiguous modinfo section")
    modinfo = sections[modinfo_indices[0]]
    require(modinfo[1] == 1, "module: modinfo must be PROGBITS")
    entries = span(data, modinfo[4], modinfo[5], "modinfo").split(b"\0")
    vermagic = [entry for entry in entries if entry.startswith(b"vermagic=")]
    require(vermagic == [b"vermagic=" + spec["vermagic"].encode("ascii")],
            "module: vermagic differs or is ambiguous")
    return {"sha256": digest, "vermagic": spec["vermagic"],
            "allocator_symbol": elf["symbol"],
            "allocator_page_bytes": spec["allocator_page_bytes"],
            "verified_instruction_count": len(spec["instruction_checks"])}


def inspect_boot(data: bytes, spec: dict) -> dict:
    """Check the separately pinned boot image and embedded IKCONFIG without execution."""
    digest = verify_pin(data, spec, "boot")
    require(span(data, 0, 8, "boot magic") == b"ANDROID!", "boot: invalid Android magic")
    require(struct.unpack("<I", span(data, 40, 4, "boot version"))[0]
            == spec["header_version"], "boot: unexpected header version")
    kernel_size = struct.unpack("<I", span(data, 8, 4, "kernel size"))[0]
    require(kernel_size == spec["kernel_bytes"], "boot: kernel size differs")
    kernel = span(data, spec["kernel_offset"], kernel_size, "boot kernel")
    require(hashlib.sha256(kernel).hexdigest() == spec["kernel_sha256"],
            "boot: kernel SHA-256 differs")
    require(span(kernel, 56, 4, "ARM64 magic") == b"ARM\x64", "boot: invalid ARM64 kernel magic")
    require(spec["version_prefix"].encode("ascii") in kernel, "boot: kernel version differs")
    start = int(spec["ikconfig_start_marker_kernel_offset"], 0)
    end = int(spec["ikconfig_end_marker_kernel_offset"], 0)
    require(span(kernel, start, 8, "IKCONFIG start") == b"IKCFG_ST"
            and span(kernel, end, 8, "IKCONFIG end") == b"IKCFG_ED",
            "boot: IKCONFIG markers differ")
    require(end - start - 8 == spec["ikconfig_gzip_bytes"], "boot: IKCONFIG gzip size differs")
    try:
        config = gzip.decompress(span(kernel, start + 8, end - start - 8, "IKCONFIG gzip"))
    except (OSError, EOFError, zlib.error) as exc:
        raise EvidenceError("boot: invalid IKCONFIG gzip") from exc
    require(len(config) == spec["ikconfig_bytes"]
            and hashlib.sha256(config).hexdigest() == spec["ikconfig_sha256"],
            "boot: IKCONFIG pin differs")
    lines = config.splitlines()
    for evidence in spec["config_evidence"]:
        index = evidence["line"] - 1
        expected = evidence["text"].encode("ascii")
        require(0 <= index < len(lines) and lines[index] == expected and lines.count(expected) == 1,
                "boot: kernel page configuration differs")
    return {"sha256": digest, "kernel_sha256": spec["kernel_sha256"],
            "version_prefix": spec["version_prefix"],
            "ikconfig_sha256": spec["ikconfig_sha256"],
            "kernel_page_bytes": spec["kernel_page_bytes"]}


def read_regular_file(path: Path) -> bytes:
    require(stat.S_ISREG(path.stat().st_mode), f"{path}: expected an explicit regular file")
    return path.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--module", type=Path, required=True, help="Explicit stock msm_hw_fence.ko file")
    parser.add_argument("--boot", type=Path, help="Optional explicit stock boot.img file")
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        report = {"module": inspect_module(read_regular_file(args.module), manifest["module"])}
        if args.boot is not None:
            report["boot"] = inspect_boot(read_regular_file(args.boot), manifest["boot"])
        report["runtime_provider_ready"] = False
        report["runtime_controller_layout_verified"] = False
        report["build_pair_verified"] = False
        report["limits"] = manifest["not_established"]
    except (OSError, EvidenceError, struct.error) as exc:
        print(f"GPU fence stock evidence rejected: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
