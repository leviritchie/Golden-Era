# Schemas

JSON Schema (Draft 2020-12) for recovery artifacts:

| File | Purpose |
| --- | --- |
| `queue_item.schema.json` | Claimable work-queue items |
| `proof_ledger_entry.schema.json` | Per-method proof ledger rows |
| `input_manifest.schema.json` | Pinned input path manifest |
| `ir_method.schema.json` | Lifter IR method documents |
| `rename_map_entry.schema.json` | Phase 2 per-type rename decisions |
| `oracle_trace.schema.json` | Phase 3 oracle_traces fixtures |
| `direct_state_card.schema.json` | Direct State write-body symbol cards (`direct_state_cards/`) |

Validate:

```powershell
cd experiments/olden_cs_recovery
python -m olden_cs_recovery.schema_validate --manifest --all-queue --ledger --oracle
```
