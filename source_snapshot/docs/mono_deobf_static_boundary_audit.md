# Mono-to-Deobf Static Boundary Audit

Status: static-only. Runtime-unvalidated.

This audit records which parts of the Mono demo to Golden Era map have been improved as far as the current static artifacts allow, and which gaps are artifact-bound rather than merely unsearched. It exists to prevent future agents from repeatedly searching dead ends or overstating static evidence as runtime proof.

## Static artifacts currently used

| Artifact | Use | Boundary |
|---|---|---|
| Mono demo decompiled C# | Provides readable semantic names and method bodies for the older Mono build. | Old build may have structural drift; names are semantic evidence, not proof of current runtime behavior. |
| Golden Era DiffableCs shells | Provides current type/member shells and preserved exact names where available. | Most obfuscated method bodies are absent; shell shape alone cannot prove branch semantics. |
| Golden Era generated interop assemblies | Provides current callable generated type names, method ordinals, signatures, and support type shapes. | Interop metadata does not prove method bodies, call ordering, or safe Harmony hook points. |
| Golden Era ISIL dump | Provides current method body evidence where a type is present in the dump. | Coverage is incomplete for external assemblies such as `Hex.ResManager.dll`, `Hex.Sound.Runtime.dll`, and `Hex.Utils.dll` utility helpers. |
| Address-map builder output | Attaches labels to current native addresses from imported method-pointer maps plus helper inference. | Imported method-pointer labels now exist for ResManager, Sound.Runtime, and Utils; method bodies still require ISIL/native disassembly. |

## Exhausted or bounded static gaps

| Domain | Current static state | What was checked | Static boundary |
|---|---|---|---|
| `Hex.ResManager` loader families | Strong type, ordinal/signature, and imported method-pointer address map exists for singleton, asset lookup, all-assets, file enumeration, bundle lifecycle, and listener registration. | Generated interop metadata was built for `Hex.ResManager.dll`; Cpp2IL `attributeinjector` dummy DLLs were generated; method pointers were extracted to `method_pointers_hex_resmanager.csv`; `address_map_resmanager.json` now has 47 imported addresses. | No matching ISIL directory exists for `Hex.ResManager`, so current method-body/branch proof is unavailable with the current dump. Exact loader branch semantics require native disassembly/body import or runtime proof. |
| ResManager support types | `IResManagerListener -> fxi`, `ResBundle -> fxj`, `FileInfo -> fxk`, `ResFile -> fxl` are strong static aliases. | Mono/current shell shape plus generated interop support type metadata. | Callback order and mutation timing remain unproven without bodies or runtime. |
| `Hex.Sound.Runtime` core types | Strong aliases exist for sound groups, sound sets, clip data, player, source pool, mixer controller, playback receiver, and container types, now with imported method-pointer addresses. | Mono/current shell shape, generated interop metadata, Cpp2IL `attributeinjector` dummy DLLs, `method_pointers_hex_sound_runtime.csv`, and `address_map_sound_runtime.json` with 334 imported sound-runtime addresses. | The current ISIL dump still does not expose direct sound-runtime player bodies; direct playback contracts and music key selection are not proven. |
| Main-Hex spatial/map sound helpers | `eze+SoundInfo` and `ezi+PlaybackSounds` have direct current ISIL constructor body evidence. | Focused ISIL and DiffableCs reads. | These prove only helper struct field assignment and ownership context, not the full sound-runtime playback route. |
| `Hex.DirectoryHelper -> fwo` | Strong static alias and behavior model from Mono, now with imported method-pointer addresses and ordinal/signature candidates for the core helper sequence. | Generated interop metadata, DiffableCs shell, exact directory checks, focused ISIL content search, `method_pointers_hex_utils.csv`, and `address_map_hex_utils.json` with 31 imported Hex.Utils addresses. | Current `fwo`/`DirectoryHelper` method bodies are not present in the current ISIL dump. Individual helper aliases beyond the first ordinal/signature sequence still need body/call-site evidence. |
| `Hex.Utils` address map | Address-map output now includes imported `fwo` method labels plus the one scanned ISIL helper file. | `build_address_map.py --type-prefix Hex.Utils` with `method_pointers_hex_utils.csv`. | The scanned ISIL file is still `Hex/Hex/Utils/Pool\`1.txt`, not `DirectoryHelper`/`fwo`; utility path-normalization behavior cannot be body-proven from this dump. |


## Map quality gates now applied

