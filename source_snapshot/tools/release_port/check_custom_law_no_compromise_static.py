#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RELEASE_PORT = ROOT / "tools" / "release_port"


CHECKS = [
    (
        "target-spec",
        RELEASE_PORT / "validate_custom_law_targets.py",
        "Validates no-compromise target law shape and override SID coverage.",
    ),
    (
        "diagnostic-profiles",
        RELEASE_PORT / "validate_custom_law_diag_profiles.py",
        "Validates packet/profile coverage for fail-closed runtime capture setup.",
    ),
    (
        "faction-manifest-deploy-payload",
        RELEASE_PORT / "validate_custom_faction_manifest_deploy_payload.py",
        "Validates deployed faction manifest inputs stay scoped to homm3_*.json manifests.",
    ),
    (
        "runtime-index-coverage",
        RELEASE_PORT / "validate_custom_law_runtime_index_coverage.py",
        "Validates target family indices against runtime law constants.",
    ),
    (
        "target-matrix",
        RELEASE_PORT / "validate_custom_law_target_matrix.py",
        "Validates every enabled custom faction has a target entry for every target law family.",
    ),
    (
        "packet-proofs",
        RELEASE_PORT / "validate_custom_law_packet_proofs.py",
        "Validates packet proof-state coverage and gameplayAllowed gating.",
    ),
    (
        "gameplay-surface-evidence-matrix",
        RELEASE_PORT / "validate_gameplay_surface_evidence_matrix.py",
        "Validates falsifiable gameplay surface evidence claims for packet-critical custom law surfaces.",
    ),
    (
        "gameplay-surface-weak-dossier-index",
        RELEASE_PORT / "validate_gameplay_surface_weak_dossier_index.py",
        "Validates generated weak-surface dossier coverage and artifact existence.",
    ),
    (
        "gameplay-surface-runtime-candidate-coverage",
        RELEASE_PORT / "validate_gameplay_surface_runtime_candidate_coverage.py",
        "Validates generated/runtime candidate coverage for implementation-relevant gameplay surfaces.",
    ),    (
        "gamesymbols-runtime-interop-evidence",
        RELEASE_PORT / "validate_gamesymbols_runtime_interop_evidence.py",
        "Validates runtime-reflection GameSymbols used by battle law ownership against generated interop evidence.",
    ),
    (
        "packet-gate-drift",
        RELEASE_PORT / "generate_custom_law_packet_gate.py",
        "Checks runtime packet gate drift against target/proof JSON.",
    ),
    (
        "runtime-guard-usage",
        RELEASE_PORT / "audit_custom_law_runtime_guard_usage.py",
        "Audits custom law source files for direct law-runtime/packet-gate usage outside the combined guard.",
    ),
    (
        "handler-registry",
        RELEASE_PORT / "validate_custom_law_handler_registry.py",
        "Validates named custom law handler slots against target family packets.",
    ),
    (
        "source-prepared-matrix",
        RELEASE_PORT / "validate_custom_law_source_prepared_matrix.py",
        "Validates source-prepared law family seams against targets, packet proofs, handlers, and source files.",
    ),
    (
        "construction-building-category-contracts",
        RELEASE_PORT / "validate_construction_building_category_contracts.py",
        "Validates source-authored construction building category contracts against exact source mechanic rows.",
    ),
    (
        "homm3-city-building-contracts",
        RELEASE_PORT / "validate_homm3_city_building_contracts.py",
        "Validates HoMM3 custom city CITY_BUILDING_MECHANICS bonus payloads and the canonical building tree against Core city JSON.",
    ),
    (
        "building-allowlist-predicate-contracts",
        RELEASE_PORT / "validate_building_allowlist_predicate_contracts.py",
        "Validates source-authored building allowlist predicate contracts against exact construction category and effect-plan inventory rows.",
    ),
    (
        "construction-cost-parity-predicate-contracts",
        RELEASE_PORT / "validate_construction_cost_parity_predicate_contracts.py",
        "Validates source-authored construction cost parity predicate contracts against exact effect-plan inventory rows.",
    ),    (
        "object-allowlist-predicate-contracts",
        RELEASE_PORT / "validate_object_allowlist_predicate_contracts.py",
        "Validates source-authored object allowlist predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "fog-reveal-mutation-predicate-contracts",
        RELEASE_PORT / "validate_fog_reveal_mutation_predicate_contracts.py",
        "Validates source-authored fog reveal mutation predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "elemental-family-mix-predicate-contracts",
        RELEASE_PORT / "validate_elemental_family_mix_predicate_contracts.py",
        "Validates source-authored elemental family mix predicate contracts against exact effect-plan inventory rows and unit-family tags.",
    ),
    (
        "warcry-execution-predicate-contracts",
        RELEASE_PORT / "validate_warcry_execution_predicate_contracts.py",
        "Validates source-authored Warcry execution predicate contracts against exact effect-plan inventory rows and Stronghold manifest identity.",
    ),
    (
        "construct-classifier-predicate-contracts",
        RELEASE_PORT / "validate_construct_classifier_predicate_contracts.py",
        "Validates source-authored construct classifier predicate contracts against exact effect-plan inventory rows and Tower unit-family evidence.",
    ),
    (
        "corpse-casualty-context-predicate-contracts",
        RELEASE_PORT / "validate_corpse_casualty_context_predicate_contracts.py",
        "Validates source-authored corpse/casualty context predicate contracts against exact effect-plan inventory rows and Necropolis undead evidence.",
    ),
    (
        "damage-taken-event-predicate-contracts",
        RELEASE_PORT / "validate_damage_taken_event_predicate_contracts.py",
        "Validates source-authored damage-taken event predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "owned-structure-radius-predicate-contracts",
        RELEASE_PORT / "validate_owned_structure_radius_predicate_contracts.py",
        "Validates source-authored owned-structure radius predicate contracts against exact effect-plan inventory rows and enabled faction manifests.",
    ),
    (
        "astrology-progress-mutation-predicate-contracts",
        RELEASE_PORT / "validate_astrology_progress_mutation_predicate_contracts.py",
        "Validates source-authored Astrology progress mutation predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "elemental-family-mapping-predicate-contracts",
        RELEASE_PORT / "validate_elemental_family_mapping_predicate_contracts.py",
        "Validates source-authored elemental family mapping predicate contracts against exact effect-plan inventory rows and Conflux unit-family evidence.",
    ),
    (
        "battle-result-casualties-predicate-contracts",
        RELEASE_PORT / "validate_battle_result_casualties_predicate_contracts.py",
        "Validates source-authored battle result casualties predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "gating-sacrifice-summon-predicate-contracts",
        RELEASE_PORT / "validate_gating_sacrifice_summon_predicate_contracts.py",
        "Validates source-authored gating/sacrifice/summon predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "sacrifice-temporary-loss-predicate-contracts",
        RELEASE_PORT / "validate_sacrifice_temporary_loss_predicate_contracts.py",
        "Validates source-authored sacrifice/temporary loss predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "neutral-threat-data-predicate-contracts",
        RELEASE_PORT / "validate_neutral_threat_data_predicate_contracts.py",
        "Validates source-authored neutral threat data predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "status-duration-mutation-predicate-contracts",
        RELEASE_PORT / "validate_status_duration_mutation_predicate_contracts.py",
        "Validates source-authored status duration mutation predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "hero-spell-cast-predicate-contracts",
        RELEASE_PORT / "validate_hero_spell_cast_predicate_contracts.py",
        "Validates source-authored hero spell-cast predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "committed-reward-identity-predicate-contracts",
        RELEASE_PORT / "validate_committed_reward_identity_predicate_contracts.py",
        "Validates source-authored committed reward identity predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "enemy-hero-positions-predicate-contracts",
        RELEASE_PORT / "validate_enemy_hero_positions_predicate_contracts.py",
        "Validates source-authored enemy hero positions predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "corpse-undead-context-predicate-contracts",
        RELEASE_PORT / "validate_corpse_undead_context_predicate_contracts.py",
        "Validates source-authored corpse/undead context predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "enemy-morale-penalty-predicate-contracts",
        RELEASE_PORT / "validate_enemy_morale_penalty_predicate_contracts.py",
        "Validates source-authored enemy morale penalty predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "opposing-law-owner-predicate-contracts",
        RELEASE_PORT / "validate_opposing_law_owner_predicate_contracts.py",
        "Validates source-authored opposing law owner predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "poison-slow-movement-restriction-predicate-contracts",
        RELEASE_PORT / "validate_poison_slow_movement_restriction_predicate_contracts.py",
        "Validates source-authored poison/slow/movement-restriction predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "native-terrain-adjacency-predicate-contracts",
        RELEASE_PORT / "validate_native_terrain_adjacency_predicate_contracts.py",
        "Validates source-authored native terrain/adjacency predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "cove-gunpowder-focus-predicate-contracts",
        RELEASE_PORT / "validate_cove_gunpowder_focus_predicate_contracts.py",
        "Validates source-authored Cove gunpowder/focus predicate contracts against exact effect-plan inventory rows and unit-family facts.",
    ),
    (
        "living-enemy-predicate-contracts",
        RELEASE_PORT / "validate_living_enemy_predicate_contracts.py",
        "Validates source-authored living enemy predicate contracts against exact effect-plan inventory rows and unit-family facts.",
    ),
    (
        "inferno-gated-identity-predicate-contracts",
        RELEASE_PORT / "validate_inferno_gated_identity_predicate_contracts.py",
        "Validates source-authored Inferno gated/sacrifice/teleport identity predicate contracts against exact effect-plan inventory rows.",
    ),    (
        "inferno-gated-entry-predicate-contracts",
        RELEASE_PORT / "validate_inferno_gated_entry_predicate_contracts.py",
        "Validates source-authored Inferno gated-entry identity predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "dynamic-elemental-family-predicate-contracts",
        RELEASE_PORT / "validate_dynamic_elemental_family_predicate_contracts.py",
        "Validates source-authored dynamic elemental family predicate contracts against exact effect-plan inventory rows and elemental-family mapping facts.",
    ),
    (
        "forward-movement-kill-predicate-contracts",
        RELEASE_PORT / "validate_forward_movement_kill_predicate_contracts.py",
        "Validates source-authored forward movement/kill predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "cove-burning-ash-dealer-predicate-contracts",
        RELEASE_PORT / "validate_cove_burning_ash_dealer_predicate_contracts.py",
        "Validates source-authored Cove Burning Ash dealer predicate contracts against exact effect-plan inventory rows and unit-family facts.",
    ),
    (
        "conflux-elemental-consumer-predicate-contracts",
        RELEASE_PORT / "validate_conflux_elemental_consumer_predicate_contracts.py",
        "Validates source-authored Conflux elemental consumer predicate contracts against exact effect-plan inventory rows and elemental/building facts.",
    ),
    (
        "fortress-status-context-predicate-contracts",
        RELEASE_PORT / "validate_fortress_status_context_predicate_contracts.py",
        "Validates source-authored Fortress status-context predicate contracts against exact effect-plan inventory rows and status taxonomy facts.",
    ),
    (
        "dungeon-target-state-predicate-contracts",
        RELEASE_PORT / "validate_dungeon_target_state_predicate_contracts.py",
        "Validates source-authored Dungeon target-state predicate contracts against exact effect-plan inventory rows.",
    ),    (
        "construction-economy-state-predicate-contracts",
        RELEASE_PORT / "validate_construction_economy_state_predicate_contracts.py",
        "Validates source-authored construction/economy state predicate contracts against exact effect-plan inventory rows.",
    ),    (
        "necropolis-corpse-state-predicate-contracts",
        RELEASE_PORT / "validate_necropolis_corpse_state_predicate_contracts.py",
        "Validates source-authored Necropolis corpse-state predicate contracts against exact effect-plan inventory rows.",
    ),    (
        "tower-spell-state-predicate-contracts",
        RELEASE_PORT / "validate_tower_spell_state_predicate_contracts.py",
        "Validates source-authored Tower spell-state predicate contracts against exact effect-plan inventory rows.",
    ),    (
        "combat-scalar-state-predicate-contracts",
        RELEASE_PORT / "validate_combat_scalar_state_predicate_contracts.py",
        "Validates source-authored combat scalar/state predicate contracts against exact effect-plan inventory rows.",
    ),    (
        "vision-map-edge-predicate-contracts",
        RELEASE_PORT / "validate_vision_map_edge_predicate_contracts.py",
        "Validates source-authored vision map-edge predicate contracts against exact effect-plan inventory rows.",
    ),    (
        "tempo-event-predicate-contracts",
        RELEASE_PORT / "validate_tempo_event_predicate_contracts.py",
        "Validates source-authored tempo event predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "spell-taxonomy-contracts",
        RELEASE_PORT / "validate_spell_taxonomy_contracts.py",
        "Validates source-authored spell taxonomy seeds against exact spellSid evidence without SID substring inference.",
    ),    (
        "spell-school-sid-predicate-contracts",
        RELEASE_PORT / "validate_spell_school_sid_predicate_contracts.py",
        "Validates source-authored spell school/SID predicate contracts against exact taxonomy and effect-plan inventory rows.",
    ),    (
        "spell-classification-predicate-contracts",
        RELEASE_PORT / "validate_spell_classification_predicate_contracts.py",
        "Validates source-authored named spell taxonomy classification predicate contracts against exact taxonomy and effect-plan inventory rows.",
    ),    (
        "native-school-verification-predicate-contracts",
        RELEASE_PORT / "validate_native_school_verification_predicate_contracts.py",
        "Validates source-authored native school verification predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "status-taxonomy-contracts",
        RELEASE_PORT / "validate_status_taxonomy_contracts.py",
        "Validates source-authored status taxonomy seeds against exact vanilla buff/effect text IDs without SID substring inference.",
    ),    (
        "negative-status-predicate-contracts",
        RELEASE_PORT / "validate_negative_status_predicate_contracts.py",
        "Validates source-authored negative status predicate contracts against exact status taxonomy and effect-plan inventory rows.",
    ),    (
        "protect-preserve-event-predicate-contracts",
        RELEASE_PORT / "validate_protect_preserve_event_predicate_contracts.py",
        "Validates source-authored protect/preserve event predicate contracts against exact status taxonomy and effect-plan inventory rows.",
    ),
    (
        "training-damage-mutation-contracts",
        RELEASE_PORT / "validate_training_damage_mutation_contracts.py",
        "Validates source-authored TrainingDamage mutation design contracts against exact effect-plan inventory rows.",
    ),
    (
        "avenger-mark-predicate-contracts",
        RELEASE_PORT / "validate_avenger_mark_predicate_contracts.py",
        "Validates source-authored Rampart Avenger mark predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "kill-loss-event-predicate-contracts",
        RELEASE_PORT / "validate_kill_loss_event_predicate_contracts.py",
        "Validates source-authored kill/loss event predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "spell-cast-event-predicate-contracts",
        RELEASE_PORT / "validate_spell_cast_event_predicate_contracts.py",
        "Validates source-authored spell-cast event predicate contracts against exact effect-plan inventory rows.",
    ),    (
        "geometry-predicate-contracts",
        RELEASE_PORT / "validate_geometry_predicate_contracts.py",
        "Validates source-authored geometry predicate contracts against exact effect-plan inventory rows.",
    ),    (
        "battle-lifecycle-predicate-contracts",
        RELEASE_PORT / "validate_battle_lifecycle_predicate_contracts.py",
        "Validates source-authored battle lifecycle predicate contracts against exact effect-plan inventory rows.",
    ),
    (
        "adventure-owned-structure-registry-source",
        RELEASE_PORT / "validate_adventure_owned_structure_registry_source.py",
        "Validates manifest-derived custom adventure city and dwelling structure classifier source.",
    ),
    (
        "effect-plan-inventory",
        RELEASE_PORT / "report_custom_law_effect_plan_inventory.py",
        "Validates source-prepared custom law effect profiles can be inventoried without fallbacks or missing custom-faction coverage.",
    ),
    (
        "effect-planner-coverage",
        RELEASE_PORT / "validate_custom_law_effect_planner_coverage.py",
        "Validates source-prepared effect profiles have non-mutating planner and predicate-description coverage.",
    ),
    (
        "profile-predicate-surface-map",
        RELEASE_PORT / "validate_custom_law_profile_predicate_surface_map.py",
        "Validates every source-prepared profile predicate maps to explicit gameplay surface evidence or an explicit missing/rejected boundary.",
    ),
    (
        "override-target-audit",
        RELEASE_PORT / "audit_custom_law_overrides_against_targets.py",
        "Audits current law override rows against no-compromise target statuses.",
    ),
    (
        "pending-source-rows",
        RELEASE_PORT / "validate_custom_law_pending_source_rows.py",
        "Validates playable no-effect pending law rows are explicit, target-backed, and bonus-free.",
    ),
    (
        "auxiliary-handoff-drift",
        RELEASE_PORT / "validate_custom_law_auxiliary_handoffs.py",
        "Validates current icon/localization handoff files cannot carry stale runtime-law claims.",
    ),
    (
        "runtime-claim-audit",
        RELEASE_PORT / "audit_custom_law_runtime_claims.py",
        "Fails candidate runtime law claims that are only diagnostic/planned or lack source-backed mutation owner evidence.",
    ),
    (
        "strict-law-overlay-mode",
        RELEASE_PORT / "validate_strict_law_overlay_mode.py",
        "Validates explicit strict law overlay source selection and fail-closed candidate validation wiring.",
    ),
    (
        "readiness-override-contract",
        RELEASE_PORT / "validate_custom_law_readiness_override_contract.py",
        "Validates implementation readiness classes against playable and strict override row state.",
    ),
    (
        "static-implementation-packets",
        RELEASE_PORT / "validate_custom_law_static_implementation_packets.py",
        "Validates per-law static implementation packet handoff integrity in memory.",
    ),
    (
        "unit-family-tags",
        RELEASE_PORT / "validate_unit_family_tags.py",
        "Validates custom unit family tag authoring shape.",
    ),
    (
        "unit-role-contracts",
        RELEASE_PORT / "validate_unit_role_contracts.py",
        "Validates source-authored shooter/melee role contracts against exact ability override metadata and unit tags.",
    ),
    (
        "unit-family-registry-drift",
        RELEASE_PORT / "check_unit_family_registry_drift.py",
        "Checks generated unit family registry drift against validated tag source.",
    ),
    (
        "construction-building-category-registry-drift",
        RELEASE_PORT / "check_construction_building_category_registry_drift.py",
        "Checks generated construction building category registry drift against validated contract source.",
    ),
    (
        "spell-taxonomy-registry-drift",
        RELEASE_PORT / "check_spell_taxonomy_registry_drift.py",
        "Checks generated spell taxonomy registry drift against validated exact spellSid contract source.",
    ),
    (
        "status-taxonomy-registry-drift",
        RELEASE_PORT / "check_status_taxonomy_registry_drift.py",
        "Checks generated status taxonomy registry drift against validated exact vanilla status contract source.",
    ),
    (
        "training-damage-mutation-registry-drift",
        RELEASE_PORT / "check_training_damage_mutation_registry_drift.py",
        "Checks generated TrainingDamage mutation design registry drift against validated contract source.",
    ),
    (
        "adventure-owned-structure-registry-drift",
        RELEASE_PORT / "check_adventure_owned_structure_registry_drift.py",
        "Checks generated adventure owned-structure registry drift against enabled custom faction manifests.",
    ),
]

