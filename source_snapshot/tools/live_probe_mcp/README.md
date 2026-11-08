# Olden Live Probe MCP Adapter

This is a dependency-free stdio MCP adapter for Codex. It does not talk to the
game directly. It forwards MCP tool calls to the file bridge created by
`Homm3LiveProbeWorkbench` inside `OfflineUnlockMod.dll`.

The game-side bridge is disabled by default and targets the active Golden Era build. `OfficialDeobfBuild` remains a compile-profile identifier, not a different runtime install.

## Enable The Game Bridge

In the deployed `BepInEx/plugins/OfflineUnlockMod/config.json`:

```json
{
  "homm3LiveProbeWorkbench": true
}
```

Or place this flag next to the deployed plugin DLL:

```text
BepInEx/plugins/OfflineUnlockMod/homm3_live_probe_workbench.flag
```

When the game launches with the bridge enabled, it creates:

```text
BepInEx/plugins/OfflineUnlockMod/live_probe_bridge/
  token.txt
  status.json
  inbox/
  outbox/
  processed/
  probes/
```

Do not enable this during unrelated runtime tests unless the active test owner
expects the extra file bridge.

## Configure Codex

Use a project-scoped `.codex/config.toml` or your global `~/.codex/config.toml`.

```toml
[mcp_servers.olden_live_probe]
command = "node"
args = [
  "tools/live_probe_mcp/server.mjs",
  "--bridge-dir",
  "V:\\SteamLibrary\\steamapps\\common\\Heroes of Might and Magic Olden Era - Golden Era\\BepInEx\\plugins\\OfflineUnlockMod\\live_probe_bridge"
]
cwd = "V:\\Games\\Olden Era Playtest Tweak"
startup_timeout_sec = 20
tool_timeout_sec = 60
default_tools_approval_mode = "prompt"
```

When the bridge directory is outside the active Codex workspace, keep
`workspace-write` and add only that exact bridge directory as a writable root:

```toml
[sandbox_workspace_write]
writable_roots = [
  "V:\\SteamLibrary\\steamapps\\common\\Heroes of Might and Magic Olden Era - Golden Era\\BepInEx\\plugins\\OfflineUnlockMod\\live_probe_bridge"
]
```

Alternatively set:

```text
OLDEN_LIVE_PROBE_BRIDGE_DIR=<absolute path to live_probe_bridge>
```

Then configure:

```toml
[mcp_servers.olden_live_probe]
command = "node"
args = ["tools/live_probe_mcp/server.mjs"]
cwd = "V:\\Games\\Olden Era Playtest Tweak"
startup_timeout_sec = 20
tool_timeout_sec = 60
default_tools_approval_mode = "prompt"
```

Restart Codex after adding the MCP server.

### Desktop Plugin Packaging

If Codex Desktop reads the MCP server in `codex mcp list` but the running
thread does not expose `mcp__olden_live_probe__*` tools or show a
`node ... tools/live_probe_mcp/server.mjs` process, package the adapter as a
local plugin with an `.mcp.json` companion instead of relying only on raw
`~/.codex/config.toml`.

The local plugin wrapper installed and manifest-validated on June 10, 2026 is:

```text
C:\Users\<user>\plugins\olden-live-probe
```

It has:

```json
{
  "mcpServers": {
    "olden_live_probe": {
      "command": "node",
      "args": [
        "tools/live_probe_mcp/server.mjs",
        "--bridge-dir",
        "V:\\SteamLibrary\\steamapps\\common\\Heroes of Might and Magic Olden Era - Golden Era\\BepInEx\\plugins\\OfflineUnlockMod\\live_probe_bridge"
      ],
      "cwd": "V:\\Games\\Olden Era Playtest Tweak",
      "startup_timeout_sec": 20,
      "tool_timeout_sec": 60,
      "default_tools_approval_mode": "prompt"
    }
  }
}
```

After installing or updating this plugin, start a new thread so Codex refreshes
plugin and MCP tool discovery. Treat the plugin as a fix candidate until a
fresh Desktop thread confirms `mcp__olden_live_probe__*` tools are exposed and
the adapter process is launched.

## Exposed Tools