| Gate | Current result | Why it matters |
|---|---|---|
| Simple-name collision rejection | The generated map now records rejected collisions separately under `rejectedSimpleNameCollisions`; current count is 118 after framework-root collision filtering. | Prevents misleading matches such as `Hex.*.Logger -> UnityEngine.Logger`, `Code.Network.*.Extensions -> Newtonsoft.Json.Schema.Extensions`, and other framework/simple-name overlaps from polluting implementation candidates. |
| Hex namespace migration evidence | `Hex`-root same-simple-name moves, such as `Hex.Session.Logic.* -> Hex.Session.Data.*` and `Hex.Session.City.Building* -> Hex.Session.Data.Building*`, are explicitly labeled as namespace migration candidates. | These are plausible structural drift patterns from the Mono build to the current deobf build, but remain static hypotheses unless body/runtime evidence is added. |
| Focus-scope candidate cleanup | After rejection and migration labeling, focus-scope rows no longer have generic `candidate` confidence entries; unresolved focus rows are `probable-static` rather than weak/simple collisions. The remaining 22 broad-map `candidate` rows are non-focus `Hex`-internal or global-to-`Hex` simple-name hypotheses and should not drive implementation without focused dossiers. | The map is cleaner for mod-relevant work: remaining uncertainty is mostly body/order proof, not type identity noise. |

## External address-map audit

| Artifact | Result | Static implication |
|---|---|---|
| `address_map_sound_runtime.json` | Now contains 337 addresses total, including 334 imported `Hex.Sound.Runtime` method labels plus helper entries. | Improves exact current method identity and patch-drift tracking for sound runtime; native disassembly now covers all 422 imported sound-runtime method rows, but full playback/music semantics still need focused interpretation. |
| `address_map_hex_utils.json` | Now contains 34 addresses total, including 31 imported `Hex.Utils` method labels plus helper entries. | Improves exact current method identity for `fwo`/DirectoryHelper candidates; native disassembly now gives instruction-level bodies for the imported utility methods, while managed source-level semantics remain manual/inferred. |
| `address_map_resmanager.json` | Now exists with 47 imported `Hex.ResManager` method labels. | Improves exact current method identity for resource loader/listener families and feeds native disassembly annotation. Loader branch semantics now have native instruction evidence in `native_disasm_resmanager.*`, but managed-level intent still requires manual interpretation or runtime proof. |
| Native disassembly import artifacts | `disassemble_method_pointers.py` now emits static native disassembly from exact method-pointer ranges. Current packs cover ResManager, Hex.Utils, Sound.Runtime, `Hex.Session.Battle`, `Hex.Session.City`, `Hex.Cheat.UI`, `Hex.UI`, `Hex.Session.Data`, `Hex.Map`, `Hex.Configs`, `Hex.Render`, `Hex.Storage`, `Hex.Session.UI`, `Hex.Session.Hud`, `Hex.Session.Logic`, and `Hex.Session.World`; `build_native_disasm_call_graph.py` combines them into `native_disasm_call_graph_external_domains.json/md` and `native_disasm_call_graph_core_gameplay_ui.json/md`. A full imported address map, `address_map_all_dummydll_methods.json`, provides 147,540 global call-target labels. Current core gameplay/UI graph: 4,069 methods, 23,012 direct-call edges, 18,082 labeled edges. Current broad mod-relevant graph: 9,442 methods, 52,964 direct-call edges, 42,023 labeled edges. Current all-Hex game-domain graph: 14,551 methods, 74,999 direct-call edges, 59,061 labeled edges. All 14,206 `Hex.*` method-pointer rows are covered by either named packs or `method_pointers_hex_remaining_game.csv`; the method count is higher than 14,206 because external game assemblies also contain obfuscated non-`Hex.*` support types covered by the named packs. | This proves native instruction shape and direct-call graph edges where method-pointer labels exist. It still does not reconstruct managed semantic intent, object lifetime, reachability, or runtime invocation order. |
| Native graph Mono-alias consolidation | `annotate_native_call_graph_with_mono.py` joins the all-Hex native direct-call graph to strong/probable type aliases from `mono_deobf_semantic_map.json`, while `classify_anchor_path_dossiers.py` prioritizes positive anchor paths for review. | This improves reviewer navigation and candidate selection only. Type aliases are static joins; method aliases are exact-name survivals or separately labeled ordinal candidates. They do not prove current method semantics, runtime reachability, hook safety, or behavior. |
| Focused high-priority anchor path review pack | `build_focused_anchor_path_review_pack.py` joins high-priority anchor triage rows, exact path dossiers, and the Mono-annotated native graph into `focused_anchor_path_review_pack_high_priority.json/md`. Current result covers 37 high-priority paths and 37 steps with 0 missing dossiers and 0 missing annotated edges; the latest gap split is 13 strong caller method aliases, 7 generic ordinal candidates, 12 parameter-mismatch ordinal candidates, 3 likely noisy constructor-drift ordinal candidates, 2 unmapped caller types, and 1 path with exact-name aliases on both endpoints. | This is a review/prioritization artifact only. It identifies static gaps such as ordinal-only method aliases and unmapped caller types; it does not prove runtime reachability, call ordering, or hook safety. |
| Unresolved high-priority static action queue | `build_unresolved_anchor_path_actions.py` converts the focused pack into `unresolved_anchor_path_actions_high_priority.json/md`. Current queue: 36 unresolved steps: 12 `body-xref-required`, 7 `confirm-ordinal-candidate`, 2 `map-current-type`, 3 `reject-or-remap-ordinal`, and 12 `target-endpoint-or-runtime-order`. | This is a static work queue only. It improves falsifiability by naming the next proof action for each unresolved path, but it does not prove runtime behavior or method semantics. |
| Unmapped high-priority current type notes | `unmapped_high_priority_current_type_notes.json/md` records the two `map-current-type` rows. `BhSubClassView::tqm` now has a current method dossier proving hero subclass UI binding calls; `BhUnitWindowPartyView::Awake` has DiffableCs shell evidence but no ISIL body in the current dump. | Both remain current-only/unmapped types, not Mono aliases. The note prevents repeated searches and names the exact static boundary for each. |
| Confirm ordinal-candidate static review | `confirm_ordinal_candidate_static_review.json/md` reviews the seven `confirm-ordinal-candidate` rows after generating current method dossiers. Result: 4 `supported-static`, 2 `weak-static`, and 1 `likely-misnamed` (`BuildingData::bgch` is a config lookup, not reliable evidence for `OnCreateOverriden`). | This upgrades/downgrades static confidence only. Runtime reachability and hook safety remain unproven. |