REPORTS = [
    (
        "gameplay-surface-refresh",
        RELEASE_PORT / "refresh_gameplay_surface_evidence_artifacts.py",
        ROOT / "artifacts" / "custom_law_static" / "gameplay_surface_refresh_marker.md",
    ),
    (
        "target-coverage-report",
        RELEASE_PORT / "report_custom_law_target_coverage.py",
        ROOT / "artifacts" / "custom_law_static" / "custom_law_target_coverage.md",
    ),
    (
        "gameplay-surface-weak-dossier-plan",
        RELEASE_PORT / "enrich_gameplay_surface_evidence_matrix.py",
        ROOT / "artifacts" / "custom_law_static" / "gameplay_surface_weak_dossier_plan.md",
    ),
    (
        "gameplay-surface-weak-dossiers",
        RELEASE_PORT / "build_gameplay_surface_weak_dossiers.py",
        ROOT / "artifacts" / "custom_law_static" / "gameplay_surface_weak_dossier_index.md",
    ),
    (
        "gameplay-surface-runtime-candidate-coverage",
        RELEASE_PORT / "report_gameplay_surface_runtime_candidate_coverage.py",
        ROOT / "artifacts" / "custom_law_static" / "gameplay_surface_runtime_candidate_coverage.md",
    ),
    (
        "effect-plan-inventory",
        RELEASE_PORT / "report_custom_law_effect_plan_inventory.py",
        ROOT / "artifacts" / "custom_law_static" / "custom_law_effect_plan_inventory.md",
    ),
    (
        "strict-no-compromise-law-overrides",
        RELEASE_PORT / "generate_strict_no_compromise_law_overrides.py",
        ROOT / "artifacts" / "custom_law_static" / "strict_law_overrides" / "_summary.json",
    ),
    (
        "strict-candidate-rows",
        RELEASE_PORT / "report_custom_law_strict_candidate_rows.py",
        ROOT / "artifacts" / "custom_law_static" / "custom_law_strict_candidate_rows.md",
    ),
    (
        "implementation-queue",
        RELEASE_PORT / "generate_custom_law_implementation_queue.py",
        ROOT / "artifacts" / "custom_law_static" / "custom_law_implementation_queue.md",
    ),
    (
        "static-implementation-packets",
        RELEASE_PORT / "generate_custom_law_static_implementation_packets.py",
        ROOT / "artifacts" / "custom_law_static" / "custom_law_static_implementation_packets.md",
    ),
    (
        "runtime-claim-audit",
        RELEASE_PORT / "audit_custom_law_runtime_claims.py",
        ROOT / "artifacts" / "custom_law_static" / "custom_law_runtime_claim_audit.md",
    ),
]

