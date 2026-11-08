#!/usr/bin/env python3
"""Fail-closed structural checks for the agent surface guide hub and cards.

This validator proves documentation navigation integrity only. It does not claim
runtime gameplay proof for any surface, and it does not prove that Silent miss /
wrong-proof practices (keyed lookups, managed-proxy≠native identity, proof tiers,
producer→consumer windows) were followed in code — only that the hub section and
linked cards still exist.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


class ContractError(RuntimeError):
    pass


REQUIRED_SURFACE_CARDS = (
    "heroic_strike_warrior_ability.md",
    "mage_hero_battle_ability.md",
    "unit_ability_core_overrides.md",
    "damage_mutation_law_runtime.md",
    "specialization_bonus_row_types.md",
    "separate_hero_battle_actions.md",
    "buffs_and_statuses.md",
    "faction_laws.md",
    "direct_state_index.md",
    "town_city_scene.md",
    "live_probe_and_build.md",
    "gamesymbols_obfuscation.md",
    "custom_unit_skinned_mesh.md",
    "homm2_shade_object_class.md",
    "homm2_styleblit_preview.md",
)

REQUIRED_HUB_NEEDLES = (
    "# Agent Surface Guide",
    "## Silent miss / wrong proof",
    "**Producer→consumer window**",
    "**Store key ≠ retrieve key**",
    "**Managed proxy identity ≠ native identity**",
    "**Wrong proof bar**",
    "**Wrong Method_N / DiffableCs index ≠ live raise**",
    "Method_35",
    "cfin",
    "## Navigation: player intent → surface",
    "## Family checklists (do not miss)",
    "## Stale / conflict log",
    "surfaces/heroic_strike_warrior_ability.md",
    "ignoreCasterOffence",
    "heroicStrikeDamagePerLevelBonus",
    "CUSTOM_SPECIALIZATION_BONUS_TYPES",
    "Prefer native",
    "custom_unit_skinned_mesh.md",
    "TryGetCachedBattlePresentationTemplate",
    "homm2_styleblit_preview.md",
)

REQUIRED_CARD_SECTIONS = (
    "## Intent",
    "## Ownership preference",
    "## Touch points",
    "## Pitfalls",
    "## Open unknowns",
)

# Paths referenced from the hub that must exist (relative to repo root).
REQUIRED_REFERENCED_PATHS = (
    "docs/agent_surface_guide.md",
    "docs/README.md",
    "docs/custom_town_scene_paradigm.md",
    "docs/runtime_mechanics_implementation_handoff.md",
    "docs/battle_state_logic_map.md",
    "docs/gameplay_surface_evidence_matrix.md",
    "docs/ability_editor_agent_notes.md",
    "docs/homm3_custom_faction_porting_checklist.md",
    ".cursor/skills/agent-surface-guide/SKILL.md",
    ".cursor/skills/decomp-search/SKILL.md",
    ".cursor/skills/decomp-search/pitfalls.md",
    "docs/crusader_owned_bind_skinned_mesh_handoff.md",
    "tools/validate_crusader_owned_skinned_runtime_contract.py",
    "tools/release_port/apply_release_core_overlay.py",
    "tools/live_probe_mcp/README.md",
    "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/GameSymbols.cs",
    "experiments/olden_cs_recovery/recovered/Hex/Configs/DataModels/HeroStat.cs",
    "tools/validate_homm3_unit_buff_sid_contract.py",
)


def read(repo: Path, relative: str) -> str:
    path = repo / relative
    if not path.is_file():
        raise ContractError(f"missing required file: {relative}")
    return path.read_text(encoding="utf-8-sig")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise ContractError(f"{label}: missing required text: {needle}")


def markdown_links(text: str) -> list[str]:
    return re.findall(r"\[[^\]]*\]\(([^)]+)\)", text)


def validate(repo: Path) -> None:
    hub_rel = "docs/agent_surface_guide.md"
    hub = read(repo, hub_rel)
    for needle in REQUIRED_HUB_NEEDLES:
        require(hub, needle, hub_rel)

    surfaces_dir = repo / "docs" / "surfaces"
    if not surfaces_dir.is_dir():
        raise ContractError("missing directory: docs/surfaces")

    for card_name in REQUIRED_SURFACE_CARDS:
        rel = f"docs/surfaces/{card_name}"
        card = read(repo, rel)
        for section in REQUIRED_CARD_SECTIONS:
            # Supporting cards may use shortened "## Can / cannot" — still require Intent/Ownership/Touch/Pitfalls/Open
            if section == "## Touch points" and "## Touch points" not in card and "| Kind |" in card:
                continue
            require(card, section, rel)
        # Hub must link the card somehow
        if card_name not in hub and f"surfaces/{card_name}" not in hub:
            raise ContractError(f"{hub_rel}: does not reference {card_name}")

    for relative in REQUIRED_REFERENCED_PATHS:
        if not (repo / relative).exists():
            raise ContractError(f"referenced path missing: {relative}")

    # Buff / GameSymbols cards must carry the DiffableCs-index≠Method_N lesson
    # (live-negative: Method_39/cfir ChangeAbility vs Method_35/cfin buff got-buff).
    buff_card = read(repo, "docs/surfaces/buffs_and_statuses.md")
    for needle in (
        "Method_Public_Void_Object_BattleEventArgs_35",
        "cfin",
        "ChangeAbility",
        "DiffableCs",
    ):
        require(buff_card, needle, "docs/surfaces/buffs_and_statuses.md")
    symbols_card = read(repo, "docs/surfaces/gamesymbols_obfuscation.md")
    for needle in (
        "DiffableCs method-declaration index ≠ live",
        "Method_35",
        "cfin",
        "cfir",
    ):
        require(symbols_card, needle, "docs/surfaces/gamesymbols_obfuscation.md")
    pitfalls = read(repo, ".cursor/skills/decomp-search/pitfalls.md")
    for needle in (
        "DiffableCs declaration index ≠ live",
        "Method_35",
        "cfin",
        "ChangeAbilityEventArgs",
    ):
        require(pitfalls, needle, ".cursor/skills/decomp-search/pitfalls.md")

    skinned_card = read(repo, "docs/surfaces/custom_unit_skinned_mesh.md")
    for needle in (
        "TryGetCachedBattlePresentationTemplate",
        "TryGetBattlePresentationTemplate",
        "ApplySideFacing",
        "RebaseClipPaths",
        "skinned_mesh",
        "SKIPPED_DEF_GROUPS",
        "extracted_battle_source_12fps",
        "BepInEx/plugins/OfflineUnlockMod/homm3_lab",
        "repair_meshy_coil_welds",
        "CASCADE_PHYSICS",
        "rawIslandCount",
        "nFwd",
        "nIdle",
        "nRevPick",
        "rootYawCap",
        "rootYawDeferred",
        "Homm3MeshFx",
        "homm3_mesh_fx_catalog.v1",
        "TryGetCachedNativeResManagerGameObject",
    ):
        require(skinned_card, needle, "docs/surfaces/custom_unit_skinned_mesh.md")

    skill_rel = ".cursor/skills/agent-surface-guide/SKILL.md"
    skill = read(repo, skill_rel)
    for needle in (
        "docs/agent_surface_guide.md",
        "docs/surfaces/",
        "Required workflow",
        "Prefer native Core",
        "heroic_strike_warrior_ability.md",
        "DiffableCs",
        "Method_35",
        "custom_unit_skinned_mesh.md",
        "homm2_shade_object_class.md",
        "homm2_styleblit_preview.md",
    ):
        require(skill, needle, skill_rel)
    require(hub, "agent-surface-guide", hub_rel)

    shade_card = read(repo, "docs/surfaces/homm2_shade_object_class.md")
    for needle in (
        "ColorMask A",
        "EndCameraRendering",
        "Do not runtime-compile",
        "homm2_shade_object_class",
        "EObjectType",
        "Block",
        "InternalErrorShader",
        "targetTexture",
        "isInteractable",
    ):
        require(shade_card, needle, "docs/surfaces/homm2_shade_object_class.md")
    styleblit_card = read(repo, "docs/surfaces/homm2_styleblit_preview.md")
    for needle in (
        "HoMM2_StyleBlit",
        "preview_styleblit.py",
        "Do not insert it between StorePre, Feed, and Shade",
        "view-space normals",
        "Homm2ShadeObjectClassStamp",
    ):
        require(styleblit_card, needle, "docs/surfaces/homm2_styleblit_preview.md")
    shade_shader_rel = "tools/homm3_import/unity_shaders/Homm2ShadeObjectClass.shader"
    shade_shader = read(repo, shade_shader_rel)
    require(shade_shader, "ColorMask A", shade_shader_rel)
    require(shade_shader, "OldenEra/Homm2/ShadeObjectClass", shade_shader_rel)
    require(shade_shader, "UniversalPipeline", shade_shader_rel)
    stamp_rel = (
        "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/"
        "Homm2ShadeObjectClassStamp.cs"
    )
    stamp = read(repo, stamp_rel)
    for needle in (
        "EndCameraRendering",
        "homm2_shade_object_class",
        "ColorMask A",
        "HarmonyMethod",
        "Hex/TerrainMap",
        "InternalError",
        "isInteractable",
    ):
        require(stamp, needle, stamp_rel)
    if "targetTexture != null" in stamp:
        raise ContractError(
            f"{stamp_rel}: skipping every render-texture camera hides world class; "
            "stamp BhWorldCamera even when targetTexture is set."
        )
    if "ConvertDelegate" in stamp:
        raise ContractError(
            f"{stamp_rel}: ConvertDelegate unstripping failed at runtime; "
            "patch RenderPipelineManager.EndCameraRendering instead."
        )
    if 'new Material("' in stamp:
        raise ContractError(
            f"{stamp_rel}: runtime ShaderLab Material(string) is forbidden; "
            "load the precompiled ColorMask A bundle."
        )

    # Resolve relative markdown links from hub into docs/
    hub_dir = repo / "docs"
    for target in markdown_links(hub):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        cleaned = target.split("#", 1)[0].strip()
        if not cleaned:
            continue
        # Hub links are relative to docs/
        candidate = (hub_dir / cleaned).resolve()
        try:
            candidate.relative_to(repo.resolve())
        except ValueError as exc:
            raise ContractError(f"hub link escapes repo: {target}") from exc
        if not candidate.exists():
            raise ContractError(f"hub link target missing: {target} -> {candidate}")

    # Each surface card should link back to hub or be listed (deep cards must mention hub or Ownership)
    for card_name in REQUIRED_SURFACE_CARDS[:5]:
        card = read(repo, f"docs/surfaces/{card_name}")
        for heading in ("## Requirements", "## Proof labels", "## Do-not-miss checklist"):
            require(card, heading, f"docs/surfaces/{card_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    try:
        validate(repo)
    except ContractError as exc:
        print(f"agent surface guide contract FAILED: {exc}")
        return 1
    print("agent surface guide contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
