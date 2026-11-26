# Building pass: runtime agent hand-back (2026-11-22)

Owner: runtime agent. Nothing was compiled, committed, installed or launched. The coordinator compiles once.

## Files (all new, in `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`)

| File | What it does |
|---|---|
| `Homm3TownBuildingReader.cs` | The shared reader, with exactly the BUILD_BRIEF API (`public static class`). It also has internal helpers for the two runtimes: `IsSiegeBattle`, `TryGetSiegeDefender`, `CityMatchesSid`, `CityIdentity` and `TryResolveSideIndex`. |
| `Homm3TownSiegeDefenseRuntime.cs` | All ten REVIEW §1 siege-defender buildings. It is a `BattleLogic.Init` prefix at `Priority.High` plus a finalizer at `Priority.Low`. |
| `Homm3StrongholdEscapeTunnelRuntime.cs` | Escape Tunnel: a postfix on the native CanEscape that lets the defending hero of a Stronghold town with Fort L1 retreat. |

No shared file was edited.

## Plugin.cs registrations needed

Add these next to the other battle runtimes in the law-runtime block, for example right after `Homm3BulwarkRunesRuntime.TryRegister(_harmony, Log);` (around line 1103):

```csharp
// Building pass 2026-11-22: siege-defender buildings (battle-only hero stats) + Stronghold Escape Tunnel (Fort L1).
Homm3TownSiegeDefenseRuntime.TryRegister(_harmony, Log);
Homm3StrongholdEscapeTunnelRuntime.TryRegister(_harmony, Log);
```

- Register order does not matter, because the siege runtime sets its Harmony priorities explicitly.
- The reader needs no registration.
- No csproj change is needed if the project globs `*.cs`. If the csproj lists files explicitly, add all three.

## Final SID list per entry (coordinator-confirmed 2026-11-22)

Every entry fires at building level 1 or higher. The town must match the city id; a land-on clone matches its canonical id.

| Entry | City id | Building SID | Battle-only stat on the defending hero |
|---|---|---|---|
| Brotherhood of the Sword | `homm3_castle_city` | `Build_Mother_Nature` | Morale +2 |
| Fountain of Fortune | `homm3_rampart_city` | `Build_Mother_Nature` | Luck +2 |
| Glyphs of Fear | `homm3_fortress_city` | `Build_Mother_Nature` | Defense +2 |
| Blood Obelisk | `homm3_fortress_city` | `Build_Mycelium_Roots` | Attack +2 |
| Carnivorous Plant (grail) | `homm3_fortress_city` | `Build_Spring_of_Life` | Attack +10, Defense +10 |
| Brimstone Stormclouds | `homm3_inferno_city` | `Build_Resource_Depot_level_2` (the literal SID) | Spell Power +2 |
| Warlords' Monument (grail) | `homm3_stronghold_city` | `Build_Spy_Network` | Attack +20 |
| Guardian of Earth (grail) | `homm3_dungeon_city` | `Build_Spy_Network` | Spell Power +12 |
| Skyship (grail) | `homm3_tower_city` | `Build_Golden_Calf` | Knowledge +15, which raises max mana and current mana by the native amount |
| Spirits of the Forebears (grail) | `homm3_bulwark_city` | `Build_Spring_of_Life` | Defense +20 |
| Escape Tunnel (no SID) | `homm3_stronghold_city` | `Build_Wall` at level 1 or higher | The defending hero may retreat |

- The table is `Homm3TownSiegeDefenseRuntime.Entries`. Changing a SID is a one-line edit there.
- Faction groups should write player text that matches these numbers. For example, add "Heroes defending this city may retreat from battle." to the Stronghold Fort text.

## How it works (live symbols re-verified against the 26615913 interop and Ghidra)

### Reader

- **Data source.** It reads `Hex.Session.Data.ObjCity` from the session `Data.objects.cityObjs`, through `Homm3FactoryLogisticsEffects.TryGetData`.
  - It reads every typed section list on `BuildingsData`, mains through walls.
  - Grail rows are in `bonusBanks`: native `CreateBuildingFromConfig` puts `EBuildingType.Graal` there.
  - It skips the lazy aggregate list.
- **Built level** is `isConstructed ? level : 0`, the highest among rows that share the SID. The SID is read through `Homm3ConstructionNativeAdapter.TryReadBuildingIdentity`.
- **City identity** is the rows' `citySid`, which is the native `_cityConfig.sid`. It falls back to `ObjCity.sidConfig`. Land-on aliases go through `Homm3CustomFactionRegistry.MatchesCitySidOrLandOnAlias`.
- **Accepted inputs.**
  - `city` can be an `ObjCity`, a `BuildingsData`, or any city context `Homm3ConstructionNativeAdapter.TryResolveBuildingsDataFromCityContext` understands (city logic).
  - `owner` can be an int side index, a `Data.Side`, a `TransferSide`, a `Data.Hero`, an `ObjCity`, a logic side, or a logic hero (via `Homm3CustomFactionLawRuntime.TryResolveDataSideFromLogicHeroExplained`).
- **Caching.** The city list is cached per session Data pointer and game day. Ownership and building levels are read live, so a capture or construction later the same day shows up immediately.
- **Failure.** Every entry point catches exceptions and fails closed. It writes at most 16 warnings.
- **Finding the besieged town.** `TryGetBesiegedCity` accepts a battle logic, a `TransferBattle`, or a lone `TransferSide` (which returns false, because it has no back-reference to its battle). It does not use the obfuscated `battleControllers` chain. Instead:
  - A siege is `battleType == ForCity`.
  - A `Type_Hero` defender matches the town by `garnisonHeroId` or `visitorHeroId` equal to `entityIdInWorld`, plus `ownerSide == sideIdInWorld`. `BattleMaker` builds hero sides with `entityIdInWorld = hero.id`.
  - A `Type_Garnison` defender matches the only owned town flagged `inBattle`.
  - Side 1 is tried first.

