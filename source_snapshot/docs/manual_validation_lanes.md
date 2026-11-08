# Manual Validation Lanes

Status: active registry of `tools/validate_*.py` contracts that are **not** wired into the
build (`.csproj`/`.props`/`.targets`) and are **not** imported by another validator.
They run on demand for their lane. Verified 2026-09-19 by stem-match sweep over
`.github`, `tools/**/*.py`, and build files; re-run that sweep before adding rows.

Wire-up decision (2026-09-19): none of these are wired into the plugin build.
They are lane/scenario-scoped diagnostics, several are expected-fail until their
lane proves out (e.g. EventIR census default mode), and CI runs no validators at
all (`.github/workflows/release.yml` only packages the Stronghold installer).
Wire one in only when its lane becomes a normal-build contract.

## Campaign lanes

- `tools/validate_campaign_event_ir_census.py` — EventIR inventory vs delivery readiness.
  Runbook: `docs/plans/2026-07-15-golden-era-campaign-event-translation-handoff.md`.
  `python tools/validate_campaign_event_ir_census.py --repo-root . --census-only` is
  inventory; default flags are delivery-readiness fail-closed (expected FAIL until
  backends prove out).
- `tools/validate_campaign_starting_bonus_dialog_contract.py` — Day-1 starting-bonus
  Dialog wiring for Homecoming / Razor Claw / Guardian Angels.
  `python tools/validate_campaign_starting_bonus_dialog_contract.py --repo-root .`
  Lane context: `docs/handoffs/2026-07-30-starting-bonus-main-level-3.md`.
- `tools/validate_campaign_water_traversal_profile_contract.py` — water traversal
  profile resolution. `python tools/validate_campaign_water_traversal_profile_contract.py --repo-root .`
  (PASS 2026-09-19.)
- `tools/validate_h3_campaign_placed_heroes_contract.py` — placed stubs stay out of
  roster / in campaignHeroes. `python tools/validate_h3_campaign_placed_heroes_contract.py`
  (PASS 2026-09-19: 37 stubs.)

## Scenery / footprint lanes

- `tools/validate_homm3_bank_remapping_contract.py` — opt-in creature-bank / Den of
  Thieves remapping gate. Runbook: `docs/homm3_bank_remapping_handoff.md`.
  (Self-tests PASS 2026-09-19: 6 checks.)
- `tools/validate_native_footprint_model_contract.py` — audit model vs recovered
  native footprint contract. `python tools/validate_native_footprint_model_contract.py`
  (PASS 2026-09-19.)
- `tools/validate_raw_translation_visual_scenery_canon_postpass_contract.py` —
  visual scenery / canon terrain postpass static checks.
  `python tools/validate_raw_translation_visual_scenery_canon_postpass_contract.py`
  (PASS 2026-09-19.)

## Vanilla-stock lane

Runbook: `docs/plans/2026-07-12-native-only-homm3-scenario-feasibility.md`.

- `tools/validate_vanilla_stock_map_contract.py` — single-map validator
  (`--map`, `--stock-core`, `--expect-*`).
- `tools/validate_vanilla_stock_batch_contract.py` — batch validator.
  `python tools/validate_vanilla_stock_batch_contract.py --require-installed`
- `tools/validate_vanilla_stock_regression_contract.py` — regression maps vs golden
  fingerprints (`--manifest`, `--repo-root`, `--only`).

## Release / catalog lanes (runbooked elsewhere)

- `tools/validate_nexus_release_package_contract.py` — executed by
  `tools/release_installer/package_nexus_release.ps1` (and `*_v11.ps1`).
- `tools/validate_hota_factory_bulwark_neutral_asset_contract.py` — runbook:
  `tools/homm3_import/README.md`.
- `tools/validate_town_scene_mesh_contract.py` — runbook:
  `tools/homm3_town_scene_meshes/README.md`.

## Explicitly not manual (run elsewhere, verified call sites)

Imported and called by build-wired validators or installers; no manual step needed:
`validate_agent_surface_guide_contract`, `validate_campaign_town_name_contract`,
`validate_homm3_landon_dwelling_localization_contract`,
`validate_homm3_neutral_catalog_contract`,
`validate_scenery_footprint_oe_larger_contract`, `validate_seer_hut_quest_contract`.

Mesh/animation pipeline validators (`mocap_delivery`, `mocap_pipeline`, `smartrig`,
`sprite_feasibility_surgery`, `sprite_pose_editor`, `skinned_clip_pose`) are out of
scope for this registry; their execution lives inside that pipeline.
