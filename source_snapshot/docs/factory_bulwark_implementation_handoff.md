# Factory And Bulwark Implementation Handoff

Last updated: 2026-07-25

This is the current continuation record for activating the HotA Factory and
Bulwark factions in Olden Era. It records milestones and proof boundaries, not
runtime claims. Update it whenever a significant implementation or validation
milestone completes.

## Objective

- Activate Factory and Bulwark as manifest-owned custom factions.
- Preserve Factory's authentic two-tier-7 recruitment structure.
- Give Factory the custom `Split Assembly` faction skill.
- Port Bulwark's HotA `Runes` mechanic without guessed event bindings.
- Own all required unit, town, hero, icon, Core, bundle, and deploy surfaces
  through fail-closed validators.

## Decisions

### Factory: Split Assembly

- Natural lines: Halfling, Armadillo, Sandworm, Couatl.
- Industrial lines: Mechanic, Automaton, Gunslinger, Dreadnought.
- Count distinct represented recruit lines at battle start, never raw split
  stacks.
- Each counted Natural line grants +1 army Offence.
- Each counted Industrial line grants +1 army Defence.
- Basic, Advanced, and Expert cap each branch at 2, 3, and 4 lines.
- The faction manifest owns line classification; runtime code must not maintain
  a second hardcoded classification table.

### Bulwark: Runes

- Preserve HotA's per-stack Rune Levels.
- Basic, Advanced, and Expert caps are 3, 6, and 9.
- Completed attack or cast: +1 Rune Level.
- Taking damage during an action: +2 Rune Levels.
- Defend: +3 Rune Levels.
- Cumulative thresholds grant +2 Offence at levels 1/4/7, +2 Defence at
  2/5/8, and +1 Speed at 3/6/9.
- Do not treat Wait as Defend and do not bind the mechanic to stale generated
  method ordinals.

### Rosters

- Factory uses its 16 non-special source heroes: eight Mercenaries followed by
  eight Artificers.
- Factory hero order is Henrietta, Sam, Tancred, Melchior, Floribert, Wynona,
  Dury, Morton; then Celestine, Todd, Agar, Bertram, Wrathmont, Ziph, Victoria,
  and Eanswythe. The nine source heroes marked `special` remain excluded.
- Bulwark uses eight Chieftains followed by eight Elders. Biarma is the default
  non-water hero; Haugir remains excluded because the source marks him
  `onlyOnWaterMap`.
- Bulwark hero order is Dhuin, Oidana, Neia, Eikthurn, Creyle, Spadum, Kynr,
  Ergon; then Kriv, Glacius, Sial, Dalton, Biarma, Akka, Vehr, and Allora.
- Factory's Couatl line is primary tier 7. Dreadnought is an explicit
  additional tier-7 recruitment line bound to the Gantry, not an invented
  tier 8 creature.

## Milestones

### 1. Repository And Source Inventory - Complete

Evidence:

- Factory has 17 source unit labs plus eight selected alternate-upgrade labs.
- Bulwark has 14 source unit labs plus seven selected alternate-upgrade labs.
- All 46 labs contain battle and map prefabs.
- `tools/homm3_import/build_out` contains 46 corresponding UnityFS bundles.
- The source archives contain town scenes, buildings, map objects, heroes,
  portraits, class map sprites, audio, and Bulwark Rune assets.
- Selected alternate upgrades are user-locked in
  `material_class_hs_selections.json`; older `awaiting_user_choice` prose is
  stale.

Proof boundary: source and generated unit artifacts inspected. No faction
runtime or deployed-payload claim follows from this milestone.

### 2. Mechanic Specification And Decomp Branch - Complete

Evidence:

- Factory can use the existing exact `BattleLogic.Init` hook and temporary
  `TransferHero` stat capture/restore pattern.
- Bulwark attack, damage, Skip, Wait, StartAction, and EndAction event families
  are statically identified.
- The active Golden Era Defend-to-Skip event equivalence is not yet live-proven.

Proof boundary: Factory implementation surface is source-proven. Bulwark Runes
must remain unregistered until an active-build event pilot proves Defend
correlation.

### 3. Asset Ownership Generator - Historical Generated Baseline

Implemented:

- `tools/build_hota_factory_bulwark_runtime_assets.py`
- `tools/validate_hota_factory_bulwark_runtime_assets.py`
- Factory/Bulwark runtime town, map-object, hero, faction, and skill assets.
- 46 import/bundle ownership rows and deterministic source/hash manifest.
- Build and deploy wiring for the focused runtime-asset validator.
- Factory's Gantry is pinned as `Build_Factory_Gantry` levels 1/2, town layers
  `tbfadw_7`/`tbfaup_7`, townhall icon frames 37/45, and the eighth Factory
  dwelling billboard.
