# Next pilot focus: battle Unit law-owner registry

June 19 source-prepared/runtime-unproven: the next combat pilot should verify `HoMM3 battle unit law-owner registry registered` during battle load, then `HoMM3 battle unit law-owner registry hit` during damage and morale hooks. A successful pilot should replace generic active-law ownership misses with either resolved active law/rank or a more specific packet proof gate. Registry misses remain fail-closed and should not be approximated.
# Custom Law Runtime Pilot Plan

Purpose: collect proof-grade runtime evidence for the custom law packet surfaces with one preferred combat runtime and one optional town/economy runtime.

Boundary: this is diagnostic capture only. Passing this pilot does not automatically promote `gameplayAllowed=true`; logs still need review against packet proof requirements.

## Profiles

### `pilot-combat-law-surfaces`

Use this first. It avoids construction/economy hot paths and the probes already implicated in June 18 crashes/softlocks. It now batches the sanitized combat surfaces so one runtime can cover most remaining combat packet evidence:

- `battle-event`: exact event constructor/dispatch-adjacent traces only; broad `BattleEventArgs` dispatcher probing remains rejected.
- `counterattack`: exact listener/change-event traces only; counterattack-correlation ability-resolve tracing remains disabled after the June 18 softlock.
- `morale`: exact candidate roll traces.
- `buff/debuff`: read/query traces for status-surface evidence.
- `focus`: exact Energy/Focus event constructors only; broad `BhHeroAbilitiesView` UI bind probing remains rejected.
- `spell-cooldown`: actual spell cast, cast gate, spellbook/cooldown state.
- `spellbook`: spellbook init/show/update/filter traces.

Still excluded from this profile:

- `construction`: UI/resource hot paths remain in the town/economy profile.
- `reward-result` and economy mutation traces: keep separate from combat to simplify attribution.
- `warcry` and broad game UI probes: separate profile until the sanitized combat batch is proven stable.

### `pilot-town-economy-law-surfaces`

Use this second only after combat capture is done. It isolates historically riskier town/economy traces:

- `construction`: displayed cost, eligibility, charged resources, constructed state, daily construction count.
- `reward-result`: committed reward choice, reward-set queue/remove/apply, resource mutation.
- `vision`: object descriptor/reveal/scouting adjacent surfaces.
- `economy`: side/resource heap correlation.

## Setup commands

Set `PLUGIN_ROOT` to the deployed Golden Era plugin folder:

```powershell
$PLUGIN_ROOT = "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod"
```

Clear old diagnostic flags before each runtime:

```powershell
python tools\release_port\custom_law_diag_flags.py clear --plugin-root $PLUGIN_ROOT --all-known
```

Apply the combat pilot profile:

```powershell
python tools\release_port\custom_law_diag_flags.py apply --plugin-root $PLUGIN_ROOT --profile pilot-combat-law-surfaces
```

Apply the town/economy pilot profile:

```powershell
python tools\release_port\custom_law_diag_flags.py apply --plugin-root $PLUGIN_ROOT --profile pilot-town-economy-law-surfaces
```

The game should be started after applying flags because diagnostic flags are cached in process.

## Runtime 1: combat pilot

Use any custom faction hero with a spellbook if possible.

Perform these actions in one battle:

1. Confirm combat entry completes.
2. Open the spellbook.
3. Change one spellbook filter or page if available.
4. Cast one hero spell if possible.
5. Perform one ordinary melee attack that should produce a counterattack if available.
6. Perform one ranged attack if available.
7. Continue for a few unit turns to allow a morale event if practical.
8. Stop after the first softlock/crash or after the battle remains responsive through those actions.

Useful player note to record afterward:

```text
battle entry completed: yes/no
spellbook opened: yes/no
spell cast: yes/no
melee counterattack happened: yes/no
ranged attack happened: yes/no
morale trigger happened: yes/no
battle still responsive after combat actions: yes/no
```

Capture logs:

