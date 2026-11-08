# `edb` / `dxy` Mono-to-current surface mapping

> **SUPERSEDED / CONTRADICTED for live GE movement publish (2026-07-20).**
>
> This note’s hub map (`edb` ≈ Logic `BattleLogicEvents`, ordinal 21 `cfkg` ↔ `OnUnitChangedHex`) is **dump/ISIL-era** and must **not** be used as live Golden Era truth for movement commit publish.
>
> Live GE (Iteration 10 / W11): `eda` ≈ Logic, `edb` ≈ View; Logic `OnUnitChangedHex` ≈ `eda.cfhz`; commit raiser ≈ `eda.cfia` (`OnUnitEndedMovement`, ordinal-inferred); `edb.cfkg` ≈ View `OnCrit`.
>
> Authoritative: `docs/battle_state_logic_map.md` **S40–S45** / **W11** (also `docs/direct_state_movement_static_trace_handoff.md`).

Status: in-depth static analysis (**historical** for `edb` event-field names on live GE movement). This is not runtime proof. It is intended to replace one-off surface guesses with a durable method-mapping approach — **except** where contradicted above for live GE hubs/movement publish.

Primary evidence:

- Mono demo assembly: `V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo\HeroesOE_Data\Managed\Hex.dll`
- Current DiffableCs: `tmp\cpp2il_experiment\out_dev_diffable_cs\DiffableCs\Hex\edb.cs`
- Current DiffableCs: `tmp\cpp2il_experiment\out_dev_diffable_cs\DiffableCs\Hex\dxy.cs`
- Current DiffableCs: `tmp\cpp2il_experiment\out_dev_diffable_cs\DiffableCs\Hex\dxx.cs`
- Current DiffableCs: `tmp\cpp2il_experiment\out_dev_diffable_cs\DiffableCs\Hex\cni.cs`
- Current DiffableCs: `tmp\cpp2il_experiment\out_dev_diffable_cs\DiffableCs\Hex\crw.cs`
- Mono semantic index: `tmp\mono_demo_battle_semantic_index.txt`
- Mono fingerprints: `tmp\mono_demo_critical_battle_fingerprints.json`

## Executive summary

Yes, we can infer many methods from xrefs and structure, but the inference quality differs by cluster.

- `edb` is almost certainly the current equivalent of demo `Hex.Session.Battle.BattleLogicEvents`.
- `dxy` is almost certainly the current equivalent of demo `Hex.Session.Battle.Ability`.
- The first 49 `edb` event fields line up cleanly with the 49 demo battle event fields by declaration order.
- Current `edb` has 87 event fields, meaning the current game added roughly 38 battle-event surfaces after the demo. This is expected after eight months of development and is a structural-change warning.
- Current `edb` has 267 `public void *(object, BattleEventArgs)`-shaped methods versus 46 such demo dispatchers. Dispatcher order alone is therefore not a safe map.
- Current `dxy` method order is much closer to demo `Ability` than `edb` dispatcher order is, and xrefs split likely UI/text helpers from likely gameplay methods.

## `edb` as `BattleLogicEvents`

### Field order map

The strongest static evidence for `edb` is field order. The current field names are obfuscated, but the shape is very close: a long run of `EventHandler` fields followed by booleans.