| High-priority action static review | `high_priority_action_static_review.json/md` consolidates the body/xref and target-endpoint dossier runs. Result: body/xref rows are 4 `supported-static`, 4 `weak-static`, 1 `likely-misnamed`, and 3 `missing-isil`; target endpoints are 5 `supported-static`, 2 `weak-static`, and 5 `missing-isil`. | This resolves some review actions into stronger static evidence, but weak/missing rows still require native disassembly, refreshed ISIL, or runtime proof. |
| Missing-ISIL native call graph supplement | `missing_isil_native_callgraph_supplement.json/md` covers high-priority rows where normal ISIL method dossiers fail. Result: 6 exact-label rows have outbound native-call edges only, 2 have both inbound and outbound edges, and 2 have inbound edges only. | This improves static identity/xref evidence for missing-ISIL methods, but does not provide managed body proof, runtime ordering, or hook safety. |
| Post-native high-priority static coverage | `post_review_anchor_path_static_queue.json/md` reduces the old 36-row unresolved queue to 13 `resolved-static` rows plus 23 still-cautious rows. `native_disasm_method_review_*.json/md` and `post_native_static_coverage.json/md` then provide exact native body review coverage for all 23 remaining rows, across 20 unique current methods. | High-priority current method body evidence is no longer missing for this queue. Remaining gaps are semantic interpretation, runtime reachability/order, and hook safety; those cannot be proven solely by the static map. |
| Static semantic interpretation review | `static_semantic_interpretation_review.json/md` interprets all 23 post-review cautious rows from exact native body reviews. Result: 4 `supported-static-semantic`, 4 `weak-static-semantic`, 5 `contradicts-mono-alias`, 3 `contradicts-or-weakens-mono-alias`, 5 `static-exhausted-accessor`, and 2 `current-only-static-body`; there are 0 missing interpretations. | This is the current static boundary for the high-priority queue. More progress is possible only through targeted manual native interpretation for a named method, refreshed/fuller ISIL output, new external anchors, or runtime proof. |
| Broad candidate static audit | `broad_candidate_static_audit.json/md` audits the 22 remaining broad `candidate` aliases. Focus rows have 0 candidate/weak-candidate entries. Result: 3 focus-adjacent candidates, 17 leave-candidate-boundary rows, and 2 plausible non-focus namespace migrations to leave candidate unless that domain is needed. `focus_adjacent_broad_candidate_review.json/md` then reviews the 3 focus-adjacent rows: 2 are supported static semantics and 1 is shell-only/static-exhausted. | Broad candidate uncertainty is now classified. Remaining broad candidate rows are outside current focus or lack body/callgraph evidence; improving them further would require a targeted domain need, refreshed ISIL, or new anchors. |
| Focus probable-static audit | `focus_probable_static_audit.json/md` classifies all 36 focusRows whose top candidate is `probable-static`. Result: 4 `safe-static-type-alias`, 16 `method-level-review-if-hooked`, and 16 `type-alias-only`; categories include magic UI migrations, city-building data migrations, and logic-to-data migrations. | Focus probable rows are now explicitly bounded as type-alias evidence. Method-level use still requires targeted dossiers/native review. |
| Static map completion boundary audit | `static_map_completion_boundary_audit.json/md` verifies the current broad static map state and reports `static-boundary-reached` with 0 blockers. It checks semantic-map counts, focus confidence, high-priority semantic interpretation, post-native coverage, broad candidate audit, focus-adjacent broad review, and focus probable audit. | This is a static boundary, not runtime proof. Future improvement requires a named target/domain, refreshed/fuller ISIL, new anchors, or runtime evidence. |

