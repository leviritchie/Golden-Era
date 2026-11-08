# Surface: GameSymbols / obfuscation hygiene

## Intent

Resolve live IL2CPP names safely so feature code does not scatter dump-era or hotfix-drifted identifiers.

## Ownership preference

Centralize pins in `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/GameSymbols.cs` (and established Direct State / `GameMember` resolvers). New live pins also belong in mono↔live pin tables when they are battle-state family names.

## Touch points

| Kind | Path |
| --- | --- |
| Symbol hub | `OfflineUnlockMod/GameSymbols.cs` |
| Access helpers | `GameMember` |
| Examples | `WarcryHeroAbility`, `BattleEventLaws.BattleUnitApplyDamage`, `BattleUnitInit.SideTypeHints` |
| Pin table | `experiments/direct_state_movement_trace/mono_live_pin_table.md` |
| Skill pitfalls | `.cursor/skills/decomp-search/pitfalls.md` |

## Pitfalls

- Dump ≠ live (factory `egd.bdpz` vs dump `egb.bdoh`).
- No silent fallback aliases for removed methods (`bbgw`).
- Hook arg type must match map key type (e.g. Unit.Init `[2]` is live `ObjectPublicPrcgObPrcgInTrPrcgInUnique` via `BattleUnitInit.SideTypeHints` — legacy `eir`/`ehh` aliases only — not `TransferSide`). Bridge before lookup.
- Silent miss class: non-empty plan/dict + `TryGetValue` false → diagnose key identity; do not conclude “no plan.”
- After the type/bridge is correct: Il2Cpp managed proxies of the same native object often diverge under `GetHashCode` / `ReferenceEquals` — key plan/dict caches by native pointer (`Homm3DirectStateIdentity`), not managed identity. Matching `nativeKey`s = same native object; distinct `nativeKey`s = different objects / wrong ownership key.
- Producer→consumer: keep plan/register state until every consumer has run (or own apply on one shared registration surface); do not clear in an earlier postfix than apply. Quiet miss logs + emptied map → timing/ownership. Do not throw fail-closed from optional pilots on `BattleLogic.Init` (also runs under adventure-map / session `Loader`).
- Il2Cpp lists: prefer `Count` + indexer when managed `foreach` has been empty wrongly; verify before pattern-copy.
- Do not hardcode RVAs in feature hooks.
- **DiffableCs method-declaration index ≠ live `Method_N`.** Counting `void(object, BattleEventArgs)` in DiffableCs and picking `Method_Public_Void_Object_BattleEventArgs_<index>` invents the wrong raise. Prefer ISIL field offset → interop `GetIl2CppField(..., "shortName")` → `field_…_N` → raise `Method_…_N`. Buff got-buff: DiffableCs `bcja` index 39 is **not** live `Method_39` (`cfir`/ChangeAbility); correct pin is `cfin`/`Method_35` in `BuffDebuffLaws.BuffEventDispatch`.
- Broader keyed-cache / proof-tier / lifecycle rules: hub **Silent miss / wrong proof**; detail dump in `.cursor/skills/decomp-search/pitfalls.md`.

## Open unknowns

Name drift after each Golden Era hotfix — re-pin before coding; do not trust dated AGENT_REFERENCE symbols.

## Proof

Symbol comments that cite live metadata are `proven-live-metadata` for identity only until the feature’s mutation path is proven.

Hub: [../agent_surface_guide.md](../agent_surface_guide.md).
