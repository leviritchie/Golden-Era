# HoMM3 Live Probe Workbench Design

Initial target: Golden Era build only.

## Goal

Reduce compile/deploy/restart loops by shipping one controlled runtime workbench that an agent can query and steer while the game is already running. The workbench is not a replacement for dedicated probes; it is a reusable probe host that can answer adjacent questions exposed by one runtime test without rebuilding the DLL.

The intended operator is an agent with computer-use skills. The primary interface should be MCP-like: small discoverable tools, typed resources, JSON inputs, bounded JSON/log outputs, and explicit side-effect flags.

## Non-Goals

- No arbitrary C# compilation or eval path. The workbench may expose exact
  allowlisted probes, but it must not become general runtime code execution.
- No arbitrary method body replacement.
- No automatic invocation of generated property getters.
- No broad "explore everything" sweep that can crash IL2CPP or pollute evidence.
- No silent visual/gameplay fallback. The workbench observes or performs explicitly requested mutations only.

## Activation

The workbench is disabled by default.

Enable with either:

- `homm3LiveProbeWorkbench=true` in `BepInEx/plugins/OfflineUnlockMod/config.json`
- `BepInEx/plugins/OfflineUnlockMod/homm3_live_probe_workbench.flag`

The first implementation is gated to `OFFICIAL_DEOBF_BUILD`. Non-deobf builds should log a warning and do nothing.

## Agent-Facing Protocol

Expose a local JSON protocol after the in-process host exists. The current implementation uses a file bridge rather than an HTTP listener so Unity does not bind ports during unrelated debugging:

`BepInEx/plugins/OfflineUnlockMod/live_probe_bridge/{token.txt,status.json,inbox,outbox,processed}`

The actual Codex-facing MCP server is the external stdio adapter in `tools/live_probe_mcp/server.mjs`. Codex talks MCP to that process; the adapter forwards bounded JSON requests to the file bridge.

Implemented MCP resources:

- `olden-live-probe://status`
- `olden-live-probe://bridge-info`

Planned workbench resources:

- `workbench://status`
- `workbench://recipes`
- `workbench://triggers`
- `workbench://sessions/current`
- `workbench://captures/{id}`
- `workbench://symbols/candidates`
- `workbench://safety/denylist`

Tools:

- `status`: report build profile, scene, frame, enabled recipes, registered triggers, and last errors.
- `reload_recipes`: reload `homm3_live_probe_recipes.json` without restarting.
- `list_triggers`: list precompiled lifecycle hook points and whether each is registered.
- `list_recipes`: return validated recipes and validation errors.
- `run_recipe`: run a manual recipe by id.
- `query_types`: search loaded assemblies by exact name, namespace, substring, and assignability where safe.
- `query_unity_objects`: search live Unity objects by type/name/path with result caps.
- `snapshot_fields`: field-only object snapshot with max depth, max nodes, cycle detection, and denylist.
- `diff_fields`: compare two snapshots.
- `method_signatures`: list method metadata only; do not invoke.
- `field_signatures`: list declared field metadata only; do not read values.
- `unity_renderers`: report bounded GameObject/Renderer summaries for a name/path filter.
- `unity_ui_surfaces`: report bounded read-only Unity UI summaries for a name/path filter. This is curated for panel/card diagnosis, not generic property exploration. It covers GameObject state, Transform/RectTransform geometry, nearest Canvas state including Canvas `objectId`, CanvasGroup chain/effective alpha, bounded child Graphic/Image/RawImage/TextMeshProUGUI summaries, and layout/mask clue components.
- `unity_objects_exact`: report lightweight GameObject summaries by exact name or exact transform path for root existence checks without UI-heavy child Graphic enumeration.
- `town_ui_state`: report current cached town wrapper/faction/city state and `OfflineUnlockStrongholdTownLayers` root counters.
- `mutation_capabilities`: list guarded and volatile writing capabilities with risk descriptions.
- `set_unity_ui_property`: guarded object-handle write for curated Unity UI properties only.
- `set_nearest_canvas_property`: guarded Canvas-only write from a captured descendant `objectId` to its nearest parent Canvas. It supports only `enabled`, `overrideSorting`, `sortingOrder`, `sortingLayerID`, `sortingLayerName`, and `planeDistance`; the Canvas must be in the active scene, or in additive `CityUI` while the active scene is `cityHuman` / `cityHuman2`, and active hierarchy.
- `set_canvas_by_name`: guarded Canvas-only write by exact Canvas GameObject name in the active scene or additive `CityUI` town scope and active hierarchy. It uses the same property allowlist and fails closed on ambiguous names.
- `volatile_set_canvas_property`: last-resort real Canvas mutation by captured `objectId`, exact `canvasName` / `name`, or exact transform `path`. It is still bounded to the active scene/additive `CityUI` town scope and Canvas allowlist, requires a reason, supports expected-old-value compare-and-swap, and reports old/new values, target path, target scene, active scene, and `volatile=true`.
- `volatile_set_ui_sibling`: last-resort real Transform sibling-order mutation by captured `objectId`, exact `name`, or exact transform `path`. It supports only `setFirst`, `setLast`, and `setIndex`, optionally checks `expectedOldSiblingIndex`, and uses the same town UI scope.
- `volatile_invoke_exact_noarg_getter`: invoke an exact no-arg semantic getter only when the exact method name and expected return type are in the built-in allowlist or live `volatile_exact_getter_allowlist.json`.
- `volatile_invoke_allowlisted_method`: invoke an exact method only when target type, method name, return type, and primitive/string/enum parameter types match live `volatile_operation_allowlist.json`.
- `volatile_set_allowlisted_member`: write an exact field or property only when target type, member kind, member name, and primitive/string/enum member type match live `volatile_operation_allowlist.json`, with compare-and-swap and post-write retention checks.
- `volatile_refresh_town_layers_from_cached_wrapper`: one-shot semantic town-layer refresh from the cached wrapper using exact allowlisted ObjCity/ObjCityConfig getters and existing production backdrop/layer sync.
- `set_primitive_component_field`: guarded primitive/string/enum field write on a named component attached to a captured GameObject.
- `invoke_known_safe_method`: invoke only allowlisted methods with primitive or known object arguments.
- `invoke_allowlisted_method`: bridge command variant for exact built-in allowlisted Unity calls only.
- `create_ui_diagnostic_overlay`: create a non-raycast UI overlay under a captured RectTransform for bounds/draw-order proof.
- `remove_ui_diagnostic_overlays`: remove workbench diagnostic overlays.
- `enable_precompiled_patch`: reserved guarded command for future dormant precompiled patch toggles.
- `volatile_arbitrary_csharp_eval`: intentionally unavailable. The workbench must not become arbitrary managed-code execution.
- `volatile_reflection_invoke`: named last-resort arbitrary reflection invocation capability; currently fails closed.
- `volatile_generated_getter_sweep`: named last-resort generated getter exploration capability; currently fails closed.
- `volatile_write_object_reference`: named last-resort object-reference write capability; currently fails closed.
- `volatile_autopatch_same_shape_methods`: named last-resort same-shape Harmony patching capability; currently fails closed.
- `volatile_global_ui_setter_patch`: named last-resort global UI setter patch capability; currently fails closed.
- `set_primitive_field`: write primitive fields only when the recipe has `allowMutation=true`.
- `export_evidence`: write captures, candidate symbol paths, and warnings to an artifact file.

