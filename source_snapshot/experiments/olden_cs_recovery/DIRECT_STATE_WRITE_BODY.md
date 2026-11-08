# Direct State write-body recovery lane

Extends `olden_cs_recovery` from CompGen/EventArgs into **bar-C recovery of combat WRITE BODIES** and occupancy/publish hubs. Product of each milestone is a **DirectState symbol card** plus **banned-surface validators** — not more CompGen getter counts.

Plan root: Cursor plan `direct_state_0shot_mechanics_recovery.plan.md`. Pin table: `experiments/direct_state_movement_trace/mono_live_pin_table.md`.

## Overnight-safe vs live / daytime stages

| Stage / role | Overnight-safe? | Notes |
| --- | --- | --- |
| `lift` / lifter | **Yes** | DiffableCs / ISIL / Capstone asm under `direct_state_movement_trace/`; Unresolved markers mandatory |
| `rename` / renamer | **Yes** | Pin table is mandatory second evidence; Auditor **rejects** `bcxo`↔occupancy renames |
| `equiv_test` / EquivTester | **Yes** only with **pre-captured** field-delta `live_execution` traces | Never invent oracles overnight |
| `oracle_capture` (field-delta) | **No** — needs live Golden Era | Scripted shove / controlled hex move; record `edf+0x10`, `fieldObjects` membership, `eda.cfia` invoke |
| Card publish (`publish_direct_state_card`) | **Yes** to emit `milestone_incomplete` / blocked reasons | Cannot invent equivalence-proven |
| GameSymbols export of proven surfaces | **Yes** to *refuse* export when incomplete | Export only when card `proof_status=equivalence-proven` |
| Gameplay ungating (`MovementPush` / `MovementTeleport` in `TryMove`) | **Never overnight** — M3/M6 + focused live-positive | Production gates stay fail-closed |

## Layout

```text
experiments/olden_cs_recovery/
  schemas/direct_state_card.schema.json
  direct_state_cards/<card_id>.json
  proof_ledger/milestones/ds_m0_scaffold.json
  proof_ledger/milestones/ds_m1_movement_commit.json
  proof_ledger/milestones/phase5_battle_unit_mechanics.occupancy_erratum.md
  DIRECT_STATE_WRITE_BODY.md          # this file
  olden_cs_recovery/seed_direct_state_write_body.py
  olden_cs_recovery/publish_direct_state_card.py
  olden_cs_recovery/validate_banned_surfaces.py
```

## M1 declared set (MovementPush commit)

Verified against DiffableCs + pin table:

| Live GE | Role |
|---|---|
| `UnitData::bfdi(Hex)` | commit owner |
| `UnitData::bfdh()` | readback |
| `edf::bcuo(Hex)` | position + list occupancy hub |
| `edf::bcun()` | readback |
| `Hex::bcyn(FieldObject)` | leave `fieldObjects` |
| `Hex::bcyl(FieldObject)` | enter `fieldObjects` |
| `eep::bdhv(Unit,Hex)` / `eep::bdhw(Unit,Hex)` | pre/post notify |
| `eda::bcim(object,BattleEventArgs)` → `eda.cfia` (+0xC0) | Logic publish |

**Out of M1 as occupancy/publish:** `Hex.bcxo`, `Hex.bcxn`, `edb.*`, UnitStartedMovement as publish. `bcxo`/`cfqf` is mono **lastCorpse**, not occupancy.

## Smoke

```powershell
cd experiments/olden_cs_recovery
python -m olden_cs_recovery.seed_direct_state_write_body --dry-run
python -m olden_cs_recovery.seed_direct_state_write_body
python -m olden_cs_recovery.worker --role lifter --claim 9 --partition DirectState.WriteBody/Commit
python -m olden_cs_recovery.worker --role renamer --claim 9 --partition DirectState.WriteBody/Commit
# live/daytime only (requires fresh Golden Era bridge + WriteBodyFieldDeltaProbe.v3.dll):
dotnet build probes/WriteBodyFieldDeltaProbe.csproj -c Release -o probes/build_out_field_delta
copy probes\build_out_field_delta\WriteBodyFieldDeltaProbe.dll `
  "<GoldenEra>\BepInEx\plugins\OfflineUnlockMod\live_probe_bridge\probes\WriteBodyFieldDeltaProbe.v3.dll"
