#!/usr/bin/env python3
"""Export a generic Golden Era Core.zip overlay from two Steam release archives.

Inputs must be release-build archives for the same Olden Era build:
- --vanilla-core: clean Steam release Core.zip
- --modded-core: known-good modded Steam release Core.zip

The output is a manifest plus member payload files that the installer can apply
without needing the maintainer's local Steam folder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any


FORMAT = "hommoe-golden-era-release-overlay-v1"


def normalize_name(name: str) -> str:
    return name.replace("\\", "/").lstrip("/")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path, "r") as zf:
        return {
            normalize_name(info.filename): zf.read(info.filename)
            for info in zf.infolist()
            if not info.is_dir()
        }


def read_json_member(members: dict[str, bytes], name: str) -> Any | None:
    data = members.get(name)
    if data is None:
        return None
    return json.loads(data.decode("utf-8-sig"))


def required_core_members(modded: dict[str, bytes]) -> list[str]:
    required = ["DB/data.json"]
    required.extend(
        sorted(
            name
            for name in modded
            if name.startswith("DB/fractions/") and "homm3_" in name.lower()
        )
    )
    return required


def required_core_tokens(modded: dict[str, bytes]) -> list[str]:
    tokens: list[str] = []
    for name in required_core_members(modded):
        if not name.startswith("DB/fractions/"):
            continue
        doc = read_json_member(modded, name)
        if not isinstance(doc, dict):
            continue
        array = doc.get("array")
        if not isinstance(array, list) or not array:
            continue
        first = array[0]
        if not isinstance(first, dict):
            continue
        faction_id = first.get("id")
        if isinstance(faction_id, str) and faction_id.startswith("homm3_"):
            tokens.append(faction_id)
    return sorted(set(tokens))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vanilla-core", type=Path, required=True)
    parser.add_argument("--modded-core", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    vanilla_core = args.vanilla_core.resolve()
    modded_core = args.modded_core.resolve()
    out_dir = args.out_dir.resolve()
    members_dir = out_dir / "members"

    if not vanilla_core.exists():
        raise SystemExit(f"Missing vanilla release Core.zip: {vanilla_core}")
    if not modded_core.exists():
        raise SystemExit(f"Missing modded release Core.zip: {modded_core}")
    if out_dir.exists():
        if not args.force:
            raise SystemExit(f"Output exists; pass --force to replace: {out_dir}")
        shutil.rmtree(out_dir)
    members_dir.mkdir(parents=True, exist_ok=True)

    vanilla = read_members(vanilla_core)
    modded = read_members(modded_core)

    operations = []
    skipped_deleted = 0
    for name, data in sorted(modded.items()):
        old = vanilla.get(name)
        if old == data:
            continue

        digest = sha256_bytes(data)
        payload_name = f"{digest}.bin"
        (members_dir / payload_name).write_bytes(data)
        operations.append(
            {
                "path": name,
                "operation": "replace_member" if old is not None else "add_member",
                "payload": f"members/{payload_name}",
                "sha256": digest,
                "size": len(data),
                "previousSha256": sha256_bytes(old) if old is not None else None,
            }
        )

    for name in sorted(set(vanilla) - set(modded)):
        if name:
            skipped_deleted += 1

    required_members = required_core_members(modded)
    required_tokens = required_core_tokens(modded)
    if len(required_tokens) < 1:
        raise SystemExit("Modded Core.zip does not contain any homm3_* faction rows.")

    manifest = {
        "format": FORMAT,
        "basis": "steam-release-core",
        "vanillaCore": {
            "label": "clean Steam release Core.zip",
            "sha256": sha256_file(vanilla_core),
            "size": vanilla_core.stat().st_size,
        },
        "moddedCore": {
            "label": "known-good modded Steam release Core.zip",
            "sha256": sha256_file(modded_core),
            "size": modded_core.stat().st_size,
        },
        "operationCount": len(operations),
        "skippedDeletedMemberCount": skipped_deleted,
        "requiredCoreMembers": required_members,
        "requiredCoreTokens": required_tokens,
        "operations": operations,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Exported {len(operations)} release overlay operation(s) to {out_dir}")
    print(f"Required faction tokens: {', '.join(required_tokens)}")
    if skipped_deleted:
        print(f"Skipped {skipped_deleted} vanilla member(s) missing from modded Core.zip.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