STRICT_CHECK = (
    "strict-no-compromise-law-rows",
    RELEASE_PORT / "validate_custom_law_strict_no_compromise_rows.py",
    "Fails if non-native-exact target laws still carry concrete source override bonuses.",
)

OVERLAY_DRY_RUN_CHECK = (
    "overlay-dry-runs",
    RELEASE_PORT / "validate_custom_law_overlay_dry_runs.py",
    "Optionally runs non-deploy playable and strict overlay dry-runs with candidate Core law validation.",
)


def run_check(name: str, script: Path) -> int:
    if not script.exists():
        print(f"[{name}] missing script: {script}", file=sys.stderr)
        return 1
    print(f"[{name}] running {script.relative_to(ROOT)}")
    args = [sys.executable, str(script)]
    if name == "packet-gate-drift":
        args.append("--check")
    completed = subprocess.run(args, cwd=ROOT)
    print(f"[{name}] exit={completed.returncode}")
    return completed.returncode


def run_report(name: str, script: Path, output: Path) -> int:
    if not script.exists():
        print(f"[{name}] missing report script: {script}", file=sys.stderr)
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"[{name}] writing {output.relative_to(ROOT)}")
    if name == "gameplay-surface-refresh":
        completed = subprocess.run([sys.executable, str(script)], cwd=ROOT)
        if completed.returncode == 0:
            output.write_text(
                "Gameplay surface evidence artifacts refreshed and validated.\n",
                encoding="utf-8",
            )
    elif name == "gameplay-surface-weak-dossier-plan":
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--out-plan-md",
                str(output),
                "--out-plan-json",
                str(output.with_suffix(".json")),
            ],
            cwd=ROOT,
        )
    elif name == "gameplay-surface-weak-dossiers":
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--out-index-md",
                str(output),
                "--out-index-json",
                str(output.with_suffix(".json")),
            ],
            cwd=ROOT,
        )
    elif name == "gameplay-surface-runtime-candidate-coverage":
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--out-md",
                str(output),
                "--out-json",
                str(output.with_suffix(".json")),
            ],
            cwd=ROOT,
        )
    elif name == "effect-plan-inventory":
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--out-md",
                str(output),
                "--out-json",
                str(output.with_suffix(".json")),
            ],
            cwd=ROOT,
        )
    elif name == "implementation-queue":
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--out",
                str(output),
                "--out-json",
                str(output.with_suffix(".json")),
            ],
            cwd=ROOT,
        )
    elif name == "static-implementation-packets":
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--out-md",
                str(output),
                "--out-json",
                str(output.with_suffix(".json")),
            ],
            cwd=ROOT,
        )
    elif name == "runtime-claim-audit":
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--out-md",
                str(output),
                "--out-json",
                str(output.with_suffix(".json")),
            ],
            cwd=ROOT,
        )
    elif name == "strict-no-compromise-law-overrides":
        output.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--out-dir",
                str(output.parent),
            ],
            cwd=ROOT,
        )
        if completed.returncode == 0:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RELEASE_PORT / "validate_custom_law_strict_no_compromise_rows.py"),
                    "--override-dir",
                    str(output.parent),
                ],
                cwd=ROOT,
            )
    else:
        completed = subprocess.run([sys.executable, str(script), "--out", str(output)], cwd=ROOT)
    print(f"[{name}] exit={completed.returncode}")
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run static no-compromise custom law checks. "
            "This does not build, launch the game, mutate Core, or prove runtime behavior."
        )
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List checks without running them.",
    )
    parser.add_argument(
        "--write-reports",
        action="store_true",
        help="After all static checks pass, write generated planning reports under artifacts/custom_law_static.",
    )
    parser.add_argument(
        "--strict-no-compromise-law-rows",
        action="store_true",
        help=(
            "Also run the strict no-compromise source-row check. This is expected to fail while "
            "temporary donor compromises remain in law_overrides."
        ),
    )
    parser.add_argument(
        "--validate-overlay-dry-runs",
        action="store_true",
        help=(
            "Also run non-deploy playable and strict overlay dry-runs with candidate Core law validation. "
            "This is slower and still does not prove runtime behavior."
        ),
    )
    args = parser.parse_args()

    if args.list:
        for name, script, description in CHECKS:
            print(f"{name}: {script.relative_to(ROOT)} - {description}")
        print(f"{STRICT_CHECK[0]}: {STRICT_CHECK[1].relative_to(ROOT)} - {STRICT_CHECK[2]} (optional)")
        print(f"{OVERLAY_DRY_RUN_CHECK[0]}: {OVERLAY_DRY_RUN_CHECK[1].relative_to(ROOT)} - {OVERLAY_DRY_RUN_CHECK[2]} (optional)")
        for name, script, output in REPORTS:
            print(f"{name}: {script.relative_to(ROOT)} -> {output.relative_to(ROOT)}")
        return 0

    checks = list(CHECKS)
    if args.strict_no_compromise_law_rows:
        checks.append(STRICT_CHECK)
    if args.validate_overlay_dry_runs:
        checks.append(OVERLAY_DRY_RUN_CHECK)

    failures: list[str] = []
    for name, script, _description in checks:
        if run_check(name, script) != 0:
            failures.append(name)

    if failures:
        print("static no-compromise law checks failed: " + ", ".join(failures), file=sys.stderr)
        return 1

    if args.write_reports:
        report_failures: list[str] = []
        for name, script, output in REPORTS:
            if run_report(name, script, output) != 0:
                report_failures.append(name)
        if report_failures:
            print("static no-compromise law report generation failed: " + ", ".join(report_failures), file=sys.stderr)
            return 1

    print("static no-compromise law checks passed")
    print("Note: static pass does not prove build success or runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
