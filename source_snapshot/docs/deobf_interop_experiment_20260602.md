# Deobfuscated Interop Experiment - 2026-06-02

Goal: evaluate BepInEx IL2CPP signature-derived names as an analysis aid for Steam hotfix remaps, without migrating `OfflineUnlockMod` runtime hooks away from `GameSymbols.cs`.

The Nexus BepInEx redistribution documents this config:

```ini
[IL2CPP]
UnhollowerDeobfuscationRegex = ^[a-z]{2}$|^[a-z]{3}$|^[a-c][a-z]{3}$
```

That causes short obfuscated IL2CPP type/member names to be renamed by signature while preserving the original short name in `ObfuscatedNameAttribute`. For this repo, the useful output is not the deobfuscated wrapper name itself; it is the old/new `ObfuscatedNameAttribute` value attached to a stable generated owner/member/signature.

## Isolated Run

Use an isolated copy of the official Steam build. Do not run this experiment in the Golden Era install and do not deploy `OfflineUnlockMod` into the experiment tree.

Suggested layout:

```text
V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Deobf Experiment\
```

Install BepInEx 6.0.0-be.755 there, set the regex above in `BepInEx\config\BepInEx.cfg`, delete `BepInEx\interop\`, then launch the game once and exit after interop generation completes.

Copy the generated interop folders into dated repo-local scratch folders. These folders are ignored by `.gitignore` when named under `tools/il2cpp_out_*`, so prefer a non-committed artifact path such as:

```text
tools\il2cpp_out_20260602_golden_era_deobf_interop\
tools\il2cpp_out_20260602_official_deobf_interop\
```

## Probe Command

Run the new probe against deobfuscated interop folders:

```powershell
dotnet run --project tools\deobf_symbol_probe\DeobfSymbolProbe.csproj -- `
  --old tools\il2cpp_out_20260602_golden_era_deobf_interop `
  --new tools\il2cpp_out_20260602_official_deobf_interop `
  --assembly Hex.dll `
  --game-symbols "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\GameSymbols.cs" `
  --json-out artifacts\deobf_symbol_probe_20260602\hex_symbol_probe.json `
  --md-out artifacts\deobf_symbol_probe_20260602\hex_symbol_probe.md
```

Interpretation:

- `GameSymbolsRelevantMethodRenames` and `GameSymbolsRelevantFieldRenames` are candidate `GameSymbols.cs` hint updates.
- A row is only a candidate. Still verify owner semantics, parameter types, return type, field type, and decompiled/xref context before editing hooks.
- Do not use same short obfuscated name identity as proof. Obfuscated names are reused across patches.

## Expected Follow-Up

After applying any accepted `GameSymbols.cs` updates, regenerate the normal current dump and run:

```powershell
python tools\verify_patch_surfaces.py tools\il2cpp_out_20260602_official_current\dump.cs `
  --source "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod" `
  --no-probes `
  -o artifacts\deobf_symbol_probe_20260602\verify_patch_surfaces_after_remap.json
```

The deobf probe is a remap assistant. The startup fail-fast registration gates remain the runtime contract.

## Observed Run - 2026-06-02

Isolated experiment folders:

```text
V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era Deobf Experiment\
V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\
```

Build inputs:

- Golden Era `GameAssembly.dll`: 95,546,368 bytes, 2026-05-29 18:35:25.
- Official Steam `GameAssembly.dll`: 95,436,288 bytes, 2026-06-02 16:53:53.

Both experiment copies launched with empty `BepInEx\plugins`, cleared interop/cache, `UnityLogListening=false`, and the deobfuscation regex enabled.

Generated interop:

- Golden Era deobf `BepInEx\interop\Hex.dll`: 30,617,600 bytes.
- Official deobf `BepInEx\interop\Hex.dll`: 30,749,696 bytes.

Probe output:

```text
artifacts\deobf_symbol_probe_20260602\hex_symbol_probe.json
artifacts\deobf_symbol_probe_20260602\hex_symbol_probe.md
```

Result summary:

- `Hex.dll` had 1,855 stable type-owner mappings whose `ObfuscatedNameAttribute` changed between Golden Era and current official.
- 100 type-owner mappings touched existing `GameSymbols.cs` hint names.
- No method or field `ObfuscatedNameAttribute` deltas were reported in generated `Hex.dll`; this BepInEx output appears useful primarily for owner/type remaps, not direct member-name remaps.

High-signal examples from the GameSymbols-relevant type list:

- `bva -> bvb` for `MonoBehaviourPublicTrloBonoObbaTrBhquadUnique`.
- `bcu -> bcv` for `ObjectPublicInbrStInbrCoStMaInbrUnique`.
- `beg -> beh` for `ObjectPublicInbsTeInbsCoReVebsInUnique`.
- `eyy -> eza` for `MonoBehaviourPublicBociUnique`.
- `ezb -> ezd` for `ObjectPublicPrciInSiciEAMaciEAciUnique`.

Use those only as owner candidates. Member names still need the normal dump/decompile/signature verification path.

## Method Bridge Follow-Up

Method and field wrappers do not carry `ObfuscatedNameAttribute` in the generated interop, so method remapping needs a bridge:

1. Deobf interop supplies a stable owner/method/signature identity.
2. Normal interop supplies the raw obfuscated owner/method names.
3. The bridge now prefers exact evidence matches first (`CallerCountAttribute` + `CachedScanResultsAttribute`) and only falls back to same-signature ordinal alignment when evidence cannot pick a unique candidate.