| Ordinal | Demo event | Current field | Law surfaces affected |
|---:|---|---|---|
| 0 | `OnAnimationSpeedChanged` | `cfjl` | diagnostics/timing only |
| 1 | `OnStartBattle` | `cfjm` | battle lifecycle, law state reset/setup |
| 2 | `OnEndBattle` | `cfjn` | battle cleanup, post-battle state |
| 3 | `OnStartTurn` | `cfjo` | round/turn state, buffs, readiness |
| 4 | `OnSideBuff` | `cfjp` | side buffs/status packages |
| 5 | `OnStartAction` | `cfjq` | battle-action/formation predicates |
| 6 | `OnEndAction` | `cfjr` | post-action laws, formation cleanup |
| 7 | `OnEndTurn` | `cfjs` | turn cleanup, cooldown/state expiry |
| 8 | `OnStartRound` | `cfjt` | round setup |
| 9 | `OnEndRound` | `cfju` | round cleanup |
| 10 | `OnObjectTookDamage` | `cfjv` | committed-damage observation, damage-post effects |
| 11 | `OnDamageFailed` | `cfjw` | miss/immunity/failure laws |
| 12 | `OnUnitHealed` | `cfjx` | healing/reanimation observation |
| 13 | `OnDoubleTurn` | `cfjy` | positive morale extra action |
| 14 | `OnFailTurn` | `cfjz` | negative morale failure |
| 15 | `OnSkip` | `cfka` | skip action |
| 16 | `OnWait` | `cfkb` | wait action |
| 17 | `OnContinueAfterWait` | `cfkc` | wait recovery |
| 18 | `OnUnitDismoraled` | `cfkd` | morale/fear/dread |
| 19 | `OnObjectSpawned` | `cfke` | summons/gating/spawns |
| 20 | `OnObjectDestroyed` | `cfkf` | kills, corpse/squadValue, death triggers |
| 21 | `OnUnitChangedHex` | `cfkg` | movement/formation/adjacency |
| 22 | `OnUnitEndedMovement` | `cfkh` | movement end predicates |
| 23 | `OnUnitStartedMovement` | `cfki` | movement start predicates |
| 24 | `OnChangeAbility` | `cfkj` | counterattack ability identity, cooldown/status changes |
| 25 | `OnChangeHeroAbility` | `cfkk` | hero ability changes |
| 26 | `OnCastHeroAbilityEnded` | `cfkl` | hero ability cast ended |
| 27 | `OnCastSharedAbilityEnded` | `cfkm` | shared ability cast ended |
| 28 | `OnChangeBattleAbility` | `cfkn` | battle ability state changes |
| 29 | `OnChangeMagic` | `cfko` | spellbook/magic state changes |
| 30 | `OnCastMagicEnded` | `cfkp` | committed spellcast effects |
| 31 | `OnCastMagicStarted` | `cfkq` | pre-cast spell events |
| 32 | `OnUnitGotBuff` | `cfkr` | visible buff/debuff application |
| 33 | `OnUnitRevived` | `cfks` | revive/reanimation |
| 34 | `OnUnitLostBuff` | `cfkt` | visible buff/debuff removal |
| 35 | `OnCastAbility` | `cfku` | unit ability cast |
| 36 | `OnStartCastAbility` | `cfkv` | pre-ability cast |
| 37 | `OnEndCastAbility` | `cfkw` | post-ability cast |
| 38 | `OnStartTimer` | `cfkx` | timer UI/game state |
| 39 | `OnPauseTimer` | `cfky` | timer UI/game state |
| 40 | `OnBuffTimeout` | `cfkz` | status expiry |
| 41 | `OnStartTacticsPhase` | `cfla` | tactics setup |
| 42 | `OnEndTacticsPhase` | `cflb` | tactics cleanup |
| 43 | `OnSideStartTactics` | `cflc` | tactics side start |
| 44 | `OnSideCompleteTactics` | `cfld` | tactics side complete |
| 45 | `OnUnitStartTacticsMovement` | `cfle` | tactics movement |
| 46 | `OnUnitEndTacticsMovement` | `cflf` | tactics movement end |
| 47 | `OnSideUsedEnergy` | `cflg` | Focus/energy-like side spending |
| 48 | `OnSideEnergyAccumulated` | `cflh` | Focus/energy-like side gain |

### What lines up well

The first 49 current `edb` fields match the demo event field sequence exactly by count and order. This is a strong static signal because event declarations are hard to accidentally recreate in the same shape.

This immediately improves several law packets:

- `committed-damage`: observe `cfjv` / `OnObjectTookDamage`, but do not assume it is a pre-damage mutation point.
- `morale`: observe `cfjy` / `OnDoubleTurn`, `cfjz` / `OnFailTurn`, and `cfkd` / `OnUnitDismoraled`.
- `spell-cooldown`: spell events should correlate with `cfkp` / `OnCastMagicEnded`, `cfkq` / `OnCastMagicStarted`, and `cfko` / `OnChangeMagic`.
- `visible buffs`: `cfkr` / `OnUnitGotBuff`, `cfkt` / `OnUnitLostBuff`, `cfkz` / `OnBuffTimeout`.
- `battle-action`: `cfjq` / `OnStartAction`, `cfjr` / `OnEndAction`, and movement fields `cfkg`-`cfki`.
- `counterattack`: likely through `cfkj` / `OnChangeAbility`, but this remains only one part of the discriminator.

### What does not line up cleanly

Current `edb` has 87 event fields, while the demo has 49. This means:

- New events were added after the demo.
- The original 49 appear to be a prefix, but we must not assume ordinals beyond `cflh` have demo meanings.
- If any current code inserted events in the middle while preserving some blocks, a pure ordinal map would be wrong. The clean first-49 order makes that less likely, but runtime metadata or emitter xrefs should still verify the high-value events.

Current `edb` also has 267 `object, BattleEventArgs`-shaped public dispatch methods, while the demo has 46 dispatchers. This means dispatcher order is weak evidence. Many current methods may be overload bridges, wrappers, generated handlers, hotkey handlers, new events, or duplicate obfuscator products.

### Why previous counterattack proof was fragile

The counterattack work likely latched onto an `OnChangeAbility`-neighborhood method without proving the semantic discriminator.

The demo shows that counterattack identity is not just an event hub issue. It also involves:

- `OnChangeAbility` event family.
- `Ability.GetVisualUpdateEventArgs` / `ChangeAbilityEventArgs`.
- battle log classes such as `MsgCounterSquadAttackCasted` vs `MsgDefaultSquadAttackCasted`.
- ability type/config state.

Faun parry/preemptive retaliation shows why “counter-like action happened” is not enough. We need to separate normal attack, counterattack, preemptive/parry, sentry, and ability-cast attack paths.

## `dxy` as `Ability`

### Demo method sequence

The demo `Hex.Session.Battle.Ability` method sequence is highly informative:

| Demo ordinal | Demo method | Meaning |
|---:|---|---|
| 0 | `get_cd` | cooldown read |
| 1 | `set_cd` | cooldown direct set property |
| 2 | `get_armed` | armed/readiness read |
| 3 | `set_armed` | armed/readiness set |
| 4 | `get_isDirected` | targeting classifier |
| 5 | `get_isMelee` | melee classifier |
| 6 | `get_canIgnoreObstacles` | targeting classifier |
| 7 | `GetEnergyLevelCost` | energy/focus-like cost tier |
| 8 | `GetEnergyCost` | energy/focus-like cost value |
| 9 | `GetSide` | owning side |
| 10 | `GetCastSelectionParams` | targeting UI/game predicate |
| 11 | `GetAffectSelectionParams` | affected target predicate |
| 12 | `CanBeCasted` | cast gate |
| 13 | `GetEffectiveSpellPower` | spell power read |
| 14 | `GetDamageDealer` | damage dealer object |
| 15 | `GetAllyDealer` | ally dealer object |
| 16 | `Init` | config/init |
| 17 | `GetOutcomingMinDamage` | damage text/calculation read |
| 18 | `GetOutcomingMaxDamage` | damage text/calculation read |
| 19 | `GetEffectTime` | duration read |
| 20 | `GetSelfEffectTime` | self duration read |
| 22 | `SetCharges` | charges mutation |
| 23 | `AddCharges` | charges mutation |
| 24 | `RestoreChargesFromConfig` | reset charges |
| 25 | `StartCooldown` | cooldown mutation |
| 26 | `EndCooldown` | cooldown mutation |
| 27 | `GetVisualUpdateEventArgs` | event payload producer |
| 28 | `SetCooldownFor` | cooldown mutation with source flag |
| 29 | `Arm` | armed mutation |
| 30 | `Disarm` | armed mutation |
| 31 | `SetArmed` | armed mutation |
| 32 | `CheckCastValidity` | cast gate |
| 33 | `CheckCastValidity(skipEnergyCheck)` | cast gate |
| 34 | `HasSelfCastArgs` | cast arg classifier |
| 35 | `CreateInCastArgs` | cast payload creation |
| 36 | `CreateSelfCastArgs` | cast payload creation |
| 37 | `Cast(Affect, int[], bool)` | gameplay cast mutation |
| 38 | `SendCastEvent` | event emission |
| 39 | `Cast(Affect, int[])` | gameplay cast mutation |
| 40 | `CastSentry` | sentry cast mutation |
| 41 | `GetDamageDealerCharges` | read |
| 42 | `IncreaseCdBy` | cooldown mutation |
| 43 | `SetCd` | cooldown mutation |

