#!/usr/bin/env python3
"""Pin Factory/Bulwark faction-skill and exceptional recruitment Core contracts."""

from __future__ import annotations

import argparse
import ast
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import zipfile
from typing import Any


EXACT_SKILL_TEXT: dict[str, tuple[str, str, list[str]]] = {
    "homm3_factory": (
        "Split Assembly",
        "At battle start, each distinct Natural and Industrial Factory recruit line unlocks one assembly bonus for your whole army. Skill rank scales those bonuses; the fourth bonus in each branch requires Expert and four lines.",
        [
            "Natural lines unlock 5% ranged damage, 5% less damage taken, then +1 start Focus. Industrial lines unlock 5% melee damage, +1 Speed, then +1 Initiative. Fourth-branch bonuses require Expert and four lines.",
            "Natural lines unlock 10% ranged damage, 10% less damage taken, then +1 start Focus. Industrial lines unlock 10% melee damage, +1 Speed, then +1 Initiative. Fourth-branch bonuses require Expert and four lines.",
            "Natural lines unlock 15% ranged damage, 15% less damage taken, +1 start Focus, and Carapace on all units. Industrial lines unlock 15% melee damage, +2 Speed, +2 Initiative, and Field Triage (spend 1 Focus to heal and revive any allied unit). Fourth-branch bonuses require Expert and four lines.",
        ],
    ),
    "homm3_bulwark": (
        "Runes",
        "Each creature stack in the hero's army gains Rune Levels from acting, taking damage, and defending; cumulative Rune thresholds grant Attack, Defense, and Speed.",
        [
            "Stacks can reach Rune Level 3. A completed attack or cast grants +1 Rune Level, taking damage during an action grants +2, and Defend grants +3. Levels 1/2/3 cumulatively grant +2 Attack, +2 Defense, and +1 Speed.",
            "Stacks can reach Rune Level 6 with the same action gains. Levels 4/5/6 add another +2 Attack, +2 Defense, and +1 Speed to the cumulative bonuses.",
            "Stacks can reach Rune Level 9 with the same action gains. Levels 7/8/9 add a final +2 Attack, +2 Defense, and +1 Speed to the cumulative bonuses.",
        ],
    ),
}


def fail(message: str) -> None:
    raise SystemExit("factory-bulwark-core-skill-contract: " + message)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        fail(f"missing required manifest: {path}")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        fail(f"expected JSON object: {path}")
    return value


def assignment_literal(module: ast.Module, name: str) -> Any:
    for node in module.body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == name:
            return ast.literal_eval(node.value)
    fail(f"overlay missing literal {name}")


def function_source(source: str, module: ast.Module, name: str) -> str:
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source, node) or ""
    fail(f"overlay missing function {name}")


def require_tokens(text: str, label: str, tokens: tuple[str, ...]) -> None:
    for token in tokens:
        if token not in text:
            fail(f"{label} missing {token!r}")


def validate_manifest(manifest: dict[str, Any], faction_sid: str) -> None:
    if (manifest.get("identity") or {}).get("factionSid") != faction_sid:
        fail(f"{faction_sid} identity mismatch")
    if len(manifest.get("unitLines") or []) != 7:
        fail(f"{faction_sid} must retain exactly seven primary unitLines")
    expected_skill_sid = f"skill_faction_{faction_sid}"
    if (manifest.get("skillsAndLaws") or {}).get("factionSkillSid") != expected_skill_sid:
        fail(f"{faction_sid} must bind {expected_skill_sid}")


def validate_factory_additional_line(manifest: dict[str, Any]) -> None:
    additional = manifest.get("additionalRecruitmentLines")
    matches = [line for line in additional or [] if isinstance(line, dict) and line.get("lineId") == "dreadnought"]
    if len(matches) != 1:
        fail("Factory must own exactly one additional dreadnought recruitment line")
    line = matches[0]
    expected = {
        "tier": 7,
        "recruitmentSlotSid": "Factory_Gantry",
        "cityBuildingSid": "Build_Factory_Gantry",
        "directDwellingSid": "barracks_homm3_factory_8",
    }
    for key, value in expected.items():
        if line.get(key) != value:
            fail(f"Factory dreadnought {key} must be {value!r}, got {line.get(key)!r}")
    if not isinstance(line.get("donorDwellingSid"), str) or not line["donorDwellingSid"].startswith("barracks_"):
        fail("Factory dreadnought must bind an explicit donor dwelling SID")
    if not isinstance(line.get("dwellingBillboardImage"), str) or "avgdread" not in line["dwellingBillboardImage"].lower():
        fail("Factory dreadnought billboard must come from AVGdread")
    branches = {line.get("branchFamily") for line in (manifest.get("unitLines") or []) + additional}
    if not branches.issubset({"natural", "industrial"}) or branches != {"natural", "industrial"}:
        fail(f"Factory branch families must be exactly natural/industrial, got {sorted(str(value) for value in branches)}")


