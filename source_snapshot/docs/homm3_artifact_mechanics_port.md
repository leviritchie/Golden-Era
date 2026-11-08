# HoMM3 Artifact Mechanics Port

Status: active contract for ported SoD+HotA artifacts. **Proof boundary: generated-artifact validated only.** Runtime equip, billboard pickup, and combat effect behavior remain unvalidated until separately exercised.

## What This Owns

Every catalog artifact under `custom_factions/artifacts/homm3_artifact_catalog.json` must carry non-empty Olden Era bonus rows and effect-only player text. Empty `bonuses` / `mechanicsStatus: text_only` are forbidden.

Authoritative sources, in order:

1. `custom_factions/artifacts/homm3_artifact_mechanics.json` — curated bonuses + descriptions (`native_exact` or `native_substitute`). Non-player `notes` may record remap rationale; tooltips must not.
2. `custom_factions/artifacts/homm3_artifact_slot_overrides.json` — curated OE `slotOe` remaps where literal H3→OE mapping makes combination sets unwinnable (OE has 4 accessory slots; H3 has 5 Misc). Current: Loins of Legion → `belt`.
3. `tools/homm3_import/generate_homm3_artifact_mechanics_table.py` — regenerates the mechanics table.
4. `tools/homm3_import/build_homm3_artifact_catalog.py` — applies the table + slot overrides onto the catalog (`--apply-mechanics-only` when HD Edition LOD data is unavailable).
5. `tools/homm3_import/generate_homm3_artifact_core_overlay.py` — emits DB item rows + Lang texts into `generated_core_overlay`.
6. `tools/validate_homm3_artifact_port_contract.py` — fail-closed: curated coverage, no empty/duplicate bonuses, catalog↔overlay↔Lang parity, set wearability under OE slot capacity.

## Status Labels

| Status | Meaning |
| --- | --- |
| `native_exact` | Bonus rows match a known OE donor shape for the claimed effect family. |
| `native_substitute` | Real OE effect shipped; player text describes only that effect (war machines, water items, per-spell immunities, H3 schools → OE day/night/primal/space, etc.). |

Legacy `text_only` / `mapped` / `partial` statuses must not appear in the catalog after mechanics apply.

## Rebuild

```powershell
$env:PYTHONUTF8 = '1'
python tools/homm3_import/generate_homm3_artifact_mechanics_table.py
python tools/homm3_import/build_homm3_artifact_catalog.py --apply-mechanics-only
python tools/homm3_import/generate_homm3_artifact_core_overlay.py
python tools/validate_homm3_artifact_port_contract.py
```

Full LOD/icon rebuild still uses `build_homm3_artifact_catalog.py` without `--apply-mechanics-only` when HD Edition data is present; mechanics apply runs at the end of that path too.

## Explicit Non-Claims

- Does not prove live equip or combat behavior.
- Does not redesign combination item-set tier bonuses in `homm3_artifact_sets.json`.
- Does not add Harmony/runtime war-machine, water, or per-spell immunity systems.