```powershell
python tools\release_port\collect_custom_law_capture.py --game-root "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era" --scenario pilot-combat-law-surfaces --profile pilot-combat-law-surfaces --notes "battle-entry=?, spellbook-opened=?, spell-cast=?, counterattack=?, ranged=?, morale=?, responsive-after-actions=?"
```

## Runtime 2: town/economy pilot

Use this only after Runtime 1 is captured. Start with a custom faction town scene if possible.

Perform these actions:

1. Open a custom faction town.
2. Open the construction UI and inspect one affordable building.
3. Construct exactly one building.
4. Return to adventure map.
5. Pick up one loose resource or treasure chest. If it is a chest, choose one option and note which option.
6. Move near or interact with one adventure object if convenient, but do not spend time hunting for a perfect vision target.

Useful player note to record afterward:

```text
town faction:
building constructed:
resource/chest picked:
chest option:
vision/object interaction:
```

Capture logs:

```powershell
python tools\release_port\collect_custom_law_capture.py --game-root "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era" --scenario pilot-town-economy-law-surfaces --profile pilot-town-economy-law-surfaces --notes "town=?, building=?, reward=?, option=?, vision=?"
```

## Review criteria

The pilot is sufficient if logs show:

- Active custom law/rank context at least once.
- Combat entry completes with the sanitized combat profile.
- Spell cast gate/cooldown traces after a real cast.
- Spellbook init/show/update/filter traces after opening the spellbook.
- Counterattack, morale, battle-event, buff/debuff, and Focus diagnostics either emit useful exact traces or fail closed without softlock/crash.
- Construction commit, resource mutation, and constructed-state traces in the town run.
- Reward queue/apply/resource mutation correlation in the town run.

## Known limits

- The combat pilot intentionally excludes the specific probes already implicated in crashes/softlocks, not the whole feature families.
- Vision is opportunistic in the town/economy pilot unless a suitable reveal/interaction is nearby.
- Construction and economy diagnostics are isolated in Runtime 2 because they have historically been the riskiest hot paths.

## June 19 scope decision: construction and vision runtime laws de-scoped

Construction and vision custom runtime laws are intentionally de-scoped from the active runtime proof campaign. Construction diagnostics repeatedly crashed when patching construction/town UI/session/manager surfaces, even after narrowing away direct constructed-state, building-view bind, and building-view update hooks. Vision laws are also considered likely to be brittle/janky relative to their gameplay impact.

Operational decision: use safer placeholder/donor/native effects for these law slots and do not spend further runtime proof cycles on construction or vision packets unless explicitly reopened. The `pilot-town-economy-law-surfaces` profile now excludes construction and adventure vision flags; continue with reward/economy/battle-result surfaces only.
- June 19 battle-result scope adjustment: the original `homm3_battle_result_law_diag.flag` broad pre/post logger caused a turn-end crash and remains quarantined. Post-battle law proof now uses `homm3_battle_result_safe_law_probe.flag`, a prefix-only skeletal-necromancy-style probe that reads winner, losers, stack losses, squad-value losses, and active custom law state without gameplay mutation or postfix traversal. Status is source-prepared until a battle ends and logs `HoMM3 battle-result safe law probe: status=observed`.
- June 19 battle-result safe probe result: `homm3_battle_result_safe_law_probe.flag` fired and logged `status=observed` after a Necropolis win, proving the apply-result prefix can read winner hero and before/after winner-side losses. The run then crashed on turn end, so the flag is quarantined and must not be part of broad pilot profiles. Use the existing skeletal necromancy implementation as the production model for post-battle laws rather than continuing proof hooks through turn-end.

## June 19 source-prepared counterattack payload update

Static decomp/interoperability evidence corrected the `ChangeAbilityEventArgs` reader from guessed `target` to exact `whoChangedAbility` / `get_whoChangedAbility`, with exact `abilityType` and `indexInArray` getter names retained. This is source-prepared only; the next combat pilot still needs to prove that player-visible counterattacks emit a non-default `EAbilityType` or another exact discriminator.