- `bridge_info`
- `status`
- `reload_recipes`
- `list_recipes`
- `list_triggers`
- `mutation_capabilities`
- `query_types`
- `method_signatures`
- `field_signatures`
- `unity_renderers`
- `unity_ui_surfaces`
- `unity_objects_exact`
- `unity_components_by_type`
- `component_member_path`
- `town_ui_state`
- `set_unity_ui_property`
- `set_nearest_canvas_property`
- `set_canvas_by_name`
- `volatile_set_canvas_property`
- `volatile_set_ui_sibling`
- `volatile_invoke_exact_noarg_getter`
- `volatile_invoke_allowlisted_method`
- `volatile_set_allowlisted_member`
- `volatile_refresh_town_layers_from_cached_wrapper`
- `volatile_compile_and_run_csharp`
- `set_primitive_component_field`
- `invoke_allowlisted_method`
- `create_ui_diagnostic_overlay`
- `remove_ui_diagnostic_overlays`
- `enable_precompiled_patch`
- `volatile_reflection_invoke`
- `volatile_generated_getter_sweep`
- `volatile_write_object_reference`
- `volatile_autopatch_same_shape_methods`
- `volatile_global_ui_setter_patch`

`unity_ui_surfaces` accepts `nameContains` and `limit`, then returns bounded
read-only summaries for matching GameObjects, RectTransforms, nearest Canvas,
parent CanvasGroups, child Graphics/Image/RawImage/TextMeshProUGUI entries, and
layout/mask clues. It is meant for any live Unity UI surface where renderer
summaries are not enough. Each object's `canvas` metadata includes the nearest
Canvas GameObject `objectId`.

`unity_objects_exact` is a lightweight exact-name / exact-path GameObject query
for roots that are not UI Graphics-heavy:

```json
{"name":"OfflineUnlockStrongholdTownLayers","requireActiveHierarchy":false,"limit":10}
```

`unity_components_by_type` is a bounded read-only component lookup for live
MonoBehaviours/components. It returns GameObject `objectId` handles usable with
`component_member_path`, which is the preferred route for combat/town UI owner
components that are not named like their runtime class:

```json
{"componentType":"Hex.Session.Battle.BhSelectedUnitHud","scene":"battleUI","limit":10}
```

`component_member_path` follows an exact member path from a captured object or
component and returns bounded object summaries at each step. It reads fields by
default; property getters require `allowProperties=true` because generated
IL2CPP getters can have side effects or throw on Golden Era. On Golden Era IL2CPP components, exact field reads fall back to generated
`NativeFieldInfoPtr_*` handles; this is the supported route for nested owner
state such as combat HUD component fields and selected-unit wrapper fields.

```json
{
  "objectId": 12345,
  "componentType": "Hex.Session.Battle.BhTurnView",
  "memberPath": "field_Private_Unit_0",
  "fieldLimit": 16
}
```

Use `[index]` on array/list-like segments when inspecting exact collections,
for example `field_Private_Il2CppReferenceArray_1_ObjectPublicObceInBoInceAbObELInUnique_0[0]`.

`town_ui_state` reports the current cached town wrapper type, cached/current
fraction, whether ObjCity / ObjCityConfig are non-null, and current
`OfflineUnlockStrongholdTownLayers` root counters.

The guarded mutation tools operate on `objectId` handles returned by Unity query
tools:

- `set_unity_ui_property`: curated Unity UI property writes such as
  `GameObject.activeSelf`, `Behaviour.enabled`, `CanvasGroup.alpha`,
  `Graphic.colorAlpha`, scalar `RectTransform` geometry, and selected `Canvas`
  sorting fields.
- `set_nearest_canvas_property`: from a captured descendant `objectId`, find
  the nearest parent `Canvas` and write only `enabled`, `overrideSorting`,
  `sortingOrder`, `sortingLayerID`, `sortingLayerName`, or `planeDistance`. The
  Canvas must be in the active scene, or in additive `CityUI` while the active
  scene is `cityHuman` / `cityHuman2`, and active hierarchy.
- `set_canvas_by_name`: exact Canvas GameObject name match in the active scene
  or additive `CityUI` town scope and active hierarchy, with the same Canvas
  property allowlist. Ambiguous names fail closed.