- Bulwark's faction skill icon is the source HotA expert Runes icon, not a
  substitute faction emblem.
- The rebuilt town prefab bundle contains all 368 mapped layer entries,
  including both Gantry layers.

Validation:

```text
Factory/Bulwark runtime asset validation passed under [source plugin root]:
46 unit rows, 32 active heroes.

validated HoMM3 town prefab contract: 368 mapped layer entries under
[source plugin root]
```

Proof boundary at the time of this milestone: generated artifact validated.
Milestone 8 supersedes the current state: rank-specific skill-icon ownership
changes now require regeneration before that claim becomes current again.
Bundle deployment, startup, and user-visible presentation remain unvalidated.

### 4. Shared Additional-Recruitment Schema - Complete

Implemented:

- Primary `unitLines` remains an exact seven-tier contract.
- Optional `additionalRecruitmentLines` owns explicit `lineId`, tier,
  `recruitmentSlotSid`, city building, direct dwelling, donor dwelling,
  billboard, variant, and optional branch-family bindings.
- The Core overlay emits the additional city recruitment row, dwelling map/hire
  rows, unit/localization surfaces, and exact donor binding without a fallback.
- The runtime registry includes additional lines in unit identity, donor prefab,
  recruitment, dwelling, and startup-asset contracts.
- `TryGetManifestUnitBranch` canonicalizes base, upgrade, and alternate-upgrade
  SIDs to one manifest-owned base line and branch family.
- The build-enforced recruitment contract now pins additional-line runtime
  identity participation.

Validation:

```text
custom faction manifest validation passed: 10 manifest(s), 210 unit mapping(s),
54 existing context-required collision warnings.

additional recruitment synthetic contract OK: 8 lines, 24 variants,
exact second T7 city binding.

homm3-recruitment-ability-contract: ok

Golden Era OfficialDeobf dotnet build -t:Compile:
Build succeeded. 0 errors, 17 existing warnings.
```

Proof boundary: shared schema, generator helpers, runtime registry, focused
contracts, and Golden Era compile are source/static validated. No active
Factory manifest, candidate Core, deployed payload, startup smoke, or runtime
recruitment behavior is proven by this milestone.

### 5. Factory Runtime - Initial Source/Compile Baseline

The initial `Homm3FactorySplitAssemblyRuntime.cs` implementation registered the
manifest-owned `TryGetManifestUnitBranch` lookup, counted distinct canonical
base-line identities, applied the 2/3/4 per-branch rank caps, temporarily added
Natural Offence and Industrial Defence before `BattleLogic.Init`, and restored
touched `TransferHero` stats afterward. Milestone 8 supersedes its cleanup
implementation; this milestone's compile result does not cover the current
review-hardened source.

Validation:

- Focused Split Assembly runtime contract passed.
- Custom faction manifest validation passed: 10 manifests and 210 unit
  mappings, with existing donor-collision warnings only.
- Factory/Bulwark runtime asset validation passed: 46 unit rows and 32 active
  heroes.
- Golden Era OfficialDeobf `Compile` target passed with 0 errors and 17
  pre-existing warnings.

Proof boundary at the time of this milestone: source/static and Golden Era
compile validated. Milestone 8 requires a fresh compile after rank-specific
asset generation. No candidate artifact, deployed payload, startup smoke,
runtime stat capture, or user-visible combat behavior is proven yet.

### 6. Active Faction Manifests - Source/Static Validated

Implemented:

- Active Factory and Bulwark manifests with exact source unit and hero order.
- Factory has seven primary tiers ending in Couatl plus the Gantry-owned
  Dreadnought line through `Build_Factory_Gantry`,
  `barracks_homm3_factory_8`, and `AVGdread.dir/00_00.png`.
- Every Factory line is classified as Natural or Industrial in the manifest.
- Factory owns Foundry (Sand presentation clone, tile 29) rather than sharing
  Stronghold's Wasteland or falling back to built-in Sand.
- Bulwark owns Permafrost (Snow presentation clone, tile 30) rather than sharing
  Tower's Tundra or falling back to built-in Snow, and excludes water-only Haugir.
- All 32 active heroes have explicit source-grounded class, start-army,
  first-skill, and specialization override rows.
- All 45 unit variants have fail-closed ability override rows that clear donor
  mechanics. Source creature abilities remain explicit implementation debt.

Validation:

```text
custom faction manifest validation passed: 12 manifest(s),
255 unit mapping(s), 57 context-required collision warnings.
```

### 7. Bulwark Runtime - Static Events Resolved, Live Defend Proof Blocked

