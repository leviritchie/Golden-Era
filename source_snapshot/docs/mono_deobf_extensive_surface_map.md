# Extensive Mono Demo to Golden Era Surface Map

Status: static-only, runtime-unvalidated.

Purpose: use the older readable Mono demo as semantic evidence against the current Golden Era IL2CPP/decompiled build. This document is the entry point; raw generated artifacts remain under `experiments/cpp2il_readable_csharp/samples/latest_refresh`.

## Evidence boundary

- Static evidence can identify likely current types, methods, call edges, and review priorities.
- Static evidence does not prove runtime invocation order, Unity object lifetime, hook safety, or gameplay behavior.
- Missing ISIL does not always mean unmapped: the native method-pointer/call graph may still have exact-label evidence.
- Weak or likely-misnamed rows must not be used as implementation truth without more evidence.

## Broad type map

| Metric | Count |
|---|---:|
| Mapped Mono types | 2247 |
| Focus mapped Mono types | 573 |
| Strong static matches | 2129 |
| Probable static matches | 96 |
| Candidate matches | 22 |
| Weak candidates | 0 |
| Rejected simple-name collisions | 118 |

Artifact: `mono_deobf_semantic_map.json/md`.

## Native graph and focused high-priority map

| Artifact | Result |
|---|---|
| Mono-annotated native graph | 37 high-priority focused paths are review-packed from the all-Hex native graph. |
| Unresolved action queue | 36 unresolved steps split as `{'body-xref-required': 12, 'confirm-ordinal-candidate': 7, 'map-current-type': 2, 'reject-or-remap-ordinal': 3, 'target-endpoint-or-runtime-order': 12}`. |
| Confirm ordinal review | `{'supported-static': 4, 'weak-static': 2, 'likely-misnamed': 1}`. |
| Body/xref and endpoint review | `{'bodyXref': {'supported-static': 4, 'weak-static': 4, 'likely-misnamed': 1, 'missing-isil': 3}, 'targetEndpoint': {'supported-static': 5, 'weak-static': 2, 'missing-isil': 5}}`. |
| Missing-ISIL native supplement | `{'native-callgraph-outbound-only': 6, 'native-callgraph-inbound-outbound': 2, 'native-callgraph-inbound-only': 2}`. |

## Current static confidence buckets

### Supported static evidence

These rows have enough static evidence to use as strong candidates for further native-friendly design, while still requiring runtime proof before gameplay mutation or hook-safety claims.

- Broad type aliases with `strong-static` or `probable-static` confidence in `mono_deobf_semantic_map.json`.
- Confirm ordinal rows marked `supported-static` in `confirm_ordinal_candidate_static_review.md`.
- Body/xref and target endpoint rows marked `supported-static` in `high_priority_action_static_review.md`.
- Missing-ISIL rows with exact native labels and inbound/outbound edge evidence in `missing_isil_native_callgraph_supplement.md`, but only as native call-graph evidence.

### Weak or unresolved evidence

- `weak-static` rows in action reviews: semantically adjacent, but not exact enough to implement from alone.
- `likely-misnamed` rows: current method exists but the Mono candidate name likely describes the wrong semantic.
- `missing-isil` rows without enough native graph context: use native disassembly or runtime metadata next.
- `target-endpoint-or-runtime-order` rows: even exact endpoint identity may not prove call order or mutation timing.

## Recommended workflow for future surface work

1. Start with this document, then open `mono_deobf_semantic_map.md` for broad type identity.
2. For gameplay/UI surfaces, check `focused_anchor_path_review_pack_high_priority.md` and `unresolved_anchor_path_actions_high_priority.md`.
3. If an action has already been reviewed, prefer `confirm_ordinal_candidate_static_review.md`, `high_priority_action_static_review.md`, and `missing_isil_native_callgraph_supplement.md` over re-searching.
4. If ISIL is missing, check the native call graph before declaring the method unmapped.
5. Promote static candidates only through explicit evidence labels: `static-shell`, `static-interop`, `static-body`, `native-callgraph`, `runtime-metadata`, `runtime-proven`.

