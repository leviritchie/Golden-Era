#!/usr/bin/env python3
"""Fail closed when native unit-box rewards cannot draw custom-faction units.

Pandora's box / chest variants of type ``HeroBoxUnitReward`` and
``HeroBoxOptionalVersionUnitReward`` pick their unit from
``DB/reward_units_container.json`` filtered by tier, fraction and version. A
faction with no rows there makes the native reward builder drop the reward, so
the object opens an empty reward set and does nothing.

Static: the Core overlay must own the pricing step.
Installed readback (``--core``): every unit of a core-enabled custom faction
(tiers 1..7) has exactly one positive reward row.
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools" / "release_port"))

from homm3_reward_units_core_overlay import (  # noqa: E402
    REWARD_UNITS_MEMBER,
    UNIT_LOGICS_PREFIX,
    _loads_lenient,
    load_unit_logic_rows,
    missing_reward_unit_rows,
)


def fail(message: str) -> None:
    print(f"custom-faction-reward-units: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--core", type=Path, help="Core.zip to read back (installed or staged)")
    args = parser.parse_args()

    overlay = (args.repo_root / "tools" / "release_port" / "apply_release_core_overlay.py").read_text(encoding="utf-8")
    for needle in (
        "from homm3_reward_units_core_overlay import add_custom_faction_reward_units",
        "add_custom_faction_reward_units(\n                release_zip, output, notes, CORE_ENABLED_FACTION_SIDS, write_json\n            )",
        "run_custom_faction_reward_units_validation(release_core)",
    ):
        if needle not in overlay:
            fail("apply_release_core_overlay.py no longer owns the reward-units step: " + needle.splitlines()[0])

    if args.core is None:
        print("validated custom-faction reward-units overlay wiring (source/static)")
        return

    core = args.core.resolve()
    if not core.is_file():
        fail(f"missing Core.zip: {core}")
    with zipfile.ZipFile(core) as zf:
        names = zf.namelist()
        if REWARD_UNITS_MEMBER not in names:
            fail(f"{core} has no {REWARD_UNITS_MEMBER}")
        members = {n: zf.read(n) for n in names if n.startswith(UNIT_LOGICS_PREFIX) and n.endswith(".json")}
        container = _loads_lenient(zf.read(REWARD_UNITS_MEMBER))
    unit_rows = load_unit_logic_rows(members)
    from apply_release_core_overlay import CORE_ENABLED_FACTION_SIDS  # manifest-derived faction set

    if not CORE_ENABLED_FACTION_SIDS:
        fail("no core-enabled custom factions resolved from manifests")
    problems = missing_reward_unit_rows(container, unit_rows, CORE_ENABLED_FACTION_SIDS)
    if problems:
        shown = "\n  ".join(problems[:40])
        more = f"\n  ... {len(problems) - 40} more" if len(problems) > 40 else ""
        fail(f"{len(problems)} reward-unit contract violation(s) in {core}:\n  {shown}{more}")
    count = len(container.get("unitsArr", []))
    print(f"validated {REWARD_UNITS_MEMBER} in {core}: {count} rows cover every unit of {len(CORE_ENABLED_FACTION_SIDS)} custom factions (tiers 1..7)")


if __name__ == "__main__":
    main()
