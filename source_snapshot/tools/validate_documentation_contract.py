#!/usr/bin/env python3
"""Cheap fail-closed checks for active documentation status and retired claims."""

from __future__ import annotations

import argparse
from pathlib import Path


class ContractError(RuntimeError):
    pass


def read(repo: Path, relative: str) -> str:
    path = repo / relative
    if not path.is_file():
        raise ContractError(f"missing documentation contract file: {relative}")
    return path.read_text(encoding="utf-8-sig")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise ContractError(f"{label}: missing required text: {needle}")


def forbid(text: str, needle: str, label: str) -> None:
    if needle in text:
        raise ContractError(f"{label}: retired claim still present: {needle}")


def validate(repo: Path) -> None:
    root_readme = read(repo, "README.md")
    require(root_readme, "# Olden Era Playtest Tweak", "README.md")
    require(root_readme, "scenario and campaign translation", "README.md")
    require(root_readme, "docs/README.md", "README.md")

    docs_readme = read(repo, "docs/README.md")
    require(docs_readme, "## Truth Order", "docs/README.md")
    require(docs_readme, "Runtime claims", "docs/README.md")
    require(docs_readme, "validate_documentation_contract.py", "docs/README.md")
    require(docs_readme, "../project-doc.md", "docs/README.md")
    require(docs_readme, "agent_surface_guide.md", "docs/README.md")
    require(docs_readme, "homm3_seer_hut_questscript.md", "docs/README.md")

    # Structural hub/cards/path integrity (navigation only; not runtime proof).
    from validate_agent_surface_guide_contract import validate as validate_agent_surface_guide

    validate_agent_surface_guide(repo)

    from validate_owned_bind_species_contract import validate as validate_owned_bind_species

    validate_owned_bind_species(repo)

    agents = read(repo, "AGENTS.md")
    require(agents, "## Current Validated State", "AGENTS.md")
    require(agents, "StreamingAssets/maps/Story_maps/", "AGENTS.md")
    require(agents, "docs/homm3_seer_hut_questscript.md", "AGENTS.md")
    seer_doc = read(repo, "docs/homm3_seer_hut_questscript.md")
    require(seer_doc, "Confirmed FSM", "docs/homm3_seer_hut_questscript.md")
    require(seer_doc, "SubQuestDeactivate", "docs/homm3_seer_hut_questscript.md")
    from validate_seer_hut_quest_contract import (  # noqa: WPS433
        validate_compile_shape as validate_seer_hut_compile_shape,
    )

    validate_seer_hut_compile_shape()
    gate_source = read(repo, "experiments/campaign_port_poc/raw_translation/gate_face_rotation.py")
    require(gate_source, 'POLICY = "', "GATE rotation source")
    installer = read(repo, "tools/install_roe_castle_continuity_weave.py")
    require(
        installer,
        'INSTALL_DESTINATION_POLICY = "story_maps_only_forbid_maps_root_duplicate"',
        "continuity installer",
    )
    for stale in (
        "## Current Validated Breadcrumbs",
        "installed to `maps/` + `maps/Story_maps/`",
        "Active playtest target is layered atlas only",
        "first-five campaign batch",
        "raw_single_gate_mirror_rotation_to_free_cardinal_approach",
    ):
        forbid(agents, stale, "AGENTS.md")

    archive_markers = {
        "docs/AGENT_REFERENCE.md": "Archived reference snapshot",
        "docs/OLDEN_ERA_PLAYTEST_AGENTIC_KNOWLEDGE_BASE.md": "Archived reference snapshot",
        "docs/homm3_future_faction_porting_source_of_truth.md": "Historical implementation record",
        "docs/rag_chunks/README.md": "Archived RAG snapshot",
        "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/AGENT_REBUILD_AND_MAINTENANCE.md": "Archived maintenance compendium",
    }
    for relative, marker in archive_markers.items():
        require(read(repo, relative), marker, relative)

    continuity = read(repo, "docs/plans/2026-07-10-homm3-campaign-continuity-viability.md")
    require(continuity, "Story_maps-only install policy", "continuity plan")
    require(continuity, "raw_translation", "continuity plan")
    for stale in ("Core registration unproven", "Sequels use layered atlas SIDs", "five-mission batch"):
        forbid(continuity, stale, "continuity plan")

    storyhub = read(repo, "docs/plans/2026-07-12-storyhub-visual-parity.md")
    require(storyhub, "firstShowActions", "StoryHub visual plan")
    require(storyhub, "Homm3StoryHubMapBackgroundHook", "StoryHub visual plan")
    require(storyhub, "runtime visual proof pending", "StoryHub visual plan")
    forbid(storyhub, "bridge not implemented", "StoryHub visual plan")
    forbid(storyhub, "hooks ready / assets blocked", "StoryHub visual plan")
    forbid(storyhub, "were never transcoded or installed", "StoryHub visual plan")

    native_only = read(repo, "docs/plans/2026-07-12-native-only-homm3-scenario-feasibility.md")
    require(native_only, "Stock Core is an allowlist", "stock-native plan")
    require(native_only, "Runtime load and gameplay", "stock-native plan")
    forbid(native_only, "No stock-install map emit", "stock-native plan")

    event_policy = read(repo, "docs/plans/2026-07-12-campaign-scenario-event-policy.md")
    require(event_policy, "shared policy covers all seven RoE Castle batch missions", "event policy")
    require(event_policy, "Neutral Affairs | 4 | 4 | 0 | 0", "event policy")
    require(event_policy, "QuestScript `GiveRes`", "event policy")
    forbid(event_policy, "not currently a complete batch contract", "event policy")
    forbid(event_policy, "Neutral Affairs | not pinned", "event policy")

    functional = read(repo, "docs/plans/2026-07-09-functional-points-olden-first.md")
    require(functional, "static accessibility contract", "functional-points plan")
    forbid(functional, "unreachable or uncickable", "functional-points plan")
    forbid(functional, "reachability / clickability", "functional-points plan")

    importer = read(repo, "tools/homm3_import/README.md")
    require(importer, "production default 60", "HoMM3 importer README")
    require(importer, "DeployHomm3Bundles=true", "HoMM3 importer README")
    forbid(importer, "120 FPS (production)", "HoMM3 importer README")
    forbid(importer, "deploys all `build_out", "HoMM3 importer README")

    esquire = read(repo, "tools/custom_prefab_pipeline/ESQUIRE_STOCK_VISUAL_CONTRACT.md")
    require(esquire, "legacy parsed/clamped value", "Esquire visual contract")
    forbid(esquire, "re-enable the ResManager prefix with deferral", "Esquire visual contract")

    billboard = read(repo, "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/HOMM3_NATIVE_BILLBOARD_PIPELINE.md")
    billboard_source = read(repo, "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportVisuals.cs")
    require(billboard, "TownStyleUnitBillboardScale = 0.125f", "native billboard guide")
    require(billboard_source, "TownStyleUnitBillboardScale = 0.125f", "native billboard source")
    forbid(billboard, "TownStyleUnitBillboardScale = 0.5", "native billboard guide")

    live_probe = read(repo, "tools/live_probe_mcp/README.md")
    require(live_probe, "active Golden Era build", "live probe README")
    forbid(live_probe, "Deobf build only", "live probe README")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    repo = args.repo_root.resolve()
    try:
        validate(repo)
    except ContractError as exc:
        print(f"documentation contract FAILED: {exc}")
        return 1
    print("documentation contract PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
