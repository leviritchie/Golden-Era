#!/usr/bin/env python3
"""Fail closed when HoMM3 town music would layer donor BGM under a sidecar track.

When tools/homm3_import/build_out/<faction>_city_music exists, Core
DB/city_music_sounds.json must use sounds/city/music/<faction_sid> (Stronghold
pattern). Donor sets (human/nature/demon/…) plus Homm3StrongholdCityMusic cause
overlapping town music.

Proof boundary: source/static + optional installed Core.zip readback.
Does not claim runtime audible proof.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

ROOT_DEFAULT = Path(__file__).resolve().parents[1]
OVERLAY = Path("tools") / "release_port" / "apply_release_core_overlay.py"
TOWER_OVERLAY = Path("tools") / "apply_homm3_tower_overlay.py"
CITY_MUSIC = Path("Heroes of Might & Magic Olden Era Playtest") / "OfflineUnlockMod" / "Homm3StrongholdCityMusic.cs"
CSPROJ = Path("Heroes of Might & Magic Olden Era Playtest") / "OfflineUnlockMod" / "OfflineUnlockMod.csproj"
PARADIGM = Path("docs") / "custom_town_scene_paradigm.md"
BUILD_OUT = Path("tools") / "homm3_import" / "build_out"
DEFAULT_CORE = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"homm3 city music sidecar contract failed: {message}")


def expected_sound_set(faction_sid: str) -> str:
    return f"sounds/city/music/{faction_sid}"


def list_sidecar_factions(repo: Path) -> list[str]:
    build_out = repo / BUILD_OUT
    require(build_out.is_dir(), f"missing {BUILD_OUT.as_posix()}")
    sids: list[str] = []
    for path in sorted(build_out.glob("homm3_*_city_music")):
        if not path.is_file():
            continue
        name = path.name
        if not name.endswith("_city_music"):
            continue
        sid = name[: -len("_city_music")]
        if sid.startswith("homm3_"):
            sids.append(sid)
    require(bool(sids), f"no {BUILD_OUT.as_posix()}/homm3_*_city_music bundles found")
    return sids


def read_city_music_rows(core_zip: Path) -> dict[str, str]:
    with zipfile.ZipFile(core_zip, "r") as zf:
        raw = zf.read("DB/city_music_sounds.json")
    doc = json.loads(raw.decode("utf-8-sig"))
    rows = ((doc.get("array") or {}).get("data")) if isinstance(doc, dict) else None
    require(isinstance(rows, list), f"{core_zip}: city_music_sounds missing array.data")
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get("key")
        val = row.get("val") if isinstance(row.get("val"), dict) else {}
        name = val.get("soundSetName") if isinstance(val, dict) else None
        if isinstance(key, str) and isinstance(name, str):
            out[key] = name
    return out


def validate_source(repo: Path) -> list[str]:
    errors: list[str] = []
    for rel in (OVERLAY, TOWER_OVERLAY, CITY_MUSIC, CSPROJ, PARADIGM):
        if not (repo / rel).is_file():
            errors.append(f"missing {rel.as_posix()}")

    overlay = (repo / OVERLAY).read_text(encoding="utf-8")
    for needle in (
        "faction_has_city_music_sidecar",
        "city_music_sound_set_name_for_faction",
        'music_val["soundSetName"] = city_music_sound_set_name_for_faction(faction_sid)',
        "route sidecar town music away from donor sets",
        "has_sidecar and existing_set != desired_set",
    ):
        if needle not in overlay:
            errors.append(f"{OVERLAY.as_posix()}: missing {needle}")

    tower = (repo / TOWER_OVERLAY).read_text(encoding="utf-8")
    if 'human_val["soundSetName"] = "sounds/city/music/" + FRACTION_ID' not in tower:
        errors.append(
            f"{TOWER_OVERLAY.as_posix()}: Tower city music must use faction key, not human donor"
        )
    if 'soundSetName"] = "sounds/city/music/human"' in tower:
        errors.append(f"{TOWER_OVERLAY.as_posix()}: still hardcodes human donor town music")

    city_music = (repo / CITY_MUSIC).read_text(encoding="utf-8")
    if "EnsureTownMusicPlaying" not in city_music:
        errors.append(f"{CITY_MUSIC.as_posix()}: missing EnsureTownMusicPlaying")

    paradigm = (repo / PARADIGM).read_text(encoding="utf-8")
    if "town music" not in paradigm.lower() and "city_music" not in paradigm:
        errors.append(f"{PARADIGM.as_posix()}: must mention town music / city_music ownership")

    csproj = (repo / CSPROJ).read_text(encoding="utf-8")
    if "validate_homm3_city_music_sidecar_contract.py" not in csproj:
        errors.append(f"{CSPROJ.as_posix()}: must wire validate_homm3_city_music_sidecar_contract.py")

    return errors


def validate_installed_core(core_zip: Path, sidecar_factions: list[str]) -> list[str]:
    errors: list[str] = []
    if not core_zip.is_file():
        errors.append(f"missing Core.zip: {core_zip}")
        return errors
    rows = read_city_music_rows(core_zip)
    for sid in sidecar_factions:
        sound_set = rows.get(sid)
        expected = expected_sound_set(sid)
        if sound_set is None:
            errors.append(f"installed Core missing city_music row for {sid}")
            continue
        if sound_set != expected:
            errors.append(
                f"installed Core {sid} soundSetName={sound_set!r} must be {expected!r} "
                "(donor+sidecar double music)"
            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=ROOT_DEFAULT)
    parser.add_argument(
        "--core-zip",
        type=Path,
        default=None,
        help="Optional Core.zip to assert installed music rows.",
    )
    parser.add_argument(
        "--require-installed",
        action="store_true",
        help="Fail if Core.zip is missing.",
    )
    parser.add_argument(
        "--skip-installed",
        action="store_true",
        help="Source-only checks (do not read Core.zip even if present).",
    )
    args = parser.parse_args()
    repo: Path = args.repo_root

    errors = validate_source(repo)
    sidecar_factions = list_sidecar_factions(repo) if not errors else []

    core_zip = args.core_zip
    if core_zip is None and not args.skip_installed:
        if DEFAULT_CORE.is_file():
            core_zip = DEFAULT_CORE

    if args.require_installed:
        require(core_zip is not None and core_zip.is_file(), "--require-installed needs a readable Core.zip")
        errors.extend(validate_installed_core(core_zip, sidecar_factions))
    elif not args.skip_installed and core_zip is not None and core_zip.is_file() and sidecar_factions:
        errors.extend(validate_installed_core(core_zip, sidecar_factions))

    if errors:
        for err in errors:
            print(f"ERROR: {err}")
        raise SystemExit(1)

    print(
        "homm3 city music sidecar contract OK: "
        + f"{len(sidecar_factions)} sidecar faction(s) must use faction soundSetName keys"
        + (f"; Core={core_zip}" if core_zip and core_zip.is_file() else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
