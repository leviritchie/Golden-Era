# JSON Schema validators for olden_cs_recovery

Run from `experiments/olden_cs_recovery`:

```powershell
python -m olden_cs_recovery.schema_validate --manifest --all-queue --ledger
```

IR method files under `ir/*.ir.json` validate against `ir_method.schema.json` when written by the lifter.

Rename map entries under `rename_map/entries/*.json` validate against `rename_map_entry.schema.json` when written by the renamer.

Oracle fixtures under `oracle_traces/**/*.oracle.json` validate against `oracle_trace.schema.json`:

```powershell
python -m olden_cs_recovery.schema_validate --oracle
```
