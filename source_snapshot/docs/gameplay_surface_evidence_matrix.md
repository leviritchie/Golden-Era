# Gameplay Surface Evidence Matrix

This document summarizes `custom_factions/gameplay_surface_evidence_matrix.json`.
The JSON is the authored source of truth; this Markdown is the human review
companion.

## Purpose

The matrix is an incremental, falsifiable map of Olden Era gameplay surfaces.
It starts with custom law packet surfaces because those are the surfaces
currently blocking implementation. It can grow outward into broader gameplay
systems as evidence is gathered.

This does not authorize gameplay mutation. Runtime gameplay remains gated by
`custom_factions/custom_law_packet_proofs.json` and requires exact runtime proof.

## Policy

- No fallbacks.
- Fail closed.
- Static evidence can prepare diagnostics and source seams, but cannot promote
  gameplay.
- Runtime proof is required before any surface may allow gameplay mutation.
- Ambiguous generated candidates are not exact proof.
- Contradicting evidence blocks promotion until resolved.

## Seeded Packet Domains

- `vision`: object descriptor factory identities are live-metadata proven;
  native reveal mutation remains partial.
- `committed-damage`: `Unit.bbgw(...)` has a strong generated/live metadata
  identity, but final damage ordering and safe mutation semantics remain
  unproven.
- `construction`: building lookup is live-metadata proven; displayed cost,
  charged cost, eligibility, and build commit agreement remain unproven.
- `spell-cooldown`: effective/decrement/add-if-ready candidates are useful for
  diagnostics; the old absolute setter hypothesis is rejected.
- `counterattack`: exact listener candidates are partial; broad event dispatcher
  probing is rejected.
- `reward-result`: queue/resource mutation evidence exists, but committed reward
  choice and reward-apply binding remain unproven.
- `morale`: roll classification is partial; safe action queue mutation is
  missing.
- `battle-action`: action classification and formation geometry are partial;
  unit role classification now has a native config candidate path, but the
  unit-to-default-attack traversal is not proven.

## Packet Static Evidence Summary

| Packet | Static evidence level | Strongest static anchors | Remaining non-static blockers |
| --- | --- | --- | --- |
| `vision` | strong | `DataFogOfWar.bfri`, `MapMagics.bgca/bgcb`, `DataObject.bgdo`, `MapVisionObjectDesc` factories | reveal mutation semantics, side/rank context, map refresh |
| `committed-damage` | strong | `ObjectTookDamageEventArgs` payload fields, `Unit.bbgw(...)` damage candidate | final damage ordering, death cleanup ordering, safe mutation semantics |
| `construction` | strong | `BhBuildingsManager`, `BhUIBuildingSession`, `BhBuildingView`, `BuildingData.bgck` | displayed/charged cost agreement, commit ordering, non-hot hook placement |
| `spell-cooldown` | strong | `eew.bdmd/bdmg/bdmi`, `eex.Init/bdnj`, cast-gate candidates | actual spell-cast proof, cast gate ordering, spellbook UI synchronization |
| `counterattack` | strong-partial | `dxx.barb/bgl`, `ebv.bbwi/jsd/nhw`, `dxy` change-event factories | battle attack execute identity, attack resolver identity, counterattack correlation |
| `reward-result` | strong | `czy.vji(Hero,DataRewardSet)`, `DataRewardSets.bfus/bfut`, `Resource.bggu/bggv/bggw/bggx`, `ResHeap.bggt` | bridge ordinal reconciliation, committed player choice identity, idempotence |
| `morale` | strong-partial | `eep.bdhu(Unit,Random)`, `eep.grw(Unit,Random,Boolean)`, `eda.bcih`, `edb.bcsp/bcsq` event-dispatch calls | trigger/check semantics, action phase, safe action queue mutation |
| `battle-action` | strong-partial | `CastAbilityEventArgs` payload fields, `UnitLogicConfig` attack arrays, `AbilityLogicConfig` attack type, `CastDealerConfig.shootRange`, `EAttackType.Range/Shoot` | committed action identity, preview separation, first-volley state, unit-to-default-attack traversal |

`strong-partial` means the static identity evidence is strong for the known
surface cluster, but one or more packet-critical surfaces remain missing or
contradicted. It is not permission to implement gameplay.

## Current Surface Status

