# Custom Faction Technical Implementation Proposals

Generated: 2026-05-25

Scope: concrete implementation proposals for the `Recommended Implementation Order` and `No-Change Rules` at the end of `docs/custom_faction_design_recommendations.md`. This is a technical proposal document only. It does not claim any change is implemented until the named generator, validator, Core archive, and runtime payload checks pass.

## Source Rule

All changes below should be generator-owned. Do not hand-edit the live Steam `Core.zip`, and do not use broad donor, icon, unit-view, or localization fallbacks to hide missing data. A missing source mechanic should be represented as an explicit `blocked`, `substituted`, or `trace_required` contract and enforced by validation.

## Phase 1 - Source Mechanics Contracts

Problem to solve: faction plan docs describe accepted, blocked, and substituted mechanics, but the generator has no machine-readable contract that prevents later Core rows or text from drifting away from those decisions.

Proposed files:

- Add `custom_factions/source_mechanics/homm3_castle.json`
- Add `custom_factions/source_mechanics/homm3_rampart.json`
- Add `custom_factions/source_mechanics/homm3_tower.json`
- Add `custom_factions/source_mechanics/homm3_inferno.json`
- Add `custom_factions/source_mechanics/homm3_necropolis.json`
- Add `custom_factions/source_mechanics/homm3_dungeon.json`
- Add `custom_factions/source_mechanics/homm3_fortress.json`
- Add `custom_factions/source_mechanics/homm3_conflux.json`
- Add `custom_factions/source_mechanics/homm3_cove.json`
- Add `custom_factions/source_mechanics/homm3_stronghold.json`

Proposed schema:

```json
{
  "schemaVersion": 1,
  "factionSid": "homm3_cove",
  "sourceDoc": "docs/homm3_faction_plans/cove.md",
  "mechanics": [
    {
      "id": "cove.shipyard",
      "surface": "building",
      "sourceName": "Shipyard",
      "status": "blocked",
      "reason": "Current Olden Era target has no verified water/ship gameplay route.",
      "currentRows": ["Build_Artifact_Market"],
      "currentBehavior": "artifactMarkets row; Quartermaster's Wharf text must describe artifact access, not ship purchase.",
      "implementationOwner": "tools/release_port/apply_release_core_overlay.py",
      "validationOwner": "tools/validate_custom_faction_manifests.py",
      "playerTextPolicy": "must_not_claim_source_behavior"
    }
  ]
}
```

Allowed `status` values:

- `exact`: the source behavior is implemented in current data/runtime.
- `substituted`: current behavior intentionally differs from source, and player text must describe the substitute.
- `blocked`: source behavior is not implementable in the current target until a missing engine route exists.
- `trace_required`: source behavior is desired, but the exact Olden Era route is not proven.

Generator changes:

- In `tools/release_port/apply_release_core_overlay.py`, add `SOURCE_MECHANICS_DIR = DEFAULT_MANIFEST_DIR / "source_mechanics"` near `HERO_OVERRIDE_DIR`.
- Add `load_source_mechanics(faction_sid: str) -> dict[str, Any] | None`.
- Add `source_mechanics_for_surface(faction_sid: str, surface: str) -> list[dict[str, Any]]`.
- Call the loader from `normalize_generic_city_doc`, `apply_city_building_mechanics`, `apply_custom_ability_overrides_to_custom_unit_rows`, and `apply_custom_hero_overrides` only for validation notes and metadata stamping, not for fallback behavior.
- Stamp generated rows with narrow metadata such as `xHomm3SourceMechanic: "cove.shipyard"` and `xHomm3MechanicsStatus: "substituted"` when a row intentionally substitutes source behavior. This keeps future audits local to the row.

Validator changes:

- In `tools/validate_custom_faction_manifests.py`, add `validate_source_mechanics_contract(core: Path, manifest: dict[str, Any], v: Validation)`.
- Call it from `validate_core_members` after `validate_city_building_presentation`.
- Fail if any player-facing `Lang/english/texts/*.json` row claims a `blocked` or `trace_required` source mechanic as working. Use exact tokens listed in the contract rather than broad phrase scans.
- Fail if a `substituted` contract lacks a generated row with matching `xHomm3SourceMechanic`.
- Warn if an `exact` contract has no validation hook named in `validationOwner`.

