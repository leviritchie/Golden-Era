#!/usr/bin/env python3
"""Materialize unit corpus frames for the authentic DEF-source picker.

The mocap corpus already contains the original grouped sprite frames used to
fit the six Castle pilots.  The picker expects those frames in its lab layout:
``<unit>/extracted_battle_source_12fps/<name>.dir/GG_FF.png``.  This tool makes
that layout reproducibly without touching an installed Unity or game tree.

This is source-prepared evidence only.  It does not claim a fit, a bundle, or
runtime/gameplay proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "artifacts/homm3_mocap_v2/skin_mesh_pilot"
DEFAULT_OUTPUT = ROOT / "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_lab"
SCHEMA = "homm3-mocap-lab-source-materialization.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected an object")
    return value


def _absolute(path_value: str | Path, *, base: Path) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        path = base / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _frame_list(value: Any, *, label: str, base: Path) -> list[Path]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        raise ValueError(f"{label}: expected a path or list of paths")
    result = [_absolute(item, base=base) for item in values]
    if not result:
        raise ValueError(f"{label}: frame list is empty")
    return result


def _groups(manifest: dict[str, Any], *, manifest_path: Path) -> dict[int, list[Path]]:
    base = manifest_path.parent
    idle_value = manifest.get("idle")
    # Older corpus manifests pin idle by its first frame only.  In that form,
    # consume the complete numbered sibling directory rather than silently
    # producing a one-frame idle group.
    if isinstance(idle_value, str):
        idle_first = _absolute(idle_value, base=base)
        siblings = sorted(
            (path for path in idle_first.parent.glob("*.png") if path.is_file()),
            key=lambda path: path.name.lower(),
        )
        idle = siblings or [idle_first]
    else:
        idle = _frame_list(idle_value, label=f"{manifest_path}: idle", base=base)
    groups: dict[int, list[Path]] = {2: idle}
    clips = manifest.get("clips")
    if not isinstance(clips, list):
        raise ValueError(f"{manifest_path}: clips must be a list")
    for index, clip in enumerate(clips):
        if not isinstance(clip, dict):
            raise ValueError(f"{manifest_path}: clips[{index}] is not an object")
        try:
            group = int(clip["group"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{manifest_path}: clips[{index}] has no integer group") from exc
        frames = _frame_list(clip.get("frames"), label=f"{manifest_path}: clips[{index}]", base=base)
        if group in groups:
            # Corpus manifests repeat idle as context around other clips.  A
            # repeated group must be byte-identical, never silently replaced.
            prior = groups[group]
            if len(prior) != len(frames) or [_sha256(path) for path in prior] != [_sha256(path) for path in frames]:
                raise ValueError(f"{manifest_path}: conflicting frame lists for group {group}")
            continue
        groups[group] = frames
    return dict(sorted(groups.items()))


def _manifest_candidates(input_root: Path, unit: str) -> list[Path]:
    # Corpus folders predate the lab SIDs and usually omit ``h3_``/``toa_``.
    # Accept only deterministic aliases; never fuzzy-match a different unit.
    aliases = [unit]
    for prefix in ("h3_", "toa_"):
        if unit.startswith(prefix):
            aliases.append(unit[len(prefix) :])
    candidates: list[Path] = []
    for alias in dict.fromkeys(aliases):
        unit_dir = input_root / alias
        if unit_dir.is_dir():
            candidates.extend(unit_dir.glob("source_*/manifest.json"))
    return sorted(candidates, key=lambda path: (path.parent.parent.name, path.parent.name))


def _select_manifest(input_root: Path, unit: str) -> Path:
    candidates = _manifest_candidates(input_root, unit)
    if not candidates:
        raise FileNotFoundError(f"no source_*/manifest.json for {unit} under {input_root}")
    return candidates[-1]


def materialize_one(*, unit: str, manifest_path: Path, output_root: Path, overwrite: bool) -> dict[str, Any]:
    manifest = _read(manifest_path)
    declared = str(manifest.get("unit") or "").strip()
    if declared != unit:
        raise ValueError(f"{manifest_path}: manifest unit {declared!r} != requested {unit!r}")
    groups = _groups(manifest, manifest_path=manifest_path)
    destination = output_root / unit / "extracted_battle_source_12fps" / f"materialized_{unit}.dir"
    marker = destination / "materialization.json"
    if destination.exists():
        if not overwrite and marker.is_file():
            prior = _read(marker)
            if prior.get("manifestSha256") == _sha256(manifest_path):
                return prior
            raise FileExistsError(f"{destination} exists with different provenance; pass --overwrite")
        if not overwrite:
            raise FileExistsError(f"{destination} exists; pass --overwrite")
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=False)
    rows: list[dict[str, Any]] = []
    for group, frames in groups.items():
        for frame_index, source in enumerate(frames):
            target = destination / f"{group:02d}_{frame_index:02d}.png"
            shutil.copy2(source, target)
            rows.append({
                "group": group,
                "frame": frame_index,
                "source": str(source).replace("\\", "/"),
                "sourceSha256": _sha256(source),
                "target": str(target).replace("\\", "/"),
            })
    result = {
        "schema": SCHEMA,
        "proof": "source-prepared",
        "unit": unit,
        "manifest": str(manifest_path.resolve()).replace("\\", "/"),
        "manifestSha256": _sha256(manifest_path),
        "output": str(destination.resolve()).replace("\\", "/"),
        "groups": {str(group): len(frames) for group, frames in groups.items()},
        "frames": rows,
        "runtimeClaim": False,
    }
    marker.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def run(*, input_root: Path, output_root: Path, units: list[str], overwrite: bool) -> dict[str, Any]:
    rows = []
    for unit in units:
        manifest_path = _select_manifest(input_root, unit)
        rows.append(materialize_one(unit=unit, manifest_path=manifest_path, output_root=output_root, overwrite=overwrite))
    result = {
        "schema": SCHEMA,
        "proof": "source-prepared",
        "inputRoot": str(input_root.resolve()).replace("\\", "/"),
        "outputRoot": str(output_root.resolve()).replace("\\", "/"),
        "units": rows,
        "runtimeClaim": False,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "materialization_manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--unit", default="all", help="unit SID, comma-separated, or all discovered source manifests")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    input_root = args.input_root.resolve()
    output_root = args.output_root.resolve()
    if args.unit.strip().lower() == "all":
        units = sorted({path.parent.parent.name for path in input_root.glob("*/source_*/manifest.json")})
    else:
        units = [part.strip() for part in args.unit.split(",") if part.strip()]
    if not units:
        raise ValueError("no units selected")
    result = run(input_root=input_root, output_root=output_root, units=units, overwrite=args.overwrite)
    print(json.dumps({"ok": True, "units": len(result["units"]), "outputRoot": result["outputRoot"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
