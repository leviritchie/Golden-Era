# AI start-combat cheat-surface static evidence - 2026-06-20

Purpose: preserve current static evidence for the remaining `ai_start_combat` Step 4 investigation without exposing an unproven AI MCP command.

## Evidence status

- Runtime proof: blocked. Golden Era `ai_driver_bridge/status.json` remains stale at frame 35372 in `cityDungeon`, and `live_probe_bridge/status.json` remains stale at frame 35368.
- Command exposure: unchanged. `ai_start_combat` and `ai_open_town` must remain absent.
- Evidence level: static DiffableCs/ISIL proves the cheat command payload shape and selector values. Runtime/generated type metadata exists for `cux`/`eys`, but live method metadata and runtime ordering are not proven.

## Static enum evidence

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/TypeCmdWorldCheats.cs`
  - `BattleAutoWin = 12`
  - `CreateSquad = 16`
  - `CreateRandomSquad = 17`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/World/StateCheatClickNode.cs`
  - `CreateSquad = 1`
  - `CreateRandomSquad = 2`

## `eys` click-state dispatch evidence

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/eys.cs`
  - `StateCheatClickNode cixc` at field offset `0x3C`.
  - Methods present: `dvf()`, `bhzm()`, `bhzo()`, `bhzj(bool)`.
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/eys.txt`
  - `dvf()` checks `cixc` and dispatches state 1 to `eys.bhzm()`, state 2 to `eys.bhzo()`, otherwise to `eys.bhzn()`/normal path.
  - `bhzm()` creates a `cux` command, writes current coordinates into `[rbx+64h]`, `[rbx+68h]`, `[rbx+6Ch]`, writes selector `[rbx+20h] = 0x10`, then dispatches through native address `0x1827078D0`.
  - `bhzo()` creates a `cux` command, writes coordinate-like fields `[rbx+64h]` and `[rbx+6Ch]`, writes selector `[rbx+20h] = 0x11`, then dispatches through `0x1827078D0`.
  - `bhzj(bool)` creates a `cux` command, writes selector `[rbx+20h] = 0x0C` and bool `[rbx+34h]`, then dispatches through `0x1827078D0`. This matches `BattleAutoWin = 12`, but it is battle-related rather than a combat-entry route.

## `cux` payload evidence

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/cux.cs`
  - `cafe` at offset `0x20` is the inner `TypeCmdWorldCheats` selector.
  - `caff` at offset `0x24` receives a current-context value in the `eys` builders.
  - `cafi` at offset `0x34` is the bool written by `bhzj(bool)`.
  - `cafp`, `cafq`, `cafr` at offsets `0x64`, `0x68`, `0x6C` are coordinate-like/int fields used by `CreateSquad`/`CreateRandomSquad` paths.
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/cux.txt`
  - `hsf()` returns `ECmd` value `0x71` / `113`, so `cux` is the outer command type and `cafe` is an inner selector.
  - `vdb()`/similar handlers read `[rdi+20h]`, bounds-check selector values up to `0x16`, load a jump-table entry from `[rdx+rax*4+2BE4C3Ch]`, add the base pointer, and `jmp rcx`. This proves `cafe` participates in command execution, not merely UI state.
  - The create-squad branches read `[rdi+64h]` and `[rdi+6Ch]`, call into map/session helpers, and do not by themselves prove deterministic battle entry.

## Runtime/generated metadata evidence

`experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map.json` contains generated type rows:

- obfuscated `cux` -> runtime type `Object1PublicIncaStIncaBoStcaInStUnique`, method_count 49.
- obfuscated `eys` -> runtime type `ObjectPublicInciObInciBoObStInciUnique`, method_count 77.

The current extraction did not recover readable method names for `dvf`/`bhzm`/`bhzo`/`bhzj`, so a future live `resolve_decomp_method` or `method_signatures` check is still needed once the bridge resumes.

## Generated owner-candidate evidence

`experiments/cpp2il_readable_csharp/samples/latest_refresh/runtime_interop_map.json` also narrows the next live owner-discovery probe. The generated metadata shows these runtime owner candidates expose `get_sideCheats()` / `set_sideCheats(ObjectPublicInciObInciBoObStInciUnique)`:

- `Hex.Cheat.UI.BhWindowWorld`
- `Hex.Cheat.UI.BhWindowHero`
- `Hex.Cheat.UI.BhWindowMagic`

The same generated map shows `ObjectPublicObBhcjObIncjSiObIncoUnique` (obfuscated `fda`) has `get_field_Public_ObjectPublicInciObInciBoObStInciUnique_0()`, another exact generated getter returning the `eys` type. These are useful generated owner candidates for a future read-only live proof. They are not runtime owner proof, invocation proof, or command authorization while the bridge is stale.

## Centralized symbol status

