# Direct-State Overclaim Remediation Plan

Date: 2026-07-19

Status: Phases 0–3 and 5 implemented in worktree (source/static). Phase 4 awaiting Golden Era combat retest after deploy. Not user-visible gameplay proof until commit log + visible move (or named CapLog block).

## Purpose

Close the gap where direct-state contracts, dossiers, and validators treated named symbols or string presence as write-path proof. Fix the highest-confidence contract/code mismatches first, then re-prove Bellwether Shoulder Check push under honest proof labels.

## Root failure mode

1. A dossier or symbol sentence described a write path.
2. Validators pinned tokens or type names, not read↔write coupling.
3. Headless / startup / aggregate stress were easy to confuse with combat proof.
4. Combat then exposed that the named method did not publish the field `get_Hex` reads (`Method_Public_Void_Unit_Hex_0`).

One problem gets one solution. Prefer fail-closed CapLog over silent returns. Do not invent alternate topologies while a named live failure already exists.

## Proof lanes (do not promote across)

| Lane | Meaning |
| --- | --- |
| source/static | Code, Cecil, Dump.cs, GameSymbols, validators |
| generated | Manifest/fixture artifacts |
| build target | Golden Era / OfficialDeobf compile |
| deployed | Installed plugin/Core readback |
| startup smoke | Plugin loads; headless harness runs |
| runtime behavior | Named log line in live combat |
| user-visible | Stack actually moves / ability effect seen |

Accepted live facts as of this plan:

- Hex neighbour **field** reads work in combat (not getter Invoke).
- `BattleLogic` `Unit_Hex_0` does **not** change unit hex / `get_Hex`.
- User-visible MovementPush after `Homm3DirectStateUnitHexNative` (`field_Private_Hex_0` + occupant) remains **unproven** until a combat retest logs commit **and** the stack moves.

## Severity policy

| Class | Rule |
| --- | --- |
| P0 | Live code contradicts dossier/validator, or ingress can silently skip / mis-route |
| P1 | Gate that cannot observe the condition it claims, or Prepare that claims readiness without checks |
| P2 | Geometry / occupancy soft-fail / pull death that blocks real ops but is not today’s Shoulder Check path |
| P3 | Doc hygiene where Proof already says runtime-unvalidated; dead retired symbols; inventory mismatch |

Do not flatten the long family laundry list into a flat P0 backlog. NestedDamage/Kill “token without native invoke” items need a second pass before code changes unless they already fail compile or combat.

## Phase 0 — Honesty (docs + validators)

Goal: stop advertising false write paths. Source/static only.

1. Rewrite `docs/direct_state_adapter_dossiers.md` §movement:
   - Neighbour resolution: native neighbour **fields** (`Homm3DirectStateHexNeighbourNative`), not exact getter Invoke.
   - Hex write: `Homm3DirectStateUnitHexNative` / position-helper `field_Private_Hex_0` + Hex occupant, not `BattleLogic(Unit,Hex)`.
   - State explicitly: `Unit_Hex_0` live-proven **no publish**; user-visible push unproven.
   - Cap-logged / ability / surviving-target claims must match code after Phase 1, or be labeled aspirational until then.
2. Update handoff / any doc that still lists `BattleLogicUnitHexCommit` as the live write.
3. Fix validators that pin retired tokens:
   - `tools/validate_direct_state_adapter_invariants.py` — drop or replace `BattleLogicUnitHexCommit` with the UnitHexNative / gateway commit symbols that exist.
   - `tools/run_direct_state_replay.py` — remove `or True` on the proof-label require; either require a real label or delete the check.
4. Run `validate_documentation_contract.py` and direct-state validators; commit when green.

Exit: dossier and validators describe the current code path; no token requires the dead Unit_Hex Harmony commit.

## Phase 1 — Ingress fail-closed (code)

Goal: MovementPush routing never fails open without a named CapLog. Build + deploy; combat optional.

1. **Silent returns → CapLog** in `Homm3DirectStateIngressDispatcher.TryRouteMovementPushCore`:
   - null caster/receiver
   - `Damage <= 0`
   - missing active mechanics for SID
   Keep messages short and stable for log grepping.
2. **Ability identity on bound path**: require non-empty ability and `IsAbilityNameMatch`; remove empty-ability auto-commit (or document and CapLog a deliberate sole-ability bypass with a distinct reject code if product insists).
3. **`IsAbilityNameMatch`**: stop matching any observed `shoulder` / `abilities_0` once `expectedAbilityName` is set; keep substring only against the expected name (or explicit allowlist per mechanic).
4. **Dead-stack gate**: replace `TryGetStackCount && stacks <= 0` with an API that can return `0` (or a dedicated TryGet including zero). Today `TryGetStackCount` only returns true when stacks > 0, so the “already dead” reject is unreachable.

