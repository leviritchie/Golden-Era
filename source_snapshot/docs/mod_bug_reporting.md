# Mod Bug Reporting

Status on 2026-10-04: source/static checks, offline fixtures and the established OfficialDeobf Release
build are proven. The version-2 anonymous player receiver is published and enabled, with six synthetic
HTTP checks and private-byte readback for its two accepted ZIPs; the separate synthetic-pilot route remains
disabled. The plugin is installed as a binary-only payload, and the four reporting/telemetry config keys
were merged with all 82 pre-existing plugin-config values preserved. Startup, native hook behavior,
report-form completion, and gameplay remain unproven. See [Google receiver](google_bug_report_relay.md)
for cloud evidence and [the in-game check queue](ingame_check_queue.md) for the remaining user-visible test.

The target is the active Golden Era install, Steam build 25672315 / `GameBuildKind.Current`.
Select the build by `GameAssembly.dll` hash, not the directory name. An old
`MethodAddressToToken.db` was found to disagree with that installed binary during this integration.
New report-form pins must use the hash-bound current `PortInterop native-addresses` output;
old database-based callback and native-body claims are not current evidence.

## Ownership

The player uses the game's report button. Reporting belongs to Golden Era, not the original
developer, when the mod redirect and telemetry protection are active. There is one delivery path:
an explicit, consented player submission to the configured anonymous Apps Script receiver.
No browser, GitHub login, GitHub issue creation, automatic desync upload, or alternative endpoint
is part of this path. `leviritchie/Golden-Era` is the intended future issue tracker, not a fallback.

The native `HexAnalytics.SendReport` sink is a nine-argument `void` method. Intercepting it alone
cannot make the native report form await remote receipt. The integrated Submit owner must also
control the native capture/completion boundary, prevent premature native success, and present
truthful pending and acknowledged states. A recent form-open timestamp is not submission consent.
Game member names and current-build pins belong in `GameSymbols.ModBugReporting`.

`ModBugReportRedirect` always suppresses the native send. Its existing fail-closed behavior blocks
the form opener and every desync launcher if the sink cannot be patched, with an explicit error.
`NativeTelemetryBlock` continues to suppress gameplay metrics, table sends and automatic desync
reports. It leaves the report sink to the redirect when the redirect holds it. `Plugin.Load`
registers the redirect before the telemetry block. Unbound protection is an error, not a success.

## Submission Contract

The required player experience is a report form followed by a clear private-upload consent choice.
Logs and report text go to the mod owner's private Google Drive folder; screenshot inclusion also
requires the player's choice and `modBugReportingIncludeScreenshot=true` (default `false`, opt-in). A
screenshot is not text-scrubbed. The consent screen must disclose this rather than imply that all personal
details are guaranteed removed. It also discloses the metadata sent (plugin/game/OS versions, report ID,
timestamps), that Google sees the connection's IP address, and the retention periods: up to 90 days in the
private Drive, up to 30 days (newest 50) locally.

The consent, status and notice windows are written for players: plain language, no error codes, paths or
config keys (those go to `BepInEx/LogOutput.log`); a sent report shows only the first block of its report ID
as a reference. They are laid out on a 720-line virtual screen and scaled up by `GUI.matrix` with the
screen height (never below 1:1), and the input shield is placed at the scaled pixel rect.

Only bounded managed strings and copied byte arrays may cross into the background transaction.
IL2CPP proxies, dictionaries, Unity objects and UI controls remain on the main thread. Scrubbing,
log reads, hashing, ZIP compression, persistence and HTTP submission run off that thread.
An upload may continue while the player returns to the game; its status must not steal focus.

