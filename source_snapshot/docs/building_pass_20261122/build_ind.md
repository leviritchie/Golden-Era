# Building pass 2026-11-22: group IND (Inferno, Necropolis, Dungeon) hand-back

Nothing is compiled, installed or committed. `apply_release_core_overlay.py --check-building-overrides` reports
`homm3_inferno: OK (5 rows)`, `homm3_necropolis: OK (5 rows)` and `homm3_dungeon: OK (6 rows, 1 removal)`. The only
warnings are missing description locales, which the coordinator adds centrally. `validate_custom_faction_manifests.py`
passes. `validate_symbol_literal_confinement.py` reports nothing in IND files; its current failures are in Stronghold and
TownSiegeDefense files.

## Files

### Created

| File | Content |
|---|---|
| `custom_factions/building_overrides/homm3_inferno.json` | Bank, Castle Gate, Order of Fire, Brimstone Stormclouds, Deity of Fire |
| `custom_factions/building_overrides/homm3_necropolis.json` | Bank, Necromancy Amplifier, Cover of Darkness, Skeleton Transformer, Soul Prison |
| `custom_factions/building_overrides/homm3_dungeon.json` | Bank, Mana Vortex, Portal of Summoning, Battle Scholar Academy, Mushroom Rings, Guardian of Earth; removes `Build_Lyceum` |
| `OfflineUnlockMod/Homm3InfernoCastleGateRuntime.cs` (152 lines) | Castle Gate destination filter |
| `OfflineUnlockMod/Homm3NecropolisCoverOfDarknessRuntime.cs` (189 lines) | Cover of Darkness fog |
| `OfflineUnlockMod/Homm3DungeonManaVortexRuntime.cs` (534 lines) | Mana Vortex weekly doubling, per-frame host, save carrier |

### Edited

- **`OfflineUnlockMod/Homm3SkeletalNecromancyProbe.cs`**
  - Constants at lines 53-57.
  - Necromancy share terms at lines 277-289 in `ApplyPostBattleSkeletonReward`:
    - the law note becomes `boneConductors`;
    - the Necromancy Amplifier building (`Build_Mother_Nature`) adds +5%;
    - Soul Prison (`Build_Gaping_Maw`) adds +10%.
  - New helper `NecropolisSideOwnsBuilding` at line 431. It uses `Homm3TownBuildingReader.SideHasBuilding(owner, sid, "homm3_necropolis_city")`.
- **`custom_factions/law_overrides/homm3_necropolis.json`, line 202**
  - `fraction_law_homm3_necropolis_7` nameText changes from "Necromancy Amplifier" to **"Bone Conductors"**. Name only, nothing else changed.
- **`custom_factions/source_mechanics/homm3_{inferno,necropolis,dungeon}.json`**
  - Every building mechanic is now `exact`, with `currentRows` pointing at the SIDs below. Player-text tokens are regenerated.
  - New mechanic `dungeon.mushroom_rings`.
  - `necropolis.cover_of_darkness` loses `changeDisposition` and `implementationOwner`; its policy is `must_match_current_behavior`.

## `Plugin.cs` registrations needed (coordinator)

Add these next to the other building-pass registrations, after `_harmony` exists (about line 838):

```csharp
Homm3InfernoCastleGateRuntime.TryRegister(_harmony, Log);
Homm3NecropolisCoverOfDarknessRuntime.TryRegister(_harmony, Log);
Homm3DungeonManaVortexRuntime.TryRegister(_harmony, Log);
```

- The Necromancy terms need no registration: they run in the existing probe.
- The csproj uses default compile globbing, so no csproj edit is needed.
- `Homm3DungeonManaVortexHost` is an injected MonoBehaviour. Its runtime registers it itself through `ClassInjector.RegisterTypeInIl2Cpp`.

## Core row needed (coordinator, same build as the Mana Vortex runtime)

Mana Vortex saves its weekly marks in a hidden side-buff carrier with sid **`homm3_ind_town_building_store`**. It needs a
Core side-buff row built the same way as `make_homm3_cove_treasure_store_side_buff_row`
(`apply_release_core_overlay.py` about line 7580, merged at about line 17849):

