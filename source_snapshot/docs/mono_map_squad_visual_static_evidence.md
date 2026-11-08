# Mono-to-Deobf Map Squad Visual and Fog Adapter Evidence

Status: source-prepared/static-only. This document is not runtime proof.

## Why this exists

Older mod code still contains map-squad assumptions that match the Mono demo shape more than the current Golden Era shape. In particular, `EsquirePikemanMapBillboardFogSync.cs` still names `Hex.Map.BhMapSquad` and falls back through parent-component and node-by-position heuristics. The Mono build shows why that was tempting, but the current deobf does not support treating that as the primary native surface.

## Mono demo shape

Mono type `Hex.Map.BhMapSquad` is a very small wrapper:

- `TextMeshPro text`
- private `MapSquad squad_`
- `MapSquad squad` property getter/setter

Mono type `Hex.Session.World.BhSquadViewHelper` exposes a serialized `Transform questMarkerPoint` and a `QuestMarkerPoint` getter.

This means the old named `BhMapSquad` was not a rich, authoritative gameplay surface. It was a small UI/world wrapper around `MapSquad`.

## Current deobf shape

The current deobf does not expose `BhMapSquad.cs` by that name in the checked DiffableCs surface. Focused static evidence points to a split current model:

- `fdh` is the likely world-squad/domain object. It owns `DataSquad`, session, map/node-ish fields, view/effects references, and hero/squad state.
- `ezp` is the likely world-squad visual/presentation object. Its `Init(fdh _worldSquad, ctr _session)` stores the world squad and session, then sets up unit view config, animator, `BhSquadViewHelper`, and `BhMapEffectsController` state.
- `etv` is a small interaction/cursor wrapper around `fdh`; its `Init(fdh _worldSquad)` stores the world-squad reference.
- `BhSquadViewHelper.bigb()` is only a quest-marker-point accessor. It should not be treated as a squad identity or fog truth surface.

## Current dossiers

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/map_squad_BhSquadViewHelper_bigb_dossier.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/map_squad_ezp_Init_dossier.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/map_squad_fdh_Init_dossier.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/map_squad_etv_Init_dossier.md`
- `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_priority_map_squad_decompiled.cs`

## Native-friendly implications

For map node, fog, or visibility behavior, resolve from the current `fdh` world-squad object or its current data/node accessors. Do not rely on a parent `BhMapSquad` component or a node-by-position fallback as the authoritative route.

For map visual presentation, target `ezp.Init` or focused `ezp` presentation methods after dossiers identify the exact method. Avoid broad `ResManager` prefixes for map-squad visual behavior; previous notes indicate those can affect unrelated `Map.Init` and scene setup.

For cursor/interaction behavior, target `etv` only after a focused dossier proves the specific method. The small `etv.Init(fdh)` body proves the wrapper relationship, not the click/hover semantics.

## Current mod risk

`EsquirePikemanMapBillboardFogSync.cs` is likely carrying a legacy Mono assumption:

- hardcoded type name `Hex.Map.BhMapSquad`
- parent-component search
- reflected member read of `squad`
- fallback to node-by-position when squad/node is unreadable

That is useful as a historical bridge, but it is not the preferred current deobf route. A future fix should replace the legacy component heuristic with a direct current-world-squad adapter rooted in `fdh` and only use visual methods on `ezp` for presentation.

## Gaps before implementation

These are still static gaps, not permission to guess:

- focused dossier for the `fdh` `DataSquad` getter, likely `bjhs()` from current naming patterns
- focused dossiers for current `fdh` map-node accessors, likely nearby `bjhx`, `bjhz`, `bjib`, or generated property wrappers
- focused dossier for `ezp` effect/visibility methods if custom map visual syncing still needs effect state
- runtime ordering proof if a Harmony patch is added to any of these methods

## Evidence boundary

Static evidence can show the current type split and why `BhMapSquad` is stale. It does not prove Unity object lifetimes, pooled visual reuse order, fog refresh timing, or that any proposed Harmony prefix/postfix is safe.