## Method-pointer extraction result

| Attempt | Result | Boundary |
|---|---|---|
| Added `experiments/cpp2il_readable_csharp/export_dummydll_method_pointer_map.ps1` to read `Cpp2ILInjected.AddressAttribute` from dummy DLL methods and convert method RVA to VA using the current `GameAssembly.dll` PE image base. | Running against the pre-existing `tmp/cpp2il_experiment/out_dev_dummydll` emitted 0 rows because that output did not contain method `AddressAttribute` data. | The pre-existing dummy DLLs are not enough. |
| Reran Cpp2IL to `experiments/cpp2il_readable_csharp/samples/latest_refresh/out_dummydll_with_attrs` with `--use-processor attributeinjector --output-as dummydll`. | Succeeded in 11.3s and generated address-attributed dummy DLLs. | Static-only; no game runtime involved. |
| Exported `method_pointers_from_dummydll_with_attrs.csv`. | Succeeded with 199,233 method address rows using image base `0x180000000`. High-value subsets: `Hex.ResManager` 51 rows, `Hex.Sound.Runtime` 422 rows, `Hex.Utils` 36 rows. | Provides method-pointer labels, not method body/control-flow proof. |
| Rebuilt external address maps from filtered imports. | `address_map_resmanager.json`, `address_map_sound_runtime.json`, and `address_map_hex_utils.json` now include imported method labels. | Further static gains require native body disassembly or deeper call-site/body reconstruction. |

## Full ISIL regeneration attempt

| Attempt | Result | Boundary |
|---|---|---|
| Ran current dev Cpp2IL `--output-as isil` against the Golden Era install. | Failed while writing `IsilDump\Hex\<PrivateImplementationDetails>{...}` because the ISIL output formatter sanitized path characters but not invalid Windows filename characters such as `<` and `>`. | This blocks a refreshed full ISIL dump on Windows with the unpatched tool. |
| Ran the same ISIL pass with `--use-processor stablenamer`. | Failed at the same invalid filename. | Stable naming does not avoid the invalid private-implementation type path. |
| Patched local Cpp2IL source `Cpp2IL.Core\OutputFormats\IsilDumpOutputFormat.cs` so `SanitizePathElement` also replaces `Path.GetInvalidFileNameChars()`. | Source-prepared only. Building the patched Cpp2IL tree is blocked during NuGet/MSBuild restore graph evaluation around `Cpp2IL.Core -> LibCpp2IL`, and the local `nuget.config` points at `https://nuget.samboy.dev/v3/index.json`, which fails TLS/auth in this environment. Public NuGet/ignore-failed-source overrides still exit during restore graph generation with no surfaced compiler error. | A patched ISIL exporter remains the best next static improvement, but it is currently a tooling/build problem, not a missing decomp search problem. Existing method-pointer maps are therefore the strongest current static evidence for external assemblies. |
## Practical implications

- It is now reasonable to use the Mono map to choose candidate current types and method families for ResManager, sound runtime, and path normalization.
- It is not reasonable to use this static map alone to patch broad generic resource loaders, invoke sound playback directly, or assume callback order.
- For static-only next steps, the highest-value improvement is now focused interpretation of selected native disassembly packs or focused interpretation of selected Sound.Runtime methods when a concrete question requires it. Method-pointer labels and native instruction dumps exist for the current high-value external domains.
- For runtime next steps, use narrow metadata/proof requests around the already-mapped candidate method families, not broad event-bus or generic-loader probes.

## Documentation rule

When adding future evidence, mark it as one of:

- `static-shell`: type/member shape only.
- `static-interop`: generated callable type/method metadata.
- `static-body`: current method body or branch evidence from ISIL/native disassembly.
- `runtime-metadata`: live metadata resolution without behavior proof.
- `runtime-proven`: observed behavior in the current game build.

Do not upgrade a surface to gameplay-safe solely because it has a strong Mono alias.