| Surface | Domain | Status | Allowed uses |
| --- | --- | --- | --- |
| `vision.objectDescriptorFactories` | vision | proven-live-metadata | diagnostic, readOnly, sourcePrepared |
| `vision.nativeRevealMutation` | vision | partial | diagnostic, sourcePrepared |
| `committedDamage.unitDamageApply` | committed-damage | proven-live-metadata | diagnostic, readOnly, sourcePrepared |
| `committedDamage.buffDebuffApplyQuery` | committed-damage | partial | diagnostic, readOnly, sourcePrepared |
| `construction.buildingLookup` | construction | proven-live-metadata | diagnostic, readOnly, sourcePrepared |
| `construction.displayedCost` | construction | partial | diagnostic, sourcePrepared |
| `construction.chargedCostAndCommit` | construction | partial | diagnostic, sourcePrepared |
| `spellCooldown.effectiveCooldownRead` | spell-cooldown | proven-live-metadata | diagnostic, readOnly, sourcePrepared |
| `spellCooldown.absoluteSetter` | spell-cooldown | rejected | none |
| `spellCooldown.castGateAndUiSync` | spell-cooldown | partial | diagnostic, sourcePrepared |
| `counterattack.listenerCandidates` | counterattack | partial | diagnostic, sourcePrepared |
| `counterattack.broadBattleEventDispatch` | counterattack | rejected | none |
| `rewardResult.queueAndResourceMutation` | reward-result | partial | diagnostic, readOnly, sourcePrepared |
| `rewardResult.applyRewardSet` | reward-result | partial | diagnostic |
| `morale.rollClassification` | morale | partial | diagnostic, sourcePrepared |
| `morale.eventDispatch` | morale | proven-static | diagnostic, sourcePrepared |
| `morale.actionQueueMutation` | morale | missing | none |
| `battleAction.actionClassification` | battle-action | partial | diagnostic, sourcePrepared |
| `battleAction.unitRoleClassifier` | battle-action | candidate | diagnostic, sourcePrepared |
| `battleAction.formationGeometry` | battle-action | partial | diagnostic, sourcePrepared |
| `battleAction.battleLifecycleState` | battle-action | candidate | diagnostic |
| `lawState.dataFractionLawRows` | law-state | proven-static | diagnostic, readOnly, sourcePrepared |
| `lawState.logicFractionLawQueries` | law-state | runtime-proven | diagnostic, readOnly, sourcePrepared |
| `spellbook.heroAndDataMagicCollections` | spellbook | proven-static | diagnostic, readOnly, sourcePrepared |
| `spellbook.castMagicEventPayloads` | spellbook | partial | diagnostic, sourcePrepared |
| `townBuilding.buildingCatalogAndDailyCount` | town-building | proven-static | diagnostic, readOnly, sourcePrepared |
| `ui.spellbookVisualOnlyBoundary` | ui | partial | diagnostic, sourcePrepared |
| `heroIdentity.heroCoreData` | hero-identity | proven-static | diagnostic, readOnly, sourcePrepared |
| `heroSkill.heroSkillRows` | hero-skill | proven-static | diagnostic, readOnly, sourcePrepared |
| `heroSkill.heroStatNativeFeatureFlags` | hero-skill | proven-static | diagnostic, readOnly, sourcePrepared |
| `abilityConfig.unitAbilityDefinitions` | ability-config | proven-static | diagnostic, readOnly, sourcePrepared |
| `buffStatus.buffConfigDefinitions` | buff-status | proven-static | diagnostic, readOnly, sourcePrepared |
| `sessionState.calendarAndNewDayFlags` | session-state | proven-static | diagnostic, readOnly, sourcePrepared |
| `battleLifecycle.battleLogicCoreState` | battle-lifecycle | proven-static | diagnostic, readOnly, sourcePrepared |
| `battleLifecycle.transferHeroUnitState` | battle-lifecycle | proven-static | diagnostic, readOnly, sourcePrepared |
| `partySquad.heroPartyUnits` | party-squad | proven-static | diagnostic, readOnly, sourcePrepared |
| `partySquad.neutralSquadRows` | party-squad | proven-static | diagnostic, readOnly, sourcePrepared |
| `itemArtifact.itemRowsAndContainers` | item-artifact | proven-static | diagnostic, readOnly, sourcePrepared |
| `adventureObject.objectRootCollections` | adventure-object | proven-static | diagnostic, readOnly, sourcePrepared |
| `adventureObject.resourceObjectsAndMines` | adventure-object | proven-static | diagnostic, readOnly, sourcePrepared |
| `townHire.hireAssortmentState` | town-hire | proven-static | diagnostic, readOnly, sourcePrepared |
| `market.marketItemAndExchangeState` | market | proven-static | diagnostic, readOnly, sourcePrepared |
| `mapArea.areaReachabilityState` | map-area | proven-static | diagnostic, readOnly, sourcePrepared |
| `mapTrigger.markerZoneState` | map-trigger | proven-static | diagnostic, readOnly, sourcePrepared |
| `calendarWeather.weatherAndWeekState` | calendar-weather | proven-static | diagnostic, readOnly, sourcePrepared |
| `turnMode.turnQueueState` | turn-mode | proven-static | diagnostic, readOnly, sourcePrepared |
| `teleportation.portalAndTownGateState` | teleportation | proven-static | diagnostic, readOnly, sourcePrepared |
| `adventureMovement.heroNodeAndMovePoints` | adventure-movement | proven-static | diagnostic, readOnly, sourcePrepared |
| `biome.nativeBiomeClassification` | biome | proven-static | diagnostic, readOnly, sourcePrepared |
| `energy.heroEnergyPools` | energy | proven-static | diagnostic, readOnly, sourcePrepared |
| `magicRules.schoolSidCostCounterSets` | magic-rules | proven-static | diagnostic, readOnly, sourcePrepared |
| `magicRules.magicConfigBattleWorldRows` | magic-rules | proven-static | diagnostic, readOnly, sourcePrepared |
| `heroAbility.heroAbilityLevelRows` | hero-ability | proven-static | diagnostic, readOnly, sourcePrepared |
| `luckMorale.distributionConfigs` | luck-morale | proven-static | diagnostic, readOnly, sourcePrepared |
| `damageForecast.damageEventAndUiParams` | damage-forecast | proven-static | diagnostic, readOnly, sourcePrepared |
| `corpseDeath.staticDeathCorpseSignals` | corpse-death | partial | diagnostic, sourcePrepared |
| `rewardConfig.rewardRowsAndConfig` | reward-config | proven-static | diagnostic, readOnly, sourcePrepared |
| `rewardConfig.rewardUnitContainers` | reward-config | proven-static | diagnostic, readOnly, sourcePrepared |
| `bonusSystem.bonusConfigCore` | bonus-system | proven-static | diagnostic, readOnly, sourcePrepared |
| `bonusSystem.mapAndPickedBonuses` | bonus-system | proven-static | diagnostic, readOnly, sourcePrepared |
| `objectProperty.propertyRowsAndActions` | object-property | proven-static | diagnostic, readOnly, sourcePrepared |
| `bonusSystem.bonusBankBuildings` | bonus-system | proven-static | diagnostic, readOnly, sourcePrepared |
| `townService.tavernAndPrisonHeroSources` | town-service | partial | diagnostic, readOnly, sourcePrepared |
| `adventureService.garrisonOutpostDefenseRows` | adventure-service | proven-static | diagnostic, readOnly, sourcePrepared |
| `townService.trainingAndRebirthServices` | town-service | proven-static | diagnostic, readOnly, sourcePrepared |
| `townService.magicManaIntelConverterRoots` | town-service | partial | diagnostic, readOnly, sourcePrepared |
| `artifactService.artifactChangerAndMarket` | artifact-service | proven-static | diagnostic, readOnly, sourcePrepared |
| `eventBank.bankAndEventBankServices` | event-bank | proven-static | diagnostic, readOnly, sourcePrepared |
| `battleOutcome.resultAndLoserRows` | battle-outcome | proven-static | diagnostic, readOnly, sourcePrepared |
| `battleOutcome.startTransferContext` | battle-outcome | proven-static | diagnostic, readOnly, sourcePrepared |
| `diplomacy.neutralNegotiationConfig` | diplomacy | proven-static | diagnostic, readOnly, sourcePrepared |
| `necromancy.necromancyConfigAndHeroFlags` | necromancy | proven-static | diagnostic, readOnly, sourcePrepared |
| `scenarioState.winConditionsAndCampaignCounters` | scenario-state | proven-static | diagnostic, readOnly, sourcePrepared |
| `scenarioState.heroStartSquadConfig` | scenario-state | proven-static | diagnostic, readOnly, sourcePrepared |
| `configTaxonomy.factionAndLawConfigTree` | config-taxonomy | proven-static | diagnostic, readOnly, sourcePrepared |
| `configTaxonomy.heroConfigBaseline` | config-taxonomy | proven-static | diagnostic, readOnly, sourcePrepared |
| `configTaxonomy.unitConfigStatsViewCost` | config-taxonomy | proven-static | diagnostic, readOnly, sourcePrepared |
| `configTaxonomy.buildingConfigTaxonomy` | config-taxonomy | proven-static | diagnostic, readOnly, sourcePrepared |
| `configTaxonomy.objectConfigTaxonomy` | config-taxonomy | proven-static | diagnostic, readOnly, sourcePrepared |
| `configTaxonomy.sharedStatCostRows` | config-taxonomy | proven-static | diagnostic, readOnly, sourcePrepared |
| `eventPayload.baseBattleEventFields` | event-payload | proven-static | diagnostic, readOnly, sourcePrepared |
| `eventPayload.damageAndObjectLifecyclePayloads` | event-payload | proven-static | diagnostic, readOnly, sourcePrepared |
| `eventPayload.castAbilityAndMagicPayloads` | event-payload | proven-static | diagnostic, readOnly, sourcePrepared |
| `eventPayload.buffStatusPayloads` | event-payload | proven-static | diagnostic, readOnly, sourcePrepared |
| `eventPayload.sideEnergyStartOutcomePayloads` | event-payload | proven-static | diagnostic, readOnly, sourcePrepared |
| `battleActor.casterSourceReceiverInterfaces` | battle-actor | proven-static | diagnostic, readOnly, sourcePrepared |
| `battleActor.fieldObjectAndUnitIdentity` | battle-actor | proven-static | diagnostic, readOnly, sourcePrepared |
| `battleActor.sideContextAndHeroStats` | battle-actor | proven-static | diagnostic, readOnly, sourcePrepared |
| `battleActor.buffRuntimeObjects` | battle-actor | proven-static | diagnostic, readOnly, sourcePrepared |