### Current `dxy` likely method groups

Current `dxy` declaration order and xrefs suggest this rough grouping:

| Current method(s) | Likely demo equivalent | Evidence | Confidence |
|---|---|---|---|
| `barp`, `barq` | `get_cd`, `set_cd` | Compiler-generated int property around `<ceit>` backing field | High static |
| `bart`, `baru` | `get_armed`, `set_armed` | Compiler-generated bool property around `<cejh>` backing field | High static |
| `cnxx`, `cnxy`, `cnxz` | `isDirected`, `isMelee`, `canIgnoreObstacles` | three bool properties before ctor, same shape as demo classifiers | Medium-high |
| `basa` | `GetSide` or related owner read | xref from UI validation in `crw`; returns `eir` | Medium |
| `basb` | effective power or scalar read | returns float, extra current-build shape | Low-medium |
| `basc`, `basd` | cast/affect selection params | return `TargetSelectionParams` with int arg | High static |
| `base` | `CanBeCasted` | override bool with side-like arg | Medium-high |
| `basi`, `basj` | min/max damage or duration reads | called repeatedly from `cni`, which has tooltip/formula methods like `GetBaseDamage`, `GetTotalDamage`, `GetBaseDuration` | Medium-high, but read-only/UI-text risk |
| `bask`, `basl` | duration or self-duration reads | same sequence neighborhood as demo read methods | Medium |
| `basm`, `baso`, `bati`, `batj`, `boz`, `dbm`, `iev`, `mub`, `nby`, `wi` | charges/cooldown/armed integer mutation candidates | many `void int` methods; xref counts show `batj` used often | Low until xref caller classifies them |
| `basn`, `basp`, `basv`, `basw`, `mxq`, `nt`, `jgm`, `ddn` | no-arg state mutation candidates | likely reset/start/end cooldown/arm/disarm variants | Low-medium |
| `bast`, `dwf`, `kda`, `mgi` | `GetVisualUpdateEventArgs` variants | return `ChangeAbilityEventArgs`; `bast` has the highest xref count among `dxy` methods | High static that these create visual/update event args; exact semantic variant not proven |
| `basu(int,bool)`, `ehw(int,bool)` | `SetCooldownFor(int,bool)` candidates | exact signature shape `int,bool=false`; likely cooldown/source flag mutations | Medium-high |
| `basx(bool)`, `lsw(bool)` | `SetArmed(bool)` or related flag mutation | exact `void bool`; xrefs show `basx` is used | Medium |
| `basy`, `basz`, `bata`, `hwh`, `kxw`, `qu` | cast validity / classification gates | bool returns, some bool args, xref counts show `basy` used often | Medium |
| `batb`, `batc` | `CreateInCastArgs`, `CreateSelfCastArgs` | return `InCastArgs`, signature matches demo | High static |
| `batd`, `hau` | private `Cast(Affect,int[],bool)` candidates | private void `(dxz,int[],bool=false)` matches demo cast body with source flag | High static |
| `batf` | public `Cast(Affect,int[])` | override void `(dxz,int[])` matches demo public cast | High static |
| `batg`, `kpc`, `mfn` | `CastSentry` variants | void `(dxz,int[],Sentry,bool)` exact shape | High static, exact duplicate reason unknown |
| `bate`, `cec`, `ldn` | `SendCastEvent` or target filtering helpers | private void `(int[],HashSet)` shape; near cast methods | Medium |

