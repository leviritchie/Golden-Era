# Obfuscation Mapping: Learnings & Architecture

## The problem

Every game hotfix re-obfuscates the IL2CPP type/method/field names. Our Harmony
patches and `GameMember` lookups reference the old names, which silently break
after a hotfix. We need to map old names → new names.

## What we learned

### 1. Index (TypeDefIndex order) is the stable identifier

Obfuscated names are assigned in definition order. A hotfix may insert or remove
types, but most types stay at the same index. Names shift alphabetically because
the obfuscator reassigns names in order — if 3 types are inserted at index 100,
every type after 100 gets a name that's ~3 positions later in the alphabet.

**Key insight:** same index = same type. Names are cosmetic. Match by position,
validate with structural similarity.

### 2. The alphabetic "shift" is real but per-region, not global

Earlier we hypothesized a global positional shift. This is wrong. The shift
varies by region — +3 in one area, 0 in another, -1 in another — depending on
where types were inserted or removed. The solver approach (interpolating shift
from anchors) failed because the shift isn't smooth across the entire sequence.

### 3. Heuristic anchors match functionality, not identity

`find_calculator_type()` and `find_forecast_result_type()` find types with
specific structural patterns (e.g., a method taking `DamageUiParams, bool`).
But between builds, functionality can MIGRATE from one type to another. The
old calculator (`elc`) and new calculator (`eky`) are DIFFERENT types — both
exist in both dumps, but the calculator pattern moved. These are NOT renames.

### 4. Most types keep the same name

Across a minor hotfix (12,173 → 12,169 classes), ~89% of obfuscated types
keep the same name. Only ~11% actually rename. Identity is the default.

### 5. Named types' methods also shift positionally

Types with readable names (`BhBuildingsManager`, `BhCityUISession`) don't
change names between builds, but their OBFUSCATED MEMBERS do. The same
index-based matching applies: methods at the same position in the method list
are the same method, just with a shifted obfuscated name.

### 6. Structural similarity alone is insufficient

Simple types (3 void methods, 0 fields) are structurally indistinguishable.
Two different types can have identical structure. Index position breaks
these ties.

## The current pipeline

```
dump_old.cs + dump_new.cs
        │
        ▼
map_obfuscation.py  ───  rename_map.json
  ├─ parse_dump()         ├─ type_renames
  ├─ build_name_sequence()│─ method_renames
  ├─ match_by_index()     ├─ field_renames
  └─ detect_signature_changes()  └─ breakpoints
        │
        ▼
verify_patch_surfaces.py  ───  report.json
  ├─ parse_patches()         ├─ patch_findings
  └─ verify_against_dump()   └─ summary
```

### map_obfuscation.py

Parses two Il2CppDumper `dump.cs` files. Extracts all classes with their
methods, fields, and properties. Matches obfuscated types by index alignment:
walking both sequences in order, matching `old[i]` to `new[i + offset]`.
When structural confirmation fails, detects insertion/deletion breakpoints
and adjusts the offset. Produces `type_renames`, `method_renames`, and
`field_renames`.

Does NOT handle:
- Method renames on named types (obfuscated methods on readable types)
- Types that migrated to a completely different index (rare)
- The gap between patch baseline and the "old" dump

### verify_patch_surfaces.py

Scans the OfflineUnlockMod C# source for all Harmony `[HarmonyPatch]`
attributes, `GameMember.FindMethods()`, `AccessTools.Constructor()`, etc.
Cross-references each against the new dump. Applies `type_renames` and
`method_renames` from the rename map. Reports orphans, signature mismatches,
and gone types.

### analyze_hotfix.py

Reads the verify report and prints a human-readable summary with
recommended actions.

## How to use after a hotfix

1. Decompile the new build with Il2CppDumper → `dump_new.cs`
2. Run the pipeline:
   ```
   python tools/map_obfuscation.py dump_old.cs dump_new.cs -o rename_map.json
   python tools/verify_patch_surfaces.py dump_new.cs --rename-map rename_map.json -o report.json
   ```
3. Review the report. Fatal issues fall into categories:
   - **Obfuscated type renames**: should be resolved by `type_renames`
   - **Method renames on named types**: need manual mapping (see below)
   - **Genuinely removed types/methods**: the game changed, patch needs rewrite
   - **Diagnostic probes**: gated by flag files, can be ignored
4. For remaining named-type method orphans, compare old vs new method lists
   by position. Methods at the same position with the same signature are
   the same method. Add manual entries to the rename map.

## Manual overrides

Some mappings span multiple builds. The patches may reference names from
a build older than the "old" dump. These need manual overrides added to
the rename map:

```json
{
  "type_renames": {
    "ejz": "eky"
  },
  "method_renames": {
    "ejz.bdwu": "ddu",
    "ejz.oez": "bemf"
  }
}
```

## Key files

| File | Purpose |
|---|---|
| `tools/map_obfuscation.py` | Build rename map from two dump.cs |
| `tools/verify_patch_surfaces.py` | Cross-reference patches against dump |
| `tools/analyze_hotfix.py` | Human-readable analysis of verify report |
| `tools/il2cpp_out_20260506/dump.cs` | "Old" baseline dump |
| `tools/il2cpp_out_live/dump.cs` | Live/current build dump |
| `tools/il2cpp_out_new/dump.cs` | Newest build dump |
| `tools/rename_map_index.json` | Index-based rename map (20260506→new) |
| `tools/rename_map_patched.json` | With manual overrides for patch baseline |
