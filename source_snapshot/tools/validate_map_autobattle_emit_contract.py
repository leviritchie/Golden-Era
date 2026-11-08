#!/usr/bin/env python3
"""Fail-closed: generated maps allow auto-battle vs neutrals, not vs enemy heroes.

Policy (source/static):
  - propRandomSquads.isAutobatle = true for emitted neutrals/guards
  - settings.disableAutoBattleAgainstEnemyHeroes = true

Runtime auto-battle UI remains unproven until exercised in Golden Era.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
APPROACH = POC / "approach_cell"


def _load(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    errors: list[str] = []

    if str(POC) not in sys.path:
        sys.path.insert(0, str(POC))
    if str(APPROACH) not in sys.path:
        sys.path.insert(0, str(APPROACH))

    surface = _load("surface_emit_autobattle_contract", APPROACH / "surface_emit.py")
    guard_row = surface.map_event_guard_prop_random_squad_row(
        7,
        squad_overlay_sid="contract_guard_squad",
        stacks=[{"sid": "unit_placeholder", "valueBudget": 100}],
    )
    if guard_row.get("isAutobatle") is not True:
        errors.append(
            "surface_emit.map_event_guard_prop_random_squad_row must set isAutobatle=true; "
            f"got {guard_row.get('isAutobatle')!r}"
        )

    from procedural_scenarios.emitter import SCENARIO_SETTINGS  # noqa: WPS433

    if SCENARIO_SETTINGS.get("disableAutoBattleAgainstEnemyHeroes") is not True:
        errors.append(
            "procedural SCENARIO_SETTINGS.disableAutoBattleAgainstEnemyHeroes must be true; "
            f"got {SCENARIO_SETTINGS.get('disableAutoBattleAgainstEnemyHeroes')!r}"
        )

    for rel, needle in (
        (
            "experiments/campaign_port_poc/approach_cell/surface_emit.py",
            'native_settings["disableAutoBattleAgainstEnemyHeroes"] = True',
        ),
        (
            "experiments/campaign_port_poc/raw_translation/build_raw_translation_map.py",
            'native_settings["disableAutoBattleAgainstEnemyHeroes"] = True',
        ),
        (
            "experiments/campaign_port_poc/vanilla_stock/emit_map.py",
            'settings["disableAutoBattleAgainstEnemyHeroes"] = True',
        ),
        (
            "experiments/campaign_port_poc/vanilla_stock/victory_events.py",
            '"isAutobatle": True',
        ),
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if needle not in text:
            errors.append(f"{rel} missing assignment: {needle}")

    # Catch regressions that reintroduce False defaults on emit paths.
    for rel in (
        "experiments/campaign_port_poc/approach_cell/surface_emit.py",
        "experiments/campaign_port_poc/vanilla_stock/victory_events.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        if '"isAutobatle": False' in text:
            errors.append(
                f"{rel} still contains \"isAutobatle\": False; "
                "neutrals/guards must emit true (enemy-hero auto is settings-gated)"
            )

    if errors:
        print(json.dumps({"ok": False, "errors": errors}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "policy": "autobattle_neutrals_yes_enemy_heroes_no",
                "proof": "source/static",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