Documentation changes:

- Add a short `## Implementation Contract` table to every active faction plan doc in `docs/homm3_faction_plans/*.md`.
- Create `docs/homm3_faction_plans/stronghold.md` or add a Stronghold section to `docs/homm3_future_faction_porting_source_of_truth.md`; the source contract should not live only in old release-port notes.
- Table columns: `Mechanic`, `Status`, `Current row/hook`, `Owner`, `Validation`, `Player text policy`.

## Phase 2 - Hero Specialization Overrides

Problem to solve: `tools/ability_editor/prefill_homm3_hero_overrides.py` currently writes `specialization` objects with `mode: "custom"` and empty `sourceSpecId`, `nameText`, `descriptionText`, `iconKey`, and `bonuses`. `apply_custom_hero_overrides()` then preserves or normalizes generated rows, but empty override payloads are not source-confirmed design.

Proposed data changes:

- Update every `custom_factions/hero_overrides/homm3_*.json` entry so each enabled hero has one of these explicit specialization states:
  - `mode: "custom"` with non-empty `sourceSpecId`, `nameText`, `descriptionText`, `iconKey`, and `bonuses`.
  - `mode: "copy"` with non-empty `sourceSpecId` and a copied Olden Era source row that is explicitly justified in `notes`.
  - `mode: "blocked"` with `sourceSpecId`, `reason`, and no generated gameplay text claiming the source specialty works.

Proposed `mode: "custom"` shape:

```json
"specialization": {
  "mode": "custom",
  "sourceSpecId": "h3_orrin_archery",
  "nameText": "Archery",
  "descriptionText": "Ranged Castle units gain a source-checked Archery specialist bonus. Receiver SIDs: h3_archer, h3_archer_upg, h3_archer_upg_alt, h3_monk, h3_monk_upg, h3_monk_upg_alt.",
  "iconKey": "skill_assault",
  "bonuses": [
    {
      "type": "unitStat",
      "fraction": "homm3_castle",
      "unitTags": ["h3_archer", "h3_archer_upg", "h3_archer_upg_alt"],
      "parameters": ["outAllDmgMod", "0.05"]
    }
  ]
}
```

Script changes:

- In `tools/ability_editor/prefill_homm3_hero_overrides.py`, add a `H3_SPECIALTY_TO_OVERRIDE` table keyed by normalized hero name. The table should hold `sourceSpecId`, display text, icon, and a generator callback name.
- Add generator helpers:
  - `make_unit_specialist_spec(faction_sid, unit_sids, stat_key, base_value, level_step=None)`.
  - `make_skill_specialist_spec(skill_sid, stat_key, base_value, level_step=None)`.
  - `make_resource_specialist_spec(resource_sid, amount)`.
  - `make_spell_specialist_spec(spell_sid, value_key, base_value, level_step=None)`.
- Keep `BASE_HOTA_START_ARMIES` for starter armies, but do not let starter-army fallback create a specialization fallback. If no source specialty is known, emit `mode: "blocked"` and a warning.
- Add `--require-specializations` to return nonzero when any enabled hero would be written with `mode: "blocked"` or empty custom bonuses.

Overlay changes:

- In `tools/release_port/apply_release_core_overlay.py`, update `build_custom_specialization_row()` so:
  - `mode: "blocked"` keeps or emits a non-gameplay diagnostic row only if the faction is not release-enabled; release-enabled factions should fail validation instead.
  - `mode: "custom"` requires cleaned bonuses. Empty bonuses should append a warning and leave the current row unchanged only in dry-run contexts.
  - `sourceSpecId` is copied to `xHomm3SourceSpecId`.
- Keep `normalize_custom_hero_specialization_text_for_all()` after `apply_custom_hero_overrides()` so text derives from final bonus rows, not stale override descriptions.

Validator changes:

