# Google Bug Report Relay

Status: the player-report receiver was published as version 2 on 2026-10-04 at 19:57 CDT, and
`PRODUCT_ACCEPTANCE_ENABLED=true` is verified. The synthetic-pilot route's
`PILOT_ACCEPTANCE_ENABLED=false` remains unchanged.
Six anonymous synthetic HTTP checks exercised disabled refusal, acceptance, same-ID duplicate
acknowledgement, exact-limit acceptance, oversize refusal, and ID/hash conflict refusal. Two product
reports were committed (888 bytes and 8 MiB); both private Drive files were downloaded through the
owner UI and independently matched to the expected lengths and SHA-256 values. The historical two
pilot records remain preserved. No real game logs, saves, screenshots, or player reports were uploaded.
The reporting plugin binary and scoped configuration are installed and independently read back against
the built candidate. Startup, native UI, and gameplay behavior remain unproven.

The original feasibility test uses
anonymous Google Apps Script receipt with private Google Drive ZIP storage. It is not a public Google Form,
does not require a player account, and does not create GitHub issues. The intended eventual GitHub destination
remains `leviritchie/Golden-Era`; credential setup and issue forwarding are separate, unfinished work.

The original version-1 synthetic pilot folder was created on 2026-10-04. Connector metadata readback returned `shared=false`
with only the owner permission. No real report has been uploaded. After owner sign-in on 2026-10-04, the synthetic
pilot project was created. Private folder and project identifiers are retained in the ignored local receipt,
not this tracked document. At project creation, editor readback after reload matched the committed receiver
source (line endings and trailing whitespace normalized) and manifest (parsed JSON comparison). Saved Script Properties point to the existing
private folder and set `PILOT_ACCEPTANCE_ENABLED=false`. Folder metadata again returned `shared=false`
with only the owner permission.

Historically, after explicit owner approval, version 1 was deployed with owner execution and `Anyone` access. No new OAuth
dialog appeared in that turn; successful `setupPilot()` execution and owner/schema Script Properties proved
the required services were available. This does not establish when the underlying grant was first made.
Anonymous probes carry no Google credentials or browser cookies. Their accepted replies were independently
checked against owner-downloaded private files, not just the receiver's claimed hashes or HTTP 200.

The earlier local `project_prepared.json` is a historical preparation snapshot. Version-1 pilot evidence is
in `artifacts/port_current/bug_report_routing_25672315/google_pilot/cloud_receipt.json`. Current version-2
activation evidence is in the ignored `artifacts/port_current/bug_report_routing_25672315/report_button_player_intake_proof.json`;
it records the publication, live properties, tests and private-byte readback. Private cloud identifiers stay
in that ignored receipt, not this tracked document.

## Player-Report Intake

`Code.gs` now has a separate `player-report` route. It accepts a bounded, opaque ZIP rather than requiring
one of the pilot's fixed synthetic hashes. Its properties and ledger are isolated from the pilot:
`PRODUCT_ACCEPTANCE_ENABLED`, `PRODUCT_PRIVATE_FOLDER_ID`, `PRODUCT_OWNER_EMAIL`,
`PRODUCT_LEDGER_SCHEMA`, and `product.report.*`. The two existing committed pilot records remain preserved.

An owner-owned folder named **Golden Era Bug Reports** was created and verified through connector metadata
as `shared=false`, with only the owner permission. The saved source was reviewed and deployed as version 2
on the existing endpoint after explicit owner approval. The web app executes as the owner and accepts
anonymous requests; players receive no Drive access. The product intake flag is enabled while the
synthetic-pilot route remains disabled. The private project/folder identifiers stay in the ignored owner receipt.

The live acceptance tests used only fixed, in-memory synthetic ZIPs. Owner-UI downloads of both accepted
files were independently checked without executing or extracting the archives. The two accepted product
records consume 8,389,496 bytes of the bounded receiver allowance. No real game log, save, screenshot, or
player report has been uploaded during integration work.

Historical disabled-route check: one explicit in-memory synthetic submission through the managed uploader
reached the then-disabled version-1 endpoint and returned `receiver_refused:disabled`. The current version-2
player-route results are recorded below.

