# Decomp artifact map

Paths relative to repo root unless absolute.

## Start here

| Doc | Role |
|-----|------|
| `docs/battle_state_logic_map.md` | Running claims + evidence labels + domain model |
| `docs/direct_state_adapter_dossiers.md` | Per-adapter ownership recipes |
| `docs/direct_state_movement_static_trace_handoff.md` | Movement static closeout (not ship permission) |
| `docs/runtime_mechanics_implementation_handoff.md` | Runtime mechanics / pilots |
| `AGENTS.md` | Install root, proof boundaries, GameSymbols rule |

## Live Golden Era

| Asset | Path |
|-------|------|
| Game | `V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/` |
| Core.zip | `…/HeroesOldenEra_Data/StreamingAssets/Core.zip` |
| BepInEx log | `…/BepInEx/LogOutput.log` |
| Plugin | `…/BepInEx/plugins/OfflineUnlockMod/` |

## Pins and disasm

| Artifact | Role |
|----------|------|
| `experiments/direct_state_movement_trace/mono_live_pin_table.md` | Mono → live GE movement/occupancy pins |
| `experiments/direct_state_movement_trace/*.asm.txt` | Capstone bodies (`UnitData_bfdi`, `ehh_bdpe`, `emz_bfbe`, …) |
| `tools/il2cpp_out_20260719_golden_era/dump.cs` | Live DummyDll dump (when present) |

## C# recovery / equivalence

| Path | Role |
|------|------|
| `experiments/olden_cs_recovery/README.md` | Lifter, rename, equiv harness overview |
| `experiments/olden_cs_recovery/proof_ledger/` | Proven / blocked / incomplete milestones |
| `experiments/olden_cs_recovery/oracle_traces/CAPTURE.md` | Live probe capture notes |
| `experiments/olden_cs_recovery/direct_state_cards/` | Declared DS surface cards |
| `experiments/olden_cs_recovery/rename_map/` | Proposed mono renames |

## Config / overrides

| Path | Role |
|------|------|
| `custom_factions/ability_overrides/` | Unit special donors + `directStateNativeShell` |
| `custom_factions/runtime_mechanics/homm3_state_pilots.json` | Diagnostic DS pilots |
| `tools/release_port/apply_release_core_overlay.py` | Writes Core unit rows from overrides |
| `tools/validate_homm3_runtime_mechanics_contract.py` | Contract gate for pilots/shells |

## Plugin surface

| Path | Role |
|------|------|
| `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/GameSymbols.cs` | Centralized obfuscated names |
| `…/Homm3DirectState*.cs` | Direct State adapters / ingress |
| `…/Homm3RuntimeMechanic*.cs` | Pilot registry / hooks |

## Known live mech pins (movement family)

| Config / mono | Live GE |
|---------------|---------|
| `push_unit` / `EMechType.PushUnit=37` | `egd.bdpz` → `ehh` |
| `MechPushUnit.ApplyForReceiver` | `ehh.bdpe` |
| `PushUnitStep` / queue | `ejn` / `ejr` (shape-static) |
| Push presentation | `enb.bfcr` → `emz` → then `bfdi` |
| `UnitData.set_hex` | `UnitData.bfdi` |
| Occupancy lists | `Hex.bcyn` / `Hex.bcyl` inside `edf.bcuo` |
| Logic end-move publish | `eep.bdhw` → `eda.bcim` → `eda.cfia` |
| Logic hub / View hub | `eda` / `edb` |
| `Hex.lastCorpse` | `cfqf` / `bcxo` — **not** occupancy |
| Command: Fear style move | Core mech `teleport` (Arbitrator abilities) |

Full table: `experiments/direct_state_movement_trace/mono_live_pin_table.md`.