### Xref evidence for `dxy`

Collected ISIL xrefs show 101 direct `dxy.*` calls. Highest counts:

| Method | Xref count | Initial interpretation |
|---|---:|---|
| `dxy.bast` | 24 | likely high-use `ChangeAbilityEventArgs` producer / visual update args |
| `dxy.batj` | 11 | likely state mutation or cooldown/charge integer mutator |
| `dxy.basy` | 10 | likely cast-validity/readiness gate |
| `dxy.barx` | 9 | likely property/classifier read |
| `dxy.Init` | 9 | config init |
| `dxy.basx` | 8 | likely armed/readiness bool mutation |
| `dxy.basi` | 5 | tooltip/formula read from `cni` |
| `dxy.basj` | 5 | tooltip/formula read from `cni` |
| `dxy.basw` | 4 | state reset/mutation candidate |
| `dxy.batd` | 4 | private cast body candidate |

`cni.cs` is a description/formula text class with readable methods like `GetBaseDamage`, `GetTotalDamage`, `GetBaseDuration`, `GetEffectTime`-style behavior. Therefore, `dxy.basi` and `dxy.basj` are likely read-only tooltip/formula surfaces, not gameplay mutation surfaces.

`crw.cs` references `BhBattleAbilityView` and `BhHeroAbilitiyView`, so xrefs from `crw` are UI/view evidence. Useful for identifying display methods and click gates, but insufficient for gameplay mutation.

## Where things do not line up

### `edb` field count expanded significantly

Demo `BattleLogicEvents` has 49 event fields. Current `edb` has 87 event fields.

Likely explanations:

- New event surfaces were added since the demo.
- Hotkey/hero/battle ability events expanded.
- Additional timing, UI, replay, AI, or animation events were added.
- Obfuscation/generation may have split generic event surfaces into multiple wrappers.

Impact:

- The first 49 fields are strong candidates for the demo events.
- Events after `cflh` are current-only and must be mapped by xrefs/runtime metadata, not demo ordinal.

### `edb` dispatch method count exploded

Demo has 46 `object, BattleEventArgs` dispatch-like methods. Current `edb` has 267.

Impact:

- Dispatcher ordinal mapping is unsafe.
- Event field mapping is safer than method mapping.
- To hook event semantics, prefer subscribing to the mapped event field/add accessor if possible, rather than patching random dispatch methods.
- If patching dispatch methods is unavoidable, map them by event-field usage or emitter xrefs, not by declaration order.

### `dxy` gained duplicate-looking cast/cooldown methods

The current `dxy` has multiple methods with the same signature family:

- several `void int` methods,
- several no-arg state methods,
- multiple `ChangeAbilityEventArgs` producers,
- multiple `CastSentry`-shaped methods,
- multiple private cast-body-shaped methods.

Likely explanations:

- Current build added hero/shared/battle/sentry variants.
- Some methods are wrappers for alternate names retained by obfuscator/output.
- Some methods may be compatibility shims or overload forwarders.
- Some are UI-triggered methods and some are gameplay logic methods.

Impact:

- We should not implement cooldown laws by guessing one setter.
- We should map cooldown mutation through xrefs from cast execution and `OnChangeAbility`/`OnChangeMagic` emission.
- `SetCooldownFor(int,bool)` candidates (`basu`, `ehw`) are promising, but not proven.

## Law-packet implications

### Committed damage

Use `edb.cfjv` / demo `OnObjectTookDamage` for observation. This likely proves post-commit damage, not pre-commit mutation.