The production budget is **40 reports / 160 MiB per UTC day**, including uncertain reserved writes. It
permits an 8 MiB ZIP in a 12 MiB JSON envelope. Version 3 of the receiver source (this commit, not yet
deployed) replaces the old 512-report / 1 GiB lifetime stop with rotation: committed reports older than
**90 days** are moved to the Drive trash, then the oldest ones once **1000 reports or 1 GiB** would be
exceeded (at most 5 removals per request; the owner trigger `pruneReports()` does up to 200). Today's reports
are never rotated out, so a same-day flood is refused with `storage_budget` instead of erasing yesterday's
real reports. A file is trashed only after its parent is confirmed to be the intake folder; a trash failure
stops pruning and alerts. These are this receiver's admission limits, not Google's plan quotas. An anonymous
endpoint cannot reliably distinguish a malicious sender from a player: abuse can consume the daily allowance.
The client must show an unconfirmed/refused result and retain the finalized local ZIP, not claim success or
fall back to another service.

Player bundles are inspected before storage. The central directory is read first (no zip64, no encryption,
methods stored/deflate only, no duplicate names, declared sizes within caps) and must list only the entries
in `bundle_contract.json`: `report.json` (256 KiB), `bepinex_log_tail.txt` (2.25 MiB: the client tail is 2 MiB, plus room for the truncation line and scrubber growth), `payload_manifest.json`
(256 KiB), optional `native_log.txt` (1 MiB) and optional `screenshot.png` (4 MiB, PNG signature). Then
`Utilities.unzip` must reproduce exactly those entries within the same caps, and `report.json` must be schema
`oe_mod_bug_report.v3` with bounded string fields, the request's report ID, and a screenshot value matching
the entry. Refusals: `invalid_bundle_entries`, `bundle_entry_too_large`, `invalid_report_json`. Nothing is
executed; extraction stays in memory and is not a malware scan.

Alerts: daily-limit, rotation, storage-budget, trash-failure and privacy events send at most one e-mail per
kind every 6 hours to `Session.getEffectiveUser()` (the deploying account) via `MailApp`. Alerts carry counts
and codes only, never report text. This needs the `script.send_mail` scope, which forces re-authorization.

Client token: envelope version 2 adds `clientToken`. While `PRODUCT_CLIENT_TOKEN` is unset the player route
accepts v1 and v2, so the already-installed plugin keeps working during the transition. Once it is set, only
v2 with that exact token is accepted (`client_token_mismatch` otherwise). The token is compiled into a public
mod, so it is **not real security**: it only filters drive-by scanners that find the `/exec` URL. The daily
caps, inspection and rotation are the actual abuse limits.

The receiver checks private folder ownership before admission and private file access after creation. A
detected sharing problem stops product acceptance and retains the charged pending record; it does not prove
that exposure was undone. The owner must disable the deployment if stopping cannot be confirmed and
reconcile the file. Uploaded archives are inspected in memory (see above) but not executed, malware-scanned, or server-side scrubbed.
The client scrubs known identifiers on a best-effort basis and asks the player to consent to private storage;
screenshots require a separate default-off choice.

The managed client validates the exact report-ID/hash acknowledgement and uses only the allowed
body-free Google ContentService redirect. Disk I/O, hashing, compression and HTTP run on a worker. No Google
login, GitHub login, browser handoff, automatic upload or automatic retry is part of the player workflow.
The native integration and its current proof boundary are owned by [mod_bug_reporting.md](mod_bug_reporting.md).

## Scope

The desired player workflow is the existing in-game report form and Submit button. Compression, disk I/O and
network work must leave the game thread; completion must reflect actual receiver acknowledgement, not HTTP
200 or a fire-and-forget task. No browser, login, copy/paste, manual file selection, automatic report upload,
retry loop, idle polling, or diagnostic bridge should be added. The original version-1 cloud pilot did not
change the native path. The native Submit integration has since been implemented and installed; its source
and remaining runtime proof are documented in `mod_bug_reporting.md`.

