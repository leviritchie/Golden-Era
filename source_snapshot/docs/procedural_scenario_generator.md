# Procedural Scenario Generator

## Scope

The procedural scenario framework generates deterministic, native Olden Era `.map` and paired `.json` payloads for single-player exploration, conquest, and objective-chain scenarios. It does not modify the three bespoke scenario builders.

The public Python package is `procedural_scenarios`; implementation modules live under `experiments/campaign_port_poc/procedural_scenarios/`. The desktop application and CLI use the same service APIs.

## Pipeline

1. Normalize and validate `ScenarioProfileV1` without implicit relaxation.
2. Resolve the installed Golden Era + OfflineUnlockMod context and build an immutable `ContentCatalogSnapshot` from its active `Core.zip` plus optional validated custom manifests.
3. Derive independent deterministic RNG streams for topology, layout, terrain, placement, and events.
4. Generate and embed the progression graph, paint surface terrain, and place native settlements, objectives, encounters, rewards, interactables, and scenery with validated footprints.
5. Compile typed mechanics with one explicit victory action.
6. Optionally request structured flavor text after mechanics are frozen.
7. Emit a deterministic Olden container and composable Core deltas.
8. Validate the bundle and, only on explicit request, install it transactionally against a pending effective Core.

Generation failures return structured constraint violations. The generator does not silently reduce density, replace content, change topology, or add a fallback victory path.

## Profile

The checked-in baseline is `scenarios/procedural/default.profile.json`. It defaults to a 64x64 surface map, text mode `none`, and meaningful decision spacing between 6 and 10 movement steps. Supported sizes are 32x32, 48x48, and 64x64.

All major choices are profile fields: seed, archetype, size, player and AI factions, AI count, difficulty, economy, biomes, gameplay and scenery density, event policy, topology toggles, locale, and text-provider configuration. Unsupported water generation fails closed rather than emitting an unproven map.

## Text Policy

Mechanical event specifications and flavor presentation are separate.

- `none`: emits standardized mechanical labels and no dialog or flavor localization.
- `optional`: records provider/schema failure and retains the valid textless scenario.
- `required`: fails generation on provider, schema, cache, or presentation failure.

Quest-log `name`/`desc` fields are still LocKit SIDs even in text mode `none`. The emitter writes stable SIDs such as `{mapSid}_main_name` and `{objectiveSid}_name`, and the installer upserts the mechanical English strings into every Core `Lang/*/texts/customMaps.json` `tokens` and `array` section. Inline English in those fields renders as `LOC:` placeholders.

The OpenAI-compatible provider uses strict structured output. Cached entries are keyed by the mechanical fingerprint, provider, model, prompt version, and locale. Presentation can only append dialog actions and Core localization/dialog members; it cannot alter conditions or mechanical actions.

## Commands

```powershell
python tools\procedural_scenario_cli.py catalog
python tools\procedural_scenario_cli.py generate --profile scenarios\procedural\default.profile.json --output <bundle>
python tools\procedural_scenario_cli.py validate <bundle>
python tools\procedural_scenario_cli.py install <bundle> --game-root <Golden Era root>
python tools\procedural_scenario_cli.py uninstall <map-sid> --game-root <Golden Era root>
```

Catalog and generation discover the active modded installation from Steam and derive its `Core.zip` and canonical native schema map automatically. `--game-root <Golden Era root>` is their single explicit override and `OLDEN_GOLDEN_ERA_ROOT` is the environment equivalent. Discovery fails closed when there is no valid installation, more than one valid installation, or the selected root lacks the game executable, active Core, canonical schema map, or `OfflineUnlockMod.dll`. Install and uninstall remain opt-in mutating commands and therefore require `--game-root` explicitly.

`--core` remains an advanced catalog override; generation requires it to be paired with the advanced `--donor` override. These file-level options are reserved for fixture and patch-audit work, are not exposed in the desktop application, and cannot be combined with `--game-root`.

Cheap source/schema contract:

```powershell
python tools\validate_procedural_scenario_contract.py
```

Explicit generation/diversity audit:

```powershell
python tools\validate_procedural_scenario_contract.py --expensive --core <Core.zip> --donor <donor.map> --output <audit-dir>
```

The expensive audit requires at least 20 fixed seeds per archetype, emits and validates every fixed-seed native bundle, stages its effective Core, runs map-load preflight for every fixed seed, checks all supported size/archetype combinations, retains rejected-seed diagnostics, and measures topology/layout/biome/route/encounter/objective diversity.

## Desktop Application

`tools/procedural_scenario_gui.py` launches the PySide6 application from the developer environment. It exposes one persisted Golden Era installation selector with strict Steam auto-detection; Core and donor files are implementation details and have no GUI fields. The remaining surface covers profile editing, presets, seed controls, catalog and faction selection, map preview, density summaries, structured diagnostics, a timestamped activity log with copy/clear controls, bundle library, validation, and install/uninstall management.

Build the self-contained Windows executable with:

```powershell
powershell -File tools\procedural_scenario_gui\build.ps1
```