Transport:

- Current: file inbox/outbox bridge plus per-run token.
- Future optional: localhost HTTP on an explicit port from config, bound only to `127.0.0.1`.
- Keep all responses bounded and paginated.

## Recipe Manifest

Path:

`BepInEx/plugins/OfflineUnlockMod/homm3_live_probe_recipes.json`

Example:

```json
{
  "recipes": [
    {
      "id": "town-building-wrapper-fields",
      "enabled": true,
      "trigger": "townBuildingViewBind",
      "action": "snapshotFields",
      "target": "argument:0",
      "maxDepth": 2,
      "maxNodes": 80
    },
    {
      "id": "manual-prop-city-type-search",
      "enabled": false,
      "trigger": "manual",
      "action": "searchTypes",
      "query": "PropCity"
    }
  ]
}
```

Rules:

- Every recipe needs `id`, `trigger`, and `action`.
- Mutation recipes require `allowMutation=true`.
- Trigger names must come from the curated registry.
- Actions must come from the precompiled workbench action registry.
- Recipes can be reloaded live. New lifecycle trigger/action implementations
  still require a bridge upgrade, but exact getters, exact primitive method
  calls, and exact primitive member writes should be added through live bridge
  allowlist JSON whenever possible so individual runtime hypotheses do not
  require another rebuild.

## Curated Trigger Registry

Initial high-value triggers:

- `manual`
- `configReload`
- `sceneLoaded`
- `mapPrepare`
- `mapBuildPostfix`
- `townSessionBind`
- `townBuildingViewBind`
- `townNavigationBind`
- `heroHudBind`
- `selectedUnitHudBind`
- `dwellingInit`
- `hireInit`
- `mapSquadVisualInit`
- `terrainPrepare`
- `terrainBuild`

Do not register broad same-shape Harmony scans from this system. Each trigger must map to a centralized `GameSymbols` surface or a proven existing hook.

## Safety Model

Default operation is read-only.

Field reads:

- Prefer CLR fields and known IL2CPP backing fields.
- Do not call generated property getters unless the member is explicitly allowlisted as safe.
- Use depth/node/string-length limits.
- Track visited native/managed identities to prevent cycles.
- Include null and exception markers in evidence instead of hiding them.

Method handling:

- Signature listing is allowed.
- Invocation is deny-by-default.
- Known-safe method invocation must name the exact declaring type, method, parameter shape, and reason.

