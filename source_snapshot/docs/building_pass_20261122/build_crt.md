# Building pass: CRT hand-back (Castle, Rampart, Tower), 2026-11-22

Proof tier: **source/static only.**
- The override JSONs pass the applier's check, run against my three files only: `python tools/release_port/apply_release_core_overlay.py --check-building-overrides --building-overrides-dir V:/olden_port_work/crt_building_pass/ovr`. All three towns are OK. The only warning is the missing authored description locales; the coordinator adds those centrally.
- The runtime C# was **not compiled** (the coordinator compiles) and was **not run in game**.
- Nothing was committed. Nothing was written to the GE install.

Building IDs are exactly the ones the coordinator listed:
- Castle: `Build_Stables`, `Build_Mother_Nature` (Brotherhood of the Sword), `Build_Mycelium_Roots` (Signal Beacon).
- Rampart: `Build_Mystic_Pond`, `Build_Mother_Nature` (Fountain of Fortune), `Build_Rampart_Treasury`.
- Tower: `Build_Library`.
- `Build_Bank` is the plain Bank in all three towns.

## Files

### New

**`custom_factions/building_overrides/homm3_castle.json`** (93 lines)

| Row | Change |
|---|---|
| `Build_Bank` | Replace with the vanilla Bank: 2500 Gold, 5 Wood, 5 Ore; 1000 Gold daily; vanilla icon. |
| `Build_Stables` | New `heroBonusBanks` row with empty bonuses. Cost 2000 Gold + 10 Wood. Takes the old Bank (Stables) icon. |
| `Build_Mother_Nature` (Brotherhood) | New `banks` row with empty bonuses. Cost 500 Gold + 5 Wood. |
| `Build_Mycelium_Roots` (Signal Beacon) | New `banks` row with empty bonuses. Cost 2000 Gold + 10 Ore. |
| `Build_Golden_Calf` (Colossus) | Keeps its 6 `sideResHumGraal` entries and adds graal side `heroStat moral 2` (receiverAllegiance ally). |
| `Build_Treasury` | Renamed "Treasury". |

**`custom_factions/building_overrides/homm3_rampart.json`** (84 lines)

| Row | Change |
|---|---|
| `Build_Bank` | Vanilla Bank. |
| `Build_Mystic_Pond` | New `banks` carrier. Cost 2000 Gold + 2 each of Mercury, Crystals and Gemstones. Takes the old Bank (Pond) icon. |
| `Build_Mother_Nature` (Fountain) | Replaced, moving from `heroBonusBanks` to `banks` with empty bonuses. The +2 Spell Power is gone; the cost stays 5000 Gold. |
| `Build_Rampart_Treasury` | New `banks` carrier. Cost 5000 Gold + 5 Ore. |
| `Build_Artifact_Market` | Renamed "Artifact Merchants". |
| `Build_Spring_of_Life` (Spirit Guardian) | Keeps `cityUnitsIncrement all 1` and adds graal side `heroStat luck 2`. |

**`custom_factions/building_overrides/homm3_tower.json`** (58 lines)

| Row | Change |
|---|---|
| `Build_Bank` | Renamed "Bank"; the data was already the vanilla Bank. |
| `Build_Library` | New `banks` carrier. Cost 1500 Gold + 5 each of Wood, Ore, Mercury, Crystals and Gemstones. |
| `Build_Golden_Calf` (Skyship) | Keeps its resources and +100% growth, and adds `cityBonuses cityRadiusView 999`. |
| `Build_Treasury` | Renamed "Treasury". |

**Runtime files** (all in `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`)

| File | Lines | What it contains |
|---|---|---|
| `Homm3CastleStablesRuntime.cs` | 182 | The Stables runtime. |
| `Homm3CastleSignalBeaconRuntime.cs` | 115 | The Signal Beacon runtime. |
| `Homm3RampartWeeklyIncomeRuntime.cs` | 394 | Mystic Pond and Treasury income, plus the save store. |
| `Homm3TowerLibraryRuntime.cs` | 467 | The Library runtime, plus `Homm3LogicBuildingShape`, a shape resolver for the logic building classes. Stables uses it too. |

### Edited