The build uses the pinned V-drive environment in `tools/procedural_scenario_gui/requirements.txt` and writes the executable under `build/procedural_gui/dist/`.

## Bundle And Installation

A bundle contains:

- `maps/<sid>.map` and `maps/<sid>.json`
- normalized `profile.json`
- `preview.json`
- `manifest.json` with source and payload hashes
- `core_deltas.json`
- content-addressed `sources/<sha256>` evidence for every non-Core custom manifest and declared source file

The installer requires an explicitly selected Golden Era root. It validates the bundle, rejects duplicates under `Story_maps`, applies deltas to a candidate Core, runs map-load preflight, records one original backup set, atomically replaces the Core/map/sidecar/state, verifies installed hashes, and reruns preflight. Update and uninstall operations fail on external payload drift and use reverse install order.

## Native-Parity Baseline

A read-only serialized-map audit compares generated payloads with active Golden Era maps. The current 64x64 default (`proc_exploration_1_f3a768fc`) emits 2,601 object instances across 199 native object groups and occupies 2,558 unique nodes (62.45% of the surface, 63.5 instances per 100 tiles). The vanilla comparison set measured 53.3-61.8% unique-node occupancy and 61.0-73.8 instances per 100 tiles. The generated instance density is in that envelope; unique-node occupancy is slightly above its upper bound, so it is dense rather than a sparse point scatter but still has a tracked occupancy gap.

The current payload uses four catalog-backed terrain IDs, 208 road cells, 30 climb cells, deterministic elevation with 48.3% non-zero levels, 16 contiguous painted areas, two native city-spawner starts, two neutral `random-city` settlements, 27 random-squad encounter guards, 36 resource-parameter rows, 31 reward-parameter rows, 20 activation rows, and 143 entity bindings. The full native `ObjectsProperties` 29-list schema is emitted even when a family is empty. `campaignInfo` is an explicit five-field object and `objectValuesOverrides` is the native `{ "list": [] }` wrapper; these are source-level loader-shape fixes, not runtime proof.

Random-squad encounters now use native `propRandomSquads` rows with requested value, faction, tier, and custom top unit. `propSquads` is not used for the abstract `random-squad` ObjectConfig; exact squad IR and encounter-template metadata remain deterministic mechanics, while the emitted property family matches the native map representation. Generic encounter AI-interaction rows are not emitted; the only current `propAiIntetactions` rows come from known native AI-ignore resource contracts. City starts use the native city-spawner ObjectConfig with `spawnType: 0` and `spawnPointType: 0`; neutral cities use `random-city` with owner -1.

Optional gameplay targets are sampled over the whole surface instead of stacking on zone centers. Before scenery, the placer reserves deterministic paths to every interaction, so the high-density visual pass cannot strand a valid objective or encounter. Generation failures remain structured and fail closed; no placement is silently dropped.

The current event payload contains 7 declared counters, 36 triggers, 7 subquests under one main quest, and one explicit `GameVictory` action. Objective-chain maps gate each later objective visit on the preceding objective counter. Exploration retains free objective order, and conquest has one capture victory target; no implicit defeat-all-enemies fallback is enabled.

Elevation is profile-controlled. The default fraction is tuned to the lower native range; water remains disabled because water traversal and boat behavior are not runtime-proven. `tools/audit_procedural_native_parity.py` records these comparisons and its proof boundary is serialization only.

## Proof Status

Source/static validation includes the cheap contract, profile/RNG/event tests, schema/property validation, the native parity audit, and direct current-source generation audits.

Pre-fix direct evidence (before route-detour / decision-anchor clearance work): generated and validated all 20 fixed seeds for each archetype, all nine supported size/archetype combinations, and all eleven profile extremes; each fixed-seed archetype set produced 20 unique mechanical fingerprints. A later full-map encounter search and route-detour pass exposed placement failures that were fixed without relaxing content constraints.

Post-detour direct evidence (`build/procedural_direct_matrix_post_detour/direct_matrix_report.json`, Core hash recomputed at run time): again generated and IR-validated all 20 fixed seeds per archetype, all nine size/archetype combinations, and all eleven profile extremes, with 20 unique mechanical fingerprints per archetype. Category diversity thresholds from the expensive audit are observed in that report but are not part of the direct-matrix gate; conquest with the default single AI faction naturally collapses objective-fingerprint uniqueness because the victory town stays on the same lattice seat.

Helper ObjectConfig SIDs and Core members whose archive path encodes campaign/homecoming/mission/scenario/story provenance are excluded from the default catalog unless allowlisted. Required encounters may search the full map after local seats are full, but only while an off-route clearance ring around planned decision anchors is reserved; that ring is released before exact anchor placement. Neutral cities place after anchors so radius-9 town footprints cannot strand corridor interactions.

A fresh expensive run with per-seed staged preflight is still not claimed as a complete acceptance audit. The representative random bundle must be regenerated after these placement/layout fixes before install proof.

Installation and installed map-load preflight are still separate proof tiers. Runtime menu discovery, map loading in the game, city initialization, movement, event advancement, victory, and user-visible gameplay remain unproven until the fresh random bundle is installed and exercised. The GUI remains untested.
