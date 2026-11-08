# Olden Era C# Recovery

Standalone IL2CPP → C# recovery workspace. Consumes Cpp2IL DiffableCs / ISIL / address maps and Mono demo evidence from `experiments/cpp2il_readable_csharp/`, then fans work through a partitioned claimable queue.

**This package must not live under `OfflineUnlockMod`.** Lifter / IR / recovered C# stay here.

## Proof bar C

A method is **not** promoted until:

1. **Identity bridged** — live bridge resolves the method / ctor NativeMethodInfoPtr.
2. **Oracle captured** as **`live_execution`** (inputs → observable outputs). `live_surface_metadata` is never enough.
3. **Equivalence proven** — recovered replay diffs equal the engine snapshot (with explicit float tolerances only when declared).
4. Ledger status is `equivalence-proven`.

Domain / milestone `domain_promoted` only when the **declared** method set is all `equivalence-proven`. Otherwise the promoter publishes `milestone_incomplete` with blocked reasons.

## Overnight-safe vs live-required stages

| Stage / role | Overnight-safe? | Notes |
| --- | --- | --- |
| `lift` / lifter | **Yes** | DiffableCs/ISIL/disasm only |
| `rename` / renamer + auditor rename pass | **Yes** | Mono map + collision audit |
| `equiv_test` / EquivTester | **Yes** only with **pre-captured** `live_execution` (or synthetic harness) traces | Do not invent traces overnight |
| `oracle_capture` / identity probe | **No** — needs live Golden Era | Fresh `live_probe_bridge` |
| `promote` / promoter milestone publish | **Yes** to *read* ledger and publish incomplete/complete | Does not create new live proofs |
| Overnight runner vehicle (Automations vs cron) | **Deferred** | Same `worker --role --claim` CLI either way |

Claim leases are vehicle-agnostic: one writer per `method_id`; partitions by `domain/type`.

## Worker CLI

```powershell
cd experiments/olden_cs_recovery
python -m olden_cs_recovery.worker --role lifter --claim 5 --partition Hex.Session.Battle
python -m olden_cs_recovery.worker --role renamer --claim 5 --partition Hex.Session.Battle
python -m olden_cs_recovery.worker --role auditor --claim 0 --partition Hex.Session.Battle
python -m olden_cs_recovery.worker --role oracle_capturer --claim 5 --partition Hex.Session.Battle --capture-kind live_execution
python -m olden_cs_recovery.worker --role equiv_tester --claim 5 --partition Hex.Session.Battle
python -m olden_cs_recovery.worker --role promoter --claim 0 --partition Hex.Session.Battle --publish-milestone-only
```

## Phase 4 milestone

Declared set: `proof_ledger/milestones/phase4_battle_eventargs_edb.json`  
Published ledger: `proof_ledger/milestones/phase4_battle_eventargs_edb.ledger.json`

Promoter never claims full milestone success with gaps.

## Phase 5 domain conventions

Phase 5 repeats the Phase 4 cycle per domain, in order:

1. Battle unit/mechanics → 2. City UI → 3. Map init/travel → 4. **Configs/data models** (this domain) → 5. broader `Hex.*` (optional capacity)

### Domain 1 — Battle unit/mechanics

| Item | Value |
| --- | --- |
| Declared set | `proof_ledger/milestones/phase5_battle_unit_mechanics.json` (**25** methods — explicit subset, not full Unit) |
| Ledger | `proof_ledger/milestones/phase5_battle_unit_mechanics.ledger.json` |
| Partition prefix | `Hex.Session.Battle.UnitMechanics` |
| Seed | `python -m olden_cs_recovery.seed_battle_unit_mechanics` |
| Status | **`domain_promoted` 25 / 25** |

**Coverage (declared only):** Unit CompGen accessors + Hex occupancy/neighbors + `TransferUnit::.ctor(string,int,int)`.

### Domain 2 — City UI binders