A locally finalized ZIP is not remote success. The client accepts success only from HTTP 200,
bounded `application/json`, and an exact acknowledgement containing `ok=true`, the matching UUID
and SHA-256, and a boolean duplicate flag. The transport makes one attempt. Its overall timeout is
60 seconds plus the request size at 50 KiB/s, capped at 300 seconds, so an 8 MiB bundle on a slow uplink is
not cut off at 60 seconds. The envelope is version 2 and carries a fixed shared `clientToken`; that token is
a drive-by-scanner filter, not authentication. Google ContentService's response redirect is followed only as a body-free HTTPS GET to
`script.googleusercontent.com`; arbitrary redirects, cookies and authentication are disabled.
[Google documents that response redirect](https://developers.google.com/apps-script/guides/content#redirects).

Refusal, malformed reply, lost acknowledgement, cancellation or timeout never becomes "sent."
In particular, timeout can occur after private storage succeeded, so the result is unconfirmed,
not proof that no upload happened. The finalized local ZIP remains under `BepInEx/mod_bug_reports`.
An explicit in-session retry reuses its UUID and byte-identical ZIP, verifies the saved digest, and does not
recapture, repackage, silently bypass admission, or automatically resend in a loop.
Hiding the status preserves that retry handle. To reopen it, open the native report form, enter a
non-empty title to enable its native Submit button, and press Submit; opening the form alone does
not reopen status. That Submit is intercepted before a
new capture or upload and offers the retained report's retry or explicit abandonment. Only an
explicit, warned abandon action releases a failed report's UI handle; abandonment is recorded in a `.state`
sidecar so the report is not offered again. The ZIP and integrity sidecar remain on disk if packaging
finalized them. After a game restart, the newest finalized report (at most 7 days old) that was neither
acknowledged nor abandoned is offered once, minimized, as "A bug report from your last session was not sent"
with the same explicit Try again / Discard choices. It is never resent automatically. Local retention is not a
promise that the report will eventually be delivered.

Current native evidence pins the title's value-change callback as the owner of Send interactability:
non-empty title enables it, empty title disables it. The mod does not force-enable native form
controls. Reopening the form and the retained retry workflow still require a focused gameplay check.

## Bundle And Limits

Schema: `oe_mod_bug_report.v3`. The ZIP contains sanitized report text/category/tag, report UUID,
plugin/game/OS metadata, a bounded BepInEx log tail, a bounded native log tail when supplied by
the verified capture flow, and a payload manifest. The contact value is not stored; only whether
contact was provided is recorded. Native additional attachments are summarized by bounded names
and lengths, not copied into the ZIP. Saves, maps and arbitrary files are not uploaded.

Text scrubbing replaces profile/home paths, Steam identifiers, email addresses, IPv4/IPv6 addresses
(loopback, `0.0.0.0` and broadcast are kept), Steam account and persona names read from the local
`loginusers.vdf`, and machine/user names. It is best-effort minimization, not a guarantee against every identifier or secret in a log.
Native gzip processing has independent compressed-input and inflated-byte ceilings, so producing
a short log tail cannot cause unbounded decompression.

| Client Limit | Bound |
| --- | --- |
| New-report cooldown | 120 seconds |
| New bundles per UTC day | 10 |
| Final ZIP | 8 MiB |
| BepInEx log tail | 2 MiB |
| Native log tail | 256 KiB |
| Optional screenshot | 4 MiB |
| Native compressed/input log | 4 MiB |
| Native inflated log processing | 16 MiB |
| Report text | 512-character title; 16,384-character description |

New reports are deduplicated by sanitized report-content hash within 24 hours. Disk admission history
survives a restart. Bundles whose upload was refused or abandoned do not count toward the daily cap or the
duplicate check, so a player can resubmit after a failure. Explicit retry is the same transaction, not a new
bundle. A partial/oversize temporary archive may be discarded; an already finalized report must not be
deleted on upload failure. Local bundles older than 30 days, or beyond the newest 50, are deleted with their
sidecars at startup and before each new bundle; a report that is currently being sent or retried is never
pruned.

The receiver independently enforces 8 MiB ZIP / 12 MiB JSON and 40 reports or 160 MiB per UTC day. Player
reports are inspected before storage: the ZIP central directory must list only `report.json`,
`bepinex_log_tail.txt`, `payload_manifest.json`, and optionally `native_log.txt` and `screenshot.png`, each
within its own cap (256 KiB, 2.25 MiB, 256 KiB, 1 MiB, 4 MiB), with no duplicates, encryption or zip64; then
`Utilities.unzip` must reproduce exactly those entries and `report.json` must match the schema and the
request's report ID. The shared contract is `tools/google_bug_report_relay/bundle_contract.json`. Storage
rotates instead of stopping: committed reports older than 90 days are trashed, then the oldest ones once 1000
reports or 1 GiB would be exceeded; today's reports are never rotated out, so a flood is refused with
`storage_budget` instead. These are finite safety limits chosen for this deployment, not Google plan
allowances. Rate-limited e-mail alerts reach the deploying account on daily-limit, rotation, budget and
privacy events. Anonymous traffic can still exhaust the daily allowance; there is no documented trusted
client-IP field to implement per-IP admission in `doPost`.

## Configuration

Source defaults are `modBugReporting=true`, `blockNativeTelemetry=true`,
`modBugReportingIncludeScreenshot=false`, and an empty `modBugReportingEndpoint`. The shipped plugin
`config.json` also sets `modBugReportingIncludeScreenshot=false`; an owner can set it to `true` to offer the
screenshot checkbox.
The shipped config sets the current public Apps Script `/exec` URL. That URL is not a secret and does not
grant Drive access. The 2026-10-04 installed readback (before the screenshot default changed) confirmed
`modBugReporting=true`, `blockNativeTelemetry=true`, `modBugReportingIncludeScreenshot=true`, and the endpoint
matches the deployed receiver; the next install must merge `modBugReportingIncludeScreenshot=false`. The screenshot setting permits capture when separately chosen; the player's screenshot choice
remains default-off. Receiver acceptance is independently enabled and verified in the cloud evidence.
The obsolete `modBugReportingIssueRepo` setting and browser route have been removed.
The Submit integration requires a valid configured endpoint. An empty or malformed endpoint fails
registration closed, with a diagnostic; it is not a selectable local-only reporting mode.

Configuration layers are `<GameRoot>/OfflineLauncherConfig.json`, then
`<GameRoot>/BepInEx/plugins/OfflineUnlockMod/config.json` for keys present in the plugin layer.
A plugin-side `OfflineLauncherConfig.json` is not the root layer. Binary-only plugin deployment does not
copy source config, so the reporting values were merged into the existing plugin config as a scoped update.
Readback confirmed 86 total keys, with all 82 pre-existing values unchanged. The root
`OfflineLauncherConfig.json` was absent; the stale nested launcher file was not read or modified.

With reporting off and telemetry blocking on, native reports are suppressed without delivery.
With both off, native behavior is unchanged and can reach the original developer. Neither setting
is implicitly controlled by `releaseSafeProfile`.

## Analytics Host Guard And State Notice

The redirect and the telemetry block both hook named game methods; a game update that renames them can leave
the redirect `Unprotected`. `NativeAnalyticsHostGuard.cs` is an independent second layer behind
`blockNativeTelemetry`: it prefixes the gRPC library's `GrpcChannel(Uri, GrpcChannelOptions)` constructor
and, only when the host is the developer's analytics host, substitutes `https://127.0.0.1:9/` (a closed local
port). Other hosts are untouched. Failure to bind is logged at error level and does not stop the plugin.

