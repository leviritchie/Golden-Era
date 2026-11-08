# Gameplay Surface Weak Dossier Plan

Generated from `custom_factions/gameplay_surface_evidence_matrix.json`.

Boundary: static planning only. Runtime symbol candidates here are law-dossier exact-token matches or weak-dossier generated interop matches, not proof.

Weak surface count: `21`

| Surface | Domain | Status | Candidate count | Recommended action |
| --- | --- | --- | --- | --- |
| `battleAction.actionClassification` | battle-action | partial | 1 | Build/refresh focused method dossier for matched target CastAbilityEventArgs and reconcile runtime candidate before probe. |
| `battleAction.battleLifecycleState` | battle-action | candidate | 2 | Build/refresh focused method dossier for matched target BattleEventArgs and reconcile runtime candidate before probe. |
| `battleAction.formationGeometry` | battle-action | partial | 1 | Build/refresh focused method dossier for matched target CastAbilityEventArgs and reconcile runtime candidate before probe. |
| `battleAction.unitRoleClassifier` | battle-action | candidate | 4 | Build/refresh focused method dossier for matched target UnitLogicConfig and reconcile runtime candidate before probe. |
| `battleLifecycle.baseEventBoundary` | battle-lifecycle | partial | 1 | Build/refresh focused method dossier for matched target BattleEventArgs and reconcile runtime candidate before probe. |
| `buffStatus.buffDebuffSidSurfaces` | buff-status | candidate | 4 | Build/refresh focused method dossier for matched target dzv::bbgf and reconcile runtime candidate before probe. |
| `committedDamage.buffDebuffApplyQuery` | committed-damage | partial | 4 | Build/refresh focused method dossier for matched target dzv::bbgf and reconcile runtime candidate before probe. |
| `construction.chargedCostAndCommit` | construction | partial | 3 | Build/refresh focused method dossier for matched target Hex.Session.Data.Resource::bggw and reconcile runtime candidate before probe. |
| `construction.displayedCost` | construction | partial | 2 | Build/refresh focused method dossier for matched target BhBuildingView and reconcile runtime candidate before probe. |
| `corpseDeath.staticDeathCorpseSignals` | corpse-death | partial | 2 | Build/refresh focused method dossier for matched target UnitLogicConfig and reconcile runtime candidate before probe. |
| `counterattack.listenerCandidates` | counterattack | partial | 5 | Build/refresh focused method dossier for matched target law.counterattackCorrelation.battleAttack.execute and reconcile runtime candidate before probe. |
| `morale.actionQueueMutation` | morale | missing | 2 | Build/refresh focused method dossier for matched target eep::bdhu and reconcile runtime candidate before probe. |
| `morale.rollClassification` | morale | partial | 2 | Build/refresh focused method dossier for matched target eep::bdhu and reconcile runtime candidate before probe. |
| `rewardResult.applyRewardSet` | reward-result | partial | 1 | Build/refresh focused method dossier for matched target czy::vji and reconcile runtime candidate before probe. |
| `rewardResult.queueAndResourceMutation` | reward-result | partial | 1 | Build/refresh focused method dossier for matched target Resource and reconcile runtime candidate before probe. |
| `spellCooldown.castGateAndUiSync` | spell-cooldown | partial | 8 | Build/refresh focused method dossier for matched target eew::bdmd and reconcile runtime candidate before probe. |
| `spellbook.castMagicEventPayloads` | spellbook | partial | 4 | Build/refresh focused method dossier for matched target Hex.Session.Battle.CastMagicEventArgs::bctq and reconcile runtime candidate before probe. |
| `townService.magicManaIntelConverterRoots` | town-service | partial | 4 | Build/refresh focused method dossier for matched target BuildingManaFountain and reconcile runtime candidate before probe. |
| `townService.tavernAndPrisonHeroSources` | town-service | partial | 3 | Build/refresh focused method dossier for matched target BuildingTavern and reconcile runtime candidate before probe. |
| `ui.spellbookVisualOnlyBoundary` | ui | partial | 3 | Build/refresh focused method dossier for matched target BhSpellMiniView::sph and reconcile runtime candidate before probe. |
| `vision.nativeRevealMutation` | vision | partial | 8 | Build/refresh focused method dossier for matched target Hex.Session.Data.DataFogOfWar::bfri and reconcile runtime candidate before probe. |
