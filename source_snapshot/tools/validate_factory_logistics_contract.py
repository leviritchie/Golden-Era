#!/usr/bin/env python3
"""Pin the Factory Logistics Network contract (2026-11-16).

Checks, fail closed:
- custom_factions/factory_logistics/logistics_config.json: schema, the twelve enhancements (codes 1-12, known
  effects, 3 levels of values/costs/lines), market and dwelling tables;
- the runtime C# owners exist, read the same config keys and effect names, and Plugin.cs registers the
  runtime and UI while Split Assembly stays unregistered; the compile stubs are gone;
- the csproj deploys the config;
- tools/release_port/homm3_factory_logistics_core_overlay.py builds rows that match the config and is wired
  into apply_release_core_overlay.py;
- when the Golden Era Core.zip is present (or --core is given): the clone sources exist and every subskill
  stat is a known hero stat.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

KNOWN_EFFECTS = {
    "byproduct", "export", "warehouse", "rail_station", "power_station", "synthesizer", "arcane",
    "route_hub", "food", "housing", "rail_network", "mercenary", "support",
}
DEFAULT_CORE = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)
RUNTIME_FILES = (
    "Homm3FactoryLogisticsConfig.cs",
    "Homm3FactoryLogisticsState.cs",
    "Homm3FactoryLogisticsEffects.cs",
    "Homm3FactoryLogisticsRuntime.cs",
    "Homm3FactoryLogisticsFacade.cs",
    "Homm3FactoryLogisticsRange.cs",
    "Homm3FactoryLogisticsMap.cs",
    "Homm3FactoryLogisticsViewer.cs",
    "Homm3FactoryLogisticsUi.cs",
)
RETIRED_FILES = ("Homm3FactoryLogisticsUiStubs.cs", "Homm3FactoryLogisticsViewerStub.cs", "Homm3FactoryLogisticsRangeStub.cs")


def fail(message: str) -> None:
    raise SystemExit("factory-logistics-contract: " + message)


def need(cond: bool, message: str) -> None:
    if not cond:
        fail(message)


def read_text(path: Path) -> str:
    need(path.is_file(), f"missing {path}")
    return path.read_text(encoding="utf-8-sig")


def validate_config(config: dict[str, Any]) -> None:
    need(config.get("schema") == "homm3_factory_logistics_config/1", "config schema drifted")
    need(config.get("skillSid") == "skill_faction_homm3_factory", "config skillSid must be skill_faction_homm3_factory")
    need(config.get("maxLevel") == 3, "config maxLevel must be 3 (one level per skill rank)")
    for key in ("spellSid", "carrierBuffSid", "heroStatBuffPrefix"):
        need(isinstance(config.get(key), str) and config[key], f"config {key} must be a non-empty string")
    need(isinstance(config.get("heroStatBuffMaxLevel"), int) and config["heroStatBuffMaxLevel"] >= 1, "config heroStatBuffMaxLevel must be >= 1")
    need(isinstance(config.get("rangeMpPerLevel"), int) and config["rangeMpPerLevel"] > 0, "config rangeMpPerLevel must be > 0")
    need(isinstance(config.get("persistenceEnabled"), bool), "config persistenceEnabled must be a boolean (save-carrier kill-switch)")
    astrology = config.get("astrologyPerTown")
    need(isinstance(astrology, int) and astrology > 0, "config astrologyPerTown must be a positive integer (granted, DECISIONS.md #55)")
    for enh in config.get("enhancements") or []:
        if isinstance(enh, dict) and enh.get("effect") == "arcane":
            # The texts must quote what the code grants: astrologyPerTown per town, at most [level] towns per
            # Manufactory, and level/6 of each week's dwelling growth converted (DECISIONS.md #55-#57).
            lines = enh.get("levelLines") or []
            need(len(lines) == 3, "arcane levelLines must have 3 entries")
            for level, line in enumerate(lines, start=1):
                text = str(line).lower()
                need("astrolog" in text and f"+{astrology}" in text,
                     f"arcane level {level} line must state +{astrology} astrology (astrologyPerTown)")
                need(f"{level} town" in text, f"arcane level {level} line must state the {level}-town cap")
                need(f"{level}/6" in text, f"arcane level {level} line must state the {level}/6 conversion share")
    market = config.get("market")
    need(isinstance(market, dict) and market.get("marketBuildingSids"), "config market.marketBuildingSids missing")
    dwelling = config.get("dwelling")
    need(isinstance(dwelling, dict), "config dwelling table missing")
    for table in ("tierGold", "tierWeeklyValue"):
        rows = dwelling.get(table)
        need(isinstance(rows, dict) and set(rows) == {str(t) for t in range(1, 8)}, f"config dwelling.{table} must cover tiers 1-7")
    enhancements = config.get("enhancements")
    need(isinstance(enhancements, list) and len(enhancements) == 13, "config must list exactly 13 enhancements")
    codes, ids, effects = set(), set(), set()
    for enh in enhancements:
        need(isinstance(enh, dict), "enhancement rows must be objects")
        label = enh.get("id")
        need(isinstance(label, str) and label not in ids, f"enhancement id missing or duplicated: {label!r}")
        ids.add(label)
        need(enh.get("kind") in {"mine", "dwelling", "any"}, f"{label}: kind must be mine, dwelling or any")
        need(isinstance(enh.get("code"), int) and enh["code"] not in codes, f"{label}: code missing or duplicated")
        codes.add(enh["code"])
        need(enh.get("effect") in KNOWN_EFFECTS, f"{label}: unknown effect {enh.get('effect')!r}")
        effects.add(enh["effect"])
        cost_key = "dwellingGoldFactors" if enh["kind"] == "dwelling" else "costs"
        for key in ("values", "levelLines", cost_key):
            need(isinstance(enh.get(key), list) and len(enh[key]) == 3, f"{label}: {key} must have 3 levels")
        need(isinstance(enh.get("name"), str) and enh["name"], f"{label}: name missing")
    need(codes == set(range(1, 14)), "enhancement codes must be exactly 1-13")
    need(effects == KNOWN_EFFECTS, f"enhancement effects must cover {sorted(KNOWN_EFFECTS)}, got {sorted(effects)}")


def validate_runtime(root: Path, config: dict[str, Any]) -> None:
    plugin = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
    for name in RUNTIME_FILES:
        need((plugin / name).is_file(), f"missing runtime owner {name}")
    for name in RETIRED_FILES:
        need(not (plugin / name).exists(), f"compile stub {name} must be deleted once the real owner exists")
    cfg_cs = read_text(plugin / "Homm3FactoryLogisticsConfig.cs")
    for key in ("schema", "skillSid", "spellSid", "carrierBuffSid", "heroStatBuffPrefix", "heroStatBuffMaxLevel", "enhancements"):
        need(f'"{key}"' in cfg_cs, f"Homm3FactoryLogisticsConfig.cs must read config key {key}")
    for effect in KNOWN_EFFECTS:
        need(f'"{effect}"' in cfg_cs, f"Homm3FactoryLogisticsConfig.cs must know effect {effect}")
    runtime = read_text(plugin / "Homm3FactoryLogisticsRuntime.cs")
    need(f'SpellMode = "{config["spellSid"]}"' in runtime, "runtime SpellMode must equal config spellSid")
    for token in ("TryRegister(", "Homm3FactoryLogisticsViewer.Open(", "Homm3FactoryLogisticsRange.Invalidate("):
        need(token in runtime, f"Homm3FactoryLogisticsRuntime.cs missing {token}")
    facade = read_text(plugin / "Homm3FactoryLogisticsFacade.cs")
    for token in ("TryBuild(", "TrySetActive(", "TryDemolish(", "TryRemoteHire(", "TryGetTerrainTile(", "TryGetNetwork(", "NoPath"):
        need(token in facade, f"Homm3FactoryLogisticsFacade.cs missing {token}")
    plugin_cs = read_text(plugin / "Plugin.cs")
    need("Homm3FactoryLogisticsRuntime.TryRegister(_harmony, Log)" in plugin_cs, "Plugin.cs must register Homm3FactoryLogisticsRuntime")
    need("Homm3FactoryLogisticsUi.TryRegister(" in plugin_cs, "Plugin.cs must register Homm3FactoryLogisticsUi")
    for retired in ("Homm3FactorySplitAssemblyRuntime.TryRegister(", "Homm3FactorySplitAssemblyArmyStripHud.TryRegister("):
        need(retired not in plugin_cs, f"Plugin.cs must not register retired {retired}")
    project = read_text(plugin / "OfflineUnlockMod.csproj")
    need("factory_logistics\\logistics_config.json" in project, "csproj must deploy custom_factions\\factory_logistics\\logistics_config.json")
    need("validate_factory_logistics_contract.py" in project, "csproj must gate validate_factory_logistics_contract.py")


def validate_overlay(root: Path, config: dict[str, Any], core: Path | None) -> None:
    sys.path.insert(0, str(root / "tools" / "release_port"))
    import homm3_factory_logistics_core_overlay as fl  # noqa: E402

    need(fl.SPELL_SID == config["spellSid"] and fl.CARRIER_BUFF_SID == config["carrierBuffSid"], "overlay SIDs must come from the config")
    need(len(fl.RANK_DESCS) == 3 and all(f"enhancement level {n}" in fl.RANK_DESCS[n - 1] for n in (1, 2, 3)),
         "rank texts must state maximum enhancement level 1/2/3")
    levels = fl.faction_skill_levels()
    need(len(levels) == 3 and all(any(b.get("type") == "heroMagicAddition" and b["parameters"][0] == fl.SPELL_SID for b in rank) for rank in levels),
         "every rank must grant the Logistics Network spell")
    subskills = fl.make_subskills()
    flat = [sid for level in (2, 3) for sid in fl.SUBSKILLS_BY_LEVEL[level]]
    need(sorted(r["id"] for r in subskills) == sorted(flat) and len(set(flat)) == 6, "six unique subskills must match SUBSKILLS_BY_LEVEL")
    runtime_only = {fl.SUBSKILL_IDS["roads"], fl.SUBSKILL_IDS["depots"]}  # Mobile Command Center, Supply Caravan
    need(all(r["bonuses"] or r["id"] in runtime_only for r in subskills),
         "every Logistics Network subskill except the runtime ones (Mobile Command Center, Supply Caravan) must carry a native bonus")
    arcane = fl.make_arcane_hero_buff_rows()
    need([r["id"] for r in arcane] == [f"{config['heroStatBuffPrefix']}{n}" for n in range(1, config["heroStatBuffMaxLevel"] + 1)],
         "arcane hero buff rows must match heroStatBuffPrefix 1..heroStatBuffMaxLevel")
    lang_sids = {r["sid"] for r in fl.subskill_lang_rows() + fl.magic_lang_rows() + fl.buff_lang_rows()}
    for row in subskills:
        need({row["name"], row["desc"]} <= lang_sids, f"{row['id']}: missing lang rows")
    for row in arcane:
        need({row["name"], row["description"]} <= lang_sids, f"{row['id']}: missing lang rows")

    source = read_text(root / "tools" / "release_port" / "apply_release_core_overlay.py")
    for token in (
        "import homm3_factory_logistics_core_overlay as factory_logistics",
        "factory_logistics.merge_logistics_skill_rows_into_overlay(",
        "factory_logistics.faction_skill_levels()",
        "factory_logistics.subskill_lang_rows()",
        "HOMM3_FACTORY_SPLIT_ASSEMBLY_SUBSKILLS_BY_LEVEL = factory_logistics.SUBSKILLS_BY_LEVEL",
    ):
        need(token in source, f"apply_release_core_overlay.py missing {token}")

    if core is None:
        print("factory-logistics-contract: note: no Core.zip; skipped clone-source and hero-stat checks")
        return
    with zipfile.ZipFile(core) as archive:
        def doc(name: str) -> dict[str, Any]:
            return json.loads(archive.read(name).decode("utf-8-sig"))

        magic_rows = doc(fl.SPELL_PATH)["array"]
        spell = fl.make_logistics_magic_row(magic_rows)
        settings = spell["worldMagic"]["magicSettings"]
        need(all(s.get("parameters") == [fl.SPELL_MODE] and s.get("usageLimit") == -1 for s in settings if isinstance(s, dict)),
             "spell settings must be [mode] with usageLimit -1")
        need(spell["manaCost"] == [0, 0, 0, 0], "spell must cost no mana")
        carrier = fl.make_carrier_side_buff_row(doc(fl.SIDE_BUFFS_PATH)["array"])
        need(carrier.get("hidden") is True and carrier.get("bonuses") == [], "carrier side buff must be hidden and bonus-less")
        stat_names = set(re.findall(r'"statName"\s*:\s*"(\w+)"', archive.read("DB/hero_stats_limits.json").decode("utf-8-sig")))
        # Stats native subskills use without a limits row (enableEnemyHeroInfo) also count as known.
        for native in doc(fl.SUBSKILLS_PATH)["array"]:
            if isinstance(native, dict) and not str(native.get("id", "")).startswith("sub_skill_faction_homm3_"):
                for bonus in native.get("bonuses") or []:
                    if isinstance(bonus, dict) and bonus.get("type") == "heroStat" and bonus.get("parameters"):
                        stat_names.add(bonus["parameters"][0])
        for row in subskills + arcane:
            for bonus in row["bonuses"]:
                if bonus.get("type") == "heroStat":
                    need(bonus["parameters"][0] in stat_names, f"{row['id']}: unknown hero stat {bonus['parameters'][0]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--core", type=Path, default=None, help="Core.zip for clone-source checks (default: Golden Era if present)")
    args = parser.parse_args()
    root = args.repo_root.resolve()
    config = json.loads(read_text(root / "custom_factions" / "factory_logistics" / "logistics_config.json"))
    validate_config(config)
    validate_runtime(root, config)
    core = args.core if args.core is not None else (DEFAULT_CORE if DEFAULT_CORE.is_file() else None)
    if core is not None and not core.is_file():
        fail(f"--core not found: {core}")
    validate_overlay(root, config, core)
    print("validated Factory Logistics Network contract")


if __name__ == "__main__":
    main()