Read-only inspection of the installed 25672315 interop confirmed the existing sink returns `void` and its
generated state machine uses `AsyncVoidMethodBuilder`; the hook has no returned task to replace with an
upload task. Fresh native-address evidence pinned the current form Submit coroutine and its ordering: the
native collector calls the async-void sink, then clears and closes the form without awaiting receipt. The
old address-to-token lookup database is stale for this installed binary and must not be reused.
Starting a background upload at that sink alone would not establish truthful UI success/failure handling.

The historical version-1 receiver was deliberately synthetic-only; that route remains fixture-only in version 2.
It accepts a JSON object with `purpose: synthetic-pilot`,
`reportId` (UUID), `sha256` and `bundleBase64`. Its ZIP may contain synthetic metadata, bounded log files and a
synthetic screenshot. The receiver additionally pins the exact SHA-256 and length of approved immutable
synthetic fixture ZIPs; a caller-supplied purpose label alone is not evidence that an upload is synthetic.
The probe never reads the user's logs or saves. ZIP signature/digest checks are not a general archive
validation or malware scan; uploaded ZIPs must not be executed or automatically extracted.

## Account And Exposure

Use the owner's Google account to deploy the standalone script as a web app, executing as the deploying owner
with anonymous access. The included manifest declares those settings, but a local manifest does not prove an
actual deployment uses them. The owner must authorize Drive access and verify the deployment options.
Google's built-in `DriveApp` requires the full Drive OAuth scope for file creation. The script only operates
on its configured private intake folders, but that code restriction is **not** a folder-scoped OAuth permission. The additional
`userinfo.email` scope lets owner setup verify that the folder belongs to the executing account; the owner
identity is never returned to anonymous callers. A dedicated Google
account is preferable when broad access to a personal Drive is unacceptable; the steps are below.

### Moving The Receiver To A Dedicated Google Account

The full `drive` scope lets this script read and write the whole Drive of the deploying account, so a bug
in the script, or a leaked editor session, reaches everything there. A dedicated account limits that to bug
reports. Steps (owner only; nothing here is automated):

1. Create a new Google account used only for bug-report intake. Turn on 2-step verification.
2. Signed in as that account, create a folder named **Golden Era Bug Reports**. Do not share it.
3. Create a new standalone Apps Script project. Paste `tools/google_bug_report_relay/Code.gs` and
   `appsscript.json` (enable "Show appsscript.json" in project settings).
4. In Script Properties set only `PRODUCT_PRIVATE_FOLDER_ID` to the new folder's ID.
5. Run `setupPlayerReports()` from the editor and approve the Drive, e-mail and send-mail scopes. It verifies
   the folder is private and owned by this account, records `PRODUCT_OWNER_EMAIL`, and sets intake to `false`.
6. Deploy as a web app: execute as **Me**, access **Anyone**. Copy the new `/exec` URL.
7. Set `PRODUCT_ACCEPTANCE_ENABLED=true`, then run the owner probe
   (`python tools/google_bug_report_relay/probe.py --submit-synthetic --player-format --endpoint <url>`) and
   check the stored file in Drive.
8. Put the new `/exec` URL in the plugin `config.json` (`modBugReportingEndpoint`) and in
   `SHIPPED_REPORT_SETTINGS` in `tools/validate_mod_bug_reporting_contract.py`, then rebuild and install
   through the main session.
9. On the old account, set `PRODUCT_ACCEPTANCE_ENABLED=false`, then archive the deployment once no installed
   build points at it. Move or keep the old reports as you prefer.
10. Add the daily `pruneReports` trigger (redeploy checklist, step 6) on the new project.

### Redeploy Checklist For This Source Version

Order matters, so the installed plugin is never refused during the switch:

1. Open the existing Apps Script project. Replace `Code.gs` and `appsscript.json` with this commit's files.
2. Save, then run `setupPlayerReports()` once from the editor. Google asks for the new `script.send_mail`
   scope; approve it. Setup re-verifies the folder and sets `PRODUCT_ACCEPTANCE_ENABLED=false`.