## June 19 law-state runtime note

`lawState.logicFractionLawQueries` is runtime-proven only for exact graph/query reachability. The native path `dsu -> dto -> dtj -> Logic.FractionLaws` was reached, `get_field_Private_DataFractionLaws_0` resolved the backing `DataFractionLaws`, and exact `xpk/xpl` surfaces were reached. The startup seed `fraction_law_homm3_castle_6` rank 1 returned `xpk/canApply=false`, so arbitrary activation through `xpl` is not proven and must not be forced. Future proof should use a legal native state: a player-selected law or a scenario with valid law points/prerequisites where `xpk=true`.
## Rejected Surfaces

`spellCooldown.absoluteSetter` is rejected. The old `eew.bdmh(Int32)` setter
hypothesis has ordinal-mismatch evidence and must not be used for gameplay.

`counterattack.broadBattleEventDispatch` is rejected. Broad BattleEventArgs
dispatcher probing caused a crash-risk path and must not be reused as a generic
surface discovery strategy.

## Growth Path

After packet surfaces, grow the matrix in this order:

1. Resource and economy mutation surfaces.
2. Buff, debuff, status, and ability surfaces.
3. Unit identity, unit family, role, tier, and faction classification.
4. Hero identity, skill, spellbook, and town ownership surfaces.
5. Battle lifecycle, round/day/session state, and persistence surfaces.
6. UI-only surfaces, explicitly marked non-gameplay unless backed by gameplay
   state proof.

## Broad Evidence Rings

### `packet-adjacent-core-state`

Status: source-prepared static only.