- Add `validate_hero_override_specializations(manifest, core, v)` in `tools/validate_custom_faction_manifests.py`.
- Fail when an enabled hero override has `mode: "custom"` with empty `bonuses`.
- Fail when release-enabled factions have `mode: "blocked"`.
- Fail when `DB/heroes_specializations/specializations_homm3_*.json` lacks `xHomm3SourceSpecId` for a custom hero whose override has `sourceSpecId`.
- Fail when hero specialization text in `Lang/english/texts/heroInfo.json` still contains generic phrases such as `scaling Attack and Defense` for rows whose final bonuses are not attack/defense scaling.

Validation commands:

```powershell
python tools\ability_editor\prefill_homm3_hero_overrides.py --require-specializations
python tools\release_port\apply_release_core_overlay.py --dry-run --release-core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip"
python tools\validate_custom_faction_manifests.py --core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip"
```

## Phase 3 - Unit Variant Branch Audit And Overrides

Problem to solve: the recommendations identify duplicate presentation, missing source mechanics, and alternate upgrades that may not yet create a meaningful decision. The existing `custom_factions/ability_overrides/*.json` path is the right owner for unit-level behavior, but only five factions currently have ability override files.

Proposed data changes:

- Add `custom_factions/ability_overrides/homm3_rampart.json` if not already present with explicit rows for all 21 live city-hire SIDs.
- Add `custom_factions/ability_overrides/homm3_tower.json` if not already present with explicit rows for all 21 live city-hire SIDs.
- Add `custom_factions/ability_overrides/homm3_inferno.json` if not already present with explicit rows for all 21 live city-hire SIDs.
- Add `custom_factions/ability_overrides/homm3_fortress.json` if not already present with explicit rows for all 21 live city-hire SIDs.
- Add `custom_factions/ability_overrides/homm3_stronghold.json` if not already present with explicit rows for all 21 live city-hire SIDs.
- Keep existing `custom_factions/ability_overrides/homm3_castle.json`, `homm3_conflux.json`, `homm3_cove.json`, `homm3_dungeon.json`, and `homm3_necropolis.json`, but extend them with `branchRole`, `sourceMechanicId`, and `decisionTest` fields per unit.

Proposed unit override additions:

```json
"h3_centaur_ranger_upg_alt": {
  "branchRole": "alternate-scout-skirmisher",
  "sourceMechanicId": "rampart.centaur_ranger",
  "decisionTest": "Player should choose this over Centaur Captain when speed/initiative positioning is worth lower durability or lower damage.",
  "existingSpecials": [],
  "replaceExistingAbilities": false,
  "replaceExistingPassives": false
}
```

Generator changes:

- In `apply_custom_ability_overrides_to_custom_unit_rows()`, preserve unknown documentation-only fields such as `branchRole`, `sourceMechanicId`, and `decisionTest`; do not write them into Core rows unless explicitly mapped.
- Add optional `logicPatch` and `viewPatch` subobjects for exact JSON edits that are not expressible through `existingSpecials`.
- Add helper `apply_exact_unit_patch(item, patch, allowed_paths)` where `allowed_paths` is restricted to known safe keys: `ai`, `stats`, `abilities`, `passives`, `defaultAttacks`, `alternativeAttacks`, `counterAttacks`, and view card buckets. Reject arbitrary paths.
- Add `xHomm3BranchRole` and `xHomm3SourceMechanic` metadata to generated logic/view rows when an override applies.

Specific first-pass branch fixes to document in the override files:

- Castle Angel line: mark `h3_angel`, `h3_angel_upg`, and `h3_angel_upg_alt` with `sourceMechanicId: "castle.angel_flying_resurrection"` and `decisionTest` that treats current shooter-style AI as implementation debt until the flight/resurrection presentation route is verified.
- Fortress duplicate names: for `h3_gnoll`, `h3_lizardman`, `h3_serpent_fly`, `h3_basilisk`, `h3_gorgon`, `h3_wyvern`, and `h3_hydra` lines, add `decisionTest` requiring either distinct alternate names/roles or removal of alternate presentation. Validation should fail duplicate branch display names for release-enabled factions unless a source contract marks the duplicate intentional.
- Cove Sea Dog: mark `h3_sea_dog` with `sourceMechanicId: "cove.gunpowder_warehouse_sea_dog"` and `status: "trace_required"` until a hire UI/session prerequisite hook exists. Do not add fields under `unitsHire.units[*]`; current `BuildingHireConfig` has no per-unit prerequisite field.
- Rampart Wood Elf line: mark `h3_grand_elf` as the shooter branch and `h3_elf_wardancer_upg_alt` as the melee branch. Validation should compare logic/view attack buckets so melee alternates do not reuse shooter-only attack presentation.
- Tower Giant line: mark `h3_giant` and `h3_giant_upg_alt` as non-shooter unless source says otherwise; `h3_giant_upg` / Titan remains the shooter branch.

