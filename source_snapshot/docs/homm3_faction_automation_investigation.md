# HoMM3 Faction Automation Investigation

> Superseded architecture note (2026-05-05). The proposed multi-faction registry now exists in `custom_factions/`, `Homm3CustomFactionRegistry.cs`, and `tools/validate_custom_faction_manifests.py`. Retain this file for historical automation estimates, not current architecture.
Date: 2026-05-05

## Question

Stronghold is close to release quality. This note estimates how much of the same workflow can be automated for the remaining HoMM3 factions, and where manual faction-design work is still unavoidable.

This investigation followed existing code/data paths instead of adding runtime probes. Main evidence came from:

- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/generate_homm3_stronghold_city.py`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/generate_homm3_stronghold_heroes.py`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/generate_homm3_fortress_city.py`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/generate_homm3_fortress_heroes.py`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_import.json`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportVisuals.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportUnitViewHook.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3ImportReleaseBattleVisualHook.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/StrongholdUnitSidMapping.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3StrongholdTownLayers.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/ReleaseCustomGameUiProbe.cs`
- `tools/homm3_import/`
- `docs/homm3_stronghold_canonical_town_animations.md`

## Short Answer

About 70-80% of the mechanical work can be automated once the project has a faction manifest that describes target SIDs, donor SIDs, HoMM3 asset names, heroes, towns, dwellings, and localization stems.

That automation can produce a playable scaffold. It will not, by itself, produce a release-quality faction. The remaining 20-30% is the quality-critical work: unit mechanics, faction laws, hero specialties, town screen layout, city/dwelling art placement, release UI/hook validation, and faction flavor.

The first non-Stronghold faction should be treated as an automation hardening pass, not just content production. After that pass, later factions should get much faster.

## What Is Already Automatable

### Core Data Scaffolding

`generate_homm3_stronghold_city.py` proves most Core.zip row creation is scriptable:

- clone a donor faction, city, laws, squads, map registrations, quick-game presets, and localization rows
- remap 21 unit logic/view rows
- patch abilities, buffs, upgrades, projectiles, costs, barracks, and town/city audio
- create localized text shells across locales and Lang args files
- apply a release Core overlay without replacing unrelated release campaign data

`generate_homm3_fortress_city.py` shows the same clone layer can create another faction shell, although that script is currently a debug/template clone rather than real HoMM3 Fortress content.

Automation potential: high. This should become one manifest-driven generator instead of one handwritten script per faction.

### HoMM3 Creature Asset Pipeline

`tools/homm3_import/` already provides the right lane:

- inventory rows identify source DEFs/audio and target unit SIDs
- `extract_creature.py` extracts HoMM3 DEF frames from local HoMM3 assets
- `bootstrap_homm3_lab.py` scaffolds Unity import projects from a donor prefab
- per-unit `authoring.json` presets drive frame pivots, scales, sorting, and bundle output
- `homm3_units_manifest.json` and `homm3_import.json` feed runtime visual replacement

The current `homm3_import.json` format is mostly faction-neutral: each row maps a synthetic HoMM3 battle/map resource to a vanilla donor presentation shell and an AssetBundle. The C# import hooks resolve by config SID and `gameUnitSids`, so they can cover additional factions if their rows exist.

Automation potential: medium-high. Extraction and bundle scaffolding are automatable, but per-unit art tuning still needs visual review.

### Runtime Visual Replacement

These systems are already close to table-driven:

- `Homm3ImportVisuals.cs`
- `Homm3ImportUnitViewHook.cs`
- `Homm3ImportReleaseBattleVisualHook.cs`
- preview/tooltip/custom icon caches in the HoMM3 import lane

The release battle hook already resolves units through `TransferUnit.configSid` and `gameUnitSids`, not strictly through Stronghold hard-coding. That is the right direction.

Automation potential: medium-high. More faction entries should work after data generation, but the current code still contains Stronghold wording, Stronghold projectile assumptions, and Stronghold-only sidecar hooks.

### Hero Portraits And Basic Hero Data

`generate_homm3_stronghold_heroes.py` and the portrait/class hooks show a reusable pattern:

- clone donor heroes/subclasses
- set target faction/class SIDs
- add portrait keys and localization
- surface portrait sprites through `Homm3CustomUiIconHook`

Automation potential: medium. The data rows are scriptable, but hero specialties, class labels, starting armies, spells, skills, and map sprites still need faction-specific review.

## What Still Requires Manual Intervention

### Donor Mapping And Unit Design

Each HoMM3 faction needs a deliberate mapping onto Olden Era donor mechanics. Stronghold currently leans on Dungeon donor shells. That is useful for visuals and UI, but it is not enough for faction quality.

Manual decisions:

- choose donor faction and donor unit per tier/base/upgrade/alternate
- decide which HoMM3 mechanics should be represented directly, approximated, or omitted
- tune stats, growth, costs, initiative/speed/range, shots, damage bands, and AI role
- handle projectiles and special attacks
- decide whether an OE alternate upgrade represents a real HoMM3 upgrade, a neutral variant, or a design invention