Active Golden Era static event resolution is complete against `Hex.dll` SHA256
`EDE61A05C38006AD853AB716F21CA882A4E0480EAAD46C86FDFB135D01EFFD04`.
The current event runtime type is
`ObjectPublicPrcfEvPrcf1BaPrcfEvUnique` (`edb`). Exact current bindings are:

- Skip: `Method_Public_Void_Object_BattleEventArgs_11`
- Wait: `Method_Public_Void_Object_BattleEventArgs_PDM_53`
- CastMagicStarted: `Method_Public_Void_Object_BattleEventArgs_PDM_31`
- CastMagic: `Method_Public_Void_Object_BattleEventArgs_26`
- StartAction: `Method_Public_Void_Object_BattleEventArgs_57`
- EndAction: `Method_Public_Void_Object_BattleEventArgs_PDM_62`
- ObjectTookDamage: `Method_Public_Void_Object_BattleEventArgs_PDM_102`
- CastAbility filter: `Method_Public_Void_Object_BattleEventArgs_PDM_128`

`bcsm` is excluded because its active three-argument shape does not match the
required event contract. Probe-file implementation was blocked by an automatic
usage-limit rejection; policy forbids retry or workaround. Live proof that
Defend emits exactly one Skip before EndAction, while Wait does not, therefore
remains absent. Runes stays `runtime-pending` with no current-row or implemented
runtime claim until that proof and the battle-scoped runtime land.

Proof boundary: manifest/source/static validated. Candidate Core, installed
payload, startup smoke, Factory combat behavior, Bulwark per-stack Runes
behavior, and user-visible gameplay remain unproven.


### 8. Review Hardening - Source/Static Validated, Generation Blocked

Implemented:

- Factory Split Assembly deduplicates aliased `heroStat` and
  `heroStatUnclamped` objects and no longer doubles the passive bonus.
- Prefix and finalizer cleanup returns and propagates snapshot restoration
  failures; no local cleanup path clears evidence or silently continues after
  incomplete restoration.
- The asset generator explicitly owns Factory and Bulwark Basic, Advanced, and
  Expert skill-icon outputs. Bulwark uses the source HotA Runes
  `basic.png`, `advanced.png`, and `expert.png`; there is no emblem fallback.
- Build validation requires all six exact rank-specific files.
- The active-manifest asset contract now pins archive hashes, source paths,
  hero order, all 45 recruit ownership rows plus Sandworm Larva, generated
  asset paths, dwelling order, source stat rows, and explicit alternate-stat
  inheritance.
- Factory source drift was corrected to the pinned archive: the town backdrop
  is `Data/hota/factory/town-screen/TBFaBack.png`; Couatl, Dreadnought, and
  Juggernaut use `hotaCouatl`, `hotaDreadnought`, and `hotaJuggernaut` source
  configs.
- The stale neutral-pool/alternate-gallery validator was replaced by the
  active Factory/Bulwark 46-row contract. It has no compatibility fallback to
  the removed neutral-pool manifest.

Source/static validation:

```text
validated HoMM3 Factory Split Assembly source-static runtime contract
Factory/Bulwark sources and 46 built bundles are present.
validated active Factory/Bulwark pinned sources and 46 exact ownership rows
custom faction manifest validation passed: 12 manifests, 255 unit mappings,
57 context-required collision warnings
```

Current blocking proof at the time of this milestone:

```text
Factory/Bulwark runtime asset validation FAILED
- four rank-specific `_2`/`_3` PNGs are not generated
- generated asset-manifest source rows are stale
```

The generator attempted regeneration, but the managed Windows sandbox denied
creation of the new files. The required escalation was then rejected because
the account usage limit was reached, with an explicit instruction not to work
around the denial. Two failed-generator temporary directories under `tools/`
may remain ACL-protected. Do not claim generated-artifact or compile validation
for this review milestone. The Golden Era compile was intentionally not run:
MSBuild now correctly requires the missing rank-specific icons and must remain
fail-closed until generation succeeds.

Proof boundary at the time of this milestone: runtime/source contracts and
manifest/archive ownership are source/static validated. Rank-specific generated
assets, updated asset-manifest hashes, Golden Era compile, deploy, startup,
runtime behavior, and user-visible gameplay are unvalidated. Milestone 11
clears the rank-specific asset and combined build/candidate gates.

### 9. Couatl Alternate Donor Shell - Source/Static Validated

Candidate Core validation rejected `h3_couatl_upg_alt` because the generic
alternate-shell derivation selected
`units/Nature/1Prefabs/phoenix_upg_alt`, a native prefab already classified as
unsafe for custom battle drawer construction.

Implemented:

- The Factory/Bulwark asset generator now owns an exact Couatl alternate-shell
  override to `units/Nature/1Prefabs/phoenix_upg`.
- The bundle-owned `homm3_import.json` row is synchronized to that safe shell.
- The active 46-row validator now compares all generated ownership rows to the
  live import table, rejects any remaining `phoenix_upg_alt` shell, pins the
  Couatl safe path, and verifies the existing Couatl alternate bundle payload
  contract length/hash row.
- The UnityFS bundle and its payload-contract digest were not changed: donor
  battle presentation is import metadata outside the bundle payload.

Validation:

```text
Factory/Bulwark sources and 46 built bundles are present.
validated active Factory/Bulwark pinned sources and 46 exact ownership rows
```

No full asset generation, icon creation, deploy, or runtime step was run for
this narrow correction. Milestone 8's external blocker remains: four
rank-specific skill icons and refreshed generated asset-manifest rows are still
required before the runtime-asset gate or full build can pass. Milestone 10
supersedes the earlier candidate-Core and source-compile status.

Proof boundary: generator/import/bundle-contract source state is source/static
validated for the Couatl safe-shell correction. Generated runtime assets, full
build, deployment, and runtime behavior remain unvalidated.

### 10. Candidate Core And Golden Era Compile - Validated With Asset Gate Still Blocked

Implemented and corrected:

- The existing `merge_data_json` policy is now actually wired into
  `build_overlay`; previously it was an unused helper. Candidate generation adds
  every Core-enabled custom faction to both `DB/data.json` `fractions` and
  `availableFractions`, removes disabled custom factions, deduplicates rows, and
  fails closed when either source member is not a string list.
- The build-enforced Factory/Bulwark contract pins both the merge policy and its
  overlay call so the helper cannot become dead code again.
- The strict runtime manifest parser retains exact `JTokenType` guards but uses
  shipped-interop-compatible `ToString()` and explicit numeric/boolean casts;
  unavailable parameterless `JToken.Value<T>()` calls are forbidden by the
  focused validator.

Current validation:

```text
validated Factory/Bulwark exact Core skill and additional-recruitment contracts
validated HoMM3 Factory Split Assembly source-static runtime contract
custom faction manifest validation passed: 12 manifests, 255 unit mappings,
57 context-required collision warnings
Golden Era OfficialDeobf dotnet build -t:Compile:
Build succeeded. 0 errors, 17 existing warnings.
Core overlay --dry-run candidate validation:
candidate validation complete; Core.zip was not modified.
```

The candidate Core contains Factory and Bulwark in both required `DB/data.json`
lists and passed the candidate manifest/Core validator. This proves the
generated candidate artifact, not the installed Golden Era payload.

The separate runtime-asset validator still fails closed on the four missing
Factory/Bulwark rank-specific `_2`/`_3` icons and the two stale generated
asset-manifest source rows. The successful `Compile` target does not run or
supersede that asset gate, so a full `Build`, deploy readiness, startup, combat
behavior, and user-visible gameplay are not proven. Bulwark Runes remains
`runtime-pending` until the live Defend event pilot and battle-scoped runtime are
implemented and validated.

Proof boundary: source/static validated, Golden Era compile target proven, and
candidate Core artifact validated. Full build, generated runtime-asset payload,
installed/deployed payload, startup smoke, Factory runtime behavior, Bulwark
Runes runtime behavior, and user-visible gameplay remain unvalidated.

### 11. Rank-Specific Skill Icons And Combined Asset Gate - Validated

Cleared the Milestone 8 generation blocker and revalidated the combined Factory
and Bulwark source plus asset gates.

Implemented:

- Removed the two empty failed-generator temporary directories under `tools/`.
- Regenerated Factory/Bulwark runtime assets, including all six rank-specific
  skill icons (`skill_faction_homm3_{factory,bulwark}.png` plus `_2`/`_3`) and
  refreshed `hota_factory_bulwark_asset_manifest.json` source/hash rows.
- Updated `validate_homm3_recruitment_ability_contract.py` to accept the
  fail-closed `generic_unit_hire_payload(..., context)` call shape used by the
  Core overlay after additional-recruitment hardening.

Validation:

```text
Factory/Bulwark runtime asset validation passed under [source plugin root]:
46 unit rows, 32 active heroes.

validated active Factory/Bulwark pinned sources and 46 exact ownership rows
validated HoMM3 Factory Split Assembly source-static runtime contract
validated Factory/Bulwark exact Core skill and additional-recruitment contracts
validated HoMM3 town prefab contract: 368 mapped layer entries
homm3-recruitment-ability-contract: ok
custom faction manifest validation passed: 12 manifests, 255 unit mappings,
57 context-required collision warnings

Golden Era OfficialDeobf full build (DeployPluginToGame=false):
Build succeeded. 0 errors, 50 existing warnings.

Core overlay --dry-run candidate validation:
candidate validation complete; Core.zip was not modified.
```