3. Deploy > Manage deployments > edit the existing web-app deployment > New version. Keep the same `/exec` URL.
4. Set `PRODUCT_ACCEPTANCE_ENABLED=true` again. Leave `PRODUCT_CLIENT_TOKEN` unset: v1 (installed) and v2
   (new) clients are both accepted.
5. Optional check: `probe.py --submit-synthetic --player-format --endpoint <url>` sends a contract-shaped
   synthetic bundle with envelope v2. Expect `ok=true`.
6. Triggers > Add trigger > `pruneReports`, time-driven, day timer. This runs the fuller retention pass.
7. After the main session installs the new plugin build (envelope v2 + token) and players have updated, set
   Script Property `PRODUCT_CLIENT_TOKEN=golden-era-mod-report-1`. From then on v1 clients are refused with
   `client_token_mismatch`.
8. Check the deploying account's inbox. Alert e-mails arrive from that account to itself.

The receiver grants players no Drive access; its anonymous replies contain no folder IDs, file IDs, file URLs,
credentials or OAuth token. The normal write path requires a private folder and verifies private file access
before acknowledgement. Anonymous callers receive only a bounded
result and their own report ID/hash. The folder identifier in the local owner receipt does not grant access. Do not
make the folder public or put a reusable GitHub credential into the mod.

## Admission And Failures

The code pins an 8 MiB ZIP cap and a bounded JSON envelope. A short script lock serializes admission and
bounded durable bookkeeping. The pilot permits at most 40 reports / 160 MiB per UTC day, including uncertain
reserved writes, and retains at most 48 reports / 256 MiB (older ones rotate out) so it cannot consume the
whole Drive account. Quotas and outages are explicit refusals, never permission to forward to Unfrozen,
silently discard a report, or launch a browser fallback. See `Code.gs` for authoritative constants and
documented Drive/property-write crash boundaries.

The synthetic-pilot route remains disabled. The version-2 player intake is enabled after setup and the synthetic
acceptance/readback checks recorded below. A saved file is not by itself player-workflow proof: the client
must validate the acknowledgement, and the owner must verify private storage. Google Apps Script cannot
make Drive writes and script properties one atomic transaction; uncertain failures must remain conservative,
not become false success or unbounded re-upload.

Privacy is checked again after creation. If the new file is detected as shared, the receiver refuses the report,
attempts to stop acceptance and keeps its charged pending reservation. If stopping cannot be confirmed, it
returns `acceptance_stop_failed`; the owner must disable the deployment and reconcile the file. It does
**not** silently delete the file or rewrite
permissions: the file may already exist with broader access and requires explicit owner reconciliation. This
is a fail-stop/refusal guarantee, not proof that detected exposure is undone. The enforced fixture allowlist
means only known synthetic bytes can reach the version-1 pilot; no real report data is permitted in that
route. The enabled player-report route uses the same fail-stop/reconciliation policy. Duplicate
receipts acknowledge historical acceptance; they do not undo later owner sharing or deletion of a stored file.

The disabled synthetic pilot also rotates now (30 days, 48 reports / 256 MiB retained) instead of stopping
at a lifetime ceiling.

Owner setup uses `PILOT_PRIVATE_FOLDER_ID` for the verified folder above. `setupPilot()` verifies its owner and
private sharing, preserves charged admission history, and sets `PILOT_ACCEPTANCE_ENABLED` to `false`. Only after
authorization and a disabled-response test, the owner explicitly set pilot acceptance to `true` for synthetic
probes; it was returned to `false` afterward and remains disabled. Do not edit or erase `pilot.report.*` reservations to make a refusal pass; reconcile uncertain writes
against private Drive files first. Retention rotation (above) is the only automatic cleanup; it never
removes pending reservations.

## Cloud Results

The following bounded checks ran against deployed version 2 on 2026-10-04. There were six explicit anonymous
POSTs and exactly two stored product files/committed admission records. The product folder and both files had
`shared=false` and only the owner permission in metadata readback; each file had the expected parent folder.
Independent owner-UI downloads matched the expected byte lengths and SHA-256 values. The earlier two pilot
records remained intact.

