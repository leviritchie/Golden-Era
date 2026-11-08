# Custom Law Unproven Surface Candidate Matches

Status: static candidate map, generated from current law classification docs plus Mono demo semantic metadata. This is not runtime proof.

Sources:
- `docs/custom_law_runtime_completion_classification.md`
- `docs/custom_law_remaining_implementation_backlog.md`
- `tmp/mono_demo_battle_semantic_index.txt`
- `tmp/mono_demo_critical_battle_fingerprints.json`
- current DiffableCs candidates under `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex`

## High-confidence static matches

| Law packet / mechanics | Affected unproven laws | Mono demo semantic anchors | Current-build candidates | Confidence | Notes |
|---|---|---|---|---|---|
| Native battle setup / deterministic tests | all battle-law packets | `BhUnitTest.GenTransferBattle`, `BhUnitTest.FillTransferBattle`, `Hex.CustomBattle.BhSessionCustomBattle.StartBattle`, `GenTransferBattle`, `FillTransferBattle`, `Hex.Events.EaBattleSimulateStarted` | `BhUnitTest.cs` with `gih(List,List): TransferBattle`, `gii(List): TransferSide`; `dbg.cs` dense `TransferBattle`/`TransferSide` helper cluster | High static | Best route for robust validation harness. Needs runtime/live bridge proof before use. |
| Battle event hub | committed damage, counterattack, morale, battle-action, status, spell event predicates | `Hex.Session.Battle.BattleLogicEvents` with named events including `OnObjectTookDamage`, `OnChangeAbility`, `OnStartAction`, `OnEndAction`, `OnDoubleTurn`, `OnFailTurn`, `OnUnitGotBuff`, `OnUnitLostBuff`, `OnCastMagicStarted`, `OnCastMagicEnded` | `edb.cs`, large dispatch hub with many `object, BattleEventArgs` methods and subscription helpers | High static | This should replace isolated one-method guesses. Need ordinal/event-name mapping. |
| Ability cast/cooldown | spell-cooldown laws, Tower Prepared Artifice/Overclocked Spellworks, Cove Reload Drills, Dungeon Cruel Momentum, etc. | `Hex.Session.Battle.Ability`: `StartCooldown`, `EndCooldown`, `SetCooldownFor`, `IncreaseCdBy`, `SetCd`, `Cast`, `CheckCastValidity`, `GetVisualUpdateEventArgs` | `dxy.cs`, current ability/cast/cooldown cluster with `ChangeAbilityEventArgs` producers, cooldown-like setters/incrementers, charges, cast validity, and cast methods | High static | Stronger candidate than previous ad hoc cooldown surface. Still need exact method mapping and UI/gameplay sync check. |
| Damage and damage prevention | Officer Corps, Elemental Aspect, Burning Ash, Predator's Instruction, Hidebound Drill, Infernal Ascension, Berserker Charge, Arcane Calibration, formation damage laws | `BattleLogicEvents.OnObjectTookDamage`, `OnDamageFailed`; `Affect.ApplyDamage`, `TryApplyDamage`; `BattleLog.MsgSquadWasDamaged` | `edb.cs` event hub; current Affect equivalent still needs exact current candidate mapping | Medium-high | Event hub candidate is strong. Damage mutation point still needs current Affect-equivalent match if modifying damage before commit. |
| Visible status/buff/debuff application | Avenger marker visibility, Fortress Thorned Hides, poison/slow/debuff laws, Rampart Avenger predicates, user-facing buff icons | `Affect.ApplyBuff`, `TryApplyBuff`, `OnUnitGotBuff`, `OnUnitLostBuff`, `BattleLog.MsgSquadGotEffect`, `MsgSquadLostEffect`, `BuffTimeoutArgsChecker` | `edb.cs` for events; current Affect/buff equivalent needs candidate extraction | Medium-high | This is the right path for visible law markers. Need exact status application method and safe status config. |
| Counterattack identity | Conflux Elemental Backlash, Cove Boarding Hooks, Dungeon Outnumber, Fortress Thorned Hides, Necropolis Death Grip, Rampart Avenger's Reprisal, Stronghold Blood Feud, Tower Reactive Wards | `BattleLogicEvents.OnChangeAbility`; `BattleLog.MsgCounterSquadAttackCasted`; `BattleLog.MsgDefaultSquadAttackCasted`; `Ability.GetVisualUpdateEventArgs`; `ChangeAbilityEventArgs` | `dxy.cs` produces `ChangeAbilityEventArgs`; `edb.cs` event hub, previously touched `bcry`/counterattack diagnostics | Medium | Prior runtime claims were weak because event ordinal/type discrimination was incomplete. Demo gives better discriminators: compare counter/default attack log/event paths, not just ability index. |
| Morale/dismorale | Conflux Harmony, Cove Crew Nerve, Dungeon Terror Exploitation, Fortress Cold-Blooded Endurance, Inferno Frenzy, Necropolis Dread, Rampart Defender's Grace, Stronghold Rage, Tower Synchronization | `BattleLogicEvents.OnDoubleTurn`, `OnFailTurn`, `OnUnitDismoraled`; `BattleLog.MsgSquadMoraleAffected` | `edb.cs` event hub; current logs already showed morale diagnostic events, but owner/meaning still incomplete | Medium-high | Demo provides exact semantic event family. Need current ordinal mapping and owner/side extraction. |
| Reward and battle result | Prize Shares, Subjugated Mines, Marsh Rights, Soul Contract, Mortuary Accounting, Preservation Tithe, Spoils Ledger, Transmutation Ledger, calendar/reward laws | `EaApplyReward`, `EaRewards`, `EaRewardSetArg`, `EaRewardsUnits`, `EaBattleResultsStartApplying`, `EaSideEndBattle`, `EaBattleForWoObjectFinished`, `WorldRewardLogic`, `WorldRewardSet` | Current event equivalents likely present; current reward candidate already partial-proven but commit distinction unresolved | Medium | Mono event names clarify that reward application and battle-result start are separate surfaces. We should map both, not infer from resource mutation. |
| Resource/economy mutation | reward economy laws and Tower/Conflux economy laws | `DebugUIUtility.CheckHaveResource`, `BhResourcePanel.Add*`, `SideResourcesStatistics.OnResourcesChanged`, `EaResCounterChanged`, `ResHeap` | Current resource add route already runtime-proven through AI bridge; spend route caused prior crash and needs native-safe method mapping | Medium | Grants are proven. Spend/subtract still needs exact native route if any law spends resources. |
| Spell cast identity | spell-cooldown and spell-trigger laws | `BattleLogicEvents.OnCastMagicStarted`, `OnCastMagicEnded`; `EaSideBattleMagicCasted`; `BattleLog.MsgMagicSpellCasted` | `edb.cs` event hub, `dxy.cs` ability/cast cluster | Medium-high | Use cast-ended for committed spell effects; cast-start may fire before validation/commit. |
| Battle action / formation predicates | all row 18/19 formation-style laws | `OnStartAction`, `OnEndAction`, `OnUnitStartedMovement`, `OnUnitEndedMovement`, `OnUnitChangedHex`, `AttackStep`, `BattleInput`, `BattleHighlightsDrawer` | `edb.cs` event hub; current action geometry helpers still need extraction | Medium | Event boundaries are strong; geometry/formation predicates need current object model mapping. |
| Elemental/construct/unit-family predicates | Conflux elemental laws, Tower construct laws, faction family laws | Demo config and transfer types expose unit configs/transfer units; exact family classification still data-driven | Current custom classifiers plus Core data; current bridge owner registry hits | Medium | Mostly data/classification, less native surface. Need deterministic harness armies. |