Warning: automatic donor mapping can make a unit load, but it can also silently inherit wrong native ability assumptions. This is especially risky for dragons, liches, hydras, genies, demons, undead immunities, no-retaliation units, shooters, and resurrection/summoning behavior.

### Ability Mechanics

Core JSON can cover some simple behavior, but quality mechanics often enter native controller dictionaries or UI availability paths. Stronghold already needed C# and release-specific hook work for visuals, selected-unit UI, battle wrappers, and ability surfaces.

Manual or static-trace work remains likely for:

- no-retaliation, double attack, breath attack, death cloud, life drain, rebirth, morale/luck exceptions
- spellcaster units and active abilities
- summons or transforms
- native targeting and action-bar availability
- special projectiles and impact effects

Prefer static tracing and donor comparison before adding runtime probes.

### Town Screen, Buildings, And Dwellings

Stronghold town work is not generic yet:

- `Homm3StrongholdTownLayers.cs` is Stronghold-specific
- `build_homm3_stronghold_layers_from_vcmi.py` is Stronghold-specific
- `extract_homm3_stronghold_buildings.py` is Stronghold-specific
- `tools/extract_stronghold_town_anims.py` is Stronghold-specific
- `positions.json` is hand-tuned

The scripts are good templates, but every HoMM3 town needs a manual mapping from original town DEF/building layers to Olden Era building SIDs, construction levels, hover/click expectations, and final screen coordinates.

Automation potential: medium for extraction and file generation; low-medium for polished placement.

Manual intervention:

- map HoMM3 `T*` town/background/building DEFs to OE building SIDs
- define per-building level variants and visibility conditions
- tune positions, scale, sorting, occlusion, and animation anchors
- verify canonically animated buildings using original DEF group frame counts, not cropped PNG counts
- validate city map billboard and external dwelling map billboards

### Faction Laws, City Graph, And Economy

Stronghold law cloning works mechanically, but laws are faction identity. Reusing Dungeon laws for every faction would be a placeholder.

Manual intervention:

- faction law list and icons
- city building graph and prerequisites
- Mage Guild caps and faction-specific disabled buildings
- faction-specific economy/weekly growth tuning
- localization names, descriptions, and tooltip flavor

Automation can create a donor clone and TODO markers. A human should decide release content.

### Release UI And Hook Surfaces

Release Stronghold required several static remaps after Steam hotfixes. The current release Custom Game integration appends `homm3_stronghold` and aliases UI assets through Stronghold-oriented code. It is not yet a clean multi-faction registry.

Manual/static-trace risk:

- faction picker and hero picker rows
- `SoFractions` custom faction aliasing
- class/profile/portrait surfaces
- selected-unit HUD/action-bar behavior
- battle visual initialization after interop churn
- map object billboard hooks
- town building sessions

Automation can generate more registration entries, but new release build drift still needs static validation.

### External Dwellings And RMG Integration

Core data contains Stronghold barracks map objects, and runtime visuals can replace Dungeon-prefab placeholders. That is not the same as complete random map generation or random-hire integration.

Manual/static-trace work likely remains for:

- faction-specific external dwelling placement
- random-hire pools
- RMG faction pools
- map template constraints
- neutral/faction mixed guards

Warning: visual aliasing can make a dwelling look right while the resolver still thinks it is a donor object.

## Automation Matrix

| Area | Automation potential | Manual need | Notes |
| --- | --- | --- | --- |
| Faction SID registration | High | Low | Manifest can append fraction/city/available faction rows. |
| Unit logic/view row cloning | High | Medium | Scriptable, but donor choice and stats need review. |
| Unit asset extraction | High | Medium | DEF extraction is automatable; pivots/scales need review. |
| AssetBundle project scaffolding | High | Medium | Current lane already bootstraps from donor prefabs. |
| `homm3_import.json` generation | High | Low | Should be fully manifest-driven. |
| Battle/map visual replacement | Medium-high | Medium | Runtime hooks are close to generic but need registry cleanup. |
| Projectiles | Medium | Medium-high | Data can clone; behavior/feel needs unit-specific tuning. |
| Hero data clone | High | Medium | Shells are easy; specialties/skills/armies are design work. |
| Hero portraits/icons | Medium-high | Medium | Asset resizing/generation scriptable; class mapping manual. |
| Faction laws | Medium | High | Donor clone is placeholder quality. |
| Town backdrop/layers | Medium | High | Extraction scriptable; mapping/placement manual. |
| City building graph | Medium | High | Clone works; release-quality economy requires design. |
| External dwellings | Medium | Medium-high | Core rows scriptable; RMG/random-hire needs tracing. |
| Localization shells | High | Medium | Names can be generated; text needs review. |
| Release Custom Game UI | Medium | Medium | Needs multi-faction registry and hotfix validation. |
| Verification | Medium | High | Build checks automate; visual/gameplay smoke still manual. |

