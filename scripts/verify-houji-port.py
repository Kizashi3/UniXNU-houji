#!/usr/bin/env python3
"""Run offline consistency checks for the Xiaomi 14 / houji handoff.

The checks deliberately stop at static evidence. They do not talk to a phone
and never invoke fastboot. A passing report means that the selected ADT and
Mu-Silicium artifacts are internally consistent; it does not prove that the
ShmBridge protocol is installed at runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from pathlib import Path

import tomllib

SHMBRIDGE_FILE_GUID = "41EBB6A6-2C19-4C02-841D-848CE004A282"
SHMBRIDGE_PROTOCOL_GUID = "9C1EB71F-DD6C-4ED5-9F6A-5CC0CA789F16"
UFSDXE_FILE_GUID = "0D35CD8E-97EA-4F9A-96AF-0F0D89F76567"
STALE_IDENTITY = ("Ace 5", "OnePlus", "PKG110", "giulia")


def check(report: dict, name: str, passed: bool, detail: str) -> None:
    report["checks"].append({"name": name, "passed": passed, "detail": detail})


def read_adt(path: Path) -> bytes:
    data = path.read_bytes()
    if len(data) < 16:
        raise ValueError("ADT is shorter than its node header")
    # The generator uses a private little-endian node format. Check its root
    # header and retain the raw bytes for identity checks below.
    props, children = struct.unpack_from("<II", data)
    if props < 1 or children < 1:
        raise ValueError("ADT root does not contain the expected nodes")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--mu-root", type=Path,
                        help="Mu-Silicium checkout or archived build snapshot")
    parser.add_argument("--adt", type=Path, help="Generated houji ADT to inspect")
    parser.add_argument("--image", type=Path, help="Optional image to hash")
    parser.add_argument("--sha256", help="Expected image SHA256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    report = {
        "status": "offline-static-checks",
        "device": "Xiaomi 14",
        "codename": "houji",
        "soc": "SM8650",
        "shmbridge_protocol_guid": SHMBRIDGE_PROTOCOL_GUID,
        "shmbridge_file_guid": SHMBRIDGE_FILE_GUID,
        "ufs_file_guid": UFSDXE_FILE_GUID,
        "checks": [],
    }

    board_path = root / "board.toml"
    try:
        board = tomllib.loads(board_path.read_text(encoding="utf-8"))
        check(report, "board.name", board.get("board", {}).get("name") == "houji",
              f"{board.get('board', {}).get('name')!r}")
        check(report, "board.soc", board.get("board", {}).get("soc") == "SM8650",
              f"{board.get('board', {}).get('soc')!r}")
        title = board.get("payload", {}).get("title", "")
        check(report, "board.identity", "Xiaomi 14" in title and "houji" in title, title)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        check(report, "board.toml", False, str(exc))

    adt_script = root / "scripts" / "make-houji-adt.py"
    source = adt_script.read_text(encoding="utf-8") if adt_script.is_file() else ""
    check(report, "adt.script.identity", "Xiaomi-14-houji" in source and
          "OnePlus-Ace-5" not in source, "source identity markers")
    if args.adt:
        try:
            adt = read_adt(args.adt)
            check(report, "adt.model", b"Xiaomi-14-houji\0" in adt, "model property")
            check(report, "adt.product", b"Xiaomi 14\0" in adt and b"houji\0" in adt,
                  "product properties")
            report["adt_sha256"] = hashlib.sha256(adt).hexdigest()
        except (OSError, ValueError) as exc:
            check(report, "adt.read", False, str(exc))

    if args.mu_root:
        mu = args.mu_root.resolve()
        dsc = mu / "Platforms/Xiaomi/houjiPkg/houji.dsc"
        fdf = mu / "Platforms/Xiaomi/houjiPkg/houji.fdf"
        fv = next(mu.glob("Build/houjiPkg/*/FV/FVMAIN.inf"), None)
        inf = mu / "Binaries/houji/QcomPkg/Drivers/ShmBridgeDxeLA/ShmBridgeDxeLA.inf"
        check(report, "mu.houji.dsc", dsc.is_file(), str(dsc))
        check(report, "mu.houji.fdf", fdf.is_file(), str(fdf))
        if fv and fv.is_file():
            text = fv.read_text(encoding="utf-8", errors="replace")
            check(report, "mu.fv.shmbridge", SHMBRIDGE_FILE_GUID in text, "FVMAIN entry")
            check(report, "mu.fv.ufs", UFSDXE_FILE_GUID in text, "FVMAIN entry")
        else:
            check(report, "mu.fvmain", False, "Build/*/FV/FVMAIN.inf not found")
        if inf.is_file():
            text = inf.read_text(encoding="utf-8", errors="replace")
            check(report, "mu.shmbridge.depex", re.search(r"(?im)^\s*TRUE\s*$", text) is not None,
                  "ShmBridge INF Depex")
            efi = inf.with_name("ShmBridgeDxeLA.efi")
            if efi.is_file():
                binary = efi.read_bytes()
                report["shmbridge_binary_sha256"] = hashlib.sha256(binary).hexdigest()
                check(report, "mu.shmbridge.entrypoint", b"Failed to install ShmBridgeProtocol" in binary,
                      "driver contains install-failure diagnostic")
        else:
            check(report, "mu.shmbridge.inf", False, str(inf))

    if args.image:
        digest = hashlib.sha256(args.image.read_bytes()).hexdigest()
        report["image_sha256"] = digest
        check(report, "image.sha256", not args.sha256 or digest.lower() == args.sha256.lower(), digest)

    report["passed"] = all(item["passed"] for item in report["checks"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
