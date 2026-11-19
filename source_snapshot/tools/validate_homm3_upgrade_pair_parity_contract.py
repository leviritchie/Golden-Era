#!/usr/bin/env python3
"""Gate: HoMM3 faction unit lines follow vanilla's upgrade-pair bookkeeping.

    python tools/validate_homm3_upgrade_pair_parity_contract.py [--core Core.zip]

Contract: custom_factions/contracts/homm3_upgrade_pair_parity_20261116.json, applied by
tools/release_port/homm3_upgrade_pair_parity.py inside apply_release_core_overlay.py.

Fails when, on any base -> upgrade / alternate-upgrade line the enabled faction manifests
declare (unitLines + additionalRecruitmentLines):
  * the upgrade and the alternate upgrade differ in cost (any resource), squadValue or expBonus;
  * an upgrade or alternate upgrade has hp, offence, defence, damageMin, damageMax, initiative
    or speed below its base form;
  * a line unit's expBonus is not round_half_up(squadValue * the contract's tier ratio);
  * a contract lineStatOverrides value does not read back;
  * a Core h3_* base -> upgrade -> alternate chain of a custom faction is not a manifest line
    (it would escape the rules above).

The default Core is the installed Golden Era Core.zip (deployed-payload readback, read only).
Proof tier: generated artifact or deployed payload, whichever Core is passed. Not runtime proof.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "release_port"))
import homm3_upgrade_pair_parity as parity  # noqa: E402

CORE_ZIP = Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
                "/HeroesOldenEra_Data/StreamingAssets/Core.zip")


def load_logic_rows(core: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with zipfile.ZipFile(core) as archive:
        for name in archive.namelist():
            if not name.startswith(parity.LOGIC_PREFIX) or not name.endswith(".json"):
                continue
            for row in json.loads(archive.read(name).decode("utf-8-sig")).get("array") or []:
                if isinstance(row, dict) and isinstance(row.get("id"), str):
                    rows[row["id"]] = row
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--core", "--core-zip", dest="core", type=Path, default=CORE_ZIP)
    args = parser.parse_args()
    try:
        contract = parity.load_contract()
        manifests = parity.load_enabled_manifests()
        lines = parity.unit_lines(manifests)
        rows = load_logic_rows(args.core)
    except (RuntimeError, OSError, KeyError, ValueError, zipfile.BadZipFile) as ex:
        print(f"ERROR: {ex}")
        return 1

    errors = parity.check_rows(rows, lines, contract)
    faction_sids = {manifest["identity"]["factionSid"] for manifest in manifests}
    line_sids = {sid for line in lines for sid in line[1:]}
    for sid, row in sorted(rows.items()):
        if row.get("fraction") in faction_sids and (row.get("upgradeSid") or row.get("baseSid")) and sid not in line_sids:
            errors.append(f"{sid}: {row.get('fraction')} unit with an upgrade link is not on a manifest unit line")

    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"HoMM3 upgrade pair parity contract FAILED: {len(errors)} error(s) over {len(lines)} lines in {args.core}")
        return 1
    print(f"HoMM3 upgrade pair parity contract OK: {len(lines)} lines, {len(line_sids)} units in {args.core}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