**`custom_factions/source_mechanics/homm3_castle.json`** (+64 lines)
- `castle.stables`: now exact on `Build_Stables`.
- `castle.lighthouse`: stays substituted, now on `Build_Mycelium_Roots`, with an honest reason (no ships) and `playerTextTokens` for the Beacon tokens.
- New exact entries: `castle.brotherhood_of_the_sword` on `Build_Mother_Nature`, and `castle.colossus` on `Build_Golden_Calf`.

**`custom_factions/source_mechanics/homm3_rampart.json`** (+42 lines)
- `rampart.mystic_pond`: now exact on `Build_Mystic_Pond`.
- `rampart.fountain_of_fortune`: now exact.
- New exact entries: `rampart.treasury` on `Build_Rampart_Treasury`, and `rampart.spirit_guardian` on `Build_Spring_of_Life`.

**`custom_factions/source_mechanics/homm3_tower.json`** (+36 lines)
- `tower.library`: now exact on `Build_Library`; the "Library" forbidden text is removed.
- `tower.skyship_beacon` becomes `tower.skyship`, exact. Only "fly" stays forbidden.

## Plugin.cs registrations needed

Each class has `TryRegister(Harmony, ManualLogSource)`. Each one logs and fails closed, and none of them throws.

The Signal Beacon and the weekly income depend on the Swashbuckler day-start hook. Register them **after** `Homm3SwashbucklerGoldHook.RegisterRequiredReleaseSafeSlice` (Plugin.cs:772), for example next to `Homm3CoveTreasureSubskills.TryRegister` (Plugin.cs:1083):

```csharp
Homm3CastleStablesRuntime.TryRegister(_harmony, Log);
Homm3CastleSignalBeaconRuntime.TryRegister(_harmony, Log);   // needs the day-start bus registered
Homm3RampartWeeklyIncomeRuntime.TryRegister(_harmony, Log);  // its postfix reads the day the Swashbuckler postfix caches
Homm3TowerLibraryRuntime.TryRegister(_harmony, Log);
```

The csproj needs nothing if it globs `*.cs`; otherwise add the four files.

## Core overlay rows I need (coordinator or applier; I cannot edit `apply_release_core_overlay.py`)

1. **heroes_buffs `homm3_signal_beacon_buff`.** Clone vanilla `stable_buff` with these changes:
   - `heroStat movementPerBonus 0.10`;
   - `"isPositive": true`, `"hidden": false`;
   - name token "Signal Beacon";
   - description "+10% movement points (Signal Beacon)";
   - icon `stable_buff_icon` is fine until art exists.

   Without this row the Beacon logs one warning and gives nothing.