| Check | Result | Observed Timing |
| --- | --- | --- |
| Disabled before admission | JSON refusal `disabled`; no file or ledger reservation | managed uploader 1.891 s process time |
| Small synthetic ZIP | accepted, 888 bytes; owner readback matched expected SHA-256 | managed uploader 3.719 s process time |
| Same-ID byte-identical retry | acknowledged `duplicate=true`; no additional file | managed uploader 1.781 s process time |
| Exact 8 MiB player-format ZIP | accepted, 8,388,608 bytes; owner readback matched expected SHA-256 | probe 13.5 s |
| ZIP one byte over the limit | JSON refusal `bundle_too_large`; no accepted file | 2.266 s process time |
| Accepted ID reused with different 756-byte ZIP | JSON refusal `report_id_conflict`; no extra file | 2.312 s process time |

Uploader and probe process times are bounded observations, not a latency SLA or load test. Peak memory was
not measured for these cloud probes. This is not a game-thread-performance claim; compression, persistence,
and upload must remain off the game thread with truthful pending and acknowledged completion states. The
cloud checks prove no native UI behavior.

During the historical version-1 pilot, raw connector fetch returned a streamed file reference but no local path;
attempted local materialization failed (PowerShell Schannel missing credentials; Python HTTPS 403). For the
current version-2 checks, owner-authenticated Drive UI downloads completed even though the download-event
observer timed out on the source tab. The exact named ZIPs appeared in Downloads, were copied to the V
artifact directory, and were independently hashed. This was
owner verification only, not a player workflow or client fallback.
No signed download links, tokens, real game logs, saves or game captures are retained in the receipt.

The synthetic-pilot route remains disabled and its records were not cleared. The version-2 product intake remains
enabled after the tests, with only the two verified synthetic records charged to its ledger. The public
endpoint does not make the Drive folder public; file access remained owner-only in metadata and byte-readback
checks.

## Offline Verification

`tools/validate_mod_bug_reporting_contract.py` checks the pilot manifest and runs the dependency-free Node
fixtures as part of the existing full-tier reporting gate. Node is required for this contract; missing Node or
a failed fixture is a hard failure, not a skipped check. The subprocess has a 20-second ceiling. No fixture
contacts Google, reads real game reports, or changes cloud resources. Offline measurements on 2026-10-04:

| Check | Result | Measured Cost |
| --- | --- | --- |
| Pilot receiver fixtures at version-1 milestone | 18/18 pass | 0.252 s TAP duration; 169,208 KiB / 165.242 MiB process peak RSS |
| Current pilot + player-route receiver fixtures, including namespace isolation, budget and privacy faults | 29/29 pass | 0.886 s wall time; 268,924 KiB process peak RSS |
| Managed uploader fixtures, with no network calls | 19/19 pass | 0.505 s wall time; sampled 32.1 MiB peak working set |
| Current managed uploader + linked-source packaging fixtures | 24/24 pass | 0.347 s suite timer; 66,068,480-byte process peak working set |
| Current owner HTTP probe safety fixtures, including mocked player/oversize options | 6/6 pass | 0.106 s suite duration; current peak not remeasured |
| Pilot-milestone owning validator, before the player/UI changes | passed that historical source | 1.047 s wall time |
| Pre-install player/UI owning validator, including current scoped symbols | source/static + offline fixtures pass | 3.935 s wall time; aggregate peak memory not measured |
| Post-install owning validator, 2026-10-04 | source/static + offline fixtures pass; no cloud/game calls | 5.594 s wall time; aggregate peak memory not measured |

The linked packager uses stubbed native/Harmony/config surfaces: it does not validate real hook binding or UI.
Memory numbers are individual fixture-process high-water marks, not a measured combined process-tree peak.
These offline measurements establish neither Google quota/latency nor game-thread performance. The existing
full-tier target invokes the owning validator. The test-candidate plugin compile and live-interop
reference check passed in 11.703 s with 56 warnings and no errors; independent current UI/source review found no
remaining source blockers. The strict release-wide symbol gate retains known unrelated findings;
the test-only exception and proof boundary are recorded in `docs/mod_bug_reporting.md`. The later binary-only
install and configuration readback are summarized there; startup and native UI remain untested.
The historical pilot source review completed with no remaining blocking findings. It checked scope/proof claims,
synthetic enforcement, private-storage failure handling, missing configuration, exact JSON media type and
malformed committed bookkeeping. That review is not cloud or native-runtime validation.