This is the first expansion beyond packet rows. It maps core gameplay state that
multiple law packets depend on, without promoting gameplay behavior:

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `economy.resourceDataPrimitives` | economy | proven-static | `Resource.bggu/bggv/bggw/bggx` |
| `economy.sideResourceHeap` | economy | proven-static | `Side.res`, `ResHeap.gold/wood/ore/gemstones/crystals/mercury/dust/graal/starDust`, `ResHeap.bggt` |
| `buffStatus.buffDebuffSidSurfaces` | buff-status | candidate | `dzv.bbgf/bbfn/bbfl` dossier and symbol-map candidates |
| `unitIdentity.configFactionTier` | unit-identity | proven-static | `UnitLogicConfig.baseSid/upgradeSid/tier/fraction/leaveCorpse/attack arrays` |
| `unitIdentity.battleUnitLogicConfigBridge` | unit-identity | proven-static | `Unit.chjp`, `Unit.beye()`, `Unit.Init(...,_configSid,...)` |
| `heroOwnership.sideCoreState` | hero-ownership | proven-static | `Side.res/fogData/fractionLaws/sideMagics/sideHeroes/sideObjects/fraction/startCityId` |
| `heroOwnership.cityHeroSlots` | hero-ownership | proven-static | `ObjCity.garnisonHeroId/visitorHeroId/visitParty` |
| `heroOwnership.dataRootCollections` | hero-ownership | proven-static | `Data.sides/heroes/squads/randomMagicsPool/randomSkillsPool/enableFactionLaws` |
| `battleLifecycle.baseEventBoundary` | battle-lifecycle | partial | `BattleEventArgs`, `edb` dispatch family, rejected broad dispatcher evidence |
| `ui.constructionHotPathDiagnosticsRejected` | ui | rejected | construction UI crash-history documentation |

Runtime boundary: these surfaces improve planning and diagnostics only. They do
not authorize gameplay mutation. Packet gates and runtime proof remain required.

### `state-and-ui-second-ring`

Status: source-prepared static only.

This second expansion maps native state containers and UI boundaries that sit
directly next to packet surfaces. It is meant to narrow future implementation
seams without treating static declarations as gameplay proof:

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `lawState.dataFractionLawRows` | law-state | proven-static | `DataFractionLaw.sid/line/group/level/wasApplied`, `DataFractionLaws.fraction/list/spentPoints` |
| `lawState.logicFractionLawQueries` | law-state | candidate | `FractionLaws.Init/xph/xpi/xpk/xpl/xpm/xpn/xpo` query-like declarations |
| `spellbook.heroAndDataMagicCollections` | spellbook | proven-static | `HeroMagics`, `DataMagics`, `SideMagics`, `MagicData` learned-spell collections |
| `spellbook.castMagicEventPayloads` | spellbook | partial | `CastMagicEventArgs`, `ChangeMagicEventArgs.magicIndex` payload candidates |
| `townBuilding.buildingCatalogAndDailyCount` | town-building | proven-static | `BuildingsData` building lists and `todaysConstructionsCount`, `BuildingData.sid/level/isConstructed/citySid/bgck` |
| `ui.spellbookVisualOnlyBoundary` | ui | partial | `BhSpellMiniView` and `BhBookFrameView` visual fields |

Runtime boundary: the new rows are source-prepared planning evidence only. Law
state, spellbook data, and town building state still need runtime correlation
before any law packet may mutate gameplay.

### `hero-skill-ability-session-third-ring`

Status: source-prepared static only.

This third expansion maps hero, skill, ability, buff, session calendar, and
battle-transfer state. These are high-value native seams for replacing custom
law behavior with donor/native effects, but they remain static declarations
until a packet proves runtime ordering and object ownership:

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `heroIdentity.heroCoreData` | hero-identity | proven-static | `Hero.id/sideId/configSid/status/currentLevel/currentExp/mana/party/skills/buffs/magics/specialization/subClasses/pickedBonuses/mapMagics` |
| `heroSkill.heroSkillRows` | hero-skill | proven-static | `HeroSkills.list/bfyk/bfyl`, `HeroSkill.sid/level/wasApplied/subSkills` |
| `heroSkill.heroStatNativeFeatureFlags` | hero-skill | proven-static | `HeroStat` native stat and feature fields including `magicCdBonus`, necromancy, diplomacy, tactics, movement, final damage/healing/mana cost, morale, luck, and cast-limit flags |
| `abilityConfig.unitAbilityDefinitions` | ability-config | proven-static | `UnitLogicConfig` ability/passive/attack arrays, `AbilityLogicConfig` cooldown/charges/energy/dealer/attack-type/action-cost fields, `EAbilityType` |
| `buffStatus.buffConfigDefinitions` | buff-status | proven-static | `BuffConfigBase`, `BuffConfig`, `UnitPassiveConfig`, `UnitConditionalPassiveConfig`, `GlobalUnitBuffConfig` |
| `sessionState.calendarAndNewDayFlags` | session-state | proven-static | `Data.daysInGameCount/day/week/month/startingNewDay`, feature gates, random pools |
| `battleLifecycle.battleLogicCoreState` | battle-lifecycle | proven-static | `eep` battle logic fields/accessors for random source, transfer battles, status, callbacks, and unit/action helpers |
| `battleLifecycle.transferHeroUnitState` | battle-lifecycle | proven-static | `TransferHero.configId/mana/level/heroStat/heroMagics`, `TransferHero.becc/becd(Hero)`, `TransferUnit.configSid/stacks/slotPos/becr()` |

Runtime boundary: these rows identify native data and config surfaces. They do
not prove that a given hook sees the canonical object, nor that mutating one of
these fields survives native recalculation or battle-transfer cloning.

### `adventure-party-item-economy-fourth-ring`

Status: source-prepared static only.