Exit: every MovementPush skip has a CapLog reason; ability empty cannot commit on bound path; dead gate can fire when stacks are 0.

## Phase 2 — Prepare and replay honesty (code + harness)

Goal: PrepareAdapter and headless replay stop implying write readiness they do not have.

1. For each adapter family: either implement real Prepare checks (types/fields/methods required for that family’s write) or make Prepare fail-closed / no-op with CapLog `unprepared`.
2. Headless replay: label results `startup smoke` / `source-replay` only; never “combat proven.”
3. Journal / opcode inventory: align claimed opcodes with what the gateway actually journals, or shrink the claim.

Exit: Prepare failure blocks commit for families that claim preparation; validators cannot pass on tautologies.

## Phase 3 — Movement geometry and occupancy (static then combat)

Goal: make push topology and destination gates fail-closed before more combat lottery.

1. **Occupancy / blocked**: if Hex blocked or occupant members cannot be read, reject with CapLog (no soft-pass).
2. **Ring geometry**: keep `(towardSource + 3) % N` only if N and ring order are Cecil/Dump proven for live Hex; otherwise prefer axial neighbour match only and CapLog when ring fallback is used.
3. **Pull**: either implement a real destination (adjacent hex toward caster that is free) or CapLog `MovementPull unsupported` and remove dossier “operations: pull” as ready.
4. Prefer static read↔write coupling gates (helper field written ↔ field `get_Hex` reads) before another combat session.

Exit: destination validation never succeeds by missing a read; pull is honest; ring claim is proven or removed.

## Phase 4 — Combat re-prove Shoulder Check

Goal: user-visible MovementPush or a named real block.

Setup: Golden Era install, current plugin with Phases 0–3 deployed.

Success (any one of):

- Log `HoMM3 direct-state MovementPush committed` **and** user-visible 1-hex push of the target stack.
- Named CapLog block that matches the real gate (occupied, off-board, ability mismatch, etc.) — not silent skip.

If commit logs but stack does not move: treat as publish/presentation failure; do not invent a third write path until get_Hex / view after helper write is inspected.

## Phase 5 — Second-pass family audit (deferred)

Only after Phase 4 or when blocking another pilot:

- NestedDamage / Kill / Focus / Cooldown / Status / lifecycle / aura — verify each “token present” claim against an actual native invoke or manager write.
- Demote findings that already say `runtime-unvalidated` in dossiers to doc cleanup unless validators falsely require them.
- Cleanup: retired `PrefixMovementCommit`, unused dispatch symbol names, reserveJournal fiction — only if they mislead validators or agents.

## Out of scope

- New movement topologies while a named live block exists.
- Promoting headless or aggregate stress to combat proof.
- Silent fallbacks “so the pilot looks green.”
- Broad family rewrites without a second static pass.

## Suggested work order

```text
Phase 0 (docs/validators)
  → Phase 1 (ingress CapLog / ability / dead gate)
  → Phase 2 (Prepare / replay labels)
  → Phase 3 (occupancy fail-closed + geometry honesty)
  → Phase 4 (combat retest Shoulder Check)
  → Phase 5 (other families, as needed)
```

## Key files

| Area | Path |
| --- | --- |
| Ingress | `OfflineUnlockMod/Homm3DirectStateIngressDispatcher.cs` |
| Adapters | `OfflineUnlockMod/Homm3DirectStateAdapters.cs` |
| Hex neighbours | `OfflineUnlockMod/Homm3DirectStateHexNeighbourNative.cs` |
| Hex write | `OfflineUnlockMod/Homm3DirectStateUnitHexNative.cs` |
| Gateway | `OfflineUnlockMod/NativeCombatWriteGateway.cs` |
| Ability match | `OfflineUnlockMod/Homm3BattleEventNativeAdapter.DamageIngress.cs` |
| Stack count | `OfflineUnlockMod/DamageKillMapping.cs` |
| Symbols | `OfflineUnlockMod/GameSymbols.cs` |
| Dossier | `docs/direct_state_adapter_dossiers.md` |
| Validators | `tools/validate_direct_state_adapter_invariants.py`, `tools/run_direct_state_replay.py`, `tools/validate_hex_neighbour_interop_contract.py` |

## Audit sources

- Direct-state overclaim audit (Grok explore agents: movement/gateway, damage/identity, other families), 2026-07-19.
- Post-audit review (re-verified critical ingress/dossier/replay findings; demoted severity inflation on already-hedged dossier prose).

## Done when

- Phase 0–1 green under validators and Golden Era compile.
- Phase 4 either user-visible push or a named combat CapLog that explains no move.
- No remaining validator or dossier sentence that asserts `BattleLogic(Unit,Hex)` as the live MovementPush write.