For laws that need to alter incoming/outgoing damage before it lands, we still need current equivalent of demo `Affect.TryApplyDamage` / `ApplyDamage`, not just `edb`.

### Counterattack

Use `edb.cfkj` / demo `OnChangeAbility` plus `dxy` `ChangeAbilityEventArgs` producers as the neighborhood.

Do not claim counterattack solved until we also map:

- current equivalent of demo `MsgCounterSquadAttackCasted`,
- current equivalent of demo `MsgDefaultSquadAttackCasted`,
- ability type/config discriminators,
- parry/preemptive/sentry paths.

### Morale

Use:

- `edb.cfjy` / `OnDoubleTurn`,
- `edb.cfjz` / `OnFailTurn`,
- `edb.cfkd` / `OnUnitDismoraled`.

This is much stronger than previous broad morale diagnostics. Remaining hard part is owner/side correlation and whether `DoubleTurn` represents a granted extra action, an animation notification, or both.

### Visible buffs/debuffs

Use:

- `edb.cfkr` / `OnUnitGotBuff`,
- `edb.cfkt` / `OnUnitLostBuff`,
- `edb.cfkz` / `OnBuffTimeout`.

For mutation, still map current equivalent of demo `Affect.ApplyBuff` / `TryApplyBuff`. Event observation alone will not apply visible icons.

### Spell/cooldown

Likely surfaces:

- `edb.cfkp` / `OnCastMagicEnded` for committed spell trigger,
- `edb.cfkq` / `OnCastMagicStarted` for pre-cast trigger,
- `edb.cfko` / `OnChangeMagic` for magic state updates,
- `dxy.basu` or `dxy.ehw` as likely `SetCooldownFor(int,bool)`,
- `dxy.batd`/`batf`/`hau` as cast execution bodies,
- `dxy.basy`/similar as cast gate candidates.

Do not use tooltip/UI xrefs from `cni` or `crw` as gameplay proof.

### Battle-action / formation

Use:

- `edb.cfjq` / `OnStartAction`,
- `edb.cfjr` / `OnEndAction`,
- `edb.cfkg` / `OnUnitChangedHex`,
- `edb.cfkh` / `OnUnitEndedMovement`,
- `edb.cfki` / `OnUnitStartedMovement`.

Formation geometry still needs battle hex/unit model mapping; event boundaries alone are not enough.

## Recommended next mapping work

1. Map current `Affect` equivalent.
   - Start from demo `Affect.ApplyDamage`, `TryApplyDamage`, `ApplyBuff`, `TryApplyBuff` signatures.
   - Current likely type is near `dxz`/`dxx`/cast pipeline, but needs shape/xref proof.

2. Map event add accessors for `edb` first 49 fields.
   - If we can subscribe to fields/accessors rather than patch dispatch methods, runtime hooks become much cleaner and less fragile.

3. Map `dxy.basu` and `dxy.ehw` via xrefs.
   - Determine which is `SetCooldownFor` and which is added/current-build equivalent.
   - Cross-check with `OnChangeAbility` or `ChangeAbilityEventArgs` emission.

4. Map counterattack log classes.
   - Find current equivalents of demo `MsgCounterSquadAttackCasted` and `MsgDefaultSquadAttackCasted` by field/method shape and xrefs.
   - Use those as discriminators instead of broad ability-index assumptions.

5. Use `BhUnitTest` / `TransferBattle` harness after mappings are stable.
   - The static map is useful, but the robust validation path is deterministic native battle scenarios with assertions.

## Bottom line

The Mono demo lets us infer a lot more than before, but the safe strategy is:

- use declaration order for `edb` event fields,
- use xrefs to distinguish UI/text from gameplay mutation in `dxy`,
- avoid dispatcher-order assumptions in `edb`,
- treat counterattack as unsolved until attack-type discriminators are mapped,
- treat visible status mutation as unsolved until current `Affect.ApplyBuff` equivalent is mapped.