Validator changes:

- Extend `validate_core_unit_attack_view_parity()` or add `validate_unit_branch_roles()` in `tools/validate_custom_faction_manifests.py`.
- Fail if a live city-hire SID has no matching ability override row after all ten override files exist.
- Fail if `branchRole` contains `melee` but logic/view rows contain only ranged-capable attack buckets.
- Fail if `branchRole` contains `shooter` but `validate_ranged_attack_contract()` does not pass.
- Fail if standard and alternate display names are identical and no source mechanics contract explicitly allows it.
- Fail if a row marked `trace_required` has player-facing text claiming the behavior is exact.

Validation commands:

```powershell
python tools\validate_custom_faction_manifests.py --core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip"
python tools\generate_custom_faction_wiki.py
git diff --check -- custom_factions docs tools
```

## Phase 4 - Source-Defining Building Mechanics

Problem to solve: several current city rows are honest native-supported substitutions, but source-defining buildings still need exact Olden Era routes before implementation.

Do not implement these as JSON wishcasting:

- Cove `Gunpowder Warehouse` Sea Dog prerequisite: current `BuildingHireConfig.unitsHire` has one payload for the dwelling and `UnitInfo` has only `sids` plus `weeklyIncrement`. Proposed technical route is a traced UI/session hook, not adding `prevBuildings` under `unitsHire.units[*]`.
- Cove `Shipyard`: blocked until a verified water/ship gameplay route exists.
- Inferno `Castle Gate`: requires a town-to-town owned-Inferno transfer UI/session route; do not substitute with hidden teleport text.
- Tower `Library`: requires a traced Mage Guild spell-offering expansion route; do not claim extra spells while current row is view-radius or training substitute.
- Necropolis `Necromancy Amplifier` and `Soul Prison`: require global allied-hero Necromancy modifier support or a precise session hook.
- Dungeon `Portal of Summoning`: requires external dwelling ownership and recruitment APIs.
- Rampart `Treasury`: requires weekly income ordering and owned-town iteration.
- Stronghold `Escape Tunnel` and `Freelancer's Guild`: ship as `source_mechanics` substitutions (`Build_Spy_Network` / `Build_Bank`); exact HotA siege escape / creature-sale remain optional future hook territory. `Ballista Yard` / war-machine purchase: still no proven city path.

Proposed code organization:

- Keep data-only, native-supported substitutions in `apply_city_building_mechanics()` and `ensure_city_building_mechanic_rows()`.
- Add a new section in `apply_release_core_overlay.py` named `# Source-defining custom building hooks required`. This section should only define constants and source mechanics metadata; it should not emit fake Core behavior.
- For future runtime hooks, create exact hook classes under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/` only after static tracing identifies the native surfaces. Proposed names:
  - `Homm3CoveSeaDogPrerequisiteHook.cs`
  - `Homm3InfernoCastleGateHook.cs`
  - `Homm3TowerLibraryMageGuildHook.cs`
  - `Homm3NecropolisGlobalNecromancyHook.cs`
  - `Homm3DungeonPortalOfSummoningHook.cs`
  - `Homm3RampartTreasuryWeeklyIncomeHook.cs`
  - `Homm3StrongholdSpecialBuildingsHook.cs`
- Each hook must add its obfuscated method and field names to `GameSymbols.cs` before use. Do not scatter raw obfuscated names in hook code.

Static trace requirements before any hook:

- Identify the native config type, runtime data type, UI binder, and mutation method.
- Confirm whether the behavior must persist in save data.
- Confirm how multiplayer/session ownership is represented.
- Confirm how localization/tooltips should describe disabled, unavailable, or already-used states.
- Add a validator or startup fail-closed guard for the exact symbol surface.

Validation commands after any future building implementation:

```powershell
dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -c Release "-p:GameRoot=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era" --nologo
python tools\validate_custom_faction_manifests.py --core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip" --plugin-root "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod"
```

## Phase 5 - Live Validation Gate

Problem to solve: design docs and generator output are not enough. A faction change is valid only if live packed data, loose language, plugin payloads, and runtime symbols agree.

Proposed validation script:

- Add `tools/release_port/validate_custom_faction_design_contract.py`.

Inputs:

- `--core <Core.zip>`
- `--plugin-root <OfflineUnlockMod plugin root>`
- `--manifest-dir custom_factions`
- `--recommendations docs/custom_faction_design_recommendations.md`
- `--source-mechanics-dir custom_factions/source_mechanics`

Checks:

- Every city-hire SID in live `DB/objects_logic/cities/homm3_*_city.json` has logic, view, import-table, and recommendation coverage.
- Every enabled hero in `custom_factions/hero_overrides/*.json` has a non-empty source specialization or explicit blocked state.
- Every custom building SID in live city JSON has a source mechanics contract or is listed as shared native infrastructure.
- Every `blocked` or `trace_required` mechanic lacks player-facing text claiming exact behavior.
- Every generated `xHomm3SourceMechanic` row points to a real source mechanics contract.
- `docs/custom_faction_design_recommendations.md` still references every live unit/hero/building SID after Core regeneration.

Expected output:

```text
custom faction design contract: 10 factions
units: 210/210 covered
heroes: <live count>/<live count> covered
buildings: <live count>/<live count> covered
source mechanics: <exact>/<substituted>/<blocked>/<trace_required>
errors: 0
```

Run order for a real implementation pass:

```powershell
python tools\ability_editor\prefill_homm3_hero_overrides.py --require-specializations
python tools\release_port\apply_release_core_overlay.py --dry-run --release-core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip"
python tools\validate_custom_faction_manifests.py --core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip" --plugin-root "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod"
python tools\release_port\validate_custom_faction_design_contract.py --core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip" --plugin-root "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod"
```

## No-Change Rule Enforcement

These should become validation failures, not comments:

| Rule | Proposed enforcement |
| --- | --- |
| Do not remove `upgradeSid` chains to hide preview UI problems. | Extend `validate_upgrade_base_sid_chain()` to validate all factions, including Stronghold and Tower after their current exceptions are resolved; add a second check that hire `unitsHire.units[*].sids` contains base, standard, and alternate SIDs in source order. |
| Do not broaden donor-to-custom reverse lookup. | Add a grep-style CI check or validator scan for new raw donor reverse maps in `OfflineUnlockMod/*.cs`; allowed code paths must reference `Homm3CustomFactionRegistry` and carry faction/city/saved-SID context. |
| Do not add generic `homm3_*` icon, sprite, or ability fallbacks. | Add validator/static scan for wildcard branches such as `StartsWith("homm3_")` in UI icon, sprite, ability, and billboard hooks unless the branch immediately fails closed or delegates to a manifest registry entry. |
| Do not make player-facing text describe desired behavior unless implemented. | Use `source_mechanics` contracts to check `Lang/english/texts/*.json` rows. `blocked` and `trace_required` mechanics may appear in docs, not in player-facing text as active behavior. |

## First Concrete Work Items

1. Create the ten `custom_factions/source_mechanics/*.json` files with only building mechanics first. This is low risk because it records current truth and does not change Core behavior.
2. Add `validate_source_mechanics_contract()` and wire it into `validate_core_members()`.
3. Add `--require-specializations` to `tools/ability_editor/prefill_homm3_hero_overrides.py`; run it in warning mode first to enumerate all missing source specialty payloads.
4. Add missing `custom_factions/ability_overrides/*.json` skeletons for Rampart, Tower, Inferno, Fortress, and Stronghold with all 21 live city-hire SIDs and documentation-only `branchRole` fields.
5. Add `validate_unit_branch_roles()` after all ten ability override files exist.
6. Only after the above validation is stable, implement one source-defining building hook at a time, starting with the one that has the clearest native route from static trace.
