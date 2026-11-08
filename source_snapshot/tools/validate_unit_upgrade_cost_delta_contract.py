"""No unit upgrade may have a negative cost delta in any resource.

    python tools/validate_unit_upgrade_cost_delta_contract.py [--core-zip Z]

Olden Era charges an upgrade as (target unitCost - source unitCost) per resource. A target cheaper
than any unit it can be upgraded from in any resource pays the player for upgrading (2026-10-01:
Iron Golem and Magnetic Golem paid 10 gold each after Stone Golem was raised to 210 gold).

Contract, over every DB/units/units_logics row in the Core (vanilla and custom alike):
  * Upgrade links are consistent: a row's upgradeSid names an existing row whose baseSid points
    back, and a row's baseSid names an existing row.
  * For each row and every ancestor on its baseSid chain (an alt upgrade's chain runs
    base -> upg -> upg_alt, and the game prices the alt from the base too), the row's cost is at
    least the ancestor's cost in every resource either of them lists. Zero is allowed.

The default Core is the installed Golden Era Core.zip (deployed-payload readback, read only).
Pass --core-zip for a generated candidate.
Proof tier: generated artifact or deployed payload, whichever Core is passed. Not runtime proof.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable

CORE_ZIP = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
                "/HeroesOldenEra_Data/StreamingAssets/Core.zip")
LOGIC_PREFIX = "DB/units/units_logics/"


def cost_map(row: dict[str, Any], where: str, err: list[str]) -> dict[str, int]:
    unit_cost = row.get("unitCost")
    rows = unit_cost.get("costResArray") if isinstance(unit_cost, dict) else None
    if not isinstance(rows, list):
        err.append(f"{where}: unitCost.costResArray is missing or malformed")
        return {}
    out: dict[str, int] = {}
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("cost"), int):
            err.append(f"{where}: malformed cost entry {item!r}")
            continue
        out[item["name"]] = out.get(item["name"], 0) + item["cost"]
    return out


def as_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return [v for v in value if v]
    return [repr(value)]


def unit_rows_from_members(members: Iterable[str], read: Callable[[str], bytes]) -> tuple[dict[str, tuple[str, dict[str, Any]]], list[str]]:
    units: dict[str, tuple[str, dict[str, Any]]] = {}
    err: list[str] = []
    for member in sorted(members):
        if not member.startswith(LOGIC_PREFIX) or not member.endswith(".json"):
            continue
        try:
            doc = json.loads(read(member).decode("utf-8-sig"))
        except Exception as ex:  # noqa: BLE001 - fail closed with the member name.
            err.append(f"{member}: cannot parse JSON: {ex}")
            continue
        rows = doc.get("array") if isinstance(doc, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                continue
            if row["id"] in units:
                err.append(f"{row['id']}: duplicate unit logic row in {units[row['id']][0]} and {member}")
                continue
            units[row["id"]] = (member, row)
    return units, err


def upgrade_cost_delta_errors(units: dict[str, tuple[str, dict[str, Any]]]) -> list[str]:
    err: list[str] = []
    costs = {sid: cost_map(row, sid, err) for sid, (_m, row) in units.items()}
    for sid, (_member, row) in sorted(units.items()):
        for up in as_list(row.get("upgradeSid")):
            target = units.get(up)
            if target is None:
                err.append(f"{sid}: upgradeSid {up!r} has no unit logic row")
            elif target[1].get("baseSid") != sid:
                err.append(f"{sid}: upgradeSid {up!r} but {up}.baseSid is {target[1].get('baseSid')!r}")
        base = row.get("baseSid")
        seen = {sid}
        while base:
            if not isinstance(base, str) or base not in units:
                err.append(f"{sid}: baseSid chain names missing unit {base!r}")
                break
            if base in seen:
                err.append(f"{sid}: baseSid chain loops at {base!r}")
                break
            seen.add(base)
            mine, theirs = costs[sid], costs[base]
            for res in sorted(set(mine) | set(theirs)):
                delta = mine.get(res, 0) - theirs.get(res, 0)
                if delta < 0:
                    err.append(f"{sid}: upgrading from {base} pays {-delta} {res} "
                               f"({base} costs {theirs.get(res, 0)}, {sid} costs {mine.get(res, 0)})")
            base = units[base][1].get("baseSid")
    return err


def errors(core_zip: Path) -> tuple[list[str], int]:
    if not core_zip.is_file():
        return [f"Core.zip not found: {core_zip}"], 0
    with zipfile.ZipFile(core_zip) as z:
        units, err = unit_rows_from_members(z.namelist(), z.read)
    if not units:
        err.append(f"{core_zip}: no unit logic rows found")
    return err + upgrade_cost_delta_errors(units), len(units)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--core-zip", type=Path, default=CORE_ZIP)
    a = ap.parse_args(argv)
    err, count = errors(a.core_zip)
    for e in err:
        print("FAIL", e)
    print(("OK" if not err else "FAILED") + f" unit upgrade cost delta: {count} unit rows, {len(err)} violation(s), core={a.core_zip}")
    return 1 if err else 0


if __name__ == "__main__":
    sys.exit(main())
