# Shared Ghidra project (Olden Era GameAssembly)

Owner: `tools/ghidra_oe/` (`oe_ghidra.py`, `make_labels.py`, `scripts/ImportOeSymbols.java`, `scripts/OeQuery.java`).
Purpose: read native IL2CPP method bodies for the engine questions in
`docs/broken_feature_sweep_20261021.md` (event dispatchers, remap refusals, untraced verbs).

## Layout (build 25672315)

| Path | What |
|---|---|
| `V:\olden_port_work\ghidra\inputs_25672315\` | copies of stock `GameAssembly.dll` + `global-metadata.dat`, `SHA256SUMS` (GA `D9972B0E…`, metadata `99117DC9…` — same as `idx2_live_25672315` and the Golden Era install) |
| `V:\olden_port_work\ghidra\labels_25672315.tsv` | `make_labels.py` output (regenerable) |
| `V:\olden_port_work\ghidra\project\OE_25672315.*` | the Ghidra project (Ghidra 12.1.4, JDK 21 at `V:\Tools\jdk`) |
| `V:\olden_port_work\ghidra\queries\` | default query outputs |

## What the labels give you

- **Functions** at every IL2CPP method entry from `idx2_live_25672315/gen/native_addresses.tsv`
  (207,182 methods → 153,653 distinct VAs; identical bodies are folded, so one VA can carry several methods).
  Primary name `NativeType$$native` (e.g. `Hex.Session.Battle.BhBattleEnd$$bhlq`); the interop name from
  `port_index.tsv` is a secondary label (`…BhBattleEnd$$Method_Public_Void_PDM_0`); the plate comment holds
  assembly, interop member, signature and token. 82,778 methods join to interop names (the index covers the
  assemblies the plugin binds against).
- **Metadata-usage globals** decoded from `.data` (83,120): `TypeInfo$$…`, `Il2CppType$$…`, `MethodInfo$$…`,
  `StringLiteral_<i>_<text>`, plus index-only `FieldInfo_<i>` / `MethodRef_<i>`. Metadata v31 encodes a slot as
  `(kind << 29) | (index << 1) | 1` (low 32 bits) until first use. In a decompile, `FUN_18048d410(&TypeInfo$$X)`
  is the lazy metadata init and `*(TypeInfo$$X + 0xb8)` is X's static fields — usually how you recognise which
  class a body touches.
- **Strings are thin.** All 15,892 metadata strings are labelled, but they are mostly framework text; game
  literals (`"undead"`, `_siege_elements/`) are not in the 25672315 string table at all. Start from method
  VAs / names, not string xrefs.
- **No auto-analysis.** Imported with `-noanalysis`; functions/references come from flow disassembly of the
  labelled entries. `callers` therefore finds direct calls and jumps only — vtable/interface dispatch and
  delegate invocation are missing. If a target needs them, run a scoped analysis on a copy, not the shared project.
- **No struct layouts / `il2cpp.h`.** Field accesses decompile as `*(param + 0x48)`; map offsets with the
  interop dummy DLLs (`FieldOffset` attributes) or the mono decomp.

## Use

```bash
python tools/ghidra_oe/oe_ghidra.py query decomp "Hex.Session.Battle.BhBattleEnd$$bhlq"
python tools/ghidra_oe/oe_ghidra.py query callers 0x182208240
python tools/ghidra_oe/oe_ghidra.py query find "Hex.UI.City.BhCityUIs$$*"
```

- Queries open the project `-readOnly`. Ghidra locks a project per process, so `oe_ghidra.py` serialises
  queries and setup on `project.turn.lock` (waits up to `--wait` s, then fails with a diagnostic). Batch
  several targets into one call: each call pays the JVM start + program open.
- Obfuscated non-MonoBehaviour types are renamed on this build (e.g. mono `Hex.UI.City.BhCityUIs` has no
  same-named live type). Find them by caller/callee shape from a named neighbour, then record the pin in
  `GameSymbols` / the current-scope overrides as usual.
- Setup (`oe_ghidra.py setup [--force]`) re-imports and relabels; one writer only. Claim it on the cross-agent
  board if other agents are querying.
- Evidence tier: a decompile is **source/static** evidence for the native body on this exact GameAssembly sha.
  It does not prove runtime behaviour. Golden/D477 RVAs in older docs must be re-pinned before use.

## Measured (setup on this machine, 2026-10-21)

| Step | Wall | Notes |
|---|---|---|
| `make_labels.py` | ~3 s | 32 MB `labels_25672315.tsv` |
| `setup` (import `-noanalysis` + label) | 275 s | flow disassembly from 153,653 entries 161 s; 153,652 functions + 83,120 data labels; heap cap 12 GB |
| project on disk | 1.1 GB | `V:\olden_port_work\ghidra\project` |
| one `query` call | ~12 s | mostly JVM start + program open; decompile itself is sub-second per function |

## Known gaps / follow-ups

- `callers` misses Unity event, vtable and delegate dispatch (e.g. `BhBattleEnd.OnBtnExit`'s successor `bhlq`
  has only a DATA reference from the method table). A scoped `-process` analysis on a private project copy is
  the escape hatch.
- `tools/port_current/symbol_remap/native_body.py` (`NativeSide._mem`) now decodes the v31 layout (fixed
  2026-10-21; it used `q >> 1`, `kind = tok >> 29`). On 3,000 sampled live Hex bodies, named metadata (M) features
  went from 944 to 2,586 bodies. Hex bodies carry no string-literal (S) usages on 25672315; framework assemblies do
  (10-25% of bodies). Remap outputs change, so a calibrated golden↔live re-run is still owed. It needs the golden
  `D47706EB…` GameAssembly.dll, which is not on disk.
- No golden (D477) binary on disk, so no golden↔live function diff program yet.
