# Native unit-preview startup deferral

Status: the preview class-identity wrapper fix is source-reviewed, build-target proven and
included in the installed 25672315 payload at the normal Golden Era path. The deployment
receipt is `../artifacts/port_current/consolidation_25672315/promotion_receipt.json`; build
and validation limits are summarized in `current_version_consolidation.md`. The separate
startup-deferral selector remains enabled in the installed payload, but its first-demand and
lifecycle behavior have not been tested after promotion. Run 10's prior-copy deferral observation
does not prove behavior on this install. The selector remains explicit opt-in and restricted to
the current indexed build; absence leaves it off. Golden Era is the delivery target. The wrapper
class-identity fix and startup-deferral policy are separate changes.

## Native ownership

The current GameAssembly SHA-256 is
`d9972b0e7f7dd1c17758808e2f1b80e0a728946416d9a41deaa99bad744de53a`.
Exact indexed/native-body evidence pins `Hex.BhUnitPreviews` setup `iic` (token
100666589), request `iid` (100666590), return `iie` (100666591), and preview
construction `iih` (100666594). Symbols belong in `GameSymbols.UnitPreview` and
the reviewed current-scope overrides, not in feature code or numeric offsets.

Setup's exact body `[0x182E4CA60, 0x182E4CCBE)` initializes metadata slots,
enumerates the native config list, adds a fresh queue for every key to the
existing dictionary, constructs a preview, and enqueues it. Its queue/null/key
validation, order, disposal and exception behavior remain native. The candidate
does not replace setup, rebuild the dictionary, enumerate configs in managed
code, clear queues, or modify return-to-pool behavior.

The setup call at `0x182E4CC34` passes construction's result unchanged to enqueue
at `0x182E4CC4B`. The exact specialized enqueue body stores a null item and
increments count. Request's exact body `[0x182E4CCC0, 0x182E4CF85)` dequeues a
populated queue, compares the result with null through Unity object equality,
and constructs the requested preview when that result is null. A valid model
continues to the successful return; an invalid lazy result reaches the native
throw path. A missing key still returns false. Thus the initial null is a
native-supported deferred slot, not a successful null response or error recovery.

Only setup/request/return consume the keyed map in the audited native class;
the constructor initializes it. Other methods use the separate unkeyed preview
queue or texture cache. Direct construction xrefs are setup and request. This
does not rule out indirect calls or establish Harmony detour behavior.

The earlier description of ten direct class-initializer calls was too strong:
the calls receive static slot addresses, and the observed thunk/target performs
tagged-slot lazy metadata initialization. Hidden loader callbacks remain
unproven. Keeping native setup avoids reproducing those dependencies.

## One Deferral Policy

The candidate leaves setup's original body running inside a thread-local frame
keyed by the native owner's pointer. Construction is skipped with a null result
only for a matching warmup frame. Request establishes a matching demand frame
until its finalizer, so same-owner reentrant requests and the existing shared
factory postfix still run ordinary construction. Other owners and threads are
not suppressed. Nested frames restore their predecessor on normal or exceptional
exit; original exceptions are not swallowed. Registration is exact and rolls
back only this feature's patches if incomplete.

The intentional behavior change is that construction and its asset/lifecycle
failures move from eager startup to the first request for that preview. Native
key/list/duplicate validation remains at startup. There is no alternate preview
factory, native-callsite rewrite, retry path or silent fallback.

## Configuration And Persistence

`homm3NativePreviewStartupDeferral` is one explicit boolean in the existing
launcher/mod settings channel. An absent mod property inherits the launcher
value; an explicit mod `false` overrides it. Malformed, duplicate, nested or
non-boolean effective settings produce a diagnostic and prevent activation.
Decoded property names are compared case-insensitively. The managed reader
accepts comments and trailing commas, but rejects truncated documents and
trailing content; limits are 1 MiB UTF-8 and depth 64.

The histogram tuner now merges only its own fields into the active mod settings
object. Unrelated properties survive, including JSON nulls, nested arrays and
the pilot selector. A legacy settings file is copied into the canonical channel
on save, not shadowed by a tuner-only object. Root launcher settings are not
copied into mod overrides. Malformed/empty existing files fail before writing.