Generated normal official interop from the isolated official experiment copy after blanking `UnhollowerDeobfuscationRegex`. Inputs were copied into:

```text
artifacts\deobf_symbol_probe_20260602\golden_deobf_interop\Hex.dll
artifacts\deobf_symbol_probe_20260602\golden_normal_interop\Hex.dll
artifacts\deobf_symbol_probe_20260602\official_deobf_interop\Hex.dll
artifacts\deobf_symbol_probe_20260602\official_normal_interop\Hex.dll
```

Probe output:

```text
artifacts\deobf_symbol_probe_20260602\hex_method_bridge.json
artifacts\deobf_symbol_probe_20260602\hex_method_bridge.md
artifacts\deobf_symbol_probe_20260602\hex_method_bridge_evidence.json
artifacts\deobf_symbol_probe_20260602\hex_method_bridge_evidence.md
```

Result summary:

- Old stable bridged methods: 60,414.
- New stable bridged methods: 60,513.
- Raw method rename candidates: 30,007.
- Structured `GameSymbols.cs` hint breakdown: 620 method hints, 49 type hints, 51 field hints.
- Method-name candidates after structured hint parsing: 833.
- Unambiguous method-name candidates after evidence matching: 661.
- Ambiguous method-name candidates after evidence matching: 172.
- Evidence-resolved method-name candidates: 661.
- Owner-only GameSymbols candidates: 49.

Use the 661 evidence-resolved method-name candidates as first-pass remap proposals. Use the 172 ambiguous candidates only after checking decompiled body/xrefs or another disambiguator; same-signature ordinal matching is not enough proof by itself.

## Fingerprint Scoring Pass

The production bridge in `tools/deobf_method_bridge/` now scores each candidate with body fingerprint, `CachedScanResultsAttribute`/`CallerCountAttribute` evidence, and ordinal proximity instead of treating fingerprint as a standalone selector.

Current output on the official-vs-golden experiment pair:

```text
artifacts\deobf_symbol_probe_20260602\hex_method_bridge_fingerprint2.json
artifacts\deobf_symbol_probe_20260602\hex_method_bridge_fingerprint2.md
```

Result summary:

- GameSymbols method-name candidates: 833.
- Unambiguous GameSymbols method-name candidates: 833.
- Ambiguous GameSymbols method-name candidates: 0.
- Fingerprint-resolved method-name candidates: 831.
- Evidence-resolved method-name candidates: 2.
- Ordinal-fallback method-name candidates: 0.

This is now the default automated pass for method cleanup against the current experiment build. It still does not touch `GameSymbols.cs`; it only produces a ranked/selected report for review.

## Current Official Build Compile Test

To avoid touching either ground-truth `GameSymbols.cs` or the working Golden Era install, a disposable source copy was created under:

```text
artifacts\bridge_current_build\src\OfflineUnlockMod\
```

The temp copy was built against the current official experiment interop:

```text
V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx
```

The bridge was applied only to the temp `GameSymbols.cs` copy using `artifacts\bridge_current_build\apply_bridge_to_temp_gamesymbols.js`. The safe patcher only appends hints inside `MethodSymbol(...)` initializers and `string[] { ... }` hint arrays. On the June 2 current-official experiment inputs it added 334 method hints and 25 type hints.

Result: the mod does not yet build against the current official interop, so runtime symbol-registration validation cannot be performed yet. After bridge-applied temp symbols plus a small first compile-compatibility pass (`fvj -> fwz`, stale `ezx` typed town wrapper disabled, stale `dyu` wrapper path neutralized), `dotnet build` still reported 185 compile errors from direct typed interop references. Representative blockers:

- `BattleForecastProbe`: `dyt`/`dyu` source shape changed.
- Battle-pool hooks: `bei` constructor no longer has the old 3-argument shape.
- Selected-HUD/ability hooks: `BhUnitControlsView`, `BhUnitAbilityView`, `emb`, `dwr`, `Unit`, and `ecf` fields/properties moved or changed shape.
- Main-menu/loader hooks: `MainMenuNavigationView.quickStartButton`/related fields and `Loader.utt` no longer exist under those names.
- Terrain renderer direct type `beg` is gone in the current official interop.

Conclusion: the method bridge is not the current limiting factor. The next production step is an automated direct-reference/member port for compile-time interop usages, then rerun the same temp bridge build and only then deploy to the isolated official experiment folder for runtime registration testing.

## Centralization Audit Gate

The old audit script did exist: `tools/audit_obfuscated_symbols.py`. The process failure was discoverability and scope. It was referenced in lower-level maintenance docs, but not in the top-level agent notes or this bridge runbook, and it mainly reports raw executable symbol literals/global-symbol contexts.

For current official patch repair, run both audits from repo root:

```text
python tools\audit_obfuscated_symbols.py --runtime-only
node tools\audit_direct_interop_refs.js
```

Current June 3 baseline:

- Raw runtime executable-symbol audit: 45 findings.
- Direct typed interop audit: 453 findings, written to `artifacts\direct_interop_audit_20260603\direct_interop_refs.md`.

The second count is the compile-port backlog exposed by the bridge experiment: direct `global::abc`, `typeof(abc)`, `Il2CppReferenceArray<abc>`, `new abc(...)`, generated member/property access, and fragile named generated fields outside `GameSymbols.cs`. Reducing this backlog is required before a bridge-patched temp build can validate runtime registration on the current official interop.