## Lower-confidence or still missing candidates

| Mechanic | Why still weak | Next static step |
|---|---|---|
| Exact counterattack vs parry/preemptive retaliation | Demo gives `MsgCounterSquadAttackCasted` and default attack message classes, but current ordinal mapping is not yet done. Faun parry shows counter-like behavior can happen before normal attack. | Map demo battle-log message classes to current log message/current event emitters and correlate with `ChangeAbilityEventArgs`. |
| Damage pre-mutation point | `OnObjectTookDamage` is likely post-commit; laws that need to alter damage before it lands need Affect/current damage pipeline mapping. | Identify current equivalent of demo `Affect.TryApplyDamage` and `OutDamageInfo`. |
| Visible no-op marker status | Demo confirms buff application events and logs, but not which current status SID/config is safe as a no-op visible marker. | Map current BuffInfo/status config and native `ApplyBuff` equivalent. |
| Spellbook UI sync | Demo confirms Ability cooldown/cast logic, but UI sync still needs current spellbook view/state mapping. | Search current UI spellbook classes after cooldown gameplay route is mapped. |
| Construction/vision laws | These were explicitly abandoned/hard-placeholder in prior plan. Mono surface matching was not pursued in this pass. | Reopen only if design scope changes. |

## Practical impact

The Mono demo shape/xref approach should let us replace many broad runtime probes with targeted mapping:

1. Use `BhUnitTest`/`TransferBattle` to create deterministic native battle scenarios.
2. Use `edb.cs` as the central event hub candidate and map event ordinals once.
3. Use `dxy.cs` as the central ability/cooldown/cast candidate and map exact cooldown/cast methods once.
4. Use demo `Affect` and buff/damage method names to find current pre-commit damage and visible status application surfaces.
5. Use reward event names to separate reward choice, reward apply, battle result start, and resource mutation.