Guarded mutation:

- Prefer object handles returned by prior bounded Unity query tools.
- Require exact command names and exact component/property/field names.
- Prefer `expectedOldValue` checks so writes fail closed when the live state has drifted.
- Primitive field writes support only bool, integral, float, double, string, and enum fields on named components.
- Unity UI property writes are curated: GameObject active state, Behaviour enabled, CanvasGroup alpha/input flags, Graphic alpha/raycast flags, scalar RectTransform geometry, and selected Canvas ordering fields.
- Canvas lifting/testing has dedicated commands. Prefer `set_nearest_canvas_property` from a previously captured descendant handle; use `set_canvas_by_name` only for exact scoped Canvas names and let ambiguous names fail. When guarded setters are too restrictive for an investigation, use `volatile_set_canvas_property` or `volatile_set_ui_sibling` with a concrete reason and compare-and-swap expectations.
- Diagnostic overlays must be visually obvious, non-raycast, and removable.
- Log old value, new value, object identity, member path, frame, scene, and recipe id.
- Never count a mutation as a production fix.

Volatile mutation:

- Implemented volatile commands are real runtime probes/mutations: `volatile_set_canvas_property`, `volatile_set_ui_sibling`, `volatile_invoke_exact_noarg_getter`, `volatile_invoke_allowlisted_method`, `volatile_set_allowlisted_member`, and semantic one-shot commands such as `volatile_refresh_town_layers_from_cached_wrapper`.
- Semantic volatile commands should be data-driven where possible. Exact no-arg getters can be added live through `BepInEx/plugins/OfflineUnlockMod/live_probe_bridge/volatile_exact_getter_allowlist.json`; exact primitive method invocations and exact primitive member writes can be added live through `BepInEx/plugins/OfflineUnlockMod/live_probe_bridge/volatile_operation_allowlist.json`. These live allowlists are the preferred way to avoid rebuild/restart loops after the bridge is loaded.
- `volatile_arbitrary_csharp_eval` must fail closed even if a C# scripting engine is present in the runtime.
- Broad reflection sweeps, generated getter sweeps, object-reference writes, same-shape autopatching, and global UI setter hooks still fail closed unless they are implemented as explicitly named volatile tools with clear evidence output.
- Volatile commands are last-resort only when guarded tools are truly inadequate. They must require an explicit reason, bounded input/output, and evidence logs that distinguish volatile probe effects from production fixes.

Failure:

- Fail closed.
- Emit `HOMM3_LIVE_PROBE` diagnostics with exact recipe id, trigger, action, and reason.
- Do not substitute donor assets, fallback symbols, or alternate getters.

## Evidence Promotion

The workbench may export candidate findings, but production code should still promote them manually:

- `GameSymbols` additions require centralized names and exact constraints.
- Dedicated probes remain preferred for surface-specific postconditions.
- Workbench evidence should include enough context to write or refine those dedicated probes without another exploratory restart.

## Current Scaffolding

`Homm3LiveProbeWorkbench.cs` currently provides:

- disabled-by-default startup gate
- Golden Era build guard
- recipe manifest parsing
- curated trigger/action validation
- mutation opt-in validation
- file bridge for read-only inspection plus guarded/volatile writing commands: `status`, `reload_recipes`, `list_recipes`, `list_triggers`, `mutation_capabilities`, `query_types`, `method_signatures`, `field_signatures`, `unity_renderers`, `unity_ui_surfaces`, `unity_objects_exact`, `town_ui_state`, `set_unity_ui_property`, `set_nearest_canvas_property`, `set_canvas_by_name`, `volatile_set_canvas_property`, `volatile_set_ui_sibling`, `volatile_invoke_exact_noarg_getter`, `volatile_invoke_allowlisted_method`, `volatile_set_allowlisted_member`, `volatile_refresh_town_layers_from_cached_wrapper`, `set_primitive_component_field`, `invoke_allowlisted_method`, `create_ui_diagnostic_overlay`, `remove_ui_diagnostic_overlays`, and fail-closed broad volatile command names
- no runtime hook execution
- no HTTP transport yet

`tools/live_probe_mcp/server.mjs` currently provides:

- dependency-free stdio MCP adapter
- `tools/list`, `tools/call`, `resources/list`, and `resources/read`
- bridge discovery through `--bridge-dir` or `OLDEN_LIVE_PROBE_BRIDGE_DIR`
- MCP schemas for read-only, guarded mutation, volatile UI, volatile exact getter, volatile live-operation, and town-layer refresh tools

The `unity_ui_surfaces` command is intended for any live Unity UI surface where evidence needs UI geometry, canvas, alpha, graphic, material, sprite/texture, and mask/layout state rather than renderer state. It is filter-driven and must remain curated around standard Unity UI component categories, not around one incident's object names.

This is deliberate. The next implementation step should add field snapshots before adding any lifecycle trigger execution.