Centralized `GameSymbols` entries are source-prepared in `GameSymbols.AiDriverCombatSetup` for this static surface only. They include `eys`/`cux` runtime type-name candidates, generated owner candidates (`BhWindowWorld`, `BhWindowHero`, `BhWindowMagic`, and `fda`), exact generated `get_sideCheats()` / `get_field_Public_ObjectPublicInciObInciBoObStInciUnique_0()` getters, `dvf`/`bhzm`/`bhzo`/`bhzj`/`hsf` method symbols, `cixc` and `cux` payload field symbols, the static selector constants, and the relevant field offsets. These entries are guardrails for future proof work; they do not prove live owner resolution, safe invocation, or battle entry.
## Static artifact validation status

`tools/release_port/validate_ai_driver_static.py` now checks the exact decomp/static metadata artifacts behind this note: `TypeCmdWorldCheats.cs`, `StateCheatClickNode.cs`, `eys.cs`, `cux.cs`, `eys.txt`, `cux.txt`, and `runtime_interop_map.json`. The gate verifies the enum values, field offsets, method shells, selected ISIL selector writes/dispatch reads, `cux.hsf()` returning `0x71`, exact `cux` selector jump-table tokens (`[rdi+20h]`, `0x16`, `[rdx+rax*4+2BE4C3Ch]`, `jmp rcx`) plus create-squad coordinate reads, generated runtime type candidates for `eys`/`cux`, and generated owner candidates/getters for `BhWindowWorld`/`BhWindowHero`/`BhWindowMagic`/`fda` side-cheat access. This strengthens static drift detection only; it still does not prove live metadata resolution, active owner discovery, safe invocation, or battle-mode transition.

## Live metadata probe packet

`docs/ai_start_combat_live_metadata_probe_packet.json` contains the next read-only live-probe packet to run only after the freshness preflight returns `fresh=true`. It includes `method_signatures` requests for the `eys`/`cux` generated types and the generated owner candidates, plus `resolve_decomp_method` requests for `eys.dvf`, `eys.bhzm`, `eys.bhzo`, `eys.bhzj(bool)`, `cux.hsf`, each owner `get_sideCheats()`, and the `fda` eys getter. The packet is explicitly metadata-only: it does not invoke methods, call getters, mutate state, discover live instances, or authorize command exposure. `tools/olden_ai_mcp/run_ai_start_combat_metadata_probe.mjs` is the single prepared runner for this packet; it checks both AI/live bridge freshness first, allows only `method_signatures` and `resolve_decomp_method`, and returns `runtime_not_fresh` before writing any live-probe inbox request if frames do not advance. `tools/release_port/validate_ai_driver_static.py` guards the packet schema, runner gate, read-only command set, freshness preflight requirement, and absent-command warning.


## Live owner-discovery probe packet

`docs/ai_start_combat_owner_discovery_probe_packet.json` is the next read-only packet after the metadata packet resolves. It deliberately uses only `unity_components_by_type` against exact generated owner component candidates (`Hex.Cheat.UI.BhWindowWorld`, `Hex.Cheat.UI.BhWindowHero`, and `Hex.Cheat.UI.BhWindowMagic`). It does not use `component_member_path`, `allowProperties`, getter calls, method invocation, managed-object enumeration, or mutation. `tools/olden_ai_mcp/run_ai_start_combat_owner_discovery_probe.mjs` validates the packet, requires both AI/live bridge frames to advance before any `live_probe_bridge` inbox write, rejects payload control keys and unsupported component types, and cleans up timed-out requests. The latest real run wrote `docs/ai_start_combat_latest_owner_discovery_probe_result.json` and failed closed with `runtime_not_fresh`, so no live owner-discovery request has been sent yet.
## Current conclusion

This path is useful for static prioritization but is not yet a safe `ai_start_combat` route. Static evidence proves that `eys` can build and dispatch `cux` world-cheat commands for `CreateSquad`, `CreateRandomSquad`, and `BattleAutoWin`; it does not prove a deterministic combat-entry setup command, safe live `eys` owner/instance resolution, map click target validity, or post-action `ai_observe` transition into `battle`.

Future proof requirements before exposing anything:

1. Fresh live bridge responsiveness, then run `docs/ai_start_combat_live_metadata_probe_packet.json` through read-only live bridge requests only.
2. Runtime metadata resolution for `eys.dvf`, `eys.bhzm`, `eys.bhzo`, `eys.bhzj`, and `cux.hsf`/handler method(s).
3. Read-only live owner/instance discovery for the active `eys` world cheat controller, starting from the generated owner candidates above (`BhWindowWorld`/`BhWindowHero`/`BhWindowMagic` `get_sideCheats()` and `fda` `get_field_Public_ObjectPublicInciObInciBoObStInciUnique_0()`).
4. A non-production proof that a chosen exact route enters `battle` and produces `ai_observe.mode == "battle"`.
5. Centralized `GameSymbols` entries are source-prepared; future work must verify/reuse them in one fail-closed production route only, followed by build/static/runtime validation.