- a clone of `heros_crypt_debuff_none`;
- `hidden: true` and `bonuses: []`;
- name and description keys `homm3_ind_town_building_store_name` / `homm3_ind_town_building_store_description`.

If the row is missing, saving still writes the buff. Whether the game keeps an unknown buff sid across save and load
is unproven, so ship the row with the runtime.

## SIDs renamed, reused, added or removed

| Town | SID | Kind | Becomes |
|---|---|---|---|
| Inferno | `Build_Bank` | replace | Bank: `sideRes` gold 1000; cost 2500 gold / 5 wood / 5 ore |
| Inferno | `Build_Mycelium_Roots` | new, `myceliumRoots` from nature | **Castle Gate**; plugin `Homm3InfernoCastleGateRuntime` |
| Inferno | `Build_Mother_Nature` | new, `heroBonusBanks` from nature | **Order of Fire**: `heroStat` spellPower +1 |
| Inferno | `Build_Resource_Depot_level_2` | replace, moves to `cityBonusBanks`, `[[]]` | **Brimstone Stormclouds**; plugin `Homm3TownSiegeDefenseRuntime` (runtime agent) |
| Inferno | `Build_Eternal_Flame` | replace, `graals` | **Deity of Fire**: the existing 3 side bonuses + `cityUnitsIncrement h3_imp 22` |
| Necropolis | `Build_Bank` | replace | Bank |
| Necropolis | `Build_Mother_Nature` | new, `cityBonusBanks` from `self:Build_Bank`, `[[]]` | **Necromancy Amplifier**; plugin probe |
| Necropolis | `Build_Mycelium_Roots` | new, `cityBonusBanks` from `self:Build_Bank`, `[[]]` | **Cover of Darkness**; plugin `Homm3NecropolisCoverOfDarknessRuntime` |
| Necropolis | `Build_Skeleton_Converter` | replace | **Skeleton Transformer**: tiers 1-6 become Skeletons, tier 7 becomes Bone Dragons |
| Necropolis | `Build_Gaping_Maw` | replace, `graals` | **Soul Prison**; plugin probe (+10% Necromancy) |
| Dungeon | `Build_Bank` | replace | Bank |
| Dungeon | `Build_Well_Of_Souls` | new, `manaFountains` from undead | **Mana Vortex**; plugin `Homm3DungeonManaVortexRuntime` |
| Dungeon | `Build_Portal_Summoning` | new, from unfrozen, `numberPurchases: 1` | **Portal of Summoning** |
| Dungeon | `Build_Gymnasium` | replace | **Battle Scholar Academy** (cost 5000 gold) |
| Dungeon | `Build_Resource_Depot_level_2` | replace, `banks` | **Mushroom Rings**: `cityUnitsIncrementPer h3_troglodyte 0.2596` (+7 per week on a base of 27) |
| Dungeon | `Build_Spy_Network` | replace, `graals` | **Guardian of Earth**; plugin `Homm3TownSiegeDefenseRuntime` (runtime agent) |
| Dungeon | `Build_Lyceum` | `remove` | gone |

- All building IDs from the coordinator were used as given; every one was usable.
- Every renamed row has a `nameText`, and every plugin row has a `descriptionText`.
- The `*Locales` keys are left out on purpose. Translations are needed for every new or changed name and description.

## Scene catalog keys for new SIDs (not edited, owner to apply)

The catalogs are keyed by HoMM3 layer id. `homm3_runtime_assets/town_scene_refs/homm3_<f>/layers/building_layer_map.json`
maps SID to layer.

### Inferno

- `Build_Mycelium_Roots` (Castle Gate) → **`tbinext1`**. This is the old Bank layer, as the draft says.
  - Conflict: that catalog entry's motion note says "brimstone pyre burns". Confirm the art before you remap it.
- `Build_Mother_Nature` (Order of Fire) → **`tbinext0`**.
- Stale: the map has `Build_Artifact_Market → tbinext2`, and Lang still carries "Artifact Merchants" text for Inferno. HoMM3 Inferno has no Artifact Merchants, so drop both.