def normalize_source_biography_for_override(source_bio: str, *, faction: str, source_name: str) -> str:
    """Player-facing overrides may correct known HotA orthography typos only.

    Keep this fail-closed: every correction must be an exact (faction, hero, from→to) pin.
    Do not invent broader fuzzy matching.
    """
    text = source_bio.strip()
    if faction == "factory" and source_name == "morton":
        # HotA Morton biography uses "piece" where English requires "pierce".
        corrected = text.replace(
            "ogres they can piece with a single shot",
            "ogres they can pierce with a single shot",
        )
        if corrected == text:
            fail("Factory Morton biography pin expected HotA 'piece' typo to correct to 'pierce'")
        return corrected
    return text


def validate_source_hero_biographies(root: Path) -> None:
    for faction in ("factory", "bulwark"):
        faction_sid = f"homm3_{faction}"
        manifest = read_json(root / "custom_factions" / f"{faction_sid}.json")
        overrides = read_json(root / "custom_factions" / "hero_overrides" / f"{faction_sid}.json")
        source_names = (manifest.get("heroes") or {}).get("sourceHeroConfigs")
        entries = overrides.get("heroOverrides")
        if not isinstance(source_names, list) or not isinstance(entries, dict) or len(source_names) != len(entries):
            fail(f"{faction_sid} source hero/override count mismatch")
        archive_path = root / "vcmi" / "Mods" / "hota" / "mods" / faction / "content.zip"
        if not archive_path.is_file():
            fail(f"missing pinned {faction_sid} source archive: {archive_path}")
        with zipfile.ZipFile(archive_path) as archive:
            for index, source_name in enumerate(source_names, start=1):
                sid = f"{faction_sid}_hero_{index}"
                entry = entries.get(sid)
                if not isinstance(entry, dict):
                    fail(f"{faction_sid} missing hero override {sid}")
                member = f"config/hota/{faction}/heroes/{source_name}.json"
                try:
                    source_doc = json.loads(archive.read(member).decode("utf-8-sig"))
                except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    fail(f"cannot read pinned hero source {member}: {exc}")
                source_hero = next(iter(source_doc.values()), None) if isinstance(source_doc, dict) else None
                source_texts = source_hero.get("texts") if isinstance(source_hero, dict) else None
                source_name_text = source_texts.get("name") if isinstance(source_texts, dict) else None
                source_bio = source_texts.get("biography") if isinstance(source_texts, dict) else None
                if not isinstance(source_bio, str) or not source_bio.strip():
                    fail(f"{sid} has no source biography in {member}")
                if entry.get("nameText") != source_name_text:
                    fail(f"{sid} nameText does not match {member}")
                expected_bio = normalize_source_biography_for_override(
                    source_bio, faction=faction, source_name=str(source_name)
                )
                if entry.get("descriptionText") != expected_bio:
                    fail(f"{sid} descriptionText does not exactly match {member}")


