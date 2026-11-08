# Broken / abandoned feature sweep — 2026-10-21

Static sweep (8 parallel lanes) of features that are likely broken on build 25672315 or were
abandoned because the engine side could not be traced. Read-only: nothing built, installed, or
launched; no Ghidra run. Evidence = current source, `GameSymbolsCurrent.g.cs`, installed `Core.zip`,
the 2026-10-21 12:49 `LogOutput.log` (adventure map + town + a few battles; no siege, no campaign,
no two-level map), and a late-build mono decomp at `.tmp/town_pick/hex_src/` (not pinned to 25672315).
Items marked ✔ were re-checked by the coordinator against the log / Core / decomp.

## Root causes (read this first)

1. **Remap refusals fail silently.** `GameSymbolsCurrent.g.cs` refuses 186 declarations; 130 were
   hit last session (✔ 130 `current scope REFUSED` log lines). Refused hints become sentinels, so the
   feature quietly does nothing. Rough split: ~52 owner-ambiguous literal groups (e.g. `"id"`, `"heroes"`,
   `"slots"`, `"heroFace"`) that exist on live types but span many owners — **fix by splitting the
   declarations per owner, no Ghidra**; ~24 member-ambiguous ("N golden vs M live, no native-body
   winner") and ~8 owner-type misses — **Ghidra decompile of the small candidate sets**. Any
   declaration added after the 10-03 remap is refused until it is regenerated.
2. **Native code dispatches on vanilla faction strings / slot names.** Custom `homm3_*` fractions fall
   through `switch (fraction)` and `<fraction>_...` resource paths without error (town #1, #2, #5).
   Worth a systematic grep of the mono decomp for `case "undead"` / `"_siege_elements"`-style keys.
3. **Ordinal guesses on event dispatchers.** Several `BattleEventLaws` dispatchers were remapped by
   ordinal and hook the wrong method (combat #1).
4. **Hard-coded obfuscated names outside GameSymbols** (`blc`, `qwn/qvl/qoc…`, `byu.pml`) and
   `nameof(...)` references (`BhBattleEnd.OnBtnExit`) that the live-interop ref validator cannot see.

## Likely broken now (highest user impact)

| # | Feature | Evidence | Fix path | Ghidra |
|---|---|---|---|---|
| 1 | **Unique building screens never open** for HoMM3 Necropolis (Bone Foundry), Dungeon (Lyceum), Inferno (Rebirth Shrine) | ✔ decomp `BhCityUIs.OpenUniversalBuild` switches only on `human/undead/nature/demon/unfrozen/dungeon`, no default; ✔ check-queue row 162 user Fail | Prefix mapping `homm3_*` → donor screen (`CityConvert`/`ArtifactChanger`/`ShrineOfRebirth`), mirror on `HideUniversalBuild` | HIGH to pin live successor |
| 2 | **Siege of HoMM3 towns: walls/towers invisible, castle decor falls back** | decomp `SentryDrawer`/`ObstacleDrawer` load `obstacles/<fraction>_siege_elements/…`, `BhActiveBattle` loads `battle_environment/castle/<fraction>_castle`; no plugin alias exists; overlay gives every custom town level-3 walls | ResManager path alias `homm3_X` → donor fraction; one live siege | MEDIUM |
| 3 | **Bulwark Runes gain nothing from damage** | ✔ log 3577/3586/3595 "damage read failed", 0 `corr damage`; `ObjectTookDamageDispatcher` ordinal-remapped `_44→_63` | Rebuild dispatcher map from `*EventArgs` ctor → raiser xrefs | HIGH |
| 4 | **Combat music never stops on battle exit** | ✔ log 30/649 `OnBtnExit` not found; live successor is `Method_Public_Void_PDM_0` (`bhlq`, VA 0x182208240), proven by index ordinal | Add GameSymbols pin, use in `Homm3GlobalCombatMusic` + `Homm3BattleRosterPrewarm` | none |
| 5 | **Captives / Hunting Grounds skill meter + Split Assembly HUD hidden** right after being shown | ✔ log 3404-3406: no-arg HUD refresh → "session hero null; meter hidden"; `TooltipHeroItemSessionHeroFields` refused | Pin field on `BhTooltipHeroItemView`; remember hero from the hero-arg path | LOW |
| 6 | **Dungeon Captives morale (Imperial Menagerie / Terror Mandate) always 0** | log 3574 `hero=?`; uses a cache whose builder hook didn't fire | Resolve via `startedTransferBattle.logicHero` like Hunting Grounds | LOW |
| 7 | **Quick-play hero details: custom portrait/spec/name not applied** | ✔ log 419/482 `HeroDetailsBind` refused / method not found; candidates `Method_{Public,Private}_Void_HeroConfig_0` | Owner-scoped pin (decide public vs private) | MEDIUM |
| 8 | **GameHub lobby faction popup never lists HoMM3 factions** | hard-coded `qwn/qvl/qoc/qnf/qpt/qow` all "method not found"; live list producer `ScFractionSelect.Method_Private_List_1_FractionLobbyAsset_PDM_0` | Move to GameSymbols with live pins | MEDIUM |
| 9 | **Underground view toggle not drawn on two-level maps** | `HomecomingLayerViewToggle` getters/setter refused (log 771-773) | Pin by body shape (2 `int()` getters, 1 `void(int)`) | MEDIUM |
| 10 | **Custom ability UI**: no Focus pips, no hire-preview ability cards | `AbilityViewBaseFocusMarkers`, `AbilityWrapperTryGetAbility`, `HireAbilityWrapperClone` refused | Ghidra-pin three small distinctive methods | HIGH |
| 11 | **Army-strip / garrison portraits** fall back to stand-in on refresh/pool | `UnitUiDataUnitMembers`, `*UnitSlots*` refused | Pin `"slots"` + unit field | MEDIUM |
| 12 | **Custom-biome ambient audio + fog-controller extension off** | log 265-275 | Pin tile-code / selector fields | MEDIUM |
| 13 | **Placed custom dwellings keep donor hire data** | `CustomDwellingHire.*` refused, "hire payload aliasing is skipped" | Pin hire world-object `Init` | MEDIUM |
| 14 | **Pre-RMG biome sanitize never runs** (over-limit custom map → Blitz in same process) | ✔ log 263; hard-coded `TypeByName("blc")` | Ghidra-pin live generator (golden `blc.GenerateMap` 0x1827DA790), remove literal | HIGH |
| 15 | **Town free-sweep camera** probably ignores the framing clone, while cursor pan is halved | decomp builds `SmoothSpline` once in `Awake`; plugin never calls `ResetSpline`; panScale 0.5 conflicts with "never limit camera" | Log live extremes, then `ResetSpline` or drop panScale | LOW |
| 16 | **AI battle/adventure hooks dead** (bridge parked since 10-03 anyway) | `BattleAiDecision.*` refused via junk aliases; adventure hero/party literals refused → weight bridge always fails closed; AI validators still pass on Golden-only text | Drop junk aliases, owner-qualify literals, repoint validators | MEDIUM (ScoreUnitTurn) |
| 17 | **HoMM3 unit SFX likely ignore game volume/mute** | own AudioSources at fixed 0.45, no mixer routing | Mute-SFX test; route through native SFX mixer group | HIGH (`SoundSetsPlayer`/`SoundMixersManager`) |
| 18 | **Attack VFX on owned rigs bloom at hip; `BhEffectHelper` setup never applied** | `Homm3MeshFx.cs:2012` `GetType()` on Il2Cpp proxy never matches | Use Il2Cpp class check; place at ProjectileEnd/Shield points | MEDIUM |
| 19 | **Rivulet Retreat may cost no Focus** | `dontUseEnergy: true` + `energyLevel: 1`; overlay never clears flag | Clear flag in overlay generator | none |

Lower: custom-map routing 406 warnings/session (refused post-remap key); terrain renderer "known-bad
rebuild" safety list empty (refused); analytics host guard native patch failed but logs "redirected";
`Canvas.set_sortingLayerName` span-wrapper throw (redundant write at `Plugin.cs:6394`); 13
`FIXME(steam: member absent)` disabled patches; misleading success logs (field-accessor "patched").

## Abandoned / parked because the engine couldn't be traced (Ghidra candidates)

| Feature | Blocker | Ghidra start point | Leverage |
|---|---|---|---|
| Custom projectile visuals (never worked on any build; flag off) | `BhProjectileController.Init/SetPositions` refused; launch site untraced | callers of `AbilityViewConfig.sir` / `HeroAbilityLevelConfig.sqx` getters; `BattleEffectSpawner.SpawnAttackEffect` | HIGH |
| Custom-law runtime (all 130 laws ship as native-data bonuses; 28 "candidate-runtime" in a stale doc) | counterattack owner side, morale roll, Focus grant/spend, cooldown gate, kill commit | `dxy.bate→edb.bcry`, morale-roll owner, `eir.cglw.bdwy`, `AddCooldownIfReady`/`eew` | MEDIUM-HIGH |
| True shove (`push_unit`) — replaced by teleport donor | presentation owner of mid-action reposition; `ehh.bdpe` early-outs | `egd.bdpz` jump table, `ehh.bdpe`, `UnitData.bfdi`, `emz` (Golden RVAs; re-pin first) | HIGH |
| Turncoats, pre-battle volley, counter-cast, real Borrowed Turn | out-of-turn attack, turn-queue mutation, cast cancel point | command execute (`cty.hsg` live hooked), logic-side turn queue, `CastAbilityEventArgs` producer | MEDIUM-HIGH |
| Battle Init vs Unit.Init ordering (Death March, Split Assembly, Strategem) | nesting unproven; `BattleUnitInit.Init` refused | battle `Init(Int32,TransferBattle,Boolean,Boolean)` + Unit.Init callers | HIGH |
| Custom passives/auras (Mammoth Defend, Yeti, Argali, Tower passives) | data can't express them | full `egd.bdpz` EMechType table + passive/aura owner | MEDIUM |
| Strongest-N hero carry / army carry between campaign missions | native writer of `StoryHubSave.heroesSaves` unknown | write xrefs to `heroesSaves` | HIGH |
| Seer hut quest types 1/2/8 (substituted) | which event re-evaluates `HeroStat` | `ECondition` evaluator + subscription | HIGH |
| Spell-granting buildings (Library, Aurora, Magic University, Order/Deity of Fire) | no traced "add spell" writer | `HeroMagics` mutators, mage-guild learn path | HIGH |
| Runtime resource spending (blocks any cost-based law/building, Freelancer's Guild) | earlier spend route crashed | `Resource.bggu–bggx`, `ResHeap.bggt`, construction charge `BuildingData.bgck` | HIGH |
| Castle Gate (substituted with gold) | — native `town_gate` object exists in Core ✔ | `ObjTownGate` visit / `ObjPortal` commit | HIGH |
| Market rates (Bulwark Fair) | single global `resources_exchange.json` table | its consumer in market trade | MEDIUM-HIGH |
| Custom construction laws (INTENTIONALLY_BLOCKED) | commit/debit ordering | `BhBuildingsManager` 0x181F6F340–0x181F6FD00 | HIGH |
| 30 faction-special buildings + Capitol/MG5 have no world slot | assumed to need authored native slot | decomp says runtime clone of a `BhBuildingSlot` before `Awake` should register; confirm live `Awake` 0x181F6F340 | MEDIUM |
| Map death fade (quarantined) | map-object removal methods refused | `fnd` removal overloads | HIGH |
| Adventure AI planner / lookahead; `ai_start_combat`; `ai_open_town` | empty bodies, opaque dispatch | `fvr.OnStartDay`, `fjg.Invoke`, `fkc` selector builders, `BhCityUIElement.OnCityOpenBtn` | HIGH |
| Grail/unique identity effects, mana buildings, Escape Tunnel | untraced apply paths | `graalType` switch, `manaFountains` apply, escape predicate | MEDIUM |
| Turn-queue portrait direct hook (trampoline recursion) | recursion cause unknown | `elq.beou` successor | MEDIUM |

**Not Ghidra-solvable (real engine absences):** boats/shipyards, war machines, new resource types.
**No-Ghidra quick win:** Dungeon Portal of Summoning — vanilla `unfrozen_city.json` already ships a
native `portalSummonings` / `Build_Portal_Summoning` section ✔; emit it for `homm3_dungeon`.
(Note: the native Universal switch routes `unfrozen` → PortalSummoning, so a `homm3_dungeon` row also
needs item #1's fraction mapping.)

## Ghidra setup state

**Superseded 2026-10-21: the shared labelled project now exists — see `docs/ghidra_oe.md`.**
The notes below describe the state at sweep time; the "plain literals absent" observation still holds,
but metadata-usage globals (TypeInfo/MethodInfo/StringLiteral) do decode with the v31 slot layout.

- No Ghidra project, `dump.cs`, `script.json` or `il2cpp.h` exists for 25672315; Il2CppDumper not
  installed; metadata v31 support unverified. GhidraMCP 2.0 is downloaded, not installed.
- Usable now: `artifacts/port_current/idx2_live_25672315/gen/native_addresses.tsv` (207k method VAs),
  `port_index.tsv` (interop ↔ native ↔ token ↔ signature), `tools/port_current/symbol_remap/native_body.py`.
- Stock install `GameAssembly.dll` has the same hash as Golden Era — analyse that copy.
- Plain string literals appear absent from `global-metadata.dat` (likely encrypted) → start from
  method VAs, not string xrefs, until that is recovered.
- Golden D477 GameAssembly is not on disk (rollback root gone/offloaded) → no golden↔live function diff.
- Proposed: one shared project under `V:\olden_port_work\ghidra\`, import with `-noanalysis`, a
  post-script that labels functions from `native_addresses.tsv` + `port_index.tsv` (base 0x180000000),
  per-target decompile with `-readOnly`; full auto-analysis only once, overnight, alone.