The canonical fixture command is `node tools/google_bug_report_relay/test_receiver.cjs`: the `node:test`
suite runs in one process and assertion failures return nonzero. `node --test` worker spawning was refused by
the Windows sandbox before fixture execution. There is no alternate runner, automatic fallback or test skip.

The owner-operated `probe.py` requires both an observed `/exec` URL and `--submit-synthetic`. It creates a valid
synthetic ZIP entirely in memory, has no cookie jar or Google credential, follows only the expected Google
Content Service redirect, bounds the reply, and performs one attempt. It never runs during build or deploy.
The default probe is small; `--at-limit` sends an exactly 8 MiB ZIP. `--oversize` sends a synthetic ZIP one
byte over that limit; it is mutually exclusive with `--at-limit`. `--player-format` selects the player-report
route without changing the synthetic origin of the bytes. Fixed ZIP timestamps make explicit
same-ID duplicate probes deterministic. Output is receipt evidence only, not owner Drive readback proof.

The version-2 cloud checks above prove anonymous small-ZIP acceptance; exact 8 MiB acceptance and private-byte
readback; disabled refusal before admission; same-ID duplicate acknowledgement without another file;
oversize and ID/hash conflict refusals; and no account/login redirect. A disabled JSON reply is an
anonymous application refusal, even though the current probe exits nonzero and prints
`anonymousHttpProven=false` for every non-acceptance. The receipt records the refusal codes and verifies no new
file or reservation; it does not treat the probe's nonzero exit as an authentication failure.
Do not broaden the probe's redirect handling if the deployed behavior differs from its admitted statuses.

Daily-cap and retention-budget exhaustion and Drive/property fault injection must remain offline or use a separately
approved disposable environment;
do not fill or rewrite the preserved pilot or player ledger just to produce a cloud refusal. The owning
validator never publishes the script, enables acceptance, sends a report, or launches the game. Do not use outgoing `UrlFetchApp`
request limits as evidence for inbound `doPost` payload size. Plugin installation is a separate proof tier;
no game launch or runtime/UI check occurred as part of these cloud tests.

## Sanitize Before Making The Repository Public

`golden_era` (origin) is private; `Golden-Era` is the public repository. Before publishing history or
pushing to the public repository, check at least:

- The original pilot Drive folder ID was committed in `ca47308a69` and removed in `ccfb58b0b1`; it is still
  in history. A folder ID grants no access while the folder is private, but publish either a squashed/filtered
  history that excludes those commits or confirm the folder stays private (or delete it). History was
  deliberately not rewritten in the private repository.
- No Script Property values, owner e-mail, project IDs, file IDs or receipts from `artifacts/` (they are
  ignored; check `git ls-files artifacts` for anything force-added).
- The `/exec` URL in `config.json` is public by design; the `clientToken` is public by design.
- Run `git log -p -S <id>` for every private identifier in the local owner receipt before publishing.

## Google References

- [Web app request and owner-execution behavior](https://developers.google.com/apps-script/guides/web)
- [Anonymous deployment manifest](https://developers.google.com/apps-script/manifest/web-app-api-executable)
- [Drive blob file creation and required authorization](https://developers.google.com/apps-script/reference/drive/drive-app#createFile(BlobSource))
- [Content Service redirects](https://developers.google.com/apps-script/guides/content#redirects)
- [Apps Script quotas](https://developers.google.com/apps-script/guides/services/quotas)
- [Utilities.unzip](https://developers.google.com/apps-script/reference/utilities/utilities#unzip(BlobSource))
- [MailApp.sendEmail](https://developers.google.com/apps-script/reference/mail/mail-app)

These references establish supported APIs. The cloud results above, not the references or offline fixtures,
establish the limited deployed synthetic receipt/readback proof.