python -m olden_cs_recovery.worker --role oracle_capturer --claim 9 --partition DirectState.WriteBody/Commit --capture-kind live_execution
python -m olden_cs_recovery.worker --role equiv_tester --claim 9 --partition DirectState.WriteBody/Commit
python -m olden_cs_recovery.worker --role promoter --claim 0 --partition DirectState.WriteBody/Commit --publish-milestone-only --milestone proof_ledger/milestones/ds_m1_movement_commit.json
python -m olden_cs_recovery.publish_direct_state_card
python -m olden_cs_recovery.validate_banned_surfaces
python ..\..\tools\validate_direct_state_banned_surfaces.py --repo-root ..\..
```

Card promotion: every `live_methods` entry must be `equivalence-proven` **or** explicitly `blocked` with reason (`bfdh` may stay blocked as readback-optional). `GameSymbols.DirectStateLaws` exports **proven surfaces only**. MovementPush stays gated.

## M2 seed (dest recipe; after M1 promote)

```powershell
python -m olden_cs_recovery.seed_direct_state_write_body --milestone proof_ledger/milestones/ds_m2_movement_dest.json
python -m olden_cs_recovery.worker --role lifter --claim 6 --partition DirectState.WriteBody/DestRecipe
python -m olden_cs_recovery.worker --role renamer --claim 6 --partition DirectState.WriteBody/DestRecipe
python -m olden_cs_recovery.apply_direct_state_pin_renames --partition DirectState.WriteBody/DestRecipe
dotnet build probes/DestRecipeCallTraceProbe.csproj -c Release -o probes/build_out_dest_recipe
copy probes\build_out_dest_recipe\DestRecipeCallTraceProbe.dll `
  "<GoldenEra>\BepInEx\plugins\OfflineUnlockMod\live_probe_bridge\probes\DestRecipeCallTraceProbe.v1.dll"
python -m olden_cs_recovery.worker --role oracle_capturer --claim 6 --partition DirectState.WriteBody/DestRecipe --capture-kind live_execution
python -m olden_cs_recovery.worker --role equiv_tester --claim 3 --partition DirectState.WriteBody/DestRecipe
python -m olden_cs_recovery.publish_direct_state_card --milestone proof_ledger/milestones/ds_m2_movement_dest.json
python -m olden_cs_recovery.validate_banned_surfaces
```

Card `movement.dest.ehh_bdpe_v1` is **equivalence-proven** (3 proven + 3 blocked-with-reason). Role=`dest_recipe` only.

## M4 seed (damage side-effects; after M3)

Declared set: `UnitData.bfde` (stack/HP write; `bfdd` same VA — out), `bfda`/`bfdf` readbacks, `Hex.bcxo`/`bcxn` lastCorpse (corpse_store only — **not** occupancy). DamageScalar stays gateway `TryCommitPreparedDamage` (not a recovered ApplyDamage body).

```powershell
python -m olden_cs_recovery.seed_direct_state_write_body --milestone proof_ledger/milestones/ds_m4_damage_side.json
python -m olden_cs_recovery.worker --role lifter --claim 5 --partition DirectState.WriteBody/DamageSide
python -m olden_cs_recovery.worker --role renamer --claim 5 --partition DirectState.WriteBody/DamageSide
python -m olden_cs_recovery.apply_direct_state_pin_renames --partition DirectState.WriteBody/DamageSide
dotnet build probes/WriteBodyFieldDeltaProbe.csproj -c Release -o probes/build_out_field_delta
copy probes\build_out_field_delta\WriteBodyFieldDeltaProbe.dll `
  "<GoldenEra>\BepInEx\plugins\OfflineUnlockMod\live_probe_bridge\probes\WriteBodyFieldDeltaProbe.v5.dll"
python -m olden_cs_recovery.worker --role oracle_capturer --claim 5 --partition DirectState.WriteBody/DamageSide --capture-kind live_execution
python -m olden_cs_recovery.worker --role equiv_tester --claim 5 --partition DirectState.WriteBody/DamageSide
python -m olden_cs_recovery.publish_direct_state_card --milestone proof_ledger/milestones/ds_m4_damage_side.json
python -m olden_cs_recovery.validate_banned_surfaces
```

## M5 seed (lifecycle spawn; after M4)

Declared: `Unit.Init` + reuse M1 `Hex.bcyl`. Collection insert = journaled IList (gateway). `Unit.Init` may stay blocked plant_incomplete.

```powershell
python -m olden_cs_recovery.seed_direct_state_write_body --milestone proof_ledger/milestones/ds_m5_lifecycle_spawn.json
python -m olden_cs_recovery.worker --role lifter --claim 1 --partition DirectState.WriteBody/LifecycleSpawn
python -m olden_cs_recovery.worker --role renamer --claim 1 --partition DirectState.WriteBody/LifecycleSpawn
python -m olden_cs_recovery.publish_direct_state_card --milestone proof_ledger/milestones/ds_m5_lifecycle_spawn.json
```

## M6 seed (teleport / non-push relocate; after M3)

Reuses `movement.commit.bfdi_v1` — no second occupancy model. Card `movement.relocate.bfdi_v1` binds `MovementTeleport` to the same journaled `TryCommitUnitHexMove` / `UnitData.bfdi` path. Pull stays unsupported.

```powershell
python -m olden_cs_recovery.validate_banned_surfaces
# live/daytime only:
# place homm3_direct_state_m6_bfdi_teleport.flag + homm3_live_probe_workbench.flag
python ..\..\tools\release_port\live_probe_request.py direct_state_m6_bfdi_teleport --timeout 90
# Expect CapLog 'HoMM3 M6_BFDI_TELEPORT_DUAL_READBACK agree' with dualAgree=True and axialDistance>=2
```

## Hard rules

- Bar C fail-closed; no fabricated oracles.
- Do not ungate `MovementPush` / `MovementTeleport` without focused live-positive dual-readback.
- Do not treat M1 as dest recipe (M2 = `ehh.bdpe` / `Hex.bcyf`).
- Prefer one journaled `bfdi` story over dual-write.
- Export `GameSymbols.DirectStateLaws` **only** for proven card surfaces.
- M4: `Hex.bcxo` may promote as **corpse_store** only; never as occupancy.
- M6: relocate reuses M1 commit triad; do not invent a second occupancy write body.