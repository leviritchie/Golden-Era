# Mono Hex Utils Static Evidence

Status: source-generated/static-only. Runtime-unvalidated.

This dossier maps the old Mono demo `Hex.Utils.dll` utility surface against the current Golden Era Cpp2IL utility shell. It matters because `Hex.ResManager` relies on these helpers for bundle asset path normalization and matching.

Evidence boundary: static Mono decompilation and current DiffableCs shell only.

## Type map

Generated interop metadata artifact: `experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map_hex_utils.json`.

| Mono semantic type | Current deobf type | Confidence | Evidence |
|---|---|---|---|
| `Hex.DirectoryHelper` | `fwo` | strong-static | Static utility class with the same method count and same signatures: relative path, file path without extension, parent path, file name, slash normalization, lower-case path, contains, and equality helpers. |

## Behavior captured from Mono

- `GetPathWithAltSeparator(path)` replaces backslashes with forward slashes.
- `GetLowerCasePath(path)` lowercases paths after null/empty checks.
- `Contains(path, containedPath)` normalizes slashes, lowercases, then matches path components from the first matching contained segment.
- `IsEquals(path1, path2)` normalizes slashes, lowercases both, then compares exact strings.
- `GetFilePathWithoutExtension(path)` splits on `.` and concatenates all segments except the final extension segment.

## Mod relevance

- Native `ResManager` stores bundle asset paths under `assets/resources/...` and uses this helper family for case-insensitive path matching.
- Custom bundle assets should use normalized resource-style paths and avoid relying on platform-specific slash direction.
- When replacing sidecar asset loaders with native `ResManager`, path bugs should be investigated through `DirectoryHelper` semantics before adding fallback path probes.

## Unresolved gaps

- Current `fwo` generated interop metadata plus imported method-pointer evidence proves static callable signatures, ordinals, and native virtual addresses. Method bodies are still not present in DiffableCs/ISIL, so individual semantic method-name aliases remain ordinal/signature candidates rather than body-proven claims.
- The current build may have additional callers or changed error behavior around malformed path arrays; that is not proven from this utility shell alone.



## Hex.Utils ISIL note

`build_address_map.py --type-prefix Hex.Utils` scanned one ISIL file, but exact directory checks show that file is `Hex/Hex/Utils/Pool\`1.txt`, not `DirectoryHelper`/`fwo`. A focused ISIL content search for `fwo`, `DirectoryHelper`, and the generated runtime type produced no matches. Therefore current utility path-normalization behavior is supported by Mono source, DiffableCs shell, generated interop metadata, and imported method-pointer addresses, but not current ISIL method bodies.

## Current method-pointer evidence

Artifacts:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/method_pointers_hex_utils.csv`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/address_map_hex_utils.json`

`out_dummydll_with_attrs` was generated with Cpp2IL `attributeinjector`, then `export_dummydll_method_pointer_map.ps1` converted `Cpp2ILInjected.AddressAttribute` RVAs to current virtual addresses using `GameAssembly.dll` image base `0x180000000`. This is static native address evidence, not method-body evidence.

| Mono `DirectoryHelper` method | Current `fwo` candidate | VA | Evidence level |
|---|---|---:|---|
| `GetRelativePath(string,string)` | `bmmy(string,string)` | `0x181E57760` | ordinal + signature + imported method pointer |
| `GetFilePathWithoutExtension(string)` | `bmmz(string)` | `0x181E57960` | ordinal + signature + imported method pointer |
| `GetFilePathWithoutNameAndExtension(string)` | `bmna(string)` | `0x181E57A20` | ordinal + signature + imported method pointer |
| `GetFileNameWithoutExtension(string)` | `bmnb(string)` | `0x181E57AA0` | ordinal + signature + imported method pointer |
| `GetPathWithAltSeparator(string)` | `bmnc(string)` | `0x181E57B10` | ordinal + signature + imported method pointer |
| `GetLowerCasePath(string)` | `bmnd(string)` and wrapper aliases sharing `0x181E57C40` | `0x181E57C40` | ordinal + signature + imported method pointer; wrappers/aliases unresolved |
| `Contains(string,string)` | `bmne(string,string)` | `0x181E57C90` | ordinal + signature + imported method pointer |
| `IsEquals(string,string)` | `bmnf(string,string)` and alias `cbb(string,string)` sharing `0x181E57E80` | `0x181E57E80` | ordinal + signature + imported method pointer; alias unresolved |

The current `fwo` type has additional string helper aliases/wrappers after the Mono-sized core sequence (`dpx`, `etb`, `giq`, `hmb`, `hqz`, `imy`, `ipt`, `je`, `kdt`, `lyx`, `mib`, `nck`, `nkj`). These are intentionally left unlabeled until body or call-site evidence distinguishes them.


## Native disassembly evidence

`experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_hex_utils.json/md` now disassembles all 36 imported `Hex.Utils` method-pointer rows from the current `GameAssembly.dll`, with 219 direct calls observed and 94 calls annotated with known address-map targets. This gives instruction-level body evidence for `fwo`/DirectoryHelper candidates while preserving the static-only boundary.