| Item | Value |
| --- | --- |
| Declared set | `proof_ledger/milestones/phase5_city_ui_binders.json` (**10** methods — explicit subset, not full City UI) |
| Ledger | `proof_ledger/milestones/phase5_city_ui_binders.ledger.json` |
| Partition prefix | `Hex.City.UI.Binders` |
| Seed | `python -m olden_cs_recovery.seed_city_ui_binders` |
| Status | **`domain_promoted` 10 / 10** |

**Coverage (declared only):**

- `BhBuildingView` CompGen bind-state getters: `trh`–`trk`, `trl`, `trm`, `trp`, `trq` (UI state / ints / city+building refs / RectTransform / hover bool)
- `BhCityUIElement` CompGen getters: `wcx`, `wcy` (rect + bool)

**Out of declaration:** `trr` / `UpdateView` / `baju` / `tuc` / `tud` bind-refresh bodies, BuildingData, Map.

### Domain 3 — Map init/travel

| Item | Value |
| --- | --- |
| Declared set | `proof_ledger/milestones/phase5_map_init_travel.json` (**20** methods — explicit subset, not full `Hex.Map`) |
| Ledger | `proof_ledger/milestones/phase5_map_init_travel.ledger.json` |
| Partition prefix | `Hex.Map.InitTravel` |
| Seed | `python -m olden_cs_recovery.seed_map_init_travel` |
| Status | **`domain_promoted` 20 / 20** |

**Coverage (declared only):**

- `Hex.Map.Map` CompGen getters after `Map.Init`: `oex` (MapData), `ofq` (MapObjects), and Init-chain façades `oez`–`ohq`
- `Hex.Map.MapData` size getters: `oiz` / `ojb` (`sizeX_` / `sizeZ_`) for travel/occupancy dimensions
- `Hex.Map.MapObjects` CompGen getters: `oph` / `opj` / `opl`

**Out of declaration:** `Map.Init`, `Map.ogz`, Map/MapData/MapObjects ctors, tile/water/road index accessors, CompGen setters (including `ofz` `sub rcx,-imm` encoding), MapEditor, Configs.

**Map CompGen conventions (fail-closed):**

- Identity uses DummyDLL `address_map_hex_map` ∩ `native_disasm_hex_map` (native-only VA allowed when DummyDLL omits CompGen getters).
- Live capture: **FieldAccessorRoundtripProbe.v1** — parameterless ctor with honest `il2cpp_object_new` fallback; getters record `returnValue` only.
- Compile-check: same-namespace type short names that match the last namespace segment (e.g. `Hex.Map.Map`) stay bare; array field types are stub-collected.

### Domain 4 — Configs / data models

| Item | Value |
| --- | --- |
| Declared set | `proof_ledger/milestones/phase5_configs_data_models.json` (**24** methods — explicit CompGen subset, not full `Hex.Configs` / `Hex.Session.Data`) |
| Ledger | `proof_ledger/milestones/phase5_configs_data_models.ledger.json` |
| Partition prefix | `Hex.Configs.DataModels` |
| Seed | `python -m olden_cs_recovery.seed_configs_data_models` |
| Status | **`domain_promoted` 24 / 24** |

**Coverage (declared only):**

- Config CompGen: `AbilityLogicConfig.rnw`, `AbilityViewConfig.roe`, `UnitLogicConfig.scs`, `UnitViewConfig.sef/seh/sej`, `BattleAiParams.sfr/sfs/sft`, `HeroConfig.rwu`, `BuffConfig.rrh`, `BuffConfigBase.rrp/rrr/rru`, `AiConfigHeroTasks.rpo/rpp`, `AiConfigRolesForMap.rpr/rps`
- Session.Data CompGen: `Side.bghq/bghr/bghs`, `Hero.bfwv`, `HeroStat.bfyp/bfyq`

**Out of declaration:** ability bucket lookups (`scu`/`sem`), `UnitStat` math, `FractionConfig` bodies, `DataSquadUnit` lazy resolve, bare ref setters without write barrier (`rnx`/`rof`), ConfigElementBase tables, ScriptableObject load paths, broader `Hex.*`.