def validate_law_overrides(root: Path) -> None:
    required_definitions = {
        "factory": {5, 20, 26, 31},
        "bulwark": {4, 11, 17, 20, 24, 26, 30, 31},
    }
    donor = {"factory": "human", "bulwark": "nature"}
    for faction, definition_indices in required_definitions.items():
        faction_sid = f"homm3_{faction}"
        doc = read_json(root / "custom_factions" / "law_overrides" / f"{faction_sid}.json")
        rows = doc.get("lawOverrides")
        if not isinstance(rows, dict):
            fail(f"{faction_sid} lawOverrides must be an object")
        expected_keys = {f"fraction_law_{faction_sid}_{index}" for index in range(1, 35)}
        if set(rows) != expected_keys:
            fail(f"{faction_sid} must own explicit icon contracts for exactly 34 law rows")
        for index in range(1, 35):
            key = f"fraction_law_{faction_sid}_{index}"
            row = rows[key]
            expected_icon = f"fraction_law_{donor[faction]}_{index}_icon"
            if row.get("iconKey") != expected_icon:
                fail(f"{key} iconKey must be {expected_icon}")
            if index not in definition_indices:
                continue
            if row.get("enabled") is not True or not all(row.get(field) for field in ("nameText", "descriptionText", "parametersPerLevel")):
                fail(f"{key} must carry an explicit enabled Core-native law definition")
            if "not claimed as a HotA-authentic" not in str(row.get("notes") or ""):
                fail(f"{key} must preserve the non-authentic integration-law proof boundary")


def validate_msbuild_target(project_path: Path) -> None:
    root = ET.fromstring(project_path.read_text(encoding="utf-8-sig"))
    target = next((node for node in root.iter() if node.tag.endswith("Target") and node.attrib.get("Name") == "ValidateHomm3FactoryBulwarkCoreSkillContract"), None)
    if target is None or target.attrib.get("BeforeTargets") != "BeforeBuild":
        fail("OfflineUnlockMod.csproj must run ValidateHomm3FactoryBulwarkCoreSkillContract BeforeBuild")


def validate_split_assembly_hud(root: Path) -> None:
    plugin = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
    required_files = (
        "Homm3FactorySplitAssemblyEvaluator.cs",
        "Homm3FactorySplitAssemblyHudSpriteCache.cs",
        "Homm3FactorySplitAssemblyArmyStripHud.cs",
        "Homm3FactorySplitAssemblyRuntime.cs",
    )
    for name in required_files:
        path = plugin / name
        if not path.is_file():
            fail(f"missing Split Assembly HUD owner: {name}")

    evaluator = (plugin / "Homm3FactorySplitAssemblyEvaluator.cs").read_text(encoding="utf-8-sig")
    require_tokens(
        evaluator,
        "Split Assembly shared evaluator",
        (
            "internal static class Homm3FactorySplitAssemblyEvaluator",
            "TryEvaluate(",
            "ResolveUnlockedTiers(",
            "ResolveRankCap(",
            "BuildTooltipText(",
            "NaturalOverclockSubSkillSid",
            "IndustrialOverclockSubSkillSid",
        ),
    )

    runtime = (plugin / "Homm3FactorySplitAssemblyRuntime.cs").read_text(encoding="utf-8-sig")
    require_tokens(
        runtime,
        "Split Assembly combat runtime evaluator join",
        (
            "Homm3FactorySplitAssemblyEvaluator.TryEvaluate(",
            "CollectTransferSideUnitSids(",
        ),
    )

    hud = (plugin / "Homm3FactorySplitAssemblyArmyStripHud.cs").read_text(encoding="utf-8-sig")
    require_tokens(
        hud,
        "Split Assembly army-strip HUD",
        (
            "internal static class Homm3FactorySplitAssemblyArmyStripHud",
            "TryRegister(",
            "HOMM3_FACTORY_SPLIT_ASSEMBLY_METERS",
            "Homm3FactorySplitAssemblyHudHoverPump",
            "EnsureLeafSprite(",
            "EnsureGearSprite(",
            "NatureGreen",
            "IndustryOrangeBrown",
            "TickHover(",
            "HOMM3_FACTORY_SPLIT_ASSEMBLY_TOOLTIP",
            "BhHeroHUDPanel",
            "HeroHudPanelHeroViewFields",
            "TooltipHeroItemPortraitFields",
            "DataPartyUnitSidMembers",
            "PositionMeterLeftOfPortrait(",
        ),
    )
    if '"Hex.Session.Hud.BhHeroUIElement"' in hud or "SideHeroIconFields" in hud:
        fail("Split Assembly army-strip HUD must not target BhHeroUIElement / side-list heroIcon")

    cache = (plugin / "Homm3FactorySplitAssemblyHudSpriteCache.cs").read_text(encoding="utf-8-sig")
    require_tokens(
        cache,
        "Split Assembly HUD sprite cache",
        (
            'FolderName = "homm3_factory_split_assembly_hud"',
            "RequiredSpriteNames",
            "TryGetOrCreateSprite(",
        ),
    )

    # Legacy pip/rail PNGs may remain for reference; simple HUD uses procedural leaf/gear icons.
    art_dir = plugin / "homm3_factory_split_assembly_hud"
    if art_dir.is_dir():
        for name in art_dir.glob("*.png"):
            if name.stat().st_size < 32:
                fail(f"empty Split Assembly HUD art: {name.name}")
            header = name.read_bytes()[:8]
            if header[:8] != b"\x89PNG\r\n\x1a\n":
                fail(f"Split Assembly HUD art must be PNG: {name.name}")

    plugin_source = (plugin / "Plugin.cs").read_text(encoding="utf-8-sig")
    if "Homm3FactorySplitAssemblyArmyStripHud.TryRegister(_harmony, Log)" not in plugin_source:
        fail("Plugin.cs must register Homm3FactorySplitAssemblyArmyStripHud")

    project = (plugin / "OfflineUnlockMod.csproj").read_text(encoding="utf-8-sig")
    require_tokens(
        project,
        "Split Assembly HUD deploy contract",
        (
            "DeployHomm3FactorySplitAssemblyHud",
            "homm3_factory_split_assembly_hud",
            "RequiredHomm3FactorySplitAssemblyHud",
        ),
    )


