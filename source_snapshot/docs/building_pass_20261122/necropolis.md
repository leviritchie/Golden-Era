# Necropolis building pass (`homm3_necropolis`, 2026-11-22)

Sources:
- Installed rows: Golden Era `Core.zip` `DB/objects_logic/cities/homm3_necropolis_city.json`.
- Vanilla: Steam `Core.zip`.
- HoMM3/HotA: heroes.thelazy.net Necropolis page.
- Necromancy runtime: `Homm3SkeletalNecromancyProbe.cs`, which resolves the share by bucket: 5/10/15%, half of HoMM3's values. The law amplifier adds 2% per law level (`LawNecromancyAmplifier = 7`, `AmplifierPercentPerLevel = 0.02f`, branch near `:264`).
- Fog: managed decompile `FogOfWar.CloseAroundCenter(WorldSide, int centerNode, int radius, int mapView)` and `OpenObjectsVisibleNodes(side)`.

Scratch scripts are in `V:/olden_port_work/building_pass/claude_ind/`.

**Slot map today.**
- `Build_Bank` is "Bone Archive". It pays 1000 Gold and is gated on MG1, but its tag says Necromancy Amplifier, which has no effect today.
- Cover of Darkness is tagged `changed` and has no row.
- `Build_Resource_Depot_level_2` is Unearthed Graves (+6 Skeletons, exact) but carries a non-vanilla extra gate on the converter.

The placement rule is the same as in `inferno.md`: the Bank goes back to the plain economy and each special gets its own SID (owner decision 1).

## 1. Special buildings

| SID | Source building (HoMM3/HotA effect) | Current effect | Status | Proposed build | Player text | Cost/power note |
|---|---|---|---|---|---|---|
| `Build_Mother_Nature` (new; section `cityBonusBanks`, `bonuses: []`) | **Necromancy Amplifier**: +10% Necromancy for every Necromancy hero of the owner in SoD. Port value: +5%, because the port halves HoMM3 Necromancy. It does not stack between towns. | None (the name and tag sit on the Bank). | substituted -> **exact** | The empty bank is inert. Plugin hook P3 adds 0.05 to the necromancy share for any hero whose side owns at least one Necropolis with this building. It applies only when the hero's bucket is above 0, so heroes without Necromancy get nothing, as in HoMM3. | Explicit: "Increases the Necromancy skill of all your heroes by 5%." | Same as Undead Well of Souls-class specials: 2500 Gold + 3 Gems/Crystals/Mercury. Gated on MG L1 (HoMM3). |
| `Build_Mycelium_Roots` (new; section `cityBonusBanks`, `bonuses: []`) | **Cover of Darkness**: enemy players lose sight of map squares within 20 of the town. | None (`changed`, removed). | changed -> **exact** | Plugin hook P4: at each enemy side's day start, `CloseAroundCenter(enemySide, cityGateNode, 20, mapView)`, then `OpenObjectsVisibleNodes(enemySide)`, so that enemy heroes and towns keep their own sight. Only the native per-side re-fog fits; the native `restoreFogOfWar` bonus is map-wide and skips the owner. | Explicit: "Covers the area around this city in darkness for enemy players." | HoMM3 price 1000 Gold + 5 Ore. Vanilla analog (a cheap utility special): 2500 Gold. Root; HoMM3 has no prerequisite. |
| `Build_Skeleton_Converter` (`unitsConverters`) | **Skeleton Transformer**: converts any creature into Skeletons; dragons become Bone Dragons. | "Bone Foundry": converts each tier to that tier's h3 base. Bans the Necropolis lines. Donor-shaped. | substituted -> **exact** | `conversionPairs`: tiers 1-6 -> `h3_skeleton`, tier 7 -> `h3_bone_dragon`. `bannedUnits`: only the Skeleton and Bone Dragon lines, so the other undead can convert, as in HoMM3. Rename it "Skeleton Transformer". | Generated, with a new converter sentence: "Converts creatures into Skeletons; 7th-level creatures become Bone Dragons." | Keep 1000 Gold + 5 Ore + 5 Wood. Make it a root, as in HoMM3. The 2026-10-02 converter UI failure is unproven since; check it in the first test install. |
| `Build_Gaping_Maw` (graal) | **Soul Prison**: +5000 Gold a day, +50% growth, +20% Necromancy. Port value: +10%. | UndeadGraal: allied creatures +10 Defense, enemy crit −50%, city growth +100%. | substituted -> **exact** (decision 3) | Keep `graalType: UndeadGraal` and `cityBonuses` +100%. Drop the battle side bonuses. P3 adds 0.10 to the necromancy share while the side owns it; this stacks with the Amplifier, as in HoMM3. | Explicit (new `graal_necropolis` template): "Increases the Necromancy skill of all your heroes by 10%. This city's dwellings produce +100% units." | The +100% growth is the GE grail convention. Not every hero can use the Necromancy, so this grail is weaker in battle than +10 Defense. |
| `Build_Resource_Depot_level_2` | **Unearthed Graves**: +6 Skeletons a week. | cityUnitsIncrementPer h3_skeleton 0.2004 (+6 of 30). | exact | No effect change. The tree drops the converter gate. | No change. | No change. |
| `Build_Well_Of_Souls` | OE-native (vanilla Undead). | Same. Gated on MG3. | OE-native, keep | No change. | No change. | No change. |
| `Build_Bank` (`banks`) | None: the shared vanilla Bank. | "Bone Archive", 1000 Gold, gated on MG1. | n/a (economy) | Unchanged sideRes gold 1000. Rename it "Bank". Gate it on Main L2. | Generated: "Produces 1000 Gold daily." | Unchanged. |