This fourth expansion maps adventure-mode ownership and economy-adjacent state:
party stacks, neutral squads, item/artifact containers, map object roots,
resource objects, recruit assortments, and market rows. These surfaces are
important for making faction laws native-friendly outside combat, but they do
not prove committed interaction or purchase timing:

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `partySquad.heroPartyUnits` | party-squad | proven-static | `DataParty.units`, `Unit.sid/stacks/slotPos/bgkt()` |
| `partySquad.neutralSquadRows` | party-squad | proven-static | `DataSquads.list/freeId`, `DataSquad.configSid/id/node/units/reactionType`, `DataSquadUnit.sid/amount/bfvf()` |
| `itemArtifact.itemRowsAndContainers` | item-artifact | proven-static | `DataItem.id/level/configSid/slotId`, `DataItems.list/freeId`, `DataItemsContainer` slots/locks, `ItemConfig` value/rarity/bonuses/set/slot data |
| `adventureObject.objectRootCollections` | adventure-object | proven-static | `DataObjects` category lists, `DataObject.idMapObject/sidConfig/released/ownerSide/garnisonParty/rewardSet/sideScoutings` |
| `adventureObject.resourceObjectsAndMines` | adventure-object | proven-static | `ObjRes.resourcesList`, `ObjRes.bgdk()`, `ObjResMine.bgdk()`, common `DataObject` owner/reward/released fields |
| `townHire.hireAssortmentState` | town-hire | proven-static | `ObjHire`, `ObjRandomHire`, `BuildingHire`, `DataHireAssortment`, `HiredUnitSet` recruit and growth rows |
| `market.marketItemAndExchangeState` | market | proven-static | `BuildingMarket`, `ObjMarket`, `DataMarketItem.sid/level/bfug/bfuh/bfui/bfuj` |

Runtime boundary: these rows classify source state. Law behavior still requires
proof that the hook sees committed object interaction, recruit purchase, market
transaction, reward selection, or battle-transfer state rather than preview or
spawn data.

### `world-session-movement-fifth-ring`

Status: source-prepared static only.

This fifth expansion maps world/session context: area reachability, trigger
markers, weather/week state, turn queue state, teleportation rows, hero movement
state, and biome/native-biome classification. These surfaces are necessary for
laws that care about location, day/week timing, map reachability, and native
terrain, but they still do not prove gameplay ordering:

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `mapArea.areaReachabilityState` | map-area | proven-static | `DataArea.id/rootNode/nodes/biome/neighbors/objectsByType/pickableObjectsValuesLeft/dataSideReachable`, `DataAreaObjects`, `DataAreas`, `DataSideReachableAreas` |
| `mapTrigger.markerZoneState` | map-trigger | proven-static | `DataMarker.id/allNodes/isReleased/isDelete/isActive/properties`, `DataMarkers.list` |
| `calendarWeather.weatherAndWeekState` | calendar-weather | proven-static | `DataWeather.index`, `Week.sid/rollChance/isMonth`, `Weeks.currentWeekSid/isMonthWeek/enabled`, `WeatherConfig`, `WeekConfig.buffSid`, `WeeksInfoConfig` |
| `turnMode.turnQueueState` | turn-mode | proven-static | `DataTurnMode.turnPhase/turnMode/sidesQueue/currentSideIndex/updateSidesQueue/nextMode`, `ETurnPhase`, `ETurnQueue` |
| `teleportation.portalAndTownGateState` | teleportation | proven-static | `ObjPortal.outPortalId/isActive/daysLeftToDestroy/garrison fields`, `ObjTownGate`, `BuildingPortalSummoning.counter/dataHireAssortment` |
| `adventureMovement.heroNodeAndMovePoints` | adventure-movement | proven-static | `Hero.node/worldMovePoints/lastDayUseMapMagic`, `DataArea.nodes/neighbors/dataSideReachable` |
| `biome.nativeBiomeClassification` | biome | proven-static | `DataArea.biome`, `BiomesInfo.fractionsByBiome`, `EBonusBiomeType`, `Hero.unitsNativeBiome`, `UnitLogicConfig.nativeBiome/fraction` |

Runtime boundary: these rows provide static world context only. Movement commit,
trigger firing, teleport use, day/week rollover, current-side transition, and
native biome bonus application remain separate runtime-ordering questions.

### `battle-special-mechanics-sixth-ring`

Status: source-prepared static only.

This sixth expansion maps specialized battle and spell mechanics that can
anchor native-friendly law designs: typed energy pools, magic school/SID/cost
and counter sets, spell config rows, hero ability levels, luck/morale
distributions, damage payloads, and limited corpse/death signals.

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `energy.heroEnergyPools` | energy | proven-static | `DataEnergy.typeEnergy/value`, `EnergyEnablesSet`, `EnergyEnableStat`, `EnergyValuesSet`, `EnergyValueStat`, `TypeEnergy` |
| `magicRules.schoolSidCostCounterSets` | magic-rules | proven-static | `MagicSchoolSet/Stat`, `MagicSidSet/Stat`, `MagicCostSchoolSet`, `MagicCostSidSet`, `MagicCounterSet`, `MagicPerRankSet`, `MagicPerSchoolStat` |
| `magicRules.magicConfigBattleWorldRows` | magic-rules | proven-static | `MagicConfig` metadata/cost/school rows, `BattleMagicConfig`, `WorldMagicConfig`, `BuildingMagicGuild`, `ObjMagicMine` |
| `heroAbility.heroAbilityLevelRows` | hero-ability | proven-static | `HeroAbilityConfig`, `HeroAbilityInfo`, `HeroAbilityLevelConfig` cooldown/charges/energy/casts/dealer/action fields |
| `luckMorale.distributionConfigs` | luck-morale | proven-static | `LuckDistributionConfig.distribution`, `MoralDistributionConfig.distribution`, `UnitLogicConfig` distribution SIDs, `HeroStat.luck/moral` |
| `damageForecast.damageEventAndUiParams` | damage-forecast | proven-static | `ObjectTookDamageEventArgs` committed-damage fields, `DamageUiParams` forecast-like fields |
| `corpseDeath.staticDeathCorpseSignals` | corpse-death | partial | `UnitLogicConfig.leaveCorpse`, `ObjectTookDamageEventArgs.stacksDestroyed/immuneToDamage/fromMech`; no dedicated corpse economy row identified yet |