Unrelated BeforeBuild contracts that previously forced Skip* piles are fixed in
the default OfficialDeobf path (battle-icon dialog-only short-circuit, billboard
LateUpdate reassertion contract, campaign menu locale fill, town-prefab grail
layers, deal_with_the_devil event policy regen). RoE Castle installed Story_maps /
Core SID readiness stays opt-in via `RequireInstalledRoeCastlePayload=true`
(not Skip*) until the continuity installer is readiness-proven per AGENTS.md.

Proof boundary: generated runtime-asset payload validated, Golden Era full build
target proven with Factory/Bulwark BeforeBuild gates, and candidate Core artifact
revalidated. Installed/deployed payload, startup smoke, Factory combat behavior,
Bulwark Runes runtime behavior, and user-visible gameplay remain unvalidated.
Bulwark Runes remains `runtime-pending` until the live Defend event pilot and
battle-scoped runtime land.

### 12. Scoped Plugin And Factory/Bulwark Bundle Deploy - Installed Payload Proven

Full `DeployHomm3Bundles=true` remains correctly fail-closed: 172 non-Factory/
Bulwark `tools/homm3_import/build_out/custom_units_*` rows are smaller than the
authoritative contract and live Golden Era `homm3_bundles`, while live lengths
match the contract. Deploying the whole directory would overwrite good live
bundles with stale build_out payloads.

Implemented:

- Extended `validate_homm3_bundle_payload_directory.py` with repeatable
  `--name-prefix` so a scoped contract check can own Factory/Bulwark rows without
  weakening the full-directory gate.
- Added opt-in `-p:DeployHomm3FactoryBulwarkBundles=true`. It validates source
  `custom_units_factory_*` / `custom_units_bulwark_*` against the contract,
  copies only those rows, refuses combination with `DeployHomm3Bundles=true`,
  and re-validates the installed prefixes after copy.

Validation:

```text
HoMM3 bundle payload directory validation passed: [build_out]
  (prefixes=['custom_units_factory_', 'custom_units_bulwark_'], rows checked)
HoMM3 bundle payload directory validation passed: [installed homm3_bundles]
  (prefixes=['custom_units_factory_', 'custom_units_bulwark_'], rows checked)
Factory/Bulwark runtime asset validation passed under [installed plugin]:
46 unit rows, 32 active heroes.
validated HoMM3 town prefab contract under [installed plugin]
custom faction manifest validation passed under [installed plugin]:
12 manifests, 255 unit mappings
Golden Era OfficialDeobf deploy build:
Build succeeded. 0 errors, 33 warnings.
live readback: 46/46 Factory/Bulwark bundles contract-ok; all six rank skill
icons present; homm3_factory.json and homm3_bulwark.json present.
```

Proof boundary: plugin DLL, Factory/Bulwark runtime assets, skill icons,
manifests, town prefabs, and the 46 Factory/Bulwark unit bundles are
installed/deployed-payload proven on Golden Era. Live `Core.zip` was not
modified. Startup smoke, Factory combat behavior, Bulwark Runes runtime, and
user-visible gameplay remain unvalidated. Full-tree `DeployHomm3Bundles=true`
remains blocked until the 172 stale build_out rows are intentionally refreshed.

### 13. Live Core Overlay Install - Installed Core Payload Proven

Applied `tools/release_port/apply_release_core_overlay.py` to the live Golden
Era `Core.zip` after the Milestone 12 plugin/bundle deploy. Automatic backup:
`Core.zip.backup-20260718-083133`.

Installed readback:

```text
candidate validation complete
Backup: ...\Core.zip.backup-20260718-083133
DB/data.json fractions: homm3_factory=True, homm3_bulwark=True
DB/data.json availableFractions: homm3_factory=True, homm3_bulwark=True
skills.json: skill_faction_homm3_factory and skill_faction_homm3_bulwark present
homm3_factory_city.json: Build_Factory_Gantry present
custom faction manifest validation against live Core: passed
  (12 manifests, 255 unit mappings, 57 context-required collision warnings)
validated Factory/Bulwark exact Core skill and additional-recruitment contracts
```

Proof boundary: installed Core payload now contains Factory and Bulwark faction
registration, skills, city/Gantry rows, and related overlay members. Startup
smoke, Factory combat behavior, Bulwark Runes runtime, and user-visible
gameplay remain unvalidated.