`source_mechanics/homm3_necropolis.json` changes:
- `necropolis.necromancy_amplifier`: `exact`, rows `Build_Mother_Nature`.
- `necropolis.cover_of_darkness`: `exact`, rows `Build_Mycelium_Roots`.
- `necropolis.skeleton_transformer`: `exact`.
- `necropolis.soul_prison`: `exact`.

The proof tier for all four is runtime-unproven until P3 and P4 are exercised.

Law note: law #7 is also called "Necromancy Amplifier" (+2/+4%). Both effects stack on the same bucket. See decision 2.

## 2. Tree changes

| Level | Current prerequisites | Proposed prerequisites | Why (convention) |
|---|---|---|---|
| Build_Main:2 | Tavern | none | Town Hall needs only the previous level. |
| Build_Main:3 | MG1, Market | none | Same. |
| Build_Market:1 | none | Tavern | Shared economy. |
| Build_Bank:1 | MG1 | Main L2 | Economy template. The MG1 gate was the Amplifier's, which moves to its own row. |
| Build_Resource_Depot:1 | Market | Market, Bank | Economy template. |
| Build_Resource_Depot_level_2:1 | T1, Converter | T1 | A horde needs only its own dwelling. The converter gate is not HoMM3 and not vanilla. |
| Build_Skeleton_Converter:1 | T1 | none | Specials have at most 1 base-level shared prerequisite. A dwelling is not one, and HoMM3 has no prerequisite. |
| Build_Tier_2:1 | T1 | none | Depth: T1->T2->T3->T5->T7 was 5 deep; vanilla is at most 4. T2 is a vanilla root in 5 of 6 cities, including Undead. |
| Build_Tier_4:2 | Bank | none | A dwelling upgrade needs only its own L1. |
| Build_Mother_Nature:1 (new) | n/a | MG L1 | Necromancy Amplifier <- MG1 (HoMM3). |
| Build_Mycelium_Roots:1 (new) | n/a | none | Cover of Darkness has no prerequisite (HoMM3). |
| other levels | as now | unchanged | Dwelling L1s keep HoMM3 flavour within 0-2 base prerequisites (T7 <- MG2 + T6 as in vanilla). Well of Souls <- MG3 is the vanilla Undead rule. Treasury <- Bank + Wall1. |

Tool edits:
- `FACTION_LEVEL_REQS["homm3_necropolis"]` gets the rows above.
- The common rows (Main, Market, Depot) are shared with the other faction files.
- buildOrders get the 2 new SIDs.
- Re-run the layout solver and the static validator. Fit: 36 levels in 45 cells; deepest dwelling chain 4.

**Levels without outside prerequisites: 19 of 34 before, 24 of 36 after** (vanilla 22-23).

## 3. Plugin work

| Hook | File | Game method | Risk |
|---|---|---|---|
| P0: town-building reader, shared with Inferno and Dungeon. | New `Homm3CityBuildingReader.cs` | `Homm3FactoryLogisticsEffects.TryBuildWorld` snapshot plus a `CountMarkets`-style scan (`:347`). Answers "side owns a `homm3_necropolis_city` with SID X constructed". | Low. |
| P3: Necromancy bonuses. Amplifier +0.05 (once per side); Soul Prison +0.10. | `Homm3SkeletalNecromancyProbe.cs`, next to the law branch (`~:264`, `NecropolisLawRank` `:380`) | After the bucket share and law amplifier are resolved, and only when the share is above 0: add the building terms through P0. Add the same terms to the display path so the hero card shows the real share. | Low. It is a pure arithmetic extension of a live, proven path. Cache the P0 result per day so the probe is not called per battle. |
| P4: Cover of Darkness. | New `Homm3NecropolisCoverOfDarknessRuntime.cs` | Side day-start hook: `GameSymbols.SwashbucklerGold.SideLogicTypeId/SideStartDayName`, the `PatchOwned` pattern in `Homm3FactoryLogisticsRuntime.cs:243-248`. For each enemy side and each Necropolis with this building: `FogOfWar.CloseAroundCenter(side, gateNode, 20, mapView)`, then `OpenObjectsVisibleNodes(side)`. | Medium. Open questions: (1) the `mapView` value for the surface vs underground level; (2) the AI must not "see through" the fog, so verify the AI reads the same fog grid; (3) multiplayer sync must run in deterministic side logic, not UI; (4) allied sides are excluded. Verify the method names against the live interop: the decompile is managed-era. |

Tooling:
- **Descriptions**:
  - explicit text for the two empty `cityBonusBanks` rows;
  - a converter sentence for the many-to-one Skeleton pairs;
  - a `graal_necropolis` template.
- **Overlay**: the new rows, the converter pairs and bans, and the graal side bonuses removed.
- **Visual map**: `building_layer_map.json` assigns the old Bank layer to the matching special, as the town-scene owner decides.

## 4. Owner decisions

1. **Economy slot vs special** (same fork as in Inferno and Dungeon). **Recommend restoring the plain Bank** and giving the Amplifier and Cover of Darkness their own rows. The other option is to move `Build_Bank` into the special's section and lose the Bank, as Fortress and Conflux did.
2. **Two "Necromancy Amplifier"s.** The building (+5%, exact HoMM3) and law #7 (+2/+4%) share a name and stack. **Recommend keeping both and renaming the law** (for example "Bone Conductors"). The building is the HoMM3 source; the law was a law-pass invention. Stacked maximum: 15% base + 5 + 4 + 10 (grail) = 34%. That is still below HoMM3's uncapped values after halving.
3. **Soul Prison strength.** Exact (+10% Necromancy plus the +100% growth convention) replaces +10 Defense / −50% enemy crit. **Recommend exact**, and add Gold later if playtests find it weak.