Both operations use one CLR `System.Text.Json` implementation. The
[6.0.11 package](https://www.nuget.org/packages/System.Text.Json/6.0.11) supplies
compile-only .NET Standard API references; runtime assets are excluded and must
not be deployed. The existing game .NET 6 host supplies the runtime assembly.
This compiler API pin is not a runtime or security upgrade. An explicit build/
deploy metadata check guards shared-host availability; it is not loader proof.
The rejected framework XML adapter is not retained as a fallback or repaired
with a custom framing scanner.

## Verification And Cost

`tools/validate_native_preview_startup_contract.py` runs in the
`FullValidationNormalized` tier. Its linked-source headless fixture executes
the real scope and JSON helpers: 12 grouped cases cover thread/native-owner
policy, nested demand/reentry, exception cleanup, invalid ordering/keys, strict
selector semantics and settings merge preservation. The latest standalone run
took 3.14 s total / 3.03 s fixture, with sampled fixture-process-tree peak RSS
241.6 MiB and a 104.0 MiB private-memory estimate. A near-limit input regression
also proves merged output is refused before writing if formatting/updates push
it above the same 1 MiB reader limit. The net9 fixture uses its own framework
parser and does not prove the plugin's API6 compilation or game .NET 6 loading.

The focused MSBuild owner target, including the shared-host metadata check,
passed in 3.86 s. Its nested warm fixture took 1.45 s, sampled fixture-tree
RSS 117.5 MiB / private estimate 52.1 MiB; these are not whole-MSBuild peak
memory measurements. A cold fixture compile took 23.03 s, fixture-tree RSS
246.7 MiB / private estimate 105.2 MiB. A missing-host-path probe failed with
the expected diagnostic in 1.99 s.

The two new current scopes are fresh (1,145 scoped, 238 refused); no matcher or
expensive asset suite ran. The isolated OfficialDeobf/F-current-copy compile
succeeded with 54 warnings / zero errors in 11.42 s MSBuild elapsed (11.983 s
wrapper elapsed). Live interop
checked 1,219 member references across 139 assemblies: 10 pre-existing allowlisted
findings and zero new unresolved references. No allowlist was widened. Restored
assets select the netstandard2.0 API6 compile asset and an empty runtime asset;
the output contains no `System.Text.Json.dll`.

The candidate DLL is 4,788,224 B, SHA-256
`bafb5515f04d56635d21434eac70d71121122162fec513a66ba3545d907d07b7`.
Output and cited logs are under
`V:/olden_port_work/port_runtime_25672315/native_preview_candidate_build/`;
stdout/empty stderr, metrics and exact command are
`logs/build_20261003_122106_168.*`. Nine process-tree samples at a requested
one-second interval recorded peak working set 983,285,760 B / private memory
797,384,704 B; these are sampled tree measurements, not host-wide or continuous
peaks. The command disables deployment and keeps package/cache/temp/output data
on V:. The earlier successful 21.60 s compile and its logs are retained under
`logs/build_20261003_121045_319.*`; its post-build metrics serialization failed,
so its memory peak/wrapper time are unknown. The second compile was required by
the output-quota source correction, not run merely to repair measurement.

At completion of the no-deploy build, F-copy plugin/dependency/Core readbacks
remained unchanged. This no-deploy build does not emit a payload ABI sidecar;
source ABI remains UnitBundle 1 / TownScene 2, not a new sidecar or installation
proof. The rebuilt project dependency is retained only as candidate output, not
installed. Fixture/build proof does not establish game .NET 6 loading, the
native detour, first-demand result, visible model, startup cost or memory savings.
This is sequential semantic/source/compile work; GPU use is not appropriate.

The user subsequently accepted shared-save/cloud testing risk and authorized
runtime testing. The F copy still shares normal saves/cloud state; neither its
local backup nor this experiment proves cloud isolation or restoration. The
unchanged resource guard controls each run. User-visible checks belong in the
existing current-version section of `docs/ingame_check_queue.md`, not in a second
queue.

## Controlled F Install And Run 10

At 2026-10-04 01:50:12 UTC the already-built candidate was installed only to
`F:/olden_port_work/Current Era 25672315 BepInEx`. Matching DLL/dependency,
PDBs and plugin dependency manifest were copied with a freshly generated ABI
sidecar (UnitBundle 1 / TownScene 2); the owning installed/source ABI check
passes. No support, interop or parser DLL, town bundle or unit bundle was copied.
The repaired campaign Core remains `87d1c9e3`; the separate config-ID source
repair is not included. Original small payloads and settings are retained under
the runtime lane's `payload_backup_run10/`.

Canonical mod settings changed only by adding the explicit boolean
`homm3NativePreviewStartupDeferral: true`; structured readback confirmed all
other settings were semantically unchanged. Run 10 (PID 38228) launched at
01:50:36 UTC with 28.034 GiB available commit and the same 10 GiB startup / 2.5
GiB runtime guards. The current-build pilot registered; fresh main-menu frames,
valid native Good1a input, the captured Homecoming dialog and its one native
Start Mission action are recorded. These are install/startup and campaign-path
observations, not evidence that the matched warmup has deferred any preview or
that first demand succeeds. The observed outcome is recorded below.

Evidence: `run10_payload_backup.json`, `run10_payload_install.json`,
`run10_process.json`, `run10_menu_bridge_freshness.json`,
`run10_video_inputs.json`, `run10_storyhub_capture.png` and
`run10_homecoming_start.json` under
`V:/olden_port_work/port_runtime_25672315/`.

### Run 10 outcome

The native log recorded 424 matched `SharedPreviewCreate` calls deferred in
1.3 ms. A fresh `worldLight` frame 18097 and the saved Homecoming capture show
terrain, Castle, HUD, Christian selected and the opening story dialog. This is
rendered-map proof; first-demand model construction, town, battle and preview
lifecycle acceptance remain pending.

Near the map capture, game-private memory was 10,225,192,960 B (about 9.52 GiB);
available commit at that sample was about 19.3 GB. The final sample was
10,280,861,696 B private (about 9.58 GiB) and 13,948,424,192 B available commit.
These observations are not a
continuous peak or an A/B benchmark against Run 9's approximately 25.9 GiB
sampled game-private value, and does not establish that preview deferral caused
the difference. The terrain-count volatile request timed out while pending; the
game exited with CLR 6 access violation `0xc0000005` at
`coreclr.dll+0x1d1fdd`. The resource guard did not stop it. Cause is unproven;
do not replay the same request. This crash does not prove the deferral caused the
exit, nor does the map capture establish first-demand behavior.

Evidence: `run10_memory.jsonl`, `run10_exit.json`,
`run10_terrain_counts.json`, `run10_crash_events.json`,
`run10_world_capture.png/log/result.json`, `Player_run10.log` and
`BepInEx_run10.log` under `V:/olden_port_work/port_runtime_25672315/`.

### Relocation status

The Run 10 tree was copied from F to
`V:/olden_port_work/Current Era 25672315 BepInEx` with native Robocopy; the
copy completed with all 227,835 files copied and zero skipped, mismatched,
failed or extra. Full native metadata comparison also passed with exit 0 and
zero mismatch, failures or extras. The user stopped expanded hash checking;
at that initial copy-verification stage no V ABI check or startup run had been
made. V is available for user testing, and
the failed queued diagnostic was moved outside its live inbox. F is retained;
no new-location runtime proof is claimed.

### Pre-promotion V refresh (historical; superseded 2026-10-04)

The later installed presentation refresh uses DLL `02ff3ec6`; the owner ABI
readback passes (UnitBundle 1 / TownScene 2), and the focused camera gate reports
12 native-provenance catalogs compatible with port camera/settings. Core and
config were unchanged, so the explicit
`homm3NativePreviewStartupDeferral: true` opt-in remains as installed. This is a
source/build/install update for custom preview and map routing, not a change to
the startup-deferral policy. Run 10's 424-call/1.3-ms observation belongs to the
earlier DLL `bafb5515`; it is not post-refresh runtime proof. No V startup was
run after this install. Registration with the refreshed DLL, first-demand model
construction, custom-preview behavior and lifecycle acceptance remain pending
user testing.

Install record: `artifacts/port_current/presentation_refresh_25672315/`;
the pre-install generated-only camera extraction and retarget evidence remains
in `town_camera_refresh_report.md`.