### 14. Startup Crash Fix - Missing Unit Interface Portraits

Startup FailFast at main-menu prewarm:

```text
Required HoMM3 portrait file was not found ... 'h3_argali.png'
Homm3RuntimeManifestPreloader.PrewarmAtMainMenuOrFail
```

All Factory/Bulwark custom unit SIDs lacked `homm3_portraits/*.png`. The runtime
asset generator owned hero portraits only; unit interface portraits were never
produced for these HotA factions.

Fix:

- Extended `tools/generate_homm3_interface_portraits.py` to load Factory icons
  from `content.zip` creature `iconLarge` paths and Bulwark icons from
  `sprites/hota/bulwark/creatures/iconsLarge/{sourceConfig}.png`.
- Material-class `_upg_alt` portraits reuse the upgraded HotA icon.
- Additional recruitment lines and `h3_sandworm_larva` are included.
- `validate_hota_factory_bulwark_runtime_assets.py` now requires those unit
  portrait PNGs.

Validation:

```text
Generated interface portraits for 256 unit SID(s); changed=47
Factory/Bulwark runtime asset validation passed (source and installed plugin)
Golden Era redeploy Build succeeded. 0 errors.
live readback: h3_argali.png and peer Factory/Bulwark portraits present
```

Proof boundary: missing-portrait startup crash cause is source-fixed and
redeployed. Startup smoke after this redeploy is still user-unvalidated until
a fresh launch succeeds.

### 15. Map-Load NRE Fix - Native Skill Bonus Sentinel

Map load looped with:

```text
HeroSkill.bfyg -> Hero.bfwz -> DataHeroes.bfrx
System.NullReferenceException
```

Static readback showed Factory and Bulwark were the only Core skills with empty
`bonuses` at every rank. Every other `skills.json` row ships at least one bonus
per level. Factory heroes start with `skill_faction_homm3_factory`, so empty
ranks hit native skill apply on every Factory map load.

Fix:

- `make_specialized_generic_skill_row` now writes a zero-effect
  `diplomacyEfficiencyPerBonus` / `0.0` sentinel at all three ranks for Factory
  and Bulwark (empty `subSkills` retained; Split Assembly / Runes stay
  runtime-owned).
- `validate_custom_faction_manifests.py` and
  `validate_homm3_factory_bulwark_core_skill_contract.py` pin that sentinel and
  refuse empty bonus arrays.
- Re-applied live Core overlay. Backup:
  `Core.zip.backup-20260718-090454`.

Installed readback:

```text
skill_faction_homm3_factory / skill_faction_homm3_bulwark:
  each rank bonuses=[{heroStat diplomacyEfficiencyPerBonus 0.0}], subSkills=[]
candidate validation complete; custom faction manifest validation passed
```

Proof boundary: installed Core skill shape is fixed and candidate-validated.
Map-load recovery, startup smoke, Factory combat, and Bulwark Runes remain
user-unvalidated until a fresh Factory map load succeeds.

### 15b. Map-Load NRE Persists - Diagnostic Deploy (superseded)

Retest after the Milestone 15 sentinel still looped on the same
`HeroSkill.bfyg` stack. Empty-bonus was therefore not a complete explanation.
A temporary dungeon-clone A/B and NRE-swallow diagnostic were deployed; that
path is superseded by Milestone 16.

### 16. Working-Faction Skill Contract Alignment

Contract review against live Core showed every working HoMM3 faction skill
ships:

- non-empty `bonuses` at Basic/Advanced/Expert
- empty `subSkills` at Basic
- exactly three Advanced and three Expert `subSkill` SIDs that resolve in
  `DB/heroes_skills/sub_skills/sub_skills.json`

Factory/Bulwark were the only rows that left Advanced/Expert `subSkills`
empty. The zero `diplomacyEfficiencyPerBonus` sentinel alone did not match
that working shape.

Fix:

- Factory/Bulwark faction skills now reuse the proven Dungeon load bonuses
  (`unitBoolStat ignoreFractionsCount=true`) plus owned Adv/Exp native-terrain
  subskill rows (human/nature donor icons).
- Split Assembly / Runes remain runtime-owned for authentic effects.
- Validators pin the working Adv/Exp subskill count and resolvable rows.
- Removed `Homm3HeroSkillApplyDiag` NRE-swallow diagnostic.
- Re-applied live Core. Backup: `Core.zip.backup-20260718-092425`.

Installed readback:

```text
skill_faction_homm3_factory / skill_faction_homm3_bulwark:
  L0 1/0, L1 1/3, L2 1/3  (bonuses/subSkills) matching Castle/Dungeon/etc.
merge homm3_factory Split Assembly subskills
merge homm3_bulwark Runes subskills
candidate validation complete
custom faction manifest validation passed against live Core
```