- `volatile_set_canvas_property`: last-resort real Canvas mutation by captured
  `objectId`, exact `canvasName` / `name`, or exact transform `path`. It uses the
  same town UI scene scope and Canvas allowlist, requires `reason`, and reports
  old/new values plus target scene and active scene.
- `volatile_set_ui_sibling`: last-resort real Transform sibling-order mutation
  by captured `objectId`, exact `name`, or exact transform `path`. Supported
  operations are `setFirst`, `setLast`, and `setIndex`; include
  `expectedOldSiblingIndex` where practical.
- `volatile_invoke_exact_noarg_getter`: invokes only an exact no-arg getter
  whose exact method name and expected return type are in the built-in semantic
  allowlist or live `volatile_exact_getter_allowlist.json`.
- `volatile_invoke_allowlisted_method`: invokes an exact method whose target
  type, method name, return type, and primitive/string/enum parameter types are
  declared in live `volatile_operation_allowlist.json`. Arguments are supplied
  as `arg0TypeFullName` / `arg0Value` through `arg3...`; no object-reference
  arguments are supported.
- `volatile_set_allowlisted_member`: writes an exact field or property whose
  target type, member kind, member name, and primitive/string/enum member type
  are declared in live `volatile_operation_allowlist.json`. It supports
  `expectedOldValue` compare-and-swap and returns `write_not_retained` if the
  post-write value does not match the normalized request. Exact IL2CPP native
  fields are writable only for primitive/string/enum types and still require the
  same allowlist entry; string writes use the IL2CPP GC write barrier. Use
  `memberPath` to traverse exact read-only parent segments and write the final
  primitive/string/enum segment on the resolved nested target.
- `volatile_refresh_town_layers_from_cached_wrapper`: a one-shot semantic action
  for the current town-layer investigation. It recaptures ObjCity /
  ObjCityConfig from the cached town wrapper via exact allowlisted getters, then
  calls the existing backdrop/layer sync once.
- `volatile_compile_and_run_csharp`: compiles arbitrary C# into a temporary
  probe DLL under `live_probe_bridge/probes`, then asks the game bridge to load
  that assembly and invoke a static method on Unity's main thread. The method
  can be `static object Run()` or `static object Run(string requestJson)`.
  This is intentionally unsafe: crashes, hangs, and live state mutation are
  acceptable outcomes when the alternative is rebuilding/restarting the game.
- `set_primitive_component_field`: primitive/string/enum field writes on a
  named component attached to the captured GameObject.
- `invoke_allowlisted_method`: exact built-in allowlist only:
  `GameObject.SetActive`, `Transform.SetAsFirstSibling`, and
  `Transform.SetAsLastSibling`.
- `create_ui_diagnostic_overlay` / `remove_ui_diagnostic_overlays`: create and
  remove non-raycast UI overlays for visual bounds/draw-order proof.
- `enable_precompiled_patch`: reserved command for future dormant patch toggles;
  this build reports no registered patches.

The implemented volatile tools are real runtime mutations/probes. The exact
operation tools are designed to avoid rebuilds for narrow primitive/member
work: add exact methods or primitive member writes to a JSON file in the live
bridge directory, then call the MCP tool. When that is too slow or too narrow,
use `volatile_compile_and_run_csharp` as the explicit near-arbitrary diagnostic
escape hatch. Probe assemblies are auditable, loaded only from
`live_probe_bridge/probes`, and should return bounded text/primitive summaries
where practical.

The remaining broad volatile categories still fail closed: arbitrary reflection
invocation by schema, generated getter sweeps, object-reference writes,
same-shape patching, and global UI setter hooks. Use a compiled probe for those
experiments instead of turning them into always-available schema tools.

## Live Getter Allowlist

To add exact semantic getters without rebuilding the DLL, write this file into
the live bridge directory:

`BepInEx/plugins/OfflineUnlockMod/live_probe_bridge/volatile_exact_getter_allowlist.json`

Shape:

```json
{
  "getters": [
    {
      "targetTypeFullName": "SomeExactRuntimeType",
      "methodName": "Method_Public_get_Something_0",
      "expectedReturnTypeFullName": "Some.Namespace.SemanticType",
      "reason": "Runtime-proven no-arg semantic getter"
    }
  ]
}
```

The bridge reloads this file by mtime on getter calls. It still requires exact
method name and exact expected return type; it does not sweep generated getters
or search by same shape.

## Live Operation Allowlist

To add exact method invocations or primitive member writes without rebuilding
the DLL, write this file into the live bridge directory:

`BepInEx/plugins/OfflineUnlockMod/live_probe_bridge/volatile_operation_allowlist.json`

Shape:

```json
{
  "operations": [
    {
      "kind": "method",
      "targetTypeFullName": "SomeExactRuntimeType",
      "methodName": "Method_Public_Void_Boolean_0",
      "expectedReturnTypeFullName": "System.Void",
      "parameterTypeFullNames": "System.Boolean",
      "reason": "Runtime-proven exact method"
    },
    {
      "kind": "member",
      "targetTypeFullName": "SomeExactRuntimeType",
      "memberKind": "field",
      "memberName": "field_Private_Int32_0",
      "memberTypeFullName": "System.Int32",
      "reason": "Runtime-proven primitive diagnostic write"
    }
  ]
}
```

`parameterTypeFullNames` is a flat `|`-separated list, for example
`System.String|System.Int32`. Leave it empty for no-arg methods. Supported
argument/member value types are bool, numeric primitives, string, and enums.
Object-reference writes and object-reference method arguments are deliberately
not handled by this generic path.

Example request shapes:

```json
{"nameContains":"Some Panel","limit":10}
```

```json
{"objectId":12345,"property":"sortingOrder","value":"500","expectedOldValue":"0"}
```

```json
{"canvasName":"CanvasCityPanel","property":"overrideSorting","value":"true","expectedOldValue":"false"}
```

Town canvas lift example:

```json
{"nameContains":"BUILDING VIEW PANEL","limit":5}
```

Use the returned object's nearest `canvas.objectId`, then:

```json
{"objectId":12345,"property":"overrideSorting","value":"true","expectedOldValue":"false","reason":"Town build panel layering probe"}
```

```json
{"objectId":12345,"property":"sortingOrder","value":"500","expectedOldValue":"0","reason":"Lift BUILDING VIEW PANEL above CanvasCityPanel for visual proof"}
```

Sibling lift example when Canvas sorting is not enough:

```json
{"path":"CityUI/CanvasCityPanel/BUILDING VIEW PANEL","operation":"setLast","expectedOldSiblingIndex":"2","reason":"Probe sibling draw order after Canvas lift"}
```

Town wrapper getter proof:

```json
{
  "target": "cachedTownWrapper",
  "methodName": "Method_Public_get_ObjCity_0",
  "expectedReturnTypeFullName": "Hex.Session.Data.ObjCity",
  "reason": "Confirm cached town wrapper can produce ObjCity without restarting"
}
```

Live operation examples after adding matching entries to
`volatile_operation_allowlist.json`:

```json
{"objectId":12345,"componentType":"Canvas","memberKind":"property","memberName":"sortingOrder","expectedMemberTypeFullName":"System.Int32","value":"500","expectedOldValue":"260","reason":"Temporarily lift exact canvas through live operation allowlist"}
```

```json
{"objectId":12345,"componentType":"GameObject","methodName":"SetActive","expectedReturnTypeFullName":"System.Void","argCount":1,"arg0TypeFullName":"System.Boolean","arg0Value":"false","reason":"Temporarily hide exact object through live operation allowlist"}
```

One-shot town-layer refresh:

```json
{"reason":"Recapture town city data from cached wrapper and sync town layers once"}
```

## Exposed Resources

- `olden-live-probe://status`
- `olden-live-probe://bridge-info`

## Safety

The adapter reads the per-run `token.txt` written by the game bridge and includes
it in each bridge request. This is not a security boundary against a local user;
it prevents stale or accidental requests from older adapter instances.

Keep tool output bounded and treat every response as diagnostic evidence only.
Production fixes still need centralized `GameSymbols` changes or dedicated probes.
