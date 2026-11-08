#!/usr/bin/env python3
"""Validate that the built OfflineUnlockMod assembly is the one deployed."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


OFFICIAL_DEOBF_BUILD_SENTINEL = "OFFLINE_UNLOCK_MOD_OFFICIAL_DEOBF_BUILD_SENTINEL_V1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def require_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")


def assembly_contains_user_string(path: Path, text: str) -> bool:
    # Search common .NET string encodings directly so validation does not need IL tooling.
    data = path.read_bytes()
    encodings = ("utf-16le", "utf-16be", "utf-8")
    return any(text.encode(encoding) in data for encoding in encodings)


def require_official_deobf_build_sentinel(path: Path, label: str) -> None:
    if assembly_contains_user_string(path, OFFICIAL_DEOBF_BUILD_SENTINEL):
        print(f"deploy-buildmode-ok {label} official-deobf-build-sentinel")
        return
    raise SystemExit(
        f"{label} does not contain the Golden Era build sentinel; "
        "rebuild cleanly with -p:OfficialDeobfBuild=true before deploying"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--deploy-dir", required=True)
    parser.add_argument("--plugins-root", required=True)
    parser.add_argument(
        "--require-official-deobf-build-sentinel",
        action="store_true",
        help="Require the deployed DLL to contain the explicit Golden Era build sentinel.",
    )
    parser.add_argument(
        "--file",
        action="append",
        dest="files",
        default=[],
        help="File name to compare between source and deploy directories.",
    )
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    deploy_dir = Path(args.deploy_dir).resolve()
    plugins_root = Path(args.plugins_root).resolve()
    files = args.files or ["OfflineUnlockMod.dll", "OfflineUnlockMod.pdb"]

    duplicate_dlls = sorted(plugins_root.rglob("OfflineUnlockMod.dll"))
    expected_dll = deploy_dir / "OfflineUnlockMod.dll"
    if duplicate_dlls != [expected_dll]:
        details = "\n".join(str(path) for path in duplicate_dlls) or "<none>"
        raise SystemExit(
            "expected exactly one OfflineUnlockMod.dll under plugins root at "
            f"{expected_dll}; found:\n{details}"
        )

    for name in files:
        source = source_dir / name
        deployed = deploy_dir / name
        require_file(source, f"source {name}")
        require_file(deployed, f"deployed {name}")
        source_hash = sha256(source)
        deployed_hash = sha256(deployed)
        if source_hash != deployed_hash:
            raise SystemExit(
                f"deployed {name} hash mismatch: source={source_hash} deployed={deployed_hash}"
            )
        print(f"deploy-hash-ok {name} {deployed_hash}")

    if args.require_official_deobf_build_sentinel:
        require_official_deobf_build_sentinel(source_dir / "OfflineUnlockMod.dll", "source OfflineUnlockMod.dll")
        require_official_deobf_build_sentinel(expected_dll, "deployed OfflineUnlockMod.dll")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())