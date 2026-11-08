#!/usr/bin/env python3
"""Pin Factory/Bulwark/Stronghold-Cyclops ranged vanilla projectile donors in the Core overlay map.

Source/static only: proves VANILLA_PROJECTILE_SPECS_BY_UNIT_SID keeps the agreed
native-safe shells. Cyclops must use Blade Dancer shoot projectiles (Hydra melee
shells do not present shoot projectiles). Optional --core-zip readback proves the
installed unit-view rows carry those projectiles after overlay apply
(deployed, not gameplay).
"""

from __future__ import annotations

import argparse
import ast
import json
import zipfile
from pathlib import Path
from typing import Any


EXPECTED_PROJECTILE_SPECS: dict[str, dict[str, Any]] = {
    # Factory
    "h3_halfling": {
        "projectile": "effects/projectiles/Halfling_projectile",
        "projectileSpeed": 45,
        "trajectory": "linear",
    },
    "h3_halfling_grenadier": {
        "projectile": "effects/projectiles/Halfling_projectile",
        "projectileSpeed": 45,
        "trajectory": "linear",
    },
    "h3_halfling_upg_alt": {
        "projectile": "effects/projectiles/Halfling_projectile",
        "projectileSpeed": 45,
        "trajectory": "linear",
    },
    "h3_gunslinger": {
        "projectile": "effects/projectiles/siege_hit_bolt_projectile",
        "projectileSpeed": 50,
        "trajectory": "linear",
    },
    "h3_bounty_hunter": {
        "projectile": "effects/projectiles/siege_hit_bolt_projectile",
        "projectileSpeed": 50,
        "trajectory": "linear",
    },
    "h3_gunslinger_upg_alt": {
        "projectile": "effects/projectiles/siege_hit_bolt_projectile",
        "projectileSpeed": 50,
        "trajectory": "linear",
    },
    # Bulwark
    "h3_snow_elf": {
        "projectile": "effects/projectiles/Elf_hit_distant_Arrow_fly_bolt",
        "projectileSpeed": 50,
        "trajectory": "linear",
    },
    "h3_steel_elf": {
        "projectile": "effects/projectiles/Elf_upg_hit_distant_Arrow_fly_bolt",
        "projectileSpeed": 50,
        "trajectory": "linear",
    },
    "h3_snow_elf_upg_alt": {
        "projectile": "effects/projectiles/Elf_upg_hit_distant_Arrow_fly_bolt",
        "projectileSpeed": 50,
        "trajectory": "linear",
    },
    "h3_shaman": {
        "projectile": "effects/rays/LightWeaver_hit_ray",
        "projectileSpeed": 200,
        "trajectory": "ray",
    },
    "h3_great_shaman": {
        "projectile": "effects/rays/LightWeaver_upg_hit_ray",
        "projectileSpeed": 200,
        "trajectory": "ray",
    },
    "h3_shaman_upg_alt": {
        "projectile": "effects/rays/Lightweaver_alt_hit_ray",
        "projectileSpeed": 200,
        "trajectory": "ray",
    },
    # Stronghold Cyclops — ranged Blade Dancer shells (not melee Hydra); same projectile family as Orcs.
    "h3_cyclops": {
        "projectile": "effects/projectiles/Blade_dancer_upg_hit_distance_projectile",
        "projectileSpeed": 35,
        "trajectory": "linear",
    },
    "h3_cyclops_upg": {
        "projectile": "effects/projectiles/Blade_dancer_alt_hit_distance_projectile",
        "projectileSpeed": 35,
        "trajectory": "linear",
    },
    "h3_cyclops_upg_alt": {
        "projectile": "effects/projectiles/Blade_dancer_alt_hit_distance_projectile",
        "projectileSpeed": 35,
        "trajectory": "linear",
    },
}

