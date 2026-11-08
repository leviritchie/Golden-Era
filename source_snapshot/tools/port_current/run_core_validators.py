"""Run every Core-reading validator against one or more Core.zip files and tabulate return codes.

The validator list is the repo's validators that take a Core path (``--core`` or ``--core-zip``);
``validate_procedural_scenario_contract`` is excluded because its ``--core`` only feeds the
explicit expensive audit. Output is a JSON table {validator: {label: {rc, tail}}}.

    python tools/port_current/run_core_validators.py --out report.json \
        --core rebuilt_25509697=path/a.zip --core golden=path/b.zip

Proof tier: whatever the validators prove on a generated Core (generated artifact at most).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# (script, core flag, *extra args)
VALIDATORS: tuple[tuple[str, ...], ...] = (
    ("tools/release_port/validate_city_construction_tree_layout.py", "--core"),
    ("tools/release_port/validate_custom_faction_design_contract.py", "--core"),
    ("tools/release_port/validate_custom_law_core_metadata.py", "--core"),
    ("tools/release_port/validate_custom_law_strict_no_compromise_rows.py", "--core"),
    ("tools/release_port/validate_homm3_city_building_contracts.py", "--core"),
    ("tools/release_port/validate_homm3_city_building_descriptions_contract.py", "--core"),
    ("tools/release_port/validate_homm3_city_building_tree_contract.py", "--core"),
    ("tools/release_port/validate_multilingual_custom_lang.py", "--core"),
    ("tools/validate_campaign_dialog_portrait_contract.py", "--core-zip"),
    ("tools/validate_campaign_port_scenario_menu_contract.py", "--core-zip"),
    ("tools/validate_campaign_town_name_contract.py", "--core-zip"),
    ("tools/validate_custom_faction_manifests.py", "--core"),
    ("tools/validate_custom_faction_reward_units_contract.py", "--core"),
    ("tools/validate_h3_campaign_placed_heroes_contract.py", "--core-zip"),
    ("tools/validate_homm3_active_ability_localization_contract.py", "--core-zip"),
    ("tools/validate_homm3_artifact_port_contract.py", "--core"),
    ("tools/validate_homm3_bulwark_ability_repair_contract.py", "--core"),
    ("tools/validate_homm3_bulwark_runes_installed_combat_audit.py", "--core"),
    ("tools/validate_homm3_campaign_heroes_roster_separation_contract.py", "--core-zip"),
    ("tools/validate_homm3_city_music_sidecar_contract.py", "--core-zip"),
    ("tools/validate_homm3_conflux_focus_spell_power_contract.py", "--core", "--repo-root", "."),
    ("tools/validate_homm3_custom_biome_runtime_contract.py", "--core"),
    ("tools/validate_homm3_custom_hero_levelup_skill_contract.py", "--core"),
    ("tools/validate_homm3_custom_hero_start_skill_contract.py", "--core"),
    ("tools/validate_homm3_factory_bulwark_projectile_donor_contract.py", "--core-zip"),
    ("tools/validate_homm3_hero_portrait_parity.py", "--core-zip"),
    ("tools/validate_homm3_inferno_gating_hex_effect_contract.py", "--core", "--repo-root", "."),
    ("tools/validate_homm3_landon_dwelling_localization_contract.py", "--core"),
    ("tools/validate_homm3_masterful_spell_description_contract.py", "--core"),
    ("tools/validate_homm3_neutral_catalog_contract.py", "--core-zip"),
    ("tools/validate_homm3_owned_attack_animation_slots.py", "--core"),
    ("tools/validate_homm3_owned_skinned_attack_clip_contract.py", "--core"),
    ("tools/validate_homm3_tower_arcane_battery_contract.py", "--core"),
    ("tools/validate_homm3_unit_ability_redesign_contract.py", "--core", "--repo-root", "."),
    ("tools/validate_homm3_unit_balance_adjustment_contract.py", "--core-zip"),
    ("tools/validate_homm3_unit_buff_sid_contract.py", "--core"),
    ("tools/validate_homm3_unit_presentation_stopgap_contract.py", "--core"),
    ("tools/validate_scenery_footprint_oe_larger_contract.py", "--core"),
    ("tools/validate_unit_battle_ai_contract.py", "--core"),
    ("tools/validate_unit_move_speed_normalization_contract.py", "--core-zip"),
    ("tools/validate_unit_upgrade_cost_delta_contract.py", "--core-zip"),
)


# Validators whose Core readback is pinned per game build (native neutral tier bands).
NEUTRAL_BAND_TARGET_VALIDATORS = {
    "tools/validate_custom_faction_manifests.py",
    "tools/validate_homm3_neutral_catalog_contract.py",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", action="append", required=True, help="label=path/to/Core.zip")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--only", action="append", default=None, help="substring filter on validator path")
    ap.add_argument("--neutral-band-target", choices=("golden_era", "steam_25509697", "steam_25672315"), required=True,
                    help="game build every --core is for; passed to the validators with target-pinned readbacks")
    args = ap.parse_args()
    cores = {}
    for item in args.core:
        label, _, path = item.partition("=")
        p = Path(path).resolve()
        if not p.is_file():
            raise SystemExit(f"missing Core for {label}: {p}")
        if "steamapps/common/" in str(p).replace("\\", "/").lower():
            raise SystemExit(f"refusing to validate a live install path directly: {p}")
        cores[label] = p
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    table: dict[str, dict[str, dict]] = {}
    for script, flag, *extra in VALIDATORS:
        if args.only and not any(o in script for o in args.only):
            continue
        table[script] = {}
        for label, core in cores.items():
            t0 = time.perf_counter()
            try:
                target_args = (["--neutral-band-target", args.neutral_band_target]
                               if script in NEUTRAL_BAND_TARGET_VALIDATORS else [])
                proc = subprocess.run([sys.executable, script, flag, str(core), *extra, *target_args], cwd=REPO, env=env,
                                      capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=args.timeout)
                rc, text = proc.returncode, (proc.stdout + proc.stderr)
            except subprocess.TimeoutExpired:
                rc, text = "timeout", ""
            lines = [ln for ln in text.splitlines() if ln.strip()]
            table[script][label] = {"rc": rc, "sec": round(time.perf_counter() - t0, 1), "tail": lines[-6:]}
            print(f"{rc!s:>7} {label:<22} {script}", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"cores": {k: str(v) for k, v in cores.items()}, "results": table},
                                   indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
