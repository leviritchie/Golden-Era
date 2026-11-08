# Procedural Scenario Generator Handoff

Date: 2026-07-29
Workspace: V:\Games\Olden Era Playtest Tweak
Active install: V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era

## Scope

The user asked for a substantial parity improvement based on reading native maps, not another GUI test. The GUI remains untested. The final random scenario has not yet been regenerated after the last placement/layout fixes and has not been installed.

## Baseline

The last committed procedural milestone is:

12d641d848 procedural: align generated maps with native schema

Preserve all unrelated dirty-worktree changes. Do not use a broad git add ..

## Native map comparison

Read and compared these active maps:

- Gorges_of_Discord.map
- Thirst_for_Power.map
- Fun_and_Graves.map
- Glittering_Strait.map

The comparison covered the native four-chunk envelope, campaignInfo, objectValuesOverrides, the complete ObjectsProperties family set, object groups/instances/nodes, terrain arrays, roads/elevation, and event graph counts.

The old generator had high serialized instance density but visibly generic scenery. Its top SIDs included fx_map_object_blocked, fx_map_smoke, homm3_xfp_*, and other map/helper content. These were not comparable to the stock scenery mix in native maps.

## Changes made after the commit

These files are currently modified and are the intended procedural scope:

- experiments/campaign_port_poc/procedural_scenarios/catalog.py
  - Excludes known helper SIDs by default.
  - Rejects map-specific member provenance containing campaign/homecoming/mission/scenario/story unless explicitly allowlisted.
  - Explicit allowlist entries still override the default exclusion.
- experiments/campaign_port_poc/procedural_scenarios/layout.py
  - Chooses route orientation by clearance/overlap score.
  - Adds short orthogonal detour candidates when direct L-routes pass through unrelated zone centers.
  - Scores candidates for decision-spacing partitionability before selecting them.
  - Current _choose_route signature includes width, height, spacing_min, and spacing_max.
- experiments/campaign_port_poc/procedural_scenarios/placement.py
  - Required encounters use a deterministic full-map search radius after local positions are occupied; nearest positions are still tried first.
  - This fixed two observed required-footprint failures without substituting content.
- tests/procedural_scenarios/test_core_catalog.py
  - Adds a regression for Homecoming exact-footprint and helper members.
- tests/procedural_scenarios/test_core_generation.py
  - Adds the synthetic seed-9065 dense-side-edge regression.
  - Imports validate_generated_ir and TopologySettings.
- tools/audit_procedural_native_parity.py
  - Reports proceduralHelperObjectInstances.
  - The current generated map showed zero helper instances.
- docs/procedural_scenario_generator.md
  - Still describes the earlier baseline and needs a small update after the final post-fix matrix.

Do not stage the unrelated dirty files listed by git status, including campaign/localization/city-scene work.

## Evidence already obtained

A bundle was generated before the last route/detour fixes:

build/random_install_1369490071_retry

Map SID:

proc_objective_chain_1369490071_6a1d8949

That bundle passed CLI generation and validation, and its staged map passed run_preflight against the active Core at the time. Its parity audit showed stock scenery SIDs and proceduralHelperObjectInstances: 0. It is now stale for final delivery because layout/placement source changed after it was generated. Regenerate into a new directory rather than overwriting this evidence.

The active Core hash observed stable during the last successful generation was:

9638471f15df1cb2887b8e849c7bf7f6419163717428110fe38880dbd6bd316a

Recompute immediately before generation and immediately before install. The Core has changed during earlier runs, so never trust this hash without a fresh read.

The parity audit reference envelope from the native maps was:

- object instances per 100 tiles: 61.0107 to 73.7956
- unique object-node fraction: 0.532959 to 0.61849

The regenerated pre-fix/current-catalog map was inside the instance-density envelope and slightly above the unique-node envelope. It used varied stock scenery and no helper instances.

## Validation history and remaining gap

Focused checks that passed:

- python -m py_compile for changed procedural modules/tests.
- Catalog helper-member regression was not runnable in the normal sandbox because temporary-directory creation under tests/procedural_scenarios returns Windows PermissionError; this is an environment/test-harness issue, not an assertion failure.
- Synthetic route regression:
  python -m unittest tests.procedural_scenarios.test_core_generation.GenerationTests.test_route_orientation_preserves_dense_side_edge_anchors
- A post-catalog 3-seed matrix for all three archetypes and all nine size/archetype combinations passed before the later detour changes.

A subsequent 20-seed-per-archetype direct matrix exposed real edge cases:

1. conquest seed 14: required encounter could not fit near side_01;
2. 32x32 conquest seed 10033: required encounter could not fit near zone_02;
3. dense exact-spacing profile seed 20002: an anchor landed on a crowded unrelated zone.

The full-map required-encounter search fixed (1) and (2). Orthogonal route detours fixed the crowded-zone condition, but initially created an exact-spacing route of length 56 that could not be partitioned into six-step segments. Partitionability scoring was then added; the focused dense profile passed afterward.

A full post-detour 20-seed matrix was started and interrupted when the user stopped work. Its result is unknown. The matrix process (PID 9540) was explicitly stopped after interruption. Do not claim the acceptance matrix passed.

The earlier expensive staged-preflight audit also timed out and produced no complete report. Do not claim full expensive acceptance.

## Resume procedure

1. Check:
   git status --short
   git diff --check
   python -m py_compile experiments/campaign_port_poc/procedural_scenarios/catalog.py experiments/campaign_port_poc/procedural_scenarios/layout.py experiments/campaign_port_poc/procedural_scenarios/placement.py tests/procedural_scenarios/test_core_catalog.py tests/procedural_scenarios/test_core_generation.py tools/audit_procedural_native_parity.py
2. Run the full direct matrix again using the script pattern from the prior turn: seeds 1..20 for each archetype, all 32/48/64 size/archetype combinations, and the eleven _profile_extremes profiles from tools/validate_procedural_scenario_contract.py. Capture the final output; treat any failure as a code issue.
3. Run the focused catalog regression with an elevated test shell only if desired. The normal sandbox fails before assertions because of temporary-directory permissions.
4. Update docs/procedural_scenario_generator.md so it distinguishes the earlier pre-fix 20-seed evidence from the post-detour evidence.
5. Have the existing review agent inspect only the catalog/layout/placement/audit changes for hidden fallback, instruction drift, and route/footprint assumptions.
6. Commit only the scoped procedural files once the matrix and focused checks pass. Use a new message such as:
   procedural: protect native scenery and route decision clearance
7. Regenerate a final bundle using the current active Core and donor. Suggested output:
   build/random_install_1369490071_final
8. Run CLI validate, tools/audit_procedural_native_parity.py, and run_preflight against that final map. Rehash Core before install.
9. Use the transactional installer with elevated permission only after the bundle source Core hash matches the active Core. Verify installed map/sidecar hashes, installer state, no Story_maps duplicate, and installed map-load preflight.
10. Report the exact installed map title/SID. State clearly that startup/runtime movement, event advancement, victory, and GUI remain unproven until separately exercised.

## Do not do

- Do not install build/random_install_1369490071_retry as the final result; it predates the last route/placement changes.
- Do not run the GUI as validation.
- Do not relax constraints silently or substitute helper content.
- Do not clean or revert unrelated dirty-worktree changes.
- Do not claim the game fixed the earlier fcr.Init NullReference without runtime evidence.