2. **logic_side_buffs `homm3_rampart_income_store`.** A hidden, bonus-less store row, cloned from `heros_crypt_debuff_none` exactly as `make_homm3_cove_treasure_store_side_buff_row` does (with that the Cove store's sid). It carries 3 durations per side: VER, last paid WEEK and an FNV SUM.

   Do not ship the weekly income without this row: the runtime adds the buff to the side's `buffs.list` the way the Cove and Factory stores do.
3. **Translations:** the coordinator adds them centrally. Names to translate (renamed or reused SIDs):
   - Castle: `Build_Bank` "Bank", `Build_Stables` "Stables", `Build_Mother_Nature` "Brotherhood of the Sword", `Build_Mycelium_Roots` "Signal Beacon", `Build_Golden_Calf` "Colossus", `Build_Treasury` "Treasury".
   - Rampart: `Build_Bank` "Bank", `Build_Mystic_Pond` "Mystic Pond", `Build_Mother_Nature` "Fountain of Fortune", `Build_Rampart_Treasury` "Treasury", `Build_Artifact_Market` "Artifact Merchants", `Build_Spring_of_Life` "Spirit Guardian".
   - Tower: `Build_Bank` "Bank", `Build_Library` "Library", `Build_Golden_Calf` "Skyship", `Build_Treasury` "Treasury".
   - Rampart `Build_Treasury` stays "Blacksmith" (draft), so Rampart shows two names, "Treasury" and "Blacksmith". That is a text-only follow-up.

## Source-mechanics metadata (applier)

`stamp_city_building_source_mechanics_metadata` copies `xHomm3SourceMechanic` and `xHomm3MechanicsStatus` from `currentRows`. If it runs before the override rows are added, the new rows (`Build_Stables`, `Build_Mycelium_Roots`, `Build_Mother_Nature` in Castle, `Build_Mystic_Pond`, `Build_Rampart_Treasury`, `Build_Library`) will lack that metadata. The strict `validate_source_mechanics_contract` would then fail with "source mechanic metadata missing". Stamp after the override call, or give override rows the stamp.

## How each runtime works and hooks the game (re-read on the 2026-11 interop, `V:/olden_port_work/battleend_ilspy/hexproj`)

**Never patched: base `Building` empty virtuals.**
- On the live build, the logic `Building` base's `HeroVisit`, `OnConstruct`, `OnChangeSide`, `Visit`, `OnStartDay` and `OnStartWeek` all show CallerCount 28355. They are identical-code-folded empty stubs, so a patch on one would fire for every folded function.
- The drafts' "postfix on base `Building.HeroVisit`" is therefore unsafe and was not built.
- Only type-specific overrides are patched. Each patch filters on the building SID, read through `Homm3ConstructionNativeAdapter.TryReadBuildingIdentity` on the base `BuildingData` property.

**`Homm3LogicBuildingShape` (in `Homm3TowerLibraryRuntime.cs`)** finds each logic class from deobfuscated anchors only:
- the class holding a field of `Hex.Session.Data.BuildingBank`, `BuildingHeroBonusBank` or `BuildingMagicGuild`;
- the real name `Init(BuildingData, city)`;
- Il2CppInterop `[CallerCount]`.

There are no obfuscated literals and no GameSymbols edits. Any ambiguity refuses to register. If you prefer pinned names, these GameSymbols entries can be added later:

| Member | 2026-11 interop name |
|---|---|
| bank logic OnConstruct | `Method_Protected_Virtual_Void_0` on `Object1PublicBuclLi1ObclBuclUnique` |
| heroBonusBank logic HeroVisit | `Method_Public_Virtual_Void_ObjectPublicHeObInObcqSiObVeBoObUnique_0` on `Object1PublicBuclLi1ObclObclObclUnique` |
| heroBonusBank logic OnConstruct | `Method_Protected_Virtual_Void_0` on `Object1PublicBuclLi1ObclObclObclUnique` |
| guild logic GetMagicsCountForRank | `Method_Private_Int32_Int32_0` on `Object1PublicBuclcgBucl1StDi2InUnique` |
| guild logic LearnMagicAddition | `Method_Public_Void_Int32_PDM_0` on `Object1PublicBuclcgBucl1StDi2InUnique` |

**Stables**
- A prefix on the heroBonusBank logic `HeroVisit` override, for `Build_Stables` only:
  - it adds vanilla `stable_buff` (`UntilNextWeek`, as the vanilla stables bank reward does) unless the hero already has it;
  - it returns false, which skips the native once-ever visit record and the empty bonus popup.
- A prefix on that class's `OnConstruct` skips the native call for `Build_Stables`, because the native would choose a hero for an empty popup.
- Every other `heroBonusBanks` row (Wall of Knowledge, Fortress Cage, ...) runs natively.

**Signal Beacon**
- A consumer on the day-start hero bus. For each logic hero it reads `Homm3TownBuildingReader.SideHasBuilding(dataHero, "Build_Mycelium_Roots", "homm3_castle_city")` and sets or removes the Infinite buff to match.

**Weekly income (Pond and Treasury)**
- Patches the side logic `OnStartDay` (same type resolution as the Factory) with a prefix and a postfix. The postfix has priority Low so it runs after the Swashbuckler postfix.
- The prefix snapshots the side's gold.
- The postfix fires on paydays only: day > 1 and (day − 1) % 7 == 0.
  1. It counts the side's Treasury and Pond rows with `SideBuildingCount(side, sid, "homm3_rampart_city")`.
  2. It reads the store; a week already stored is skipped.
  3. It computes:
     - Treasury: floor(10% × snapshot gold) × Treasury count;
     - Pond: one FNV-hashed roll per town, keyed by side, week and town ordinal, which picks a resource from {mercury, crystals, gemstones} and 1–4 units.
  4. It writes the store and verifies it by reading it back.
  5. Only then does it add the resources, through `Homm3RewardEconomyNativeAdapter`.
- A corrupt store or a failed write blocks that side's income for the session, with a warning, so it can never pay twice.

**Library**
- A postfix on guild `GetMagicsCountForRank` adds +1 when `CityHasBuilding(logicCity, "Build_Library")`. The reader accepts the logic city through the construction adapter.
- A postfix on guild `Init` fills a registry from city pointer to guild.
- A postfix on bank logic `OnConstruct`, for `Build_Library` only, calls `LearnMagicAddition(1)` on the city's guild. It does so only when some open guild level holds fewer spells than its count (which now includes the Library's +1), so a repeat call cannot add a second spell.