Runtime boundary: these rows identify native config/data/event seams only.
Resource generation, spell casting, ability ownership/cooldowns, roll triggers,
committed damage ordering, and corpse economy storage remain runtime proof
questions.

### `reward-property-bonus-seventh-ring`

Status: source-prepared static only.

This seventh expansion maps reward rows and configs, unit reward containers,
generic bonus configs/upgrades/enums, map and picked bonus storage, object
property/action rows, hero action bonus configs, and bonus-bank building roots.
These are central to converting custom law ideas into donor/native effects, but
they do not prove when those effects apply:

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `rewardConfig.rewardRowsAndConfig` | reward-config | proven-static | `DataReward`, `DataRewardSet`, `DataRewardSets`, `RewardConfig`, `RewardSetConfig`, reward type/apply enums |
| `rewardConfig.rewardUnitContainers` | reward-config | proven-static | `RewardUnit.sid/amount`, `RewardUnitsContainer.unitsArr/saq(Predicate[])` |
| `bonusSystem.bonusConfigCore` | bonus-system | proven-static | `BonusConfig.type/actionArea/receiver/fraction/parameters/biomeType/battleType/receiverRole/upgrade`, `BonusUpgrade`, `BonusOverridenParameter`, bonus enums |
| `bonusSystem.mapAndPickedBonuses` | bonus-system | proven-static | `MapBonus`, `MapBonuses`, `MapBonusConfig`, `PickedBonuses`, `DataSaveBonuses` |
| `objectProperty.propertyRowsAndActions` | object-property | proven-static | `DataProperty`, `PropertyActions`, `PropertiesActions`, `HeroActionBonusConfig` action/condition/bonus rows |
| `bonusSystem.bonusBankBuildings` | bonus-system | proven-static | `BuildingBonusBank`, `BuildingHeroBonusBank`, `BuildingCityBonusBank`, hero/city bonus bank configs |

Runtime boundary: these rows classify data and candidate donor surfaces only.
Reward choice commitment, bonus aggregation, script/property action execution,
and bonus-bank application still need runtime or focused method-dossier proof.

### `town-service-special-object-eighth-ring`

Status: source-prepared static only.

This eighth expansion maps town and special-object service roots. Some surfaces
have explicit payload fields, while others are deliberately thinner subclass
roots that need focused dossiers before they can support law design:

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `townService.tavernAndPrisonHeroSources` | town-service | partial | `BuildingTavern`, `ObjTavern`, `ObjPrison.heroSid`, tavern configs |
| `adventureService.garrisonOutpostDefenseRows` | adventure-service | proven-static | `ObjGarrison`, `ObjOutpost.garrisonStartValue/garrisonWeeklyIncrementBonus/customStacks` |
| `townService.trainingAndRebirthServices` | town-service | proven-static | `BuildingTrainingRange.heroId/stat/stateTraining`, `TrainingStat`, training config costs, `BuildingShrineOfRebirth.rebornHeroes`, rebirth config cost/level step |
| `townService.magicManaIntelConverterRoots` | town-service | partial | `BuildingManaFountain`, `BuildingIntelligence`, `BuildingUnitsConverter`, `BuildingMyceliumRoots` subclass roots only |
| `artifactService.artifactChangerAndMarket` | artifact-service | proven-static | `BuildingArtifactChanger`, `BuildingArtifactMarket.itemMarketPool`, artifact changer config costs, artifact market purchase/sell charges and rarity counts |
| `eventBank.bankAndEventBankServices` | event-bank | proven-static | `BuildingBank.wasApplied`, `BuildingBankConfig.bonuses`, `ObjEventBank.visitorsList`, `ObjEventBankConfig` variants/reroll/reset/visit fields |

Runtime boundary: these rows classify service roots and payload candidates only.
Hero hire/rescue, garrison combat transfer, training/rebirth purchase,
unit conversion, artifact transactions, bank application, event-bank variant
selection, and one-shot idempotence remain unproven.

### `battle-outcome-strategy-ninth-ring`

Status: source-prepared static only.

This ninth expansion maps battle outcome and strategic-resolution state:
result/loser rows, battle start/transfer context, diplomacy/neutral negotiation
configuration, necromancy configuration and hero flags, scenario win-condition
state, campaign counters, and starting squad config.

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `battleOutcome.resultAndLoserRows` | battle-outcome | proven-static | `BattleResultInfo.winnerIndex/losers/isShowResultsWindow`, `BattleResultLoserInfo.loserIndex/loserStatus`, `EBattleResult`, `EscapeSideEventArgs.side` |
| `battleOutcome.startTransferContext` | battle-outcome | proven-static | `StartBattleEventArgs.battleLogic`, `TransferBattle` battle type/arena/weather/seed/sides/controller/played/win-condition fields, battle phase/type enums, autobattle mode flag |
| `diplomacy.neutralNegotiationConfig` | diplomacy | proven-static | `DiplomacyInfoConfig` cost/points/reaction/stat/level/value-chance fields, `DiplomacyValueChancePair`, neutral squad diplomacy flags, HeroStat diplomacy modifiers |
| `necromancy.necromancyConfigAndHeroFlags` | necromancy | proven-static | `NecromancyConfig.value/valueRestore/blockNecromancyType`, HeroStat necromancy enable and modifier fields |
| `scenarioState.winConditionsAndCampaignCounters` | scenario-state | proven-static | `WinConditionData`, `WinConditionsData`, `Data.winConditionsData/campaignCounters/startInfo/restartInfo` |
| `scenarioState.heroStartSquadConfig` | scenario-state | proven-static | `HeroStartSquadUnitConfig.sid/min/max`, `Data.startInfo/restartInfo` |

