#!/usr/bin/env python3
"""Validate the HoMM3 Conflux spell-copy visual runtime contract."""
from __future__ import annotations

import argparse
from pathlib import Path

EXPECTED = {
    "h3_air_elemental_upg": (0, "primal_1_magic_thunderbolt", 1),
    "h3_air_elemental_upg_alt": (0, "day_3_magic_haste", 1),
    "h3_fire_elemental_upg": (0, "space_1_magic_early_start", 1),
    "h3_fire_elemental_upg_alt": (0, "primal_12_magic_chain_lightning", 1),
    "h3_earth_elemental_upg": (0, "primal_4_magic_fire_globe", 1),
    "h3_earth_elemental_upg_alt": (0, "primal_7_magic_wall_of_flame", 1),
}


def read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f"missing {label}: {needle}")


def reject(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise SystemExit(f"rejected {label}: {needle}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.repo_root.resolve()
    plugin_dir = root / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"

    runtime = read(plugin_dir / "Homm3ConfluxSpellCopyVisualRuntime.cs")
    symbols = read(plugin_dir / "GameSymbols.cs")
    plugin = read(plugin_dir / "Plugin.cs")
    project = read(plugin_dir / "OfflineUnlockMod.csproj")
    overlay = read(root / "tools" / "release_port" / "apply_release_core_overlay.py")

    for unit_sid, (ability_index, spell_sid, spell_level) in EXPECTED.items():
        require(runtime, f'new("{unit_sid}", {ability_index}, "{spell_sid}", {spell_level})', f"Conflux spell-copy visual spec for {unit_sid}")

    require(runtime, "Homm3BattleEventNativeAdapter.TryReadCastAbilityEvent", "native CastAbilityEventArgs read")
    require(runtime, "Homm3UnitLawClassifier.Classify", "caster SID classification")
    require(runtime, "GameSymbols.BattleEventLaws.CasterBattleSideMembers", "caster battle-side symbol")
    require(runtime, "GameSymbols.SpellbookLaws.MagicDataTypeHints", "MagicData centralized type symbol")
    require(runtime, "GameSymbols.SpellbookLaws.MagicDataSidConfigMembers", "MagicData sidConfig centralized symbol")
    require(runtime, "GameSymbols.SpellbookLaws.MagicDataLevelMembers", "MagicData level centralized symbol")
    require(runtime, "GameSymbols.SpellbookLaws.MagicDataIsLearnedMembers", "MagicData isLearned centralized symbol")
    require(runtime, "GameSymbols.SpellbookLaws.MagicRuntimeDataTypeHints", "magic runtime data centralized type symbol")
    require(runtime, "GameSymbols.SpellbookLaws.MagicRuntimeDataInit", "magic runtime data init symbol")
    require(runtime, "GameSymbols.SpellbookLaws.CastedMagicTypeHints", "castedMagic centralized type symbol")
    require(runtime, "TryCreateCastedMagic(casterSide, magicData, spec, out var castedMagic", "MagicData to castedMagic construction")
    require(runtime, "TryCreateMagicRuntimeData(magicData, out var magicRuntimeData", "MagicData to native runtime-data construction")
    require(runtime, "ResolveExactConstructor(", "exact castedMagic constructor resolver")
    require(runtime, "ExpectedParameterTypesMatch", "signature-token method binding")
    require(runtime, "ResolveExactInstanceMethod(type, methodName, new[] { \"MagicData\", \"Hero\" })", "MagicData runtime init signature binding")
    require(runtime, "ObjectPublicPrcgObPrcgInTrPrcgInUnique\", \"ObjectPublicObcfInStcfInObcnMacfUnique\", \"Il2CppSystem.Collections.Generic.List|Hex.Session.Battle.Hex", "CastMagicEventArgs factory signature binding")
    require(runtime, "new[] { casterSide, castedMagic, eventInfo.AttackedHexes, eventInfo.AttackedHexes }", "CastMagicEventArgs factory receives native castedMagic")
    require(runtime, "GameSymbols.SpellbookLaws.CastMagicFromListsFactory", "CastMagicEventArgs list factory symbol")
    require(runtime, "new object[] { originalArgs[0], syntheticEvent }", "synthetic CastMagicEventArgs redispatch")
    require(runtime, "originalMethod.Invoke", "native dispatcher redispatch")
    require(runtime, "__args.Length != 2", "exact dispatcher argument shape guard")
    require(runtime, "DispatchedSourceEventIds", "source event duplicate guard")

    reject(runtime, "Homm3BattleActionLawRuntime", "broad battle-action runtime dependency")
    reject(runtime, "AbilityName ==", "ability display-name matching")
    reject(runtime, "Contains(candidate.UnitSid", "substring SID matching")
    reject(runtime, "new[] { casterSide, magicData, eventInfo.AttackedHexes, eventInfo.AttackedHexes }", "raw MagicData CastMagicEventArgs factory argument")
    reject(runtime, "ResolveExactStaticMethod(type, methodName, 4)", "arity-only CastMagicEventArgs factory resolver")
    reject(runtime, "ResolveExactInstanceMethod(type, methodName, 2)", "arity-only magic runtime init resolver")

    require(symbols, "internal const string MagicDataTypeId = \"law.spellbook.magicData\";", "MagicData type id")
    require(symbols, "{ \"Hex.Session.Data.MagicData\", \"MagicData\" }", "MagicData type hints")
    require(symbols, "{ \"sidConfig\" }", "MagicData sidConfig exact member")
    require(symbols, "{ \"level\" }", "MagicData level exact member")
    require(symbols, "{ \"isLearned\" }", "MagicData isLearned exact member")
    require(symbols, "internal const string MagicRuntimeDataTypeId = \"law.spellbook.magicRuntimeData\";", "magic runtime data type id")
    require(symbols, "{ \"dro\", \"ObjectPublicMaHeccObInccStMacnBoUnique\" }", "magic runtime data type hints")
    require(symbols, "internal static readonly MethodSymbol MagicRuntimeDataInit", "magic runtime data init symbol")
    require(symbols, "internal const string CastedMagicTypeId = \"law.spellbook.castedMagic\";", "castedMagic type id")
    require(symbols, "{ \"eew\", \"ObjectPublicObcfInStcfInObcnMacfUnique\" }", "castedMagic type hints")
    require(symbols, "Method_Public_Static_CastMagicEventArgs_ObjectPublicPrcgObPrcgInTrPrcgInUnique_ObjectPublicObcfInStcfInObcnMacfUnique_List_1_Hex_List_1_Hex_0", "current CastMagicEventArgs list factory symbol")
    reject(symbols, "\"bcts\"", "stale CastMagicEventArgs bcts factory fallback")

    require(plugin, "Homm3ConfluxSpellCopyVisualRuntime.TryRegister(_harmony, Log);", "plugin runtime registration")
    reject(plugin, "Homm3BattleActionLawRuntime.TryRegister", "broad battle-action runtime registration")

    require(project, "ValidateHomm3ConfluxSpellCopyVisualRuntimeContract", "MSBuild visual runtime validator target")
    require(project, "validate_homm3_conflux_spell_copy_visual_runtime_contract.py", "MSBuild visual runtime validator path")

    reject(overlay, "HOMM3_SPELL_EFFECT_UNIT_VIEW_PRESENTATION_BY_KEY", "rejected unit AbilityViewConfig spell presentation map")
    reject(overlay, "apply_spell_effect_unit_view_presentation", "rejected unit AbilityViewConfig spell presentation graft")

    print("validated HoMM3 Conflux spell-copy visual runtime contract")


if __name__ == "__main__":
    main()