## Recommended Next Architecture

Create a faction manifest that becomes the one source of truth. The generator should produce Core overlay rows, import manifests, authoring stubs, hero rows, localization shells, and runtime registry JSON from it.

Use `docs/homm3_ai_first_pass_design_principles.md` for the placeholder design rules that should guide the manifest's first automated pass before human review.

Suggested manifest sections:

- `factionSid`, `citySid`, `donorFactionSid`, `donorCitySid`
- unit rows: `targetSid`, `tier`, `upgradeKind`, `homm3Def`, `homm3AudioStem`, `donorUnitSid`, `battlePresentationDonor`, `mapShellDonor`
- balance rows: HotA stat/cost/growth source, vanilla fallback status, and any reason HotA data is unavailable
- ability rows: source mechanic, probability in source, focus translation, focus cost, cooldown, and static-trace requirement
- alternate-upgrade rows: `upgradeDifferentiator`, required for every `_upg_alt`
- projectile rows, if not inherited safely
- hero rows: hero SID, class SID, portrait source, map sprite source, specialty placeholder
- town rows: source town/background DEFs, building DEF to OE building SID mapping, layer order, default positions
- law rows: donor law or custom law SID, icon key, TODO status
- localization stems and per-locale TODO state
- release UI aliases and icon fallback keys

Then refactor Stronghold-specific runtime code toward registries:

- replace `StrongholdUnitSidMapping.cs` with a data-driven custom unit donor-alias registry
- generalize `ReleaseCustomGameUiProbe.cs` production path from "append Stronghold" to "append configured custom factions"
- split `Homm3StrongholdTownLayers.cs` into a generic town-layer loader plus faction-specific data
- make hero portrait/class hooks consume generated class/hero registries
- keep release-safe hooks narrow and statically mapped; do not broaden runtime reflection to compensate for missing data

## Practical Faction Rollout Plan

1. Build a manifest schema and convert Stronghold into it without changing behavior.
2. Generate a second faction scaffold from the manifest and compare Core.zip diffs against the existing Fortress debug clone.
3. Generalize runtime registries only where the second faction proves Stronghold assumptions are leaking.
4. Pick one target faction and complete it to playable scaffold quality.
5. Do one manual design pass: unit stats/abilities, laws, heroes, town placement, localization.
6. Port the release overlay and verify Custom Game selection, hero selection, town entry, battle entry, unit previews, map billboards, recruitment, and one RMG/new-game path.

For the first additional faction, expect roughly:

- 1-2 days to build/generate the scaffold, assuming assets are available locally and no new release hotfix breaks the hook surface
- 3-7 days for manual release-quality work, depending on town art complexity and unit mechanics

After the manifest and runtime registry refactor, later factions should be closer to:

- less than 1 day for a basic scaffold
- 1-2 days for visual/import review
- 1-3 days for faction mechanics/town/hero polish, unless the faction has unusually native-heavy mechanics

## Faction-Specific Risk Notes

These are rough implementation risks relative to Stronghold:

- Castle: easiest mechanically if mapped onto Human donor units; many vanilla-like roles, but angels/resurrection and morale-flavored design need review.
- Rampart: moderate; shooters, dragons, dwarves, dendroids, unicorn effects, and high nature overlap make donor mapping plausible.
- Tower: high; spellcaster units, golems, genies, naga, titans, and ranged/projectile behavior need careful ability and projectile work.
- Inferno: high; demons, gating/summon-like identity, fire immunity, pit fiends, efreet, and devil teleport/no-retaliation are ability-heavy.
- Necropolis: high; undead immunities, skeleton economy, life drain, lich cloud, ghosts/wraiths, dread knight effects, and morale rules are not pure data clone work.
- Dungeon: moderate-high; some OE Dungeon donor overlap helps, but black dragons, manticores, medusas, harpies, and multi-hex/breath behavior need review.
- Fortress: moderate-high; lizardmen, basilisks, wyverns, gorgons, hydras, and swamp town visuals need unit-specific mechanics and town placement.
- Conflux: high; elementals, pixies, energy/fire/magic immunities, phoenix rebirth, and nonstandard roster identity make donor mapping less direct.
- Cove: high; HotA-only assets, pirate shooters, Accurate Shot, Cannon, Shipyard/water behavior, Nix mitigation, Sea Serpent poison, and Haspid Revenge need a separate source lane and careful focus/static-trace planning.

If HotA/Cove is included, treat it as a separate source-asset lane. HoMM3 Complete local ownership and `H3sprite.lod` are not enough by themselves for Cove assets. HotA balance should be preferred over vanilla balance for all factions when HotA has a value.

## Bottom Line

The project can automate the repetitive scaffolding for other HoMM3 factions. It should not try to automate final faction quality. The strongest path is to manifest-drive the mechanical clone/import/release-overlay steps, then reserve manual time for the parts players will notice: unit behavior, town presentation, laws, heroes, localization, and release UI reliability.