Runtime boundary: these rows classify outcome and strategy state only.
Post-battle commit, escape/surrender finality, diplomacy acceptance,
necromancy raised-unit application, scenario evaluation, campaign counter
mutation, and start-party application remain unproven.

### `config-taxonomy-tenth-ring`

Status: source-prepared static only.

This tenth expansion maps authored config taxonomy that anchors rows used by
law overlays, donor effects, unit-family targeting, building identity, object
rewards, and shared stat/cost primitives.

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `configTaxonomy.factionAndLawConfigTree` | config-taxonomy | proven-static | `FractionConfig`, `FractionLawConfig`, `FractionLawParameter`, `FractionLawsLine`, `FractionLawsGroup` |
| `configTaxonomy.heroConfigBaseline` | config-taxonomy | proven-static | `HeroConfig` |
| `configTaxonomy.unitConfigStatsViewCost` | config-taxonomy | proven-static | `UnitLogicConfig`, `UnitViewConfig`, `UnitStat`, `UnitCost`, `UnitSetConfig` |
| `configTaxonomy.buildingConfigTaxonomy` | config-taxonomy | proven-static | `BuildingConfigBase`, construction rows, settings rows, ban rows |
| `configTaxonomy.objectConfigTaxonomy` | config-taxonomy | proven-static | `ObjConfigBase`, `ObjectConfigs`, `ObjVariantConfig` |
| `configTaxonomy.sharedStatCostRows` | config-taxonomy | proven-static | `ResNameAndCost`, `ArtifactCost`, `EStatType`, `StatOverrideConfig`, `MimicStatConfig`, `HeroStatsLimitsConfig`, `HeroStatsRollConfig` |

Runtime boundary: these rows prove authored config identity only. They do not
authorize gameplay mutation. Config initialization, overlay parity, native
bonus aggregation, stat recomputation, cost charging, object interaction
commit, and build commit remain separate proof questions.

### `event-payload-eleventh-ring`

Status: source-prepared static only.

This eleventh expansion maps battle event payload taxonomy. It exists to make
future probes narrower and falsifiable: broad base-event dispatch remains
rejected, but exact payload classes can be used as dossier/probe targets.

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `eventPayload.baseBattleEventFields` | event-payload | proven-static | `BattleEventArgs.target/roundNumber` |
| `eventPayload.damageAndObjectLifecyclePayloads` | event-payload | proven-static | `ObjectTookDamageEventArgs`, `ObjectDestroyedEventArgs`, `ObjectSpawnedEventArgs`, `UnitRevivedEventArgs` |
| `eventPayload.castAbilityAndMagicPayloads` | event-payload | proven-static | `CastAbilityEventArgs`, `ChangeAbilityEventArgs`, `CastMagicEventArgs`, `ChangeMagicEventArgs` |
| `eventPayload.buffStatusPayloads` | event-payload | proven-static | `BuffEventArgs`, `SideBuffEventArgs` |
| `eventPayload.sideEnergyStartOutcomePayloads` | event-payload | proven-static | `EnergyUpdateEventArgs`, `EnergyUpdatedByMechEventArgs`, `StartBattleEventArgs`, `EscapeSideEventArgs` |

Runtime boundary: these rows prove payload fields only. They do not authorize
dispatcher hooks or gameplay mutation. Committed phase, preview separation,
event ordering, generated runtime identity, and Harmony safety remain separate
proof questions.

### `battle-actor-source-twelfth-ring`

Status: source-prepared static only.

This twelfth expansion maps the actor/source objects referenced by battle event
payloads. It connects payload fields to concrete static taxonomy without
claiming committed action timing or mutation safety.

| Surface | Domain | Status | Static evidence |
| --- | --- | --- | --- |
| `battleActor.casterSourceReceiverInterfaces` | battle-actor | proven-static | `eab`, `eac`, `eaf`, `dzx`, `eaa` |
| `battleActor.fieldObjectAndUnitIdentity` | battle-actor | proven-static | `FieldObject`, `ede`, `Unit`, `edk`, `dzr` |
| `battleActor.sideContextAndHeroStats` | battle-actor | proven-static | `eir` side context, `TransferSide`, `eex`, `HeroStat` snapshot fields, side event handlers |
| `battleActor.buffRuntimeObjects` | battle-actor | proven-static | `dzt`, `eit` runtime buff objects |

Runtime boundary: these rows classify payload object types only. They do not
authorize direct mutation, broad event hooks, or treating every actor interface
as a `Unit`. Concrete implementor identity, event ordering, live object
validity, HeroStat snapshot selection, and buff apply/remove/query semantics
remain separate proof questions.


## Battle Law-Owner Staged Proof Boundary

June 20 runtime testing showed that `TransferSide` ownership is not equivalent
to `Data.Side` law ownership. Any counterattack, morale, or battle-action
mutation must now prove these stages separately before it can be described as
ready:

1. `object-to-battle-side`: the packet object, `FieldObject`, or `Unit` resolves
   to an exact `Hex.Session.Battle.TransferSide` without broad member sweeps.
2. `battle-side-to-data-side`: that `TransferSide` resolves to the owning
   `Hex.Session.Data.Side` through a current-build exact side-index or owner
   chain. Stale side-index aliases are not accepted without proof.
3. `data-side-to-active-law-rank`: the same packet context resolves faction SID,
   law SID/index, and active rank from the owning `Data.Side`.