## Scene art for the new SIDs (catalog edits are not mine)

HoMM3 town building index → def layer. The `tb??ext*` names follow the HoMM3 special 17 / 21 / 22 slots; check them against the def list before binding.

| SID | HoMM3 building | Layer |
|---|---|---|
| Castle `Build_Stables` | Stables (Castle 21) | `tbcsext0`. Not in the Castle 3D catalog yet; needs extraction. |
| Castle `Build_Mother_Nature` | Brotherhood of the Sword (Castle 22) | `tbcsext1`. Not in the catalog. |
| Castle `Build_Mycelium_Roots` | Lighthouse (Castle 17) | `tbcsspec` (in the catalog). Fits the Beacon. |
| Rampart `Build_Mystic_Pond` | Mystic Pond (Rampart 17) | `tbrmspec` (in the catalog). |
| Rampart `Build_Mother_Nature` | Fountain of Fortune (Rampart 21) | `tbrmext0` (in the catalog). Keep its current binding if it already maps here. |
| Rampart `Build_Rampart_Treasury` | Treasury (Rampart 22) | `tbrmext1`. Not in the catalog. |
| Tower `Build_Library` | Library (Tower 22) | `tbtwext1`. Not in the catalog. `tbtwspec` (Artifact Market) and `tbtwext2` are taken. |

Icons are placeholders until art exists:

| Row | Placeholder icon |
|---|---|
| Stables | old Castle Bank icon |
| Pond | old Rampart Bank icon |
| Signal Beacon | Castle grail icon |
| Library | Wall of Knowledge icon |
| Brotherhood | `nature_city` Mother Nature icon |
| Rampart Treasury | `nature_city` Treasury icon |

## Not built, limits and risks

**Siege rows** (Brotherhood, Fountain, Skyship +15 Knowledge)
- These are data rows only; the effect is the runtime agent's `Homm3TownSiegeDefenseRuntime`.
- The text says "The hero defending this city in a siege gets ...", as the Fortress rows do, because a heroless garrison has no TransferHero to carry the stat.

**Stables**
- No same-day movement top-up: the buff raises max movement from the next refill. Vanilla's map Stables adds a separate MovePointsPercentAdditionReward, which I did not trace.
- No grant on construction to a hero already in town: the visitor or garrison read on the logic city was not traced. The hero gets the buff on its next visit.

**Signal Beacon**
- Takes effect at the next day start, after it is built, after a capture or loss, and for newly hired heroes. The text says "Takes effect from the next day."

**Weekly income**
- Without the store row it must not ship (see the Core rows above).
- The Pond roll is a fixed hash, not the game RNG. It is deterministic per save, but every game rolls the same results for the same side and week. The map seed is a possible salt; I found no proven accessor for it.
- The Treasury snapshot is taken before this side's `OnStartDay`. If native daily income is credited outside that method, the snapshot already includes that day's income.

**Library**
- `GetMagicsCountForRank` has CallerCount 1. If IL2CPP inlined it into another caller, that path misses the +1.
- The construction top-up still covers open levels.
- The guild's per-rank pool caps the stack with the law, up to +3. Not verified in game.

**Skyship map reveal**
- `cityRadiusView 999` is proven only on the vanilla DungeonGraal. The Skyship is a HumanGraal row. Check in game.

**Graal hero-stat bonuses**
- `heroStat moral/luck` on a graal follows the vanilla demon_city graal shape, which uses `crit`. Morale and luck on that path are not seen in game.

**CallerCount-based resolution**
- This is a hypothesis about the live build, from the 2026-11-19 ilspy of the 2026-11-12 interop. If an assumption breaks, each runtime refuses to register and logs why.