**Configs CompGen conventions (fail-closed):**

- Identity: DummyDLL `address_map_hex_configs` / `address_map_hex_session_data` ∩ matching `native_disasm_*` (native-only VA when DummyDLL omits CompGen).
- Missing DiffableCs base offsets (e.g. ConfigElementBase id `@0x10`) use synthetic `field_0xN` names — no invented control flow.
- Live capture: **FieldAccessorRoundtripProbe.v1**; Il2Cpp enums Int32-convertible → `kind:int`; multi-field valuetypes (`AbilityID`) → `kind:other`+type.
- Compile-check: `GlobalUsings.cs` for `Hex.Configs` ↔ `Hex.Session.Data`; strip `override` against stub bases.

## Smoke commands

```powershell
cd experiments/olden_cs_recovery
python -m olden_cs_recovery.validate_inputs
python -m olden_cs_recovery.schema_validate --manifest --oracle
python -m olden_cs_recovery.tests.test_equiv_tester
```

Live (Golden Era + fresh bridge) — Phase 5 Configs/data models:

```powershell
cd experiments/olden_cs_recovery
python -m olden_cs_recovery.seed_configs_data_models
python -m olden_cs_recovery.worker --role lifter --claim 24 --partition Hex.Configs.DataModels
python -m olden_cs_recovery.worker --role renamer --claim 24 --partition Hex.Configs.DataModels
# deploy FieldAccessorRoundtripProbe.v1.dll under live_probe_bridge/probes (see CAPTURE.md)
python -m olden_cs_recovery.worker --role oracle_capturer --claim 24 --partition Hex.Configs.DataModels --capture-kind live_execution
python -m olden_cs_recovery.worker --role equiv_tester --claim 24 --partition Hex.Configs.DataModels
python -m olden_cs_recovery.worker --role promoter --claim 0 --partition Hex.Configs.DataModels --publish-milestone-only --milestone proof_ledger/milestones/phase5_configs_data_models.json
```

See `oracle_traces/CAPTURE.md` for construct surfaces and probe fallback.

## Layout

```text
experiments/olden_cs_recovery/
  README.md
  input_manifest.json
  schemas/
  queue/partitions/
  ir/
  recovered/
  oracle_traces/{live,synthetic}/
  proof_ledger/{entries,identity_probes,milestones}/
  probes/                         # hot-load construct snapshot probe source
  olden_cs_recovery/              # Python package
```

## Honest status after Phase 5 domain 4 (Configs/data models)

- Phase 4 remains **`domain_promoted`** at **32 / 32**.
- Phase 5 Battle unit/mechanics remains **`domain_promoted`** at **25 / 25** (CompGen). Occupancy ownership erratum: `proof_ledger/milestones/phase5_battle_unit_mechanics.occupancy_erratum.md` — `bcxo` ≠ movement occupancy.
- Phase 5 City UI binders remains **`domain_promoted`** at **10 / 10**.
- Phase 5 Map init/travel remains **`domain_promoted`** at **20 / 20**.
- Phase 5 Configs/data models declared set is **`domain_promoted`** at **24 / 24**.
- Phase 5 **fixed-order domains 1–4 are complete**. Plan item 5 (“broader `Hex.*` as capacity allows”) is optional — not required to close Phase 5’s ordered scale-up. Prefer stopping here unless a concrete GameSymbols / mod surface needs another bounded CompGen slice.

## Direct State write-body lane (M0–M6)

See [`DIRECT_STATE_WRITE_BODY.md`](DIRECT_STATE_WRITE_BODY.md). M1 milestone: `proof_ledger/milestones/ds_m1_movement_commit.json`. Card: `direct_state_cards/movement_commit_bfdi_v1.json`. M6 relocate card: `direct_state_cards/movement_relocate_bfdi_v1.json` (reuses M1 bfdi via `TryCommitUnitHexMove`). Banned-surface validator: `python -m olden_cs_recovery.validate_banned_surfaces` (also wired into OfflineUnlockMod BeforeBuild).