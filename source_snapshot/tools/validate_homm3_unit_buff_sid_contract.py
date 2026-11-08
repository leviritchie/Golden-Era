#!/usr/bin/env python3
"""Fail-closed: custom unit ability buff SIDs must exist in Core buff tables.

Hire / ability UI constructs native ability wrappers that look up BuffConfig by SID.
A missing buff SID becomes a null BuffConfig and NREs BhHireUnitItemView.UpdateView
(and Unit.Init ability init). Do not invent bare spell-family names; use the exact
leveled ids from DB/buffs/*.json (e.g. magic_optical_illusion_effect_0, not
magic_optical_illusion_effect).
"""

from __future__ import annotations

import argparse
import json
import re
import zipfile
from pathlib import Path
from typing import Any


def fail(message: str) -> None:
    raise SystemExit("homm3-unit-buff-sid-contract: " + message)


def load_core_buff_ids(core_path: Path) -> set[str]:
    if not core_path.is_file():
        fail(f"missing Core.zip: {core_path}")
    ids: set[str] = set()
    with zipfile.ZipFile(core_path) as zf:
        for name in zf.namelist():
            if not name.startswith("DB/buffs/") or not name.endswith(".json"):
                continue
            data = json.loads(zf.read(name))
            rows = data.get("array") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"].strip():
                    ids.add(row["id"].strip())
    if not ids:
        fail(f"no buff ids found under DB/buffs/ in {core_path}")
    return ids


def collect_buff_sids_from_obj(obj: Any, found: set[str]) -> None:
    if isinstance(obj, dict):
        buff = obj.get("buff")
        if isinstance(buff, dict) and isinstance(buff.get("sid"), str) and buff["sid"].strip():
            found.add(buff["sid"].strip())
        buff_sid = obj.get("buffSid")
        if isinstance(buff_sid, str) and buff_sid.strip():
            found.add(buff_sid.strip())
        for value in obj.values():
            collect_buff_sids_from_obj(value, found)
    elif isinstance(obj, list):
        for item in obj:
            collect_buff_sids_from_obj(item, found)


def validate_ability_overrides(repo: Path, buff_ids: set[str]) -> list[str]:
    errors: list[str] = []
    override_dir = repo / "custom_factions" / "ability_overrides"
    if not override_dir.is_dir():
        fail(f"missing ability overrides dir: {override_dir}")
    for path in sorted(override_dir.glob("homm3_*.json")):
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
        found: set[str] = set()
        collect_buff_sids_from_obj(doc, found)
        for sid in sorted(found):
            if sid not in buff_ids:
                errors.append(f"{path.name}: unknown buff SID {sid!r} (not in Core DB/buffs)")
    return errors


def validate_overlay_after_shot_map(repo: Path, buff_ids: set[str]) -> list[str]:
    errors: list[str] = []
    overlay = repo / "tools" / "release_port" / "apply_release_core_overlay.py"
    text = overlay.read_text(encoding="utf-8")
    match = re.search(r"BULWARK_AFTER_SHOT_ICE_BY_SID\s*=\s*\{(.*?)\n\}", text, re.S)
    if not match:
        fail("apply_release_core_overlay.py missing BULWARK_AFTER_SHOT_ICE_BY_SID map")
    for sid in re.findall(r'":\s*"([^"]+)"', match.group(1)):
        if sid not in buff_ids:
            errors.append(f"BULWARK_AFTER_SHOT_ICE_BY_SID value {sid!r} not in Core DB/buffs")
    return errors


def validate_core_unit_logics(core_path: Path, buff_ids: set[str], faction_filter: str | None) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(core_path) as zf:
        for name in sorted(zf.namelist()):
            if not name.startswith("DB/units/units_logics/") or not name.endswith("_l.json"):
                continue
            if faction_filter and f"/{faction_filter}/" not in name:
                continue
            if "/homm3_" not in name:
                continue
            data = json.loads(zf.read(name))
            found: set[str] = set()
            collect_buff_sids_from_obj(data, found)
            unit_sid = name.rsplit("/", 1)[-1].replace("_l.json", "")
            for sid in sorted(found):
                if sid not in buff_ids:
                    errors.append(f"Core {name}: unit {unit_sid} references unknown buff SID {sid!r}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--core",
        type=Path,
        default=None,
        help="Core.zip used as the buff-id authority (defaults to Golden Era install when present)",
    )
    parser.add_argument(
        "--check-core-units",
        action="store_true",
        help="Also scan installed/candidate Core custom unit logics for unknown buff SIDs",
    )
    parser.add_argument(
        "--faction",
        default=None,
        help="When --check-core-units, only scan DB/units/units_logics/<faction>/",
    )
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    core = args.core
    if core is None:
        core = Path(
            r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
            r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
        )
    core = core.resolve()
    buff_ids = load_core_buff_ids(core)
    errors = validate_ability_overrides(repo, buff_ids)
    errors.extend(validate_overlay_after_shot_map(repo, buff_ids))
    if args.check_core_units:
        errors.extend(validate_core_unit_logics(core, buff_ids, args.faction))
    if errors:
        for err in errors:
            print(err, flush=True)
        fail(f"{len(errors)} unknown buff SID reference(s)")
    print(
        f"homm3-unit-buff-sid-contract: OK ({len(buff_ids)} Core buff ids; ability_overrides + after-shot map)"
    )


if __name__ == "__main__":
    main()