## Primary artifacts

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_call_graph_with_mono_aliases_all_hex_game_domains.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/focused_anchor_path_review_pack_high_priority.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/unresolved_anchor_path_actions_high_priority.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/confirm_ordinal_candidate_static_review.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/high_priority_action_static_review.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/missing_isil_native_callgraph_supplement.md`
- `docs/mono_deobf_static_boundary_audit.md`

## Post-native static coverage

After review-aware queue consolidation, the high-priority action set is now split into 13 `resolved-static` rows and 23 rows that still need semantic caution. All 23 remaining rows now have exact native disassembly body review coverage in `post_native_static_coverage.md`; remaining boundaries are runtime reachability, call order, high-level managed intent, or hook safety rather than missing current native body evidence.

Key artifacts:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/post_review_anchor_path_static_queue.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_method_review_high_priority.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_method_review_weak_static.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_method_review_reject_remap.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/native_disasm_method_review_current_only_types.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/post_native_static_coverage.md`

## Static semantic interpretation layer

`static_semantic_interpretation_review.md` interprets every one of the 23 post-review cautious rows using exact native body reviews. Current outcome split: 4 `supported-static-semantic`, 4 `weak-static-semantic`, 5 `contradicts-mono-alias`, 3 `contradicts-or-weakens-mono-alias`, 5 `static-exhausted-accessor`, and 2 `current-only-static-body`.

Practical boundary: for the high-priority queue, current native body evidence is now present for every row. Further static gains would require deeper manual native instruction interpretation for a specific method, a refreshed/fuller ISIL export, or additional external semantic anchors. Broad automatic static mapping has reached a useful boundary for this queue.

Artifact: `experiments/cpp2il_readable_csharp/samples/latest_refresh/static_semantic_interpretation_review.md`.

## Broad candidate audit

`broad_candidate_static_audit.md` audits the 22 remaining broad `candidate` type aliases outside the high-priority queue. Focus rows have no `candidate` or `weak-candidate` entries. Of the 22 broad candidates, 17 are generic/simple-name or weak non-focus namespace migrations, 2 are plausible non-focus namespace migrations, and 3 are focus-adjacent.

`focus_adjacent_broad_candidate_review.md` reviews those 3 focus-adjacent rows: `Hex.Pick.StartInfo -> Hex.Arena.StartInfo` is supported-static-semantic, `Hex.Arena.Logic.Side -> Hex.Session.Data.Side` is supported-static-semantic-broad, and `Hex.Session.World.MapBonus -> Hex.Map.MapBonus` is static-exhausted-shell-only with no ISIL/native graph evidence in current artifacts.

Artifacts:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/broad_candidate_static_audit.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/focus_adjacent_broad_candidate_review.md`

## Focus probable-static audit

`focus_probable_static_audit.md` classifies the 36 focus rows whose best type candidate remains `probable-static`. Result: 4 are `safe-static-type-alias`, 16 are `method-level-review-if-hooked`, and 16 are `type-alias-only`. This prevents probable type aliases from being mistaken for method-level behavior proof.

Artifact: `experiments/cpp2il_readable_csharp/samples/latest_refresh/focus_probable_static_audit.md`.

## Completion boundary audit

`static_map_completion_boundary_audit.md` is the current completion/boundary audit for the broad Mono-to-Deobf static map. It reports `static-boundary-reached` with 0 blockers: broad type-map counts are stable, focus rows have no candidate/weak-candidate entries, all high-priority cautious rows have native body review and semantic interpretation, broad candidates are classified, and focus probable rows are explicitly bounded.

This does not mean runtime behavior is proven. It means there is no remaining broad, non-target-specific static improvement queue exposed by current artifacts. Future gains require a named method/domain, refreshed/fuller ISIL, new external anchors, or runtime proof.

Artifact: `experiments/cpp2il_readable_csharp/samples/latest_refresh/static_map_completion_boundary_audit.md`.
