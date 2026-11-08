# Gameplay Surface Runtime Candidate Coverage

Boundary: static planning only. Runtime candidates here are not runtime proof, hook safety proof, or gameplay authorization.

Implementation-relevant surface count: `37`

## Coverage Counts

| Coverage level | Count |
| --- | ---: |
| `live-metadata-proven` | 1 |
| `no-generated-or-dossier-candidate` | 4 |
| `runtime-candidate` | 32 |

## Surfaces

| Surface | Domain | Status | Runtime candidates | Dossier statuses | Coverage |
| --- | --- | --- | ---: | --- | --- |
| `adventureObject.objectRootCollections` | adventure-object | proven-static | 1 |  | `runtime-candidate` |
| `battleAction.actionClassification` | battle-action | partial | 1 | `built` | `runtime-candidate` |
| `battleAction.battleLifecycleState` | battle-action | candidate | 2 | `built`, `built` | `runtime-candidate` |
| `battleAction.formationGeometry` | battle-action | partial | 1 | `built` | `runtime-candidate` |
| `battleAction.unitRoleClassifier` | battle-action | candidate | 4 | `built`, `built`, `built`, `declaration-only` | `runtime-candidate` |
| `battleActor.battleObjectToTransferSideAlias` | battle-actor | partial | 0 |  | `no-generated-or-dossier-candidate` |
| `battleActor.transferSideToDataSideRuntimeMap` | battle-actor | runtime-unproven | 0 |  | `no-generated-or-dossier-candidate` |
| `battleLifecycle.baseEventBoundary` | battle-lifecycle | partial | 1 | `built` | `runtime-candidate` |
| `buffStatus.buffDebuffSidSurfaces` | buff-status | candidate | 4 | `declaration-only`, `declaration-only`, `declaration-only`, `declaration-only` | `runtime-candidate` |
| `committedDamage.buffDebuffApplyQuery` | committed-damage | partial | 4 | `declaration-only`, `declaration-only`, `declaration-only`, `declaration-only` | `runtime-candidate` |
| `committedDamage.unitDamageApply` | committed-damage | proven-live-metadata | 1 |  | `runtime-candidate` |
| `construction.buildingLookup` | construction | proven-live-metadata | 1 |  | `runtime-candidate` |
| `construction.chargedCostAndCommit` | construction | partial | 3 | `built`, `built`, `built` | `runtime-candidate` |
| `construction.displayedCost` | construction | partial | 2 | `built`, `built` | `runtime-candidate` |
| `corpseDeath.staticDeathCorpseSignals` | corpse-death | partial | 2 | `built`, `built` | `runtime-candidate` |
| `counterattack.listenerCandidates` | counterattack | partial | 5 | `built`, `built`, `built` | `runtime-candidate` |
| `economy.resourceDataPrimitives` | economy | proven-static | 4 |  | `runtime-candidate` |
| `economy.sideResourceHeap` | economy | proven-static | 1 |  | `runtime-candidate` |
| `lawState.battlePacketActiveLawRankContext` | law-state | partial | 0 |  | `no-generated-or-dossier-candidate` |
| `lawState.logicFractionLawQueries` | law-state | runtime-proven | 5 |  | `runtime-candidate` |
| `lawState.packetMutationConsumesActiveRank` | law-state | runtime-unproven | 0 |  | `no-generated-or-dossier-candidate` |
| `morale.actionQueueMutation` | morale | missing | 2 | `built`, `built` | `runtime-candidate` |
| `morale.eventDispatch` | morale | proven-static | 2 |  | `runtime-candidate` |
| `morale.rollClassification` | morale | partial | 2 | `built`, `built` | `runtime-candidate` |
| `rewardConfig.rewardRowsAndConfig` | reward-config | proven-static | 2 |  | `runtime-candidate` |
| `rewardResult.applyRewardSet` | reward-result | partial | 1 | `built` | `runtime-candidate` |
| `rewardResult.queueAndResourceMutation` | reward-result | partial | 1 | `built` | `runtime-candidate` |
| `spellCooldown.castGateAndUiSync` | spell-cooldown | partial | 8 | `built`, `built`, `built`, `built`, `built`, `built` | `runtime-candidate` |
| `spellCooldown.effectiveCooldownRead` | spell-cooldown | proven-live-metadata | 0 |  | `live-metadata-proven` |
| `spellbook.castMagicEventPayloads` | spellbook | partial | 4 | `built`, `built`, `built`, `built` | `runtime-candidate` |
| `spellbook.heroAndDataMagicCollections` | spellbook | proven-static | 5 |  | `runtime-candidate` |
| `townBuilding.buildingCatalogAndDailyCount` | town-building | proven-static | 1 |  | `runtime-candidate` |
| `townService.magicManaIntelConverterRoots` | town-service | partial | 4 | `built`, `built`, `built`, `built` | `runtime-candidate` |
| `townService.tavernAndPrisonHeroSources` | town-service | partial | 3 | `built`, `built`, `built`, `built`, `built` | `runtime-candidate` |
| `ui.spellbookVisualOnlyBoundary` | ui | partial | 3 | `built`, `built`, `built` | `runtime-candidate` |
| `vision.nativeRevealMutation` | vision | partial | 8 | `built`, `built`, `built`, `built`, `built`, `declaration-only` | `runtime-candidate` |
| `vision.objectDescriptorFactories` | vision | proven-live-metadata | 3 |  | `runtime-candidate` |