Whenever the redirect is not `Redirecting`, a dismissible on-screen notice explains the state: report buttons
disabled (`EntryPointsBlocked`), upload unavailable (`SubmissionUnavailable`), or protection failed
(`Unprotected`, with which fallback layer is active). With `modBugReporting=false` the notice appears only
when the telemetry block is not discarding native reports. Proof: source/static, build and live-interop gate;
the constructor hook and the notice have not been exercised in a running game.

## Validation

The existing full-tier `ValidateModBugReportingContract` owns the source/protocol checks and
offline receiver, probe and managed-client fixtures. It must not contact Google, enable intake,
read real player reports, or launch the game. The quick build still performs live-interop and
deployment-safety checks; it is not a substitute for the owning reporting contract.

Measured completed components on 2026-10-04: receiver fixtures 29/29, 0.886 s wall / 268,924 KiB
process peak RSS; managed uploader and packaging fixtures 24/24, 0.347 s suite timer /
66,068,480-byte process peak working set. Packaging fixtures link the production packager with
stubbed native/Harmony/config surfaces; they do not exercise actual symbol binding, native hooks,
or the report UI. These are individual offline-process measurements,
not an aggregate process-tree or game-thread performance claim. The pre-install owning source/fixture
gate passed in 3.935 s; aggregate peak memory was not measured. The established OfficialDeobf
test-candidate build passed in 11.703 s with live-interop reference verification, 56 warnings and no errors.
The post-install owning validator rerun also passed in 5.594 s; it made no cloud or game calls.
The binary-only Release build/deploy completed in 18.735 s with default deployment-safety
and live-interop gates passed, 56 warnings and no errors. The strict current symbol gate still fails on
39 known flat findings and two unrelated confinement excesses; the deployed build used the documented test-only
`SkipGameSymbolsHintContract=true` exception, not an allowlist change or release pass. All eight
new reporting scope declarations are generated, exact-owner scoped and checked by the owning
reporting validator. No new reporting confinement excess remains. Current scope generation took
0.438 s and the strict audit took 4.16 s. Build/aggregate peak memory was not measured.
Sequential file I/O, parsing, standard cryptographic hashing and network transport
use the CPU. The optional screenshot uses `ScreenCapture.CaptureScreenshotAsTexture` at end of frame, a GPU
`Graphics.Blit` downscale, one `ReadPixels` of the small target and Unity's `ImageConversion.EncodeToPNG`;
the earlier ImageSharp/`AsyncGPUReadback` path was removed. Screens larger than 16 million pixels are
refused; output is limited to 1280 by 720 pixels and 4 MiB, and every texture/render target is released the
same frame. The encode is a one-frame main-thread cost on an opt-in action. A capture error offers an
explicit send-without-image choice, not an automatic substitute. Screenshot framing, orientation and
game-thread cost remain runtime-unproven.