Static review also found `Hex.Session.Battle.Unit -> TransferUnit -> UnitData` is insufficient for law-owner resolution because those objects do not expose side/hero/laws. Do not add Unit-owner fallbacks; use a field-object/event owner context or prove a new exact route first.

### June 19 source-prepared battle attack command candidate

Decomp/static evidence now identifies `cty.hsg()` as the battle attack command body: `cty.hsf()` returns `ECmd` id `0x2E`, while `cty.hsg()` performs unit lookup, target validation, branches on `caca`, and calls the concrete attack paths before returning success/failure. `runtime_interop_map.json` maps `cty` callable ordinal 1 to `Method_Public_Virtual_Boolean_0`, so `GameSymbols.CounterattackCorrelationLaws.BattleAttackExecute` now contains only `hsg` and `Method_Public_Virtual_Boolean_0`. This is source-prepared/runtime-unproven only; it is intended for the next narrow counterattack diagnostic and does not authorize gameplay mutation.

### June 19 source-prepared counterattack diagnostic registration update

The counterattack correlation diagnostic now registers the exact `cty.hsg()` / `Method_Public_Virtual_Boolean_0` battle attack command hook and reads `caby`/`cabz` plus generated field getters as the command attacker/target ids. The old `cty.hrl` stale-warning text was removed because the current source-prepared command surface is no longer that rejected symbol. This is still diagnostic-only and runtime-unproven.

### June 19 source-prepared battle owner-side getter update

`runtime_interop_map.json` maps `eir` (`ObjectPublicPrcgObPrcgInTrPrcgInUnique`) to exact `get_field_Public_TransferSide_0`, and the constructor/decomp evidence shows `eir` owns a `TransferSide`. `GameSymbols` now includes `get_field_Public_TransferSide_0` / `field_Public_TransferSide_0` alongside `basa`/`cgle` in the centralized battle-object, buff receiver, and custom law battle-side transfer-side member lists. This is source-prepared/runtime-unproven only; next combat diagnostics should confirm whether active law/rank gates stop reporting owner-side resolution failure.

### June 19 runtime pilot result: counterattack command/change-event partial proof

Runtime pilot with Dungeon completed without managed errors. Proven: exact `cty.hsg()` / `Method_Public_Virtual_Boolean_0` command hook registered and fired once (`command-start`/`command-end`); `ChangeAbilityEventArgs.whoChangedAbility` now resolves, eliminating the previous missing-target error; one native `abilityType=CounterAttack` change event was observed; morale positive-roll, damage-apply, spellbook, and spell-cooldown diagnostics remained stable. Not proven: command fields `caby`/`cabz` were absent through the current managed reader, the `CounterAttack` event still cannot resolve active law/rank because `FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique` does not expose the current owner side through the resolver path, and the safe battle-result prefix fired with `loserIndices=[]` / zero enemy lost value, so battle-result law packets are not authorized. Next work should use decomp to solve battle object owner-side resolution and battle-result timing/data source before another runtime.

- June 19 source-prepared/runtime-unproven battle object owner resolver expansion: counterattack diagnostics now read exact no-arg command getter methods, so `cty.hsg` command fields such as `get_field_Public_Int32_0/1` can be observed instead of appearing absent only because the local diagnostic reader ignored methods. `Homm3CustomFactionLawRuntime` now has a narrow exact route for battle field objects that do not expose owner side directly: `FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique` exact battle logic/hex getters -> `Hex.Method_Public_get_Unit_0` -> `Unit.Method_Public_get_TransferUnit_0` -> `TransferBattle.get_sides` -> `TransferSide.get_units`, then exact object identity match to the owning `TransferSide` and existing `TransferSide.logicHero` law-owner resolution. This is source-prepared from the refreshed interop/decomp evidence and remains runtime-unproven; do not use it to promote counterattack/damage/morale gameplay until logs show active law/rank resolves from the counterattack payload.

