#!/usr/bin/env python3
"""Compare playtest-tweaked and released Core.zip files for Stronghold porting.

The script is intentionally read-only unless --extract-overlay is supplied. It
does not modify either game archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAYTEST_CORE = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "HeroesOE_Data"
    / "StreamingAssets"
    / "Core.zip"
)
DEFAULT_RELEASE_CORE = (
    ROOT
    / "Heroes of Might and Magic Olden Era - Golden Era"
    / "HeroesOldenEra_Data"
    / "StreamingAssets"
    / "Core.zip"
)
DEFAULT_OUT_DIR = ROOT / "tools" / "_tmp_release_port_core_overlay"

TEXT_EXTS = {".json", ".txt", ".csv", ".tsv", ".xml", ".yaml", ".yml", ".bytes"}
STRONGHOLD_TOKENS = (
    "homm3_stronghold",
    "homm3_fortress",
    "stronghold",
    "fortress",
    "goblin",
    "hobgoblin",
    "wolf_raider",
    "orc",
    "ogre",
    "cyclops",
    "behemoth",
    "crag_hack",
    "gurnisson",
    "gretchin",
    "jabarkas",
    "krellion",
    "shiva",
    "tyraxor",
    "yog",
)


@dataclass(frozen=True)
class ZipMember:
    name: str
    size: int
    sha256: str


def read_members(core_zip: Path) -> dict[str, ZipMember]:
    with zipfile.ZipFile(core_zip) as zf:
        members: dict[str, ZipMember] = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            data = zf.read(info.filename)
            members[normalize_name(info.filename)] = ZipMember(
                name=normalize_name(info.filename),
                size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        return members


def normalize_name(name: str) -> str:
    return name.replace("\\", "/")


def read_zip_text(zf: zipfile.ZipFile, name: str) -> str | None:
    ext = Path(name).suffix.lower()
    if ext not in TEXT_EXTS:
        return None
    try:
        return zf.read(name).decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return zf.read(name).decode("utf-16")
        except UnicodeDecodeError:
            return None


def member_mentions_stronghold(zf: zipfile.ZipFile, name: str) -> bool:
    lowered_name = name.lower()
    if any(token in lowered_name for token in STRONGHOLD_TOKENS):
        return True
    text = read_zip_text(zf, name)
    if text is None:
        return False
    lowered_text = text.lower()
    return any(token in lowered_text for token in STRONGHOLD_TOKENS)


def find_stronghold_members(playtest_core: Path) -> list[str]:
    with zipfile.ZipFile(playtest_core) as zf:
        names = [normalize_name(info.filename) for info in zf.infolist() if not info.is_dir()]
        return sorted(name for name in names if member_mentions_stronghold(zf, name))


def load_json_member(core_zip: Path, name: str) -> Any | None:
    with zipfile.ZipFile(core_zip) as zf:
        try:
            raw = zf.read(name)
        except KeyError:
            return None
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def collect_strings(value: Any) -> set[str]:
    strings: set[str] = set()
    if isinstance(value, str):
        strings.add(value)
    elif isinstance(value, list):
        for item in value:
            strings.update(collect_strings(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            strings.add(str(key))
            strings.update(collect_strings(item))
    return strings


def direct_child_dirs(names: set[str], prefix: str) -> set[str]:
    result: set[str] = set()
    for name in names:
        if not name.startswith(prefix):
            continue
        rest = name[len(prefix) :]
        if "/" not in rest:
            continue
        result.add(rest.split("/", 1)[0])
    return result


def summarize_data_json(playtest_core: Path, release_core: Path) -> list[str]:
    lines: list[str] = []
    playtest_data = load_json_member(playtest_core, "DB/data.json")
    release_data = load_json_member(release_core, "DB/data.json")
    if not isinstance(playtest_data, dict) or not isinstance(release_data, dict):
        return ["- `DB/data.json`: could not parse one or both archives as JSON."]

    playtest_strings = collect_strings(playtest_data)
    release_strings = collect_strings(release_data)
    stronghold_strings = sorted(
        value
        for value in playtest_strings - release_strings
        if any(token in value.lower() for token in STRONGHOLD_TOKENS)
    )
    lines.append(f"- `DB/data.json`: {len(stronghold_strings)} Stronghold-token strings exist only in playtest.")
    for value in stronghold_strings[:40]:
        lines.append(f"  - `{value}`")
    if len(stronghold_strings) > 40:
        lines.append(f"  - ... {len(stronghold_strings) - 40} more")
    return lines


def write_report(
    playtest_core: Path,
    release_core: Path,
    playtest_members: dict[str, ZipMember],
    release_members: dict[str, ZipMember],
    stronghold_members: list[str],
    out_dir: Path,
) -> dict[str, Any]:
    manifest_members = []
    status_counts = {"added_to_release": 0, "changed_from_release": 0, "same_as_release": 0}
    for name in stronghold_members:
        playtest = playtest_members[name]
        release = release_members.get(name)
        if release is None:
            status = "added_to_release"
        elif release.sha256 != playtest.sha256:
            status = "changed_from_release"
        else:
            status = "same_as_release"
        status_counts[status] += 1
        manifest_members.append(
            {
                "path": name,
                "status": status,
                "playtest_size": playtest.size,
                "release_size": release.size if release else None,
                "playtest_sha256": playtest.sha256,
                "release_sha256": release.sha256 if release else None,
            }
        )

    release_names = set(release_members)
    playtest_names = set(playtest_members)
    manifest = {
        "playtest_core": str(playtest_core),
        "release_core": str(release_core),
        "status_counts": status_counts,
        "stronghold_member_count": len(stronghold_members),
        "members": manifest_members,
        "path_families": {
            "playtest_hero_dirs": sorted(direct_child_dirs(playtest_names, "DB/heroes/")),
            "release_hero_dirs": sorted(direct_child_dirs(release_names, "DB/heroes/")),
            "playtest_fraction_dirs": sorted(direct_child_dirs(playtest_names, "DB/fractions/")),
            "release_fraction_dirs": sorted(direct_child_dirs(release_names, "DB/fractions/")),
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lines = [
        "# Release Core Overlay Analysis",
        "",
        f"- Playtest Core: `{playtest_core}`",
        f"- Release Core: `{release_core}`",
        f"- Stronghold-relevant playtest members: {len(stronghold_members)}",
        f"- Added to release: {status_counts['added_to_release']}",
        f"- Changed from release: {status_counts['changed_from_release']}",
        f"- Already same: {status_counts['same_as_release']}",
        "",
        "## DB/data.json",
        "",
        *summarize_data_json(playtest_core, release_core),
        "",
        "## Path Families",
        "",
        "- Playtest hero dirs: " + ", ".join(f"`{x}`" for x in manifest["path_families"]["playtest_hero_dirs"]),
        "- Release hero dirs: " + ", ".join(f"`{x}`" for x in manifest["path_families"]["release_hero_dirs"]),
        "- Playtest fraction dirs: " + ", ".join(f"`{x}`" for x in manifest["path_families"]["playtest_fraction_dirs"]),
        "- Release fraction dirs: " + ", ".join(f"`{x}`" for x in manifest["path_families"]["release_fraction_dirs"]),
        "",
        "## Stronghold Members",
        "",
    ]
    for item in manifest_members:
        lines.append(f"- `{item['status']}` `{item['path']}`")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def extract_overlay(playtest_core: Path, manifest: dict[str, Any], extract_dir: Path) -> None:
    wanted = {
        item["path"]
        for item in manifest["members"]
        if item["status"] in {"added_to_release", "changed_from_release"}
    }
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(playtest_core) as zf:
        for name in sorted(wanted):
            target = extract_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(name))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playtest-core", type=Path, default=DEFAULT_PLAYTEST_CORE)
    parser.add_argument("--release-core", type=Path, default=DEFAULT_RELEASE_CORE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--extract-overlay",
        action="store_true",
        help="Extract added/changed Stronghold-relevant playtest members into out-dir/overlay.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    playtest_core = args.playtest_core.resolve()
    release_core = args.release_core.resolve()
    if not playtest_core.is_file():
        raise FileNotFoundError(playtest_core)
    if not release_core.is_file():
        raise FileNotFoundError(release_core)

    playtest_members = read_members(playtest_core)
    release_members = read_members(release_core)
    stronghold_members = find_stronghold_members(playtest_core)
    manifest = write_report(
        playtest_core,
        release_core,
        playtest_members,
        release_members,
        stronghold_members,
        args.out_dir.resolve(),
    )
    if args.extract_overlay:
        extract_overlay(playtest_core, manifest, args.out_dir.resolve() / "overlay")

    print(f"Wrote {args.out_dir.resolve() / 'report.md'}")
    print(f"Wrote {args.out_dir.resolve() / 'manifest.json'}")
    if args.extract_overlay:
        print(f"Extracted overlay to {args.out_dir.resolve() / 'overlay'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