FACTION_BY_SID: dict[str, str] = {
    **{sid: "homm3_factory" for sid in (
        "h3_halfling",
        "h3_halfling_grenadier",
        "h3_halfling_upg_alt",
        "h3_gunslinger",
        "h3_bounty_hunter",
        "h3_gunslinger_upg_alt",
    )},
    **{sid: "homm3_bulwark" for sid in (
        "h3_snow_elf",
        "h3_steel_elf",
        "h3_snow_elf_upg_alt",
        "h3_shaman",
        "h3_great_shaman",
        "h3_shaman_upg_alt",
    )},
    **{sid: "homm3_stronghold" for sid in (
        "h3_cyclops",
        "h3_cyclops_upg",
        "h3_cyclops_upg_alt",
    )},
}


def fail(message: str) -> None:
    raise SystemExit("factory-bulwark-projectile-donor-contract: " + message)


def assignment_literal(module: ast.Module, name: str) -> Any:
    for node in module.body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            return ast.literal_eval(node.value)
    fail(f"overlay missing literal {name}")


def validate_overlay_map(root: Path) -> None:
    overlay_path = root / "tools" / "release_port" / "apply_release_core_overlay.py"
    if not overlay_path.is_file():
        fail(f"missing overlay: {overlay_path}")
    module = ast.parse(overlay_path.read_text(encoding="utf-8-sig"))
    specs = assignment_literal(module, "VANILLA_PROJECTILE_SPECS_BY_UNIT_SID")
    if not isinstance(specs, dict):
        fail("VANILLA_PROJECTILE_SPECS_BY_UNIT_SID must be a dict")
    for sid, expected in EXPECTED_PROJECTILE_SPECS.items():
        actual = specs.get(sid)
        if actual != expected:
            fail(f"{sid} projectile donor drifted: expected {expected!r}, got {actual!r}")


def first_default_attack_projectile(view: dict[str, Any]) -> dict[str, Any] | None:
    rows = view.get("array")
    item = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else view
    if not isinstance(item, dict):
        return None
    attacks = item.get("defaultAttacks")
    if not isinstance(attacks, list) or not attacks or not isinstance(attacks[0], dict):
        return None
    attack = attacks[0]
    out: dict[str, Any] = {}
    for key in ("projectile", "projectileSpeed", "trajectory", "maxHeight"):
        if key in attack:
            out[key] = attack[key]
    return out or None


def validate_core_zip(core_zip: Path) -> None:
    if not core_zip.is_file():
        fail(f"missing Core.zip: {core_zip}")
    with zipfile.ZipFile(core_zip) as archive:
        for sid, expected in EXPECTED_PROJECTILE_SPECS.items():
            faction = FACTION_BY_SID[sid]
            member = f"DB/units/units_views/{faction}/{sid}_v.json"
            try:
                raw = archive.read(member)
            except KeyError:
                fail(f"Core missing unit view {member}")
            view = json.loads(raw.decode("utf-8-sig"))
            actual = first_default_attack_projectile(view)
            if actual != expected:
                fail(
                    f"installed {member} defaultAttacks[0] projectile drifted: "
                    f"expected {expected!r}, got {actual!r}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--core-zip",
        type=Path,
        default=None,
        help="Optional installed Core.zip for deployed unit-view readback.",
    )
    args = parser.parse_args()
    root = args.repo_root.resolve()
    validate_overlay_map(root)
    project = (
        root
        / "Heroes of Might & Magic Olden Era Playtest"
        / "OfflineUnlockMod"
        / "OfflineUnlockMod.csproj"
    ).read_text(encoding="utf-8-sig")
    if "validate_homm3_factory_bulwark_projectile_donor_contract.py" not in project:
        fail("OfflineUnlockMod.csproj must invoke validate_homm3_factory_bulwark_projectile_donor_contract.py")
    if args.core_zip is not None:
        validate_core_zip(args.core_zip.resolve())
    print("factory-bulwark-projectile-donor-contract: ok")


if __name__ == "__main__":
    main()