### 17. Map-Load Loop - Missing Gantry Construction Preset Row

Player.log (not BepInEx alone) named the fail-closed map-load errors on each
retry:

```text
Can't find building: Build_Factory_Gantry in construction config: default_buildings_construction
Can't find building: Build_Factory_Gantry in construction config: extra_rich_buildings_construction
data hero sid:human_hero_2 dont found
[SpawnsCreator] Couldn't get any hero to create in spawn!
```

Working unique city buildings (e.g. `Build_Well_Of_Souls`, `Build_Mother_Nature`)
are listed in every `DB/buildings_constructions/*` preset. Factory's additional
`Build_Factory_Gantry` was only merged into `homm3_factory_city` hires, so RMG
construction lookup failed closed and the load looped. The earlier
`HeroSkill.bfyg` BepInEx stack was a secondary symptom during that broken load.

Fix:

- `ensure_additional_recruitment_buildings_in_construction_presets` now merges
  each additional `cityBuildingSid` into all construction preset building lists
  (same shape as working unique buildings).
- Validator pins that helper and its integration.
- Re-applied live Core. Backup from this pass is under
  `Core.zip.backup-20260718-*` after the overlay run.

Proof boundary: installed Core construction presets now include
`Build_Factory_Gantry`. Map-load recovery remains user-unvalidated until a fresh
Factory RMG/map load succeeds. The `human_hero_2 dont found` spawn line is still
unproven as fixed or residual; re-check Player.log after the next load.

### 18. Spawn Cascade - Missing `skill_necromancy` On Necropolis Heroes 17/18

After Gantry was fixed, Player.log still looped with:

```text
Config with id "skill_necromancy" was not found.
data hero sid:<opponent_or_necropolis_hero> dont found
[SpawnsCreator] Couldn't get any hero to create in spawn!
```

Live Core audit: the only unresolved hero `startSkills` in all of Core were
`homm3_necropolis_hero_17` / `_18` referencing `skill_necromancy`, which is not
present in `DB/heroes_skills/skills/skills.json`. Creating those heroes NREs in
`HeroSkill.bfyg` and cascades into SpawnsCreator for any map that touches the
global hero create path (including Factory vs non-Necropolis opponents).

Fix:

- Remounted hero_overrides: Finneas → `skill_sorcery`, Haart Lich → `skill_assault`.
- `validate_homm3_custom_hero_start_skill_contract.py` now fails closed if any
  generated Core startSkill is missing from `skills.json`, and bans
  `skill_necromancy` in hero_overrides.
- Re-applied live Core. Backup: `Core.zip.backup-20260718-123724`.
- Log-only `Homm3HeroSkillApplyDiag` kept for residual `bfyg` identification
  (AccessTools lookup; does not swallow).

Proof boundary: installed Core has zero unresolved startSkills (readback).
Map-load recovery still user-unvalidated.

### 19. Factory Split Assembly Unit.Init Registration Fix

BepInEx showed Factory Split Assembly failing closed at startup:

```text
HoMM3 Factory Split Assembly runtime not registered; exact startup surface missing:
homm3.factory.splitAssembly.unit.init exact Unit.Init shape not found
```

Root cause: a private void-only `Unit.Init` finder rejected the live Golden Era
method. The battle unit law-owner registry already resolved and patched the same
`Hex.Session.Battle.Unit.Init`.

Fix:

- Added shared `Homm3BattleUnitInitSurface` with the proven 8/10-arg shape matcher
  (accepts bool return).
- Factory, law-owner registry, and Unit.Init diagnostics now share that surface.
- Contract validator pins the shared finder and rejects the retired void-only path.
- Golden Era OfficialDeobf compile succeeded; plugin deployed under
  `BepInEx/plugins/OfflineUnlockMod/` (deploy-hash matched). Removed a stale
  duplicate `BepInEx/plugins/OfflineUnlockMod.dll` that failed the single-DLL
  deploy contract.

Proof boundary: source/static + build target + deployed DLL hash proven. Startup
registration and combat buff application remain user-unvalidated until a fresh
game launch shows `HoMM3 Factory Split Assembly runtime registered` and a Factory
battle emits `planned:` / `applied unit buffs:` lines.

## Active Worktree Scope

Relevant new or modified paths currently include:

- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3CustomFactionRegistry.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3FactorySplitAssemblyRuntime.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3BattleUnitInitSurface.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/OfflineUnlockMod.csproj`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Plugin.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_runtime_assets/`
- `custom_factions/contracts/homm3_bundle_payload_contract.json`
- `custom_factions/source_mechanics/homm3_factory.json`
- `custom_factions/source_mechanics/homm3_bulwark.json`
- `custom_factions/homm3_factory.json`
- `custom_factions/homm3_bulwark.json`
- `custom_factions/hero_overrides/homm3_factory.json`
- `custom_factions/hero_overrides/homm3_bulwark.json`
- `custom_factions/ability_overrides/homm3_factory.json`
- `custom_factions/ability_overrides/homm3_bulwark.json`
- `tools/build_hota_factory_bulwark_runtime_assets.py`
- `tools/validate_hota_factory_bulwark_runtime_assets.py`
- `tools/validate_homm3_factory_bulwark_core_skill_contract.py`
- `tools/validate_homm3_recruitment_ability_contract.py`
- `tools/release_port/apply_release_core_overlay.py`
- `tools/validate_custom_faction_manifests.py`
- `tools/generate_homm3_interface_portraits.py`
- `tools/validate_homm3_bundle_payload_directory.py`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_skill_icons/skill_faction_homm3_{factory,bulwark}{_2,_3}.png`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_runtime_assets/hota_factory_bulwark_asset_manifest.json`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_portraits/h3_*.png` (Factory/Bulwark unit set)

The repository contains many unrelated user changes. Do not revert or include
them in a Factory/Bulwark commit.

## Continuation Order

1. Restart Golden Era and confirm BepInEx shows
   `HoMM3 Factory Split Assembly runtime registered` (not the Unit.Init shape
   warning). Then fight with Split Assembly and grep for `planned:` /
   `applied unit buffs:`.
2. Retest Factory map load on Golden Era after Milestone 18 (`skill_necromancy`
   remount). Confirm Player.log no longer reports `skill_necromancy` / SpawnsCreator
   hero-dont-found, and the load loop stops.
3. If `HeroSkill.bfyg` still fires, read BepInEx for `HoMM3 HeroSkill.bfyg FAILED sid=...`
   from the log-only diag and fix that skill shape next.
3. Run startup smoke and Factory combat proof with the installed plugin,
   Factory/Bulwark bundles, and Core overlay.
4. Use the live bridge event pilot to unblock Bulwark Runes.
5. Resolve or intentionally keep the unrelated default-build skip gates above
   outside the Factory/Bulwark scoped commit.
6. Keep full `DeployHomm3Bundles=true` blocked until the 172 stale non-Factory/
   Bulwark `build_out` rows are refreshed against the contract.
7. Run review, update this handoff, and commit only the scoped milestone.

### 13. Bulwark Ability Repair - Native Data + Fail-Closed Runtime (2026-07-25)

Implemented:

- All 16 Focus actives resolve native Core dealers (or Arbitrator / Sentinel
  unit-special donors) with only `targetMode` / `orderedDistance` /
  `fixedDuration` transforms. Handwritten Bulwark dealers are forbidden.
- Free Shooting text/data for Steel/Pine (adjacent-block only); Argali Ice Bolt
  damage + effect-tag immunity.
- `validate_homm3_bulwark_ability_repair_contract.py` with installed Core.zip
  readback for non-empty offensive dealers.
- Frostbound Skies: `stats.moveType == fly` classification in GameSymbols,
  native-pointer apply dedupe, faction speed-only `-1`/`-2` buffs.
- Runes: fail-closed owner with caps/gains/buff SID helpers; gameplay hooks
  remain unregistered until Defend correlation is proven. Combat proof scaffold
  at `artifacts/bulwark_combat_proof/v1/`.

Proof boundary: source/static + installed payload validated for Focus native
dealers and Frostbound Skies data/runtime wiring. Runes battle behavior and all
Focus combat feel remain unvalidated.

## Useful Commands
```powershell
python -B tools\build_hota_factory_bulwark_runtime_assets.py
python -B tools\validate_custom_faction_manifests.py
python -B tools\validate_hota_factory_bulwark_runtime_assets.py
python -B tools\validate_hota_factory_bulwark_neutral_asset_contract.py
python -B tools\validate_homm3_bundle_payload_directory.py --bundle-dir tools\homm3_import\build_out --payload-glob custom_units_* --name-prefix custom_units_factory_ --name-prefix custom_units_bulwark_
python -B tools\validate_homm3_bulwark_ability_repair_contract.py
python -B tools\validate_homm3_bulwark_flyer_slow_runtime_contract.py
python -B tools\validate_homm3_bulwark_runes_runtime_contract.py
dotnet build -c Release -p:OfficialDeobfBuild=true -p:DeployPluginToGame=true -p:DeployHomm3FactoryBulwarkBundles=true "-p:GameRoot=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
git status --short
```