### Siege runtime

- **What the prefix changes.** It adds the summed bonus to the passed `TransferBattle` defender's `hero.heroStat` and `heroStatUnclamped` (the two are deduplicated by native pointer). For Skyship it also raises `manaMax` and `mana` by `newMax - oldMax`, using the native formula.
- **Why the bonus lasts the whole battle.** Native Init sets `startedTransferBattle = passed` and builds the battle from `passed.Clone()`, which deep-copies the hero and its stats. The clone therefore carries the bonus for the whole battle.
- **What the finalizer restores.** It restores the passed object's original values, writing back only the fields this runtime changed. Nothing reaches the world hero, except leftover current mana (see risks).
- **Priority ordering.** Prefix at High, finalizer at Low. This wraps the Normal-priority snapshot and restore pairs (Conflux Elemental Conjunction, Dungeon Terror Exploitation):
  - their snapshots include the siege bonus;
  - their restores leave it in place;
  - this runtime restores last.
  - The Priority.First Factory/Bulwark force-setup prefix and the Priority.Last status postfix do not touch HeroStat.
- **Retry battle.** A battle retry re-runs Init on `startedTransferBattle`, which has already been restored, so the bonus is applied exactly once again.
- **Quick combat.** Quick combat and AI-vs-AI go through `battlesManager.Begin`, which calls Init, so they get the bonus too.

### Escape Tunnel

- **What the native check does.** The native CanEscape is `ObjectPublicAbstractSealedbf57aInESbf6abidUnique.Method_Public_Static_ESideCommandsState_ObjectPublicPrcnInPrcnSiBoPrcnInUnique_Int32_1`: Ghidra `ekf$$bfcc` at 0x182061720, token 100706108. It returns `ESideCommandsState`, not bool. For a hero whose side owns the battle object it returns `ReasonDefenderCant` (10).
- **What the postfix changes.** It flips only that value to `Allowed`, and only when all of these hold:
  - the loser index is the siege defender;
  - the defender is `Type_Hero`;
  - the town is `homm3_stronghold_city`;
  - the town has `Build_Wall` at level 1 or higher.
- **What it leaves alone.** Other refusals stay: Banned, SingleHero, Tourney, NotHero, Unknown. CanCapitulate (`_Int32_0`) is not touched.
- **Cache.** Decisions are cached per (logic pointer, transferBattle pointer, loser index), at most 33 entries.
- **What a retreat does to the town and hero** (escape path traced in the mono decomp):
  1. `CmdBattleSideEscape` calls `ApplyResult`.
  2. The escaped Type_Hero loser goes through `ReturnToSideReserve`. For a town hero this calls `CityHeroesUtility.DeleteHero(city, hero)`, which is the same cleanup as a killed defender. The hero goes to the side reserve and can be re-hired in the tavern.
  3. `CityBattleController.ApplyResults(attacker)` gives the town to the attacker, exactly as on the death path.
  4. The army is lost unless the native `enableSavePartyByEscape` bonus applies.
- **Not checked.** The live decompile of `CmdBattleSideEscape` was not re-checked to see whether it re-tests CanEscape. In mono it does not.

## Risks and limits

1. **Runtime is untested.** It has not been compiled or run. The coordinator compiles, and in-game checks are still needed:
   - a siege of each town with its building;
   - a hero retreating from a Stronghold town with Fort L1: the town falls, the hero shows in the tavern, and the garrison or visitor slots are cleared;
   - quick combat;
   - a battle retry.
2. **Clone semantics were verified in mono, not fully in live.** Live `epx$$Init` (0x1821B15A0) stores the TransferBattle and calls `TransferBattle.biir`, which is consistent with Clone. The existing Morale and Conflux laws rely on the same pattern.
3. **Hard-pinned CanEscape name.** No GameSymbols entry existed. If `_0` and `_1` swap in a game update, the patch would hit CanCapitulate instead. That would let Stronghold Fort defenders surrender rather than retreat; it would not crash. Registration fails closed (logged) if the name is missing. Re-verify after any game update. Ideally move the name into `GameSymbols` (shared file, not edited here).
4. **AI behaviour.** AI defenders in Stronghold towns with a Fort may now retreat. The native caller at 0x1808a9a41 is unidentified and may be AI logic. The AI also does not value any of these buildings when choosing builds.
5. **A garrison-only defence (no hero) gets no stat bonus.** This is the same as HoMM3. The Castle and Rampart drafts said "troops"; REVIEW says "defending hero", and REVIEW was followed.
6. **Skyship mana.** Max and current mana both rise by the native delta (about 150 at base). Battle end copies current mana back to the world hero, so unspent bonus mana can stay above the world max until it is spent, like a Magic Well overfill.
7. **Identifying the town.** A defending hero is matched by hero id on `garnisonHeroId` or `visitorHeroId`. If that ever fails, the bonus is skipped and a warning is logged; nothing wrong is applied. A garrison-only siege is resolved through `ObjCity.inBattle`, which may not be set yet at Init. That case only affects `TryGetBesiegedCity` callers, because a garrison gets no bonus.
8. **Side effect of reading session data.** The reader uses `Homm3FactoryLogisticsEffects.TryGetData`, which notes the session key in the Factory logistics runtime. That call is harmless and idempotent.

## Not built

Nothing in the runtime scope was left unbuilt.
