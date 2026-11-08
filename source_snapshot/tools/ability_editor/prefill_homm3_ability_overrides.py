from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CUSTOM_FACTIONS = ROOT / "custom_factions"
OUTPUT_DIR = CUSTOM_FACTIONS / "ability_overrides"


SPECIAL_BRANCHES: dict[str, dict[str, dict[str, str]]] = {
    "homm3_castle": {
        "h3_angel": {
            "sourceMechanicId": "castle.angel_flying_resurrection",
            "decisionTest": "Angel branch should be chosen when flying reach and late-game morale pressure matter; resurrection behavior is treated as an explicit changed design until the exact presentation route is verified.",
        },
        "h3_angel_upg": {
            "sourceMechanicId": "castle.angel_flying_resurrection",
            "decisionTest": "Archangel branch should be chosen when the player wants the strongest resurrection-adjacent late-game support profile; exact HoMM3 resurrection parity is not claimed.",
        },
        "h3_angel_upg_alt": {
            "sourceMechanicId": "castle.angel_flying_resurrection",
            "decisionTest": "Seraph branch should be chosen when the alternate upgrade's support profile is worth trading away the standard Archangel profile; exact HoMM3 resurrection parity is not claimed.",
        },
    },
    "homm3_cove": {
        "h3_sea_dog": {
            "sourceMechanicId": "cove.gunpowder_warehouse_sea_dog",
            "decisionTest": "Sea Dog should remain a distinct alternate-upgrade decision; its Gunpowder Warehouse prerequisite is a changed city-build contract until a per-upgrade prerequisite route exists.",
        },
    },
    "homm3_rampart": {
        "h3_wood_elf_upg": {
            "branchRole": "standard-shooter",
            "sourceMechanicId": "rampart.wood_elf_grand_elf_shooter_branch",
            "decisionTest": "Grand Elf should be chosen when ranged pressure and shooter attack buckets are the meaningful upgrade decision.",
        },
        "h3_wood_elf_upg_alt": {
            "branchRole": "alternate-melee-skirmisher",
            "sourceMechanicId": "rampart.wood_elf_wardancer_melee_branch",
            "decisionTest": "Elf Wardancer should be chosen when melee mobility and non-shooter attack presentation matter more than Grand Elf ranged pressure.",
        },
    },
    "homm3_tower": {
        "h3_giant": {
            "branchRole": "base-non-shooter",
            "sourceMechanicId": "tower.giant_titan_shooter_split",
            "decisionTest": "Giant should not expose Titan shooter behavior before upgrade; choose it as a high-tier melee power stack.",
        },
        "h3_giant_upg": {
            "branchRole": "standard-shooter",
            "sourceMechanicId": "tower.giant_titan_shooter_split",
            "decisionTest": "Titan should be chosen when the player wants the source shooter branch.",
        },
        "h3_giant_upg_alt": {
            "branchRole": "alternate-non-shooter",
            "sourceMechanicId": "tower.giant_titan_shooter_split",
            "decisionTest": "Storm Giant should remain a non-shooter alternate unless source data proves otherwise.",
        },
    },
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def unit_sid_for_variant(base_sid: str, suffix: str) -> str:
    return f"{base_sid}{suffix}"


def manifest_unit_sid_for_variant(line: dict[str, Any], suffix: str) -> str:
    variant_sids = line.get("variantSids")
    if isinstance(variant_sids, dict):
        sid = variant_sids.get(suffix)
        if isinstance(sid, str) and sid:
            return sid
    return unit_sid_for_variant(str(line["baseSid"]), suffix)


def default_role(suffix: str) -> str:
    if suffix == "_upg":
        return "standard-upgrade"
    if suffix == "_upg_alt":
        return "alternate-upgrade"
    return "base-line"


def default_decision(faction_name: str, names: list[str], suffix: str) -> str:
    base = names[0] if names else "base unit"
    standard = names[1] if len(names) > 1 else f"{base} standard upgrade"
    alternate = names[2] if len(names) > 2 else f"{base} alternate upgrade"
    if suffix == "_upg":
        return f"{standard} should be chosen over {alternate} when its standard role is the better answer for the current army, matchup, or build timing."
    if suffix == "_upg_alt":
        return f"{alternate} should be chosen over {standard} when its alternate role creates a better army, matchup, or build-timing decision."
    return f"{base} defines the tier baseline for {faction_name}; upgrades should create a meaningful standard-versus-alternate decision from this role."


def build_row(faction_sid: str, line: dict[str, Any], suffix: str, existing: dict[str, Any]) -> dict[str, Any]:
    base_sid = str(line["baseSid"])
    unit_sid = manifest_unit_sid_for_variant(line, suffix)
    faction_name = faction_sid.removeprefix("homm3_")
    names = [str(name) for name in line.get("names", []) if isinstance(name, str)]
    row = dict(existing)
    special = (SPECIAL_BRANCHES.get(faction_sid) or {}).get(unit_sid, {})
    row.setdefault("branchRole", special.get("branchRole") or default_role(suffix))
    row.setdefault("sourceMechanicId", special.get("sourceMechanicId") or f"{faction_name}.{base_sid.removeprefix('h3_')}_line")
    row.setdefault("decisionTest", special.get("decisionTest") or default_decision(faction_name, names, suffix))
    row.setdefault("abilities", [])
    row.setdefault("existingSpecials", [])
    row.setdefault("replaceExistingAbilities", False)
    row.setdefault("replaceExistingPassives", False)
    return row


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for manifest_path in sorted(CUSTOM_FACTIONS.glob("homm3_*.json")):
        manifest = load_json(manifest_path)
        faction_sid = manifest["identity"]["factionSid"]
        output_path = OUTPUT_DIR / f"{faction_sid}.json"
        existing = load_json(output_path) if output_path.exists() else {"schemaVersion": 1, "factionSid": faction_sid, "unitOverrides": {}}
        existing["schemaVersion"] = 1
        existing["factionSid"] = faction_sid
        old_overrides = existing.get("unitOverrides") if isinstance(existing.get("unitOverrides"), dict) else {}
        overrides: dict[str, Any] = {}
        variants = manifest.get("unitVariants") if isinstance(manifest.get("unitVariants"), list) else ["", "_upg", "_upg_alt"]
        for line in manifest.get("unitLines", []):
            if not isinstance(line, dict) or not isinstance(line.get("baseSid"), str):
                continue
            for suffix in variants:
                unit_sid = manifest_unit_sid_for_variant(line, str(suffix))
                current = old_overrides.get(unit_sid) if isinstance(old_overrides.get(unit_sid), dict) else {}
                overrides[unit_sid] = build_row(faction_sid, line, str(suffix), current)
                total += 1
        for unit_sid, row in old_overrides.items():
            if unit_sid in overrides or not isinstance(row, dict):
                continue
            if row.get("abilities") or row.get("existingSpecials"):
                overrides[unit_sid] = row
        existing["unitOverrides"] = overrides
        output_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {output_path} ({len(overrides)} unit rows)")
    print(f"prefilled {total} unit branch override rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
