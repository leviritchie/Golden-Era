"""Run every Core-reading validator against one or more Core.zip files and tabulate return codes.

The validator list is the repo's validators that take a Core path (``--core`` or ``--core-zip``);
``validate_procedural_scenario_contract`` is excluded because its ``--core`` only feeds the
explicit expensive audit. Output is a JSON table {validator: {label: {rc, tail}}}.

``validate_homm3_owned_skinned_attack_clip_contract`` also reads the owned-skinned battle bundles. It gets them
from the same plugin payload the release stages (tools/nightly/stage_release_payload.ps1 copies
<GameRoot>/BepInEx/plugins/OfflineUnlockMod): ``<--plugin-root>/homm3_bundles`` and
``<--plugin-root>/homm3_import.json``, with one ``--name-prefix`` per bundle the import table binds to the
owned-skinned battle prefab. When those inputs are missing the row records ``rc: "n/a"`` and
``not applicable: <reason>`` instead of a usage failure.

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
# stage_release_payload.ps1's default $GameRoot; only read here.
RELEASE_PLUGIN_ROOT = Path(r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
                           r"/BepInEx/plugins/OfflineUnlockMod")
OWNED_SKINNED_ATTACK_CLIP = "tools/validate_homm3_owned_skinned_attack_clip_contract.py"
OWNED_SKINNED_PREFAB_SUFFIX = "/OwnedSkinned/owned_skinned.prefab"

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
    ("tools/validate_homm3_landon_dwelling_localization_contract.py", "--core"),
    ("tools/validate_homm3_masterful_spell_description_contract.py", "--core"),
    ("tools/validate_homm3_neutral_catalog_contract.py", "--core-zip"),
    ("tools/validate_homm3_owned_attack_animation_slots.py", "--core"),
    (OWNED_SKINNED_ATTACK_CLIP, "--core"),
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


class NotApplicable(Exception):
    pass


def owned_skinned_attack_clip_args(plugin_root: Path) -> list[str]:
    """--bundle-dir / --import / --name-prefix from the release plugin payload; NotApplicable when absent."""
    bundle_dir = plugin_root / "homm3_bundles"
    import_table = plugin_root / "homm3_import.json"
    if not bundle_dir.is_dir():
        raise NotApplicable(f"no bundle directory {bundle_dir}")
    if not import_table.is_file():
        raise NotApplicable(f"no import table {import_table}")
    entries = json.loads(import_table.read_text(encoding="utf-8-sig")).get("entries") or []
    names = sorted({e["bundleName"] for e in entries if isinstance(e, dict) and e.get("bundleName")
                    and str(e.get("battlePrefabAssetPath", "")).endswith(OWNED_SKINNED_PREFAB_SUFFIX)})
    if not names:
        raise NotApplicable(f"{import_table} binds no bundle to an owned-skinned battle prefab")
    present = [n for n in names if (bundle_dir / n).is_file()]
    if not present:
        raise NotApplicable(f"none of the {len(names)} owned-skinned bundles in {import_table.name} is in {bundle_dir}")
    args = ["--bundle-dir", str(bundle_dir), "--import", str(import_table)]
    for name in present:
        args += ["--name-prefix", name]
    return args


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", action="append", required=True, help="label=path/to/Core.zip")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--only", action="append", default=None, help="substring filter on validator path")
    ap.add_argument("--neutral-band-target", choices=("golden_era", "steam_25509697", "steam_25672315", "steam_26297049", "steam_26615913"), required=True,
                    help="game build every --core is for; passed to the validators with target-pinned readbacks")
    ap.add_argument("--plugin-root", type=Path, default=RELEASE_PLUGIN_ROOT,
                    help="plugin payload dir holding homm3_bundles/ and homm3_import.json (read only); default is "
                         "the Golden Era plugin dir stage_release_payload.ps1 stages from")
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
    script_args: dict[str, list[str]] = {}
    not_applicable: dict[str, str] = {}
    if not args.only or any(o in OWNED_SKINNED_ATTACK_CLIP for o in args.only):
        try:
            script_args[OWNED_SKINNED_ATTACK_CLIP] = owned_skinned_attack_clip_args(args.plugin_root.resolve())
        except NotApplicable as ex:
            not_applicable[OWNED_SKINNED_ATTACK_CLIP] = f"not applicable: {ex}"
    table: dict[str, dict[str, dict]] = {}
    for script, flag, *extra in VALIDATORS:
        if args.only and not any(o in script for o in args.only):
            continue
        table[script] = {}
        for label, core in cores.items():
            if script in not_applicable:
                table[script][label] = {"rc": "n/a", "sec": 0.0, "tail": [not_applicable[script]]}
                print(f"{'n/a':>7} {label:<22} {script} ({not_applicable[script]})", flush=True)
                continue
            t0 = time.perf_counter()
            try:
                target_args = (["--neutral-band-target", args.neutral_band_target]
                               if script in NEUTRAL_BAND_TARGET_VALIDATORS else [])
                proc = subprocess.run([sys.executable, script, flag, str(core), *extra, *target_args,
                                       *script_args.get(script, [])], cwd=REPO, env=env,
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