### Necropolis

- `Build_Mycelium_Roots` (Cover of Darkness) → **`tbncspec`**. The catalog shows "storm cloud over the tower billows", which is HoMM3's Cover of Darkness art. Today `tbncspec` is mapped to `Build_Bank`; move it.
- `Build_Mother_Nature` (Necromancy Amplifier) → **`tbncext0`**. This layer has no mesh yet.
- The existing map lists `Mycelium_Roots → tbncext1` and `Mother_Nature → tbncext0`. If the owner keeps `tbncext1` for Cover, it has no mesh.

### Dungeon

- `Build_Well_Of_Souls` (Mana Vortex) → **`tbdnext0`**. Its fx is `vortex_wisps`, but its motion note says "portal of summoning ring". This is ambiguous; the owner should confirm.
- `Build_Portal_Summoning` → **`tbdnext1`**. This is the old Lyceum layer, which has no mesh.

## Runtime behaviour and limits

### Castle Gate (Inferno)

- **How it works.** A prefix on the real-named `Hex.Session.UI.BhViewElementMyceliumRoots.Show(<world object>, bool)`. When the open town is an Inferno town with a teleport row, it blocks every destination town that has no constructed `myceliumRoots` row of its own. Blocked entries go through the native `SetupBlocked` path.
- **Limits.**
  - UI only: AI teleports and commands issued without the window are not filtered, because no live symbol for the apply command is proven.
  - If the origin town can't be read, the filter fails open and leaves the native list.

### Cover of Darkness (Necropolis)

- **How it works.**
  - A postfix on the side logic day start (`GameSymbols.SwashbucklerGold`).
  - For every enemy-owned Necropolis town with `Build_Mycelium_Roots`, it clears `Side.fogData.visibilityMap` within Euclidean radius 20.
  - It keeps discs around the side's own towns (radius 5) and heroes (radius 6).
  - It runs every day, so nothing needs saving.
- **Limits.**
  - No ally exclusion.
  - Mines and dwellings don't protect their surroundings.
  - The fog renderer is not refreshed explicitly; no symbol for that is proven.
  - Surface and underground share the grid.

### Necromancy Amplifier and Soul Prison (Necropolis)

- **How it works.** They add +5% and +10% to the post-battle Necromancy share if the winning side owns a Necropolis town with the building. They stack with the Bone Conductors law and each other.
- **Limits.**
  - They apply only when the hero already has a Necromancy share above 0. This matches HoMM3, where the bonus adds to the skill.
  - No hero-card display path shows the extra share.

### Mana Vortex (Dungeon)

- **How it works.**
  - The native `manaFountains` row refills mana on every visit.
  - The logic visit handler is obfuscated and has no symbol, so a per-frame host polls `ObjCity.visitorHeroId` instead. It watches the Dungeon towns with the building and rescans them every 1 s.
  - When a new hero arrives and has been the visitor for 0.35 s (after the native refill), it sets `hero.mana *= 2`. This happens once per town per native week; the week id is the same one Factory uses.
  - The first observation after a load or capture only records the visitor and does not pay.
- **Save.**
  - Weekly marks go in the `homm3_ind_town_building_store` carrier as VER, (CITY, WEEK) pairs and SUM. This is the Factory/Cove pattern.
  - The carrier is read back after every write. A carrier that fails its checks is never overwritten.
- **Limits.**
  - The write comes from the UI host, not deterministic side logic, so it is not multiplayer-deterministic. War Captives has the same limit.
  - A hero who enters and leaves within one frame is missed.
  - Leaving and re-entering the same week only refills, by design.

### Siege entries (runtime agent)

Brimstone Stormclouds (`Build_Resource_Depot_level_2`) and Guardian of Earth (`Build_Spy_Network`) name
`Homm3TownSiegeDefenseRuntime`, which belongs to the runtime agent.

## Not built

- None of the IND levers was dropped.
- Not built:
  - Castle Gate filtering for the AI and for commands;
  - ally exclusion for Cover of Darkness;
  - a Necromancy share display.
- Everything above is untested in game, because nothing is compiled or installed.