4. `mutation-consumes-active-rank`: the mutation log includes the packet, owner
   side, law SID/index, active rank, and effect amount for the same event.

The validator enforces this as `proofBoundaryChains.battleLawOwnerToMutation`.
Affected packet evidence must keep the staged blockers until runtime evidence
proves the stage. This is deliberately stricter than the earlier checklist so a
future fix cannot collapse ownership, law/rank resolution, and mutation into one
assumed surface.

## Static Gap Triage

The matrix currently has strong static identity coverage for most adjacent
state, but the remaining blockers are not evenly distributed. They should be
handled in this order:

1. Mutation timing surfaces: `construction.chargedCostAndCommit`,
   `rewardResult.applyRewardSet`, `rewardResult.queueAndResourceMutation`,
   `spellCooldown.castGateAndUiSync`, and `vision.nativeRevealMutation`.
   Static work should focus on exact commit/apply call sites and caller chains,
   not UI preview rows.
2. Battle correlation surfaces: `counterattack.listenerCandidates`,
   `battleAction.actionClassification`, `battleAction.formationGeometry`,
   `battleLifecycle.baseEventBoundary`, and
   `committedDamage.buffDebuffApplyQuery`. Static work should connect event
   payloads to committed damage/action order without reintroducing broad event
   dispatcher probing.
3. Action-insertion surfaces: `morale.rollClassification` and
   `morale.actionQueueMutation`. Static work should find the native extra-action
   insertion/removal path before any gameplay mutation is attempted.
4. Classifier-only surfaces: `battleAction.unitRoleClassifier`,
   `battleAction.battleLifecycleState`, `buffStatus.buffDebuffSidSurfaces`,
   and `lawState.logicFractionLawQueries`. Static work can promote these only
   when generated/runtime candidates or exact caller evidence remove ambiguity.
5. Service roots: `townService.tavernAndPrisonHeroSources`,
   `townService.magicManaIntelConverterRoots`, `corpseDeath.staticDeathCorpseSignals`,
   `spellbook.castMagicEventPayloads`, and
   `ui.spellbookVisualOnlyBoundary`. Static work should keep these as
   source-prepared roots unless a law packet specifically needs them.

Do not promote any of these rows to gameplay mutation from static evidence
alone. The purpose of this triage is to choose narrow decomp dossiers and
runtime probes, not to bypass runtime gates.

### June 19 live metadata note: `committedDamage.buffDebuffApplyQuery`

Live bridge metadata resolved `dzv.bbgf` to a full generated signature candidate, but the runtime callable ordinal was `54` while the decomp ordinal supplied to the resolver was `38`. This is useful source-prepared metadata for exact diagnostics only. It does not authorize gameplay mutation because receiver identity, status SID semantics, duration/stack behavior, ordering relative to committed damage, and law-owner side correlation are still unproven.

Evidence artifacts:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/live_bridge_proofs/2026-06-19_dzv_bbgf_live_resolve.json`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/live_bridge_proofs/2026-06-19_dzv_method_signatures.json`

## Validation

Refresh the full gameplay-surface static artifact set after a decomp or patch
update:

```powershell
python tools\release_port\refresh_gameplay_surface_evidence_artifacts.py
```

This runs matrix enrichment, weak dossier generation, matrix validation, and
weak dossier index validation in order. It intentionally runs enrichment twice:
first from law-surface dossiers, then again after weak dossiers exist so exact
weak-dossier targets can be reconciled with generated interop metadata. It does
not run the game or prove runtime behavior.

Refresh weak-surface planning and conservative runtime candidate attachments:

```powershell
python tools\release_port\enrich_gameplay_surface_evidence_matrix.py --write-matrix
```

Candidate boundaries:

- Law-surface dossier candidates come from exact symbol-prefix or exact
  type/method token evidence in `law_surface_dossiers.json`.
- Weak-dossier candidates come from exact focused dossier targets reconciled
  against `runtime_interop_map.json`.
- Weak method candidates require either an exact generated/runtime method name
  or decomp callable ordinal plus signature shape. Signature-only weak method
  matching is deliberately rejected because it can select the wrong generated
  method when several methods share parameter shape.
- Type-only weak candidates prove generated type metadata exists. They do not
  prove a callable method, runtime reachability, or hook safety.

Run:

```powershell
python tools\release_port\validate_gameplay_surface_evidence_matrix.py
```

The validator also runs as part of:

```powershell
python tools\release_port\check_custom_law_no_compromise_static.py
```

The weak-surface dossier plan is regenerated with:

```powershell
python tools\release_port\check_custom_law_no_compromise_static.py --write-reports
```

Focused static dossiers for weak surfaces can also be regenerated directly:

```powershell
python tools\release_port\build_gameplay_surface_weak_dossiers.py
```

This writes an index to `docs/gameplay_surface_weak_dossier_index.md` and
machine-readable metadata to
`custom_factions/gameplay_surface_weak_dossier_index.json`. A `built` dossier
has ISIL body evidence; a `declaration-only` dossier has DiffableCs declaration
evidence but no matching ISIL file; an `unresolved-target` row needs a more
exact decomp target before probing.

Validate weak-surface dossier coverage:

```powershell
python tools\release_port\validate_gameplay_surface_weak_dossier_index.py
```

Runtime/generated candidate coverage for packet-linked surfaces is reported to
`docs/gameplay_surface_runtime_candidate_coverage.md` and
`custom_factions/gameplay_surface_runtime_candidate_coverage.json` by the
refresh command. Validate it directly with:

```powershell
python tools\release_port\validate_gameplay_surface_runtime_candidate_coverage.py
```

The check is static. It validates traceability and fail-closed policy only; it
does not build, launch, patch, or prove runtime gameplay behavior.