def validate_bulwark_promotion(root: Path) -> None:
    contract = read_json(root / "custom_factions" / "source_mechanics" / "homm3_bulwark.json")
    mechanics = contract.get("mechanics")
    runes = [entry for entry in mechanics or [] if isinstance(entry, dict) and entry.get("id") == "bulwark.runes"]
    if len(runes) != 1:
        fail("Bulwark source mechanics must contain exactly one bulwark.runes entry")
    mechanic = runes[0]
    status = mechanic.get("status")
    if status == "runtime-pending":
        if mechanic.get("currentRows"):
            fail("runtime-pending Bulwark Runes must not claim a current Core row")
        if mechanic.get("validationOwner") != "validate_homm3_factory_bulwark_core_skill_contract":
            fail("runtime-pending Bulwark Runes must name this promotion validator")
        return
    if status != "exact":
        fail(f"Bulwark Runes status must be runtime-pending or exact, got {status!r}")
    if mechanic.get("currentRows") != ["skill_faction_homm3_bulwark"]:
        fail("exact Bulwark Runes must claim its faction skill row")

    runtime_path = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3BulwarkRunesRuntime.cs"
    if not runtime_path.is_file():
        fail("exact Bulwark Runes requires Homm3BulwarkRunesRuntime.cs")
    runtime_source = runtime_path.read_text(encoding="utf-8-sig")
    require_tokens(
        runtime_source,
        "exact Bulwark Runes runtime",
        ("internal static class Homm3BulwarkRunesRuntime", "TryRegister("),
    )
    plugin_source = (root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Plugin.cs").read_text(encoding="utf-8-sig")
    if "Homm3BulwarkRunesRuntime.TryRegister(_harmony, Log)" not in plugin_source:
        fail("exact Bulwark Runes requires Plugin.cs runtime registration")




def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.repo_root.resolve()
    overlay_path = root / "tools" / "release_port" / "apply_release_core_overlay.py"
    source = overlay_path.read_text(encoding="utf-8-sig")
    module = ast.parse(source)
    skill_text = assignment_literal(module, "GENERIC_FACTION_SKILL_TEXT")
    for faction_sid, expected in EXACT_SKILL_TEXT.items():
        if skill_text.get(faction_sid) != expected:
            fail(f"{faction_sid} exact skill text drifted")

    specialized = function_source(source, module, "make_specialized_generic_skill_row")
    require_tokens(
        specialized,
        "specialized skill rows",
        (
            'faction_sid == "homm3_factory"',
            'faction_sid == "homm3_bulwark"',
            'unit_bool_stat_bonus("ignoreFractionsCount")',
            "HOMM3_FACTORY_SPLIT_ASSEMBLY_SUBSKILLS_BY_LEVEL",
            "HOMM3_BULWARK_RUNES_SUBSKILLS_BY_LEVEL",
            "Split Assembly:",
            "HOMM3_FACTORY_FIELD_TRIAGE_ABILITY_SID",
            'implemented = ""',
            'source_mechanic_for_surface_row(faction_sid, "faction_skill", skill_sid)',
        ),
    )
    if "levels = [[], [], []]" in specialized:
        fail("Factory/Bulwark faction skills must not ship empty Core bonus arrays; native HeroSkill apply NREs on map load")
    require_tokens(
        specialized,
        "Factory Field Triage Expert grant",
        (
            'faction_sid == "homm3_factory"',
            '{"type": "heroBattleAbility", "parameters": [HOMM3_FACTORY_FIELD_TRIAGE_ABILITY_SID, "0"]}',
        ),
    )
    for helper_name, tokens in (
        (
            "make_homm3_factory_split_assembly_subskills",
            (
                "sub_skill_faction_homm3_factory_sand_advantage",
                "landscapePenaltyPerBonus",
                "enableEnemyHeroInfo",
                "startEnergyLevelsBonus",
                "HOMM3_FACTORY_NATURAL_OVERCLOCK_SUBSKILL_SID",
                "HOMM3_FACTORY_INDUSTRIAL_OVERCLOCK_SUBSKILL_SID",
                "+1 effective Natural line count",
                "+1 effective Industrial line count",
            ),
        ),
        (
            "make_homm3_bulwark_runes_subskills",
            ("homm3_bulwark", "sub_skill_faction_nature_", "make_homm3_native_terrain_subskill"),
        ),
        (
            "make_homm3_factory_field_triage_hero_ability",
            ("HOMM3_FACTORY_FIELD_TRIAGE_ABILITY_SID", "heal_percent", "energyLevel", "with respawn", "0.30"),
        ),
        (
            "make_homm3_factory_split_assembly_buff_rows",
            (
                "homm3_factory_split_assembly_ranged_",
                "inAllDmgMod",
                "melee_attack",
                "initiative",
                "movementPositive",
                "hasteEffect",
            ),
        ),
    ):
        helper = function_source(source, module, helper_name)
        require_tokens(helper, helper_name, tokens)
    for const_name, expected_len in (
        ("HOMM3_FACTORY_SPLIT_ASSEMBLY_SUBSKILLS_BY_LEVEL", 6),
        ("HOMM3_BULWARK_RUNES_SUBSKILLS_BY_LEVEL", 6),
    ):
        mapping = assignment_literal(module, const_name)
        flat = [sid for level in (2, 3) for sid in mapping.get(level, ())]
        if len(flat) != expected_len or len(set(flat)) != expected_len:
            fail(f"{const_name} must list six unique Advanced/Expert subskill SIDs")
    generic_lang = function_source(source, module, "add_release_generic_lang")
    require_tokens(
        generic_lang,
        "exact skill localization",
        (
            'faction_sid not in {"homm3_factory", "homm3_bulwark"}',
            'faction_sid in {"homm3_factory", "homm3_bulwark"}',
            "exact faction skill text contract is missing",
            "sub_skill_faction_homm3_factory_sand_advantage_name",
            "sub_skill_faction_homm3_bulwark_snow_advantage_name",
        ),
    )
    merge_rows = function_source(source, module, "add_release_generic_mechanic_support_rows")
    require_tokens(
        merge_rows,
        "Factory/Bulwark subskill merge",
        (
            'faction_sid == "homm3_factory"',
            'faction_sid == "homm3_bulwark"',
            "make_homm3_factory_split_assembly_subskills",
            "make_homm3_bulwark_runes_subskills",
            "merge homm3_factory Split Assembly subskills",
            "merge homm3_factory Field Triage hero ability",
            "merge homm3_factory Split Assembly buff rows",
            "merge homm3_bulwark Runes subskills",
        ),
    )
    merge_data = function_source(source, module, "merge_data_json")
    require_tokens(
        merge_data,
        "DB/data.json custom faction merge",
        (
            '("fractions", "availableFractions")',
            "CUSTOM_FACTION_MANIFEST_BY_SID",
            "CORE_ENABLED_FACTION_SIDS",
            "must be a string list",
        ),
    )
    build_overlay = function_source(source, module, "build_overlay")
    require_tokens(
        build_overlay,
        "DB/data.json overlay integration",
        (
            'data_member = "DB/data.json"',
            "merge_data_json(read_json(release_zip, data_member))",
        ),
    )
    bindings = function_source(source, module, "manifest_recruitment_bindings")
    require_tokens(bindings, "additional recruitment bindings", ("lineId", "recruitmentSlotSid", "cityBuildingSid", "directDwellingSid", "donorDwellingSid", "dwellingBillboardImage"))
    city_rows = function_source(source, module, "add_additional_recruitment_city_rows")
    require_tokens(city_rows, "Gantry city generation", ('line["recruitmentSlotSid"]', 'line["cityBuildingSid"]', "generic_unit_hire_payload"))
    require_tokens(
        source,
        "Gantry construction-tree nodePos remap table",
        (
            "HOMM3_SPECIAL_BUILDING_NODE_POS_BY_FACTION",
            '"Build_Factory_Gantry:1"',
            '"Build_Factory_Gantry:2"',
        ),
    )
    node_pos = function_source(source, module, "apply_homm3_special_building_node_pos")
    require_tokens(
        node_pos,
        "Gantry construction-tree nodePos remap",
        (
            "HOMM3_SPECIAL_BUILDING_NODE_POS_BY_FACTION",
            "nodePos",
        ),
    )
    unique_pos = function_source(source, module, "assert_city_construction_tree_node_pos_unique")
    require_tokens(
        unique_pos,
        "construction-tree nodePos uniqueness gate",
        ("construction-tree nodePos collision", "nodePos"),
    )
    normalize_city = function_source(source, module, "normalize_generic_city_doc")
    require_tokens(
        normalize_city,
        "Gantry nodePos integration",
        (
            "add_additional_recruitment_city_rows",
            "apply_homm3_special_building_node_pos",
            "assert_city_construction_tree_node_pos_unique",
        ),
    )
    construction = function_source(source, module, "ensure_additional_recruitment_buildings_in_construction_presets")
    require_tokens(
        construction,
        "Gantry construction presets",
        (
            "DB/buildings_constructions/",
            "cityBuildingSid",
            "Build_Factory_Gantry",
            "isConstructed",
            "full_buildings_construction",
        ),
    )
    # The helper must be invoked from the all-factions Core row pass.
    for_all = function_source(source, module, "add_release_generic_custom_faction_core_rows_for_all")
    require_tokens(
        for_all,
        "construction preset integration",
        ("ensure_additional_recruitment_buildings_in_construction_presets",),
    )
    map_rows = function_source(source, module, "add_release_generic_map_objects")
    require_tokens(map_rows, "additional dwelling generation", ("manifest_recruitment_bindings", "missing explicit additional donor map object", "missing explicit additional donor hire row"))

    factory = read_json(root / "custom_factions" / "homm3_factory.json")
    hire_payload = function_source(source, module, "generic_unit_hire_payload")
    require_tokens(
        hire_payload,
        "fail-closed recruitment hire payload",
        ("missing unit hire payload object", "must contain a non-empty units list", "must be an object"),
    )

    registry_source = (root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3CustomFactionRegistry.cs").read_text(encoding="utf-8-sig")
    require_tokens(
        registry_source,
        "fail-closed runtime manifest parser",
        (
            "token.Type != JTokenType.String",
            "token.ToString()",
            'must be a string.',
            "value.Type != JTokenType.Integer",
            "value.Type != JTokenType.Boolean",
            "return (int)value;",
            "return (bool)value;",
            "return (float)value;",
        ),
    )
    if ".Value<" in registry_source:
        fail("runtime manifest parser must not use unavailable parameterless JToken.Value<T>()")
    bulwark = read_json(root / "custom_factions" / "homm3_bulwark.json")
    validate_manifest(factory, "homm3_factory")
    validate_manifest(bulwark, "homm3_bulwark")
    validate_factory_additional_line(factory)
    validate_msbuild_target(root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "OfflineUnlockMod.csproj")
    validate_source_hero_biographies(root)
    validate_law_overrides(root)
    validate_bulwark_promotion(root)
    validate_split_assembly_hud(root)
    print("validated Factory/Bulwark exact Core skill and additional-recruitment contracts")


if __name__ == "__main__":
    main()