2026-10-05 abuse/privacy/usability rework (offline only): receiver fixtures 38/38 (1.05 s TAP duration,
236,804 KiB peak RSS), managed uploader fixtures 21/21 and packaging fixtures 10/10, probe fixtures 7/7, and
the owning validator passed with no cloud or game calls. The OfficialDeobf build compiled and its
live-interop check reported new=0; the strict symbol gate still fails only on its known baseline.

Installed-payload readback: the installed DLL (4,857,344 bytes), PDB (1,324,348 bytes), and ABI sidecar
(497 bytes) matched the built candidate byte-for-byte. The ABI sidecar reports `UnitBundle=1` and
`TownScene=2`; reporting does not add a payload ABI surface. The active game's `GameAssembly.dll` hash
matched the 25672315 / `GameBuildKind.Current` pin. These checks prove installed bytes/configuration only;
the game was not launched, and no startup or report-button runtime test has run.

## Supervised test

Runtime and user-visible proof are separate from source, cloud fixtures, build and installed
payload proof. Do not launch/stop the game, enable a disabled diagnostic bridge, or upload the
owner's actual game logs/screenshots as an incidental test. The player must explicitly consent
to a real report's data and destination. A title saying "test" does not make the accompanying
logs or screenshot synthetic.

The single user-visible checklist belongs in `docs/ingame_check_queue.md`.
Verify startup protection, open the in-game report form and cancel consent, then explicitly
submit only after the player accepts its disclosed data. Check pending status while returning
to gameplay, receiver-acknowledged success, and retained-ZIP/unconfirmed status on refusal or
lost connectivity. Verify screenshot opt-out, no browser/login/developer route, and same-ID
manual retry. Clear neither local admission history nor the receiver ledger to manufacture a pass.

Cloud verification instead uses only deterministic in-memory synthetic ZIPs. The managed fixture
runner requires explicit `--submit-synthetic --endpoint <observed URL>` for its cloud mode;
its ordinary no-argument tests remain offline. The Python probe likewise requires
`--submit-synthetic`; `--player-format` changes only the envelope, and `--oversize` creates an
8 MiB plus one-byte synthetic refusal fixture. Neither command accepts arbitrary file inputs.
