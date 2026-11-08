#!/usr/bin/env python3
"""Validate classic HoMM3 boat map sprite extraction contract."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


EXPECTED = {
    "homm3_boat_1": "ab01_",
    "homm3_boat_2": "ab02_",
    "homm3_boat_3": "ab03_",
    "homm3_boat_cove": "ab04_",
}
EXPECTED_FRAME_COUNT = 45
EXPECTED_SIZE = (96, 64)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as f:
        header = f.read(24)
    require(header.startswith(b"\x89PNG\r\n\x1a\n"), f"{path}: not a PNG")
    return struct.unpack(">II", header[16:24])


def expected_frame_names() -> set[str]:
    names = {f"{group:02d}_00.png" for group in range(0, 5)}
    for group in range(5, 10):
        for frame in range(8):
            names.add(f"{group:02d}_{frame:02d}.png")
    return names


def validate_folder(root: Path, key: str, def_stem: str) -> None:
    folder = root / key
    require(folder.is_dir(), f"missing boat sprite folder: {folder}")
    summary_path = folder / f"{def_stem}.json"
    require(summary_path.is_file(), f"{key}: missing extraction summary {summary_path.name}")
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    groups = {int(seq["group"]): len(seq.get("frames") or []) for seq in summary.get("sequences") or []}
    for group in range(0, 5):
        require(groups.get(group) == 1, f"{key}: group {group:02d} must contain exactly one idle frame")
    for group in range(5, 10):
        require(groups.get(group) == 8, f"{key}: group {group:02d} must contain exactly eight movement frames")
    require(sum(groups.values()) == EXPECTED_FRAME_COUNT, f"{key}: expected {EXPECTED_FRAME_COUNT} total frames, got {sum(groups.values())}")

    expected = expected_frame_names()
    json_frame_paths = []
    for seq in summary.get("sequences") or []:
        for rel in seq.get("frames") or []:
            frame_path = folder / rel
            json_frame_paths.append(frame_path)
            require(frame_path.is_file(), f"{key}: JSON frame path does not exist: {rel}")
    actual_from_json = {path.name for path in json_frame_paths}
    require(actual_from_json == expected, f"{key}: JSON frame set mismatch missing={sorted(expected - actual_from_json)} extra={sorted(actual_from_json - expected)}")

    actual_files = {path.relative_to(folder).as_posix() for path in folder.rglob("*.png")}
    expected_files = {path.relative_to(folder).as_posix() for path in json_frame_paths}
    require(actual_files == expected_files, f"{key}: loose PNG files differ from JSON frames missing={sorted(expected_files - actual_files)} extra={sorted(actual_files - expected_files)}")
    for path in json_frame_paths:
        require(png_size(path) == EXPECTED_SIZE, f"{key}: {path.name} must be {EXPECTED_SIZE[0]}x{EXPECTED_SIZE[1]}")


def validate_sources(repo_root: Path) -> None:
    lod = repo_root / "HoMM 3 Complete" / "Data" / "H3sprite.lod"
    require(lod.is_file(), f"missing HoMM3 H3sprite.lod source for classic boats: {lod}")
    cove = repo_root / "vcmi" / "Mods" / "hota" / "mods" / "cove" / "Content" / "sprites" / "hota" / "cove" / "mapObjects" / "boats" / "AB04_.DEF"
    require(cove.is_file(), f"missing VCMI Cove boat DEF source: {cove}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--plugin-dir")
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    plugin = Path(args.plugin_dir).resolve() if args.plugin_dir else repo / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
    root = plugin / "homm3_boat_map_sprites"
    require(root.is_dir(), f"missing boat sprite root: {root}")
    validate_sources(repo)
    for key, def_stem in EXPECTED.items():
        validate_folder(root, key, def_stem)
    actual_dirs = {path.name for path in root.iterdir() if path.is_dir()}
    require(actual_dirs == set(EXPECTED), f"unexpected boat sprite folders: missing={sorted(set(EXPECTED) - actual_dirs)} extra={sorted(actual_dirs - set(EXPECTED))}")
    print("HoMM3 boat map sprite contract OK")


if __name__ == "__main__":
    main()
