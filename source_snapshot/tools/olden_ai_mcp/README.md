# Olden AI Driver MCP

Status: deployed/runtime-proven for `bridge_info`, `status`, `ai_observe`, fresh-observation `ai_act`, `ai_start_match`, `ai_grant_law_points`, `ai_grant_resources`, and `ai_buy_law` against the dedicated `ai_driver_bridge` directory on Golden Era.

`screen_dump` adventure-map catalog (`map_object` / `map_marker` / `map_hero`) is **deployed + runtime dump validated** on `worldLight` (raw sid/id labels; LocKit names and fog filtering remain unproven). Map screen rects are projected via `Map` node→world (`oar` / `Method_Public_Vector3_Int32_*`) + `BhWorldCamera.targetCamera_` when placed MonoBehaviour scans are cold — **source/static + build proven; live non-zero rects still need a tutorial/worldLight dump re-prove after restart**. `visible_snapshot` / `hover_snapshot` / `pilot_*` remain source-prepared for human-parity input until separately proven. `screen_dump` is an AI catalog (`srSafe=false`) and must not be fed to NVDA. Prefer `hover_snapshot` / `hover_latest.json` for focus speech — see `docs/ai_screen_perception_nvda_consumer.md`.

`ai_observe` emits bounded schema-shaped observations with visible/interactable Unity UI action descriptors. `ai_act` accepts only actions from the latest observation and revalidates observation ID, screen ID, action ID, and `screen_path` fingerprint before Unity `EventSystem` dispatch.

`ai_start_match` uses the existing configured local match startup route and is guarded to `main_menu`. It returns loader/plan details plus a post-observation; Golden Era direct bridge and MCP proofs both reached `worldLight`/`adventure_map` afterward.

`ai_grant_law_points` uses the exact native `dtj.LevelUp()` route through `Homm3CustomFactionLawRuntime.TryNativeLawLevelUpForBridge` and returns before/after law-point state plus a post-observation.

`ai_buy_law` uses native `canApply` plus native law apply through `Homm3CustomFactionLawRuntime.TryDescribeNativeLawStateForBridge(..., applyIfCan: true)`. It returns success only when native apply was invoked, plus before/after law state and a post-observation.

`ai_grant_resources` uses the exact native `Data.Side.res -> ResHeap.<resource> -> Resource.addValue(int)` route through `Homm3CustomFactionLawRuntime.TryGrantResourceForBridge`. It returns success only after exact before/after resource identity and value confirmation, plus a post-observation. `ai_open_town`, `ai_start_combat`, and `pilot_drag` remain absent until each route is proven and recorded in `docs/ai_runtime_driver_mcp_plan.md` and `AGENTS.md`.

Enable the game-side bridge only in Golden Era diagnostic builds with `homm3AiDriverBridge` in config or `homm3_ai_driver.flag`. Release-candidate builds must exclude the game-side bridge source.
## Fail-Closed Adapter Behavior

The MCP adapter validates bridge-backed tool arguments before writing any bridge request. Malformed `ai_act`, law-point, resource, law-buy, observe, dump, hover, or pilot calls return `invalid_request` locally and do not create `inbox` files. Required strings are not coerced to empty values, numeric arguments are not clamped into range, and `ai_grant_resources` accepts only the exact native resource names advertised by the schema. Unknown extra tool arguments are rejected locally, including extra `targetFingerprint` fields for `ai_act`, matching the `additionalProperties: false` schema boundary.

If a tokened bridge is available but does not answer before `OLDEN_AI_DRIVER_TIMEOUT_MS`, the adapter returns `bridge_timeout` and removes any still-pending `inbox/<id>.json` request file before returning. This prevents a request that the caller already considers failed from being processed later as stale setup/action work.


Runtime proof against the installed Golden Era game should pass the deployed bridge explicitly, for example:

```powershell
node tools\olden_ai_mcp\server.mjs --bridge-dir "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\ai_driver_bridge"
```

`OLDEN_AI_DRIVER_BRIDGE_DIR` is also supported for MCP hosts that cannot pass process arguments. Do not rely on the repo-local default when proving Golden Era runtime behavior; it may point at a non-running development tree.


Before attempting live runtime proof, check that the deployed AI and live bridges are advancing frames. This helper is read-only: it samples `status.json` files and does not write inbox/outbox requests.

```powershell
node tools\olden_ai_mcp\check_runtime_freshness.mjs --ai-bridge-dir "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\ai_driver_bridge" --live-bridge-dir "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\live_probe_bridge" --sample-ms 1500
```

Only claim fresh runtime proof when both reported frame values advance during the sample window. If the helper returns `fresh=false`, restart or refresh the game/bridge host before sending bridge requests intended as proof. Add `--require-fresh` in scripts that must hard-fail stale runtime state; it exits with code 1 when either bridge frame does not advance and still performs only read-only status sampling.
Static schemas live under `schemas/`: `ai_observation.schema.json`, `ai_act_request.schema.json`, `screen_dump.schema.json`, `visible_snapshot.schema.json`, and `hover_snapshot.schema.json`.