- June 19 runtime-proven partial counterattack diagnostic rerun: after rebuilding/deploying build 0.1.299 and explicitly re-enabling Dungeon auto-launch, the fresh combat pilot produced no managed exceptions. `cty.hsg` command diagnostics now read exact generated no-arg methods: command-start/end logged `attackerId=2` and `targetId=0`, proving the diagnostic reader fix. Three `ChangeAbilityEventArgs` counterattack observations fired with `abilityType=CounterAttack` and `counterattacker=FieldObjectPublicAbstractObUnObcfcnObstcnUnHeUnique`, but `changeEventProfile` and `changeEventPlan` still failed with `counterattacking battle object law-owner resolution failed: battle object did not expose exact owner side via FieldObject.basa`. This means the command-field read is proven, but the field-object-to-owner resolver is not yet being used by the counterattack runtime path or the failure text is masking a deeper exact-route failure. Battle-result safe probe remained stable but still reported `loserIndices=[]` and `winnerLaws=none-or-unresolved`.

- June 18 runtime-unproven central active-law resolver explain diagnostics: `Homm3CustomFactionLawRuntime.ExplainActiveKnownCustomLawResolution(...)` now mirrors the active-law resolver with step-level failure text for dataFractionLaws, custom faction SID, law list lookup, rank, wasApplied, line/group, logic-hero routing, and battle-object transfer-side routing. `Homm3CustomLawRuntimeGuard.TryResolveCandidateActiveLaw(...)` now includes that exact explanation in packet failures instead of collapsing every miss to generic active law/rank unresolved text. This is diagnostic-only and unvalidated until the next runtime pilot confirms the emitted failure step.

- June 18 runtime-proven central resolver explain diagnostics, ownership route still blocked: the next Dungeon combat pilot emitted the new step-level active-law failure text without crashing. Runtime evidence included `returnedTrue=True` morale rolls, one `abilityType=CounterAttack` change event, and damage-apply candidates with battle unit faction/tier classifier evidence. The previous generic `active law/rank could not be resolved` blocker is now narrowed: battle `Hex.Session.Battle.Unit` sources do not yet resolve to a law-owning side because exact battle-object routing fails either at `Hex.Session.Battle.Hex exposed no exact occupant unit` or `transfer unit Hex.Session.Battle.TransferUnit was not present in transfer battle sides; sides=2 sidesWithoutUnits=0 comparedUnits=5`. Treat morale/counterattack/damage event detection as useful runtime evidence, but do not promote gameplay mutation until the unit-to-side ownership route is corrected and proven.

- June 18 runtime-unproven battle Unit ownership route correction prepared: decomp/runtime interop evidence confirmed `Hex.Session.Battle.Unit.get__chjo_k__BackingField()` returns `TransferUnit`, `TransferUnit` exposes exact `configSid` and `slotPos`, and `TransferSide.units` exposes transfer-unit arrays. `Homm3CustomFactionLawRuntime` now treats a battle `Unit` source as the unit directly instead of requiring `Unit -> Hex -> occupant -> Unit`, and matches transfer units by reference or exact `(configSid, slotPos)` identity. This is source-prepared only until the next combat pilot proves active custom law/rank can resolve from morale, damage, and counterattack sources.


- June 19 runtime-proven DataFractionLaws row/SID access, active rank still requires an applied law scenario: startup auto-launch with Dungeon/Castle proved `Side.fractionLaws -> DataFractionLaws.list` is an `Il2CppSystem.Collections.Generic.List<DataFractionLaw>`, not a CLR enumerable. `Homm3CustomFactionLawRuntime` now reads that list through exact generated `get_Count`/`get_Item(int)` members. Runtime logs showed Dungeon `totalRows=33 readableSidRows=33 knownRows=12` and Castle `totalRows=32 readableSidRows=32 knownRows=13`, with exact SIDs such as `fraction_law_homm3_dungeon_3` and `fraction_law_homm3_castle_3`. The same startup run showed `activeKnownRows=0`, meaning the quick-game scenario had no applied custom law ranks; this does not prove active-rank consumption in gameplay hooks. Next proof must use a scenario with a visibly applied law row or a diagnostic-only native law-level seed, then confirm `level/wasApplied/line/group` through the same resolver before promoting packet gameplay.
