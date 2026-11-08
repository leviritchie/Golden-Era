# Current-version port runtime work

Status: historical isolated-copy runtime evidence. The 25672315 payload has since been
promoted to the existing Golden Era path; the authoritative receipt, current build/install
evidence and remaining checks are in `current_version_consolidation.md`. Runs and observations
below remain tied to their named F/V copies and builds; they do not prove startup or gameplay
on the promoted install. The 2026-10-02 authorization applied to this port lane only; unrelated
frozen lanes remain frozen.

Safety: the controlled copy isolates executable/plugin/Core payloads, **not saves
or cloud state**. It uses the regular LocalLow account and Steam's matching save cache.
Verified local-account and Steam-cache backups exist on V; neither proves
service-side cloud isolation or restoration. On 2026-10-03 the user explicitly
accepted testing against the shared cloud state. That risk decision is resolved;
do not ask for it again. It does not prove isolation/restoration or authorize
unnecessary deletion of existing profiles. Profile/mission tests remain within
this recorded test-copy scope and subject to a fresh resource check before launch.
Native Campaign profile-selector and campaign-selection visibility are proven,
not gameplay. Run 7 used the native default-name Continue path for slot II;
run 8's separate selector capture verifies persisted `PROFILE 2` in that slot.
Existing profile I was not deleted by this lane.

## Resource gate

After the user's background-process cleanup, run 7's launch record at 2026-10-04
00:27:40 UTC (2026-10-03 19:27 CDT) records 29.266 GiB available commit.
The 10 GiB startup guard passed. No other-owner
process was stopped by this lane. Run 7's 28 samples had 23.639 GiB minimum
available commit and 5.309 GiB maximum game private memory; the 2.5 GiB runtime
guard did not stop it. These are sampled values, not interval-wide peaks.
Run 9 resolved the native Good1 video failure. Run 10 reached a rendered map at a
sampled game-private-memory value of about 9.5 GiB; the game then exited with a
CLR access violation while a terrain-count request was pending. Run 9's separate 27.8 GB
guard stop and this one Run 10 sample are different attempts, not an A/B benchmark
or proof that preview deferral caused the memory difference. Town, battle and
first-demand preview behavior remain unaccepted.

### Earlier low-headroom evidence

The host has 31.771 GiB visible physical RAM. Low **commit headroom** is not the
same as low free physical RAM: Windows must back committed allocations with RAM
or pagefile capacity; see Microsoft's
[commit-limit definition](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-performance_information).
At 2026-10-03 15:14:15 UTC, with no game running, committed
memory was 50.312 GiB of 54.599 GiB, leaving 4.287 GiB, while 11.846 GiB physical
RAM remained available. The existing 10 GiB startup guard was not satisfied.
Earlier in this inspection available commit fell to 0.964 GiB; these are changing
point samples, not a fixed machine limit or a measured leak rate.

The live process inventory showed 183 Node processes totaling about 10.06 GiB
private memory. Targeted command-line classification found Codex/tool-server
processes in that group. Python allocations were also substantial, including
the existing town preview and two transient multi-GiB workers; those workers
exited before their ownership could be recovered. No currently live port-owned
build/helper/game process was identified. No other process, pagefile setting or
memory guard was changed. The historical map-run peak below remains separate
evidence; it is not the normal game's proven RAM requirement. Shared-cloud
consent removed that decision gate, not the need for a fresh resource check.

## Ownership and target

- Shared-board project: `7e5e8c425fdd4eceb4bd7773e8257aea`.
- Current runtime target: `V:/olden_port_work/Current Era 25672315 BepInEx`.
  Copy and full native metadata comparison passed; expanded hash checking was
  stopped at the user's request. No V startup test was run. F remains retained.
- Steam build: 25672315; GameAssembly SHA-256
  `d9972b0e7f7dd1c17758808e2f1b80e0a728946416d9a41deaa99bad744de53a`.
- Source baseline: port commits `e068605357` and `68a3946e6b`; plugin build
  0.1.318. The Run 10 candidate plugin (`bafb5515`), `OldenAiSim.dll`
  (`c340a580`), repaired Core (`87d1c9e3`) and explicit preview-deferral opt-in
  were copied with the runtime. Installed readback at V is pending. The separate
  config-ID repair remains source-only and was not included. ABI is UnitBundle 1 /
  TownScene 2.
- Normal Golden Era and vanilla Steam payloads have not been modified by this lane.
- Evidence and backups: `V:/olden_port_work/port_runtime_25672315/`.
  Old plugin files, logs, bridge directories and interop were preserved before
  staging. The current game's interop was regenerated rather than reusing the
  preceding hotfix's cache.

## Payload preparation

The paused build had passed Core layers 1-10. Only its unfinished continuity
layer was resumed using the existing explicit diagnostic-resume option. This is
not evidence of a fresh, full rebuild from vanilla.

- Input Core: `52f05f7a8e5949c694c744a12b3a48014aced3abb68e7ca1343de22df98f9bfc`.
- Pre-video-repair Core: `21f1877c8a12bbb7fd5a1e7c03b80b1dbede28f287bdce2ab314f51a2bc293c0`.
- Final layer passed in 734.573 seconds; guarded process-tree peak private memory
  was 1.09 GB. This is CPU/I/O work, not a GPU raster or array-math stage.
- Installer timings: spawn validation 203.907 s, map installation 8.318 s,
  single Core rewrite 460.524 s, installed verification 61.339 s. Regeneration was
  skipped explicitly because the generated missions were unchanged.
- All 174 generated Story_maps payload files were copied and SHA-256 readback
  checked in the isolated runtime. Their filenames had no duplicates in the
  root maps directory. Core copy plus member readback took 1.498 seconds.
- Reports: `core_final_work/rebuild_report.json`, `core_final_guard.log` and
  `final_payload_preparation.json` in the evidence folder.

### Native campaign video dependency delivery

The isolated F payload now has the prepared dependency closure for all 85 clip
keys referenced by its 23 StoryHubs. The new final rebuild layer derives that
set from the target hubs rather than copying every donor clip. It adds only the
referenced registry rows, MP4/sidecar files and English native subtitle tokens;
it preserves the target's tokens-only cinematic schema and does not fabricate
a legacy array. No playback patch, subtitle suppression or video skip is used.

The 2026-10-04 UTC delivery changed two Core JSON members and installed 166
previously missing media/sidecar files (737,521,186 bytes). The target registry
now has 86 rows and English cinematic has 539 native tokens. Core installed
readback is `87d1c9e35598ac41e0a1f031bf81283b7c46bf7285d4f69d1630e4a6bdc4365d`;
the plugin remains `6c9ea9b4`. Maps and large asset bundles were not rebuilt.
The original Core is backed up under the delivery work folder. Golden Era
donor Core `0986a509` was read-only; normal Golden Era and vanilla Steam payloads
remain untouched.

Independent source review corrected unsafe scratch/report destinations,
incomplete mutation reporting, tokens-only locale handling and constrained
candidate-member addition. The owning 12-layer gate passes, including the
synthetic helper suite (14 tests, one explicit real-7z skip). It is wired to the
existing FullValidation build target; an ordinary quick build does not prove
this contract. The separate opt-in real-7z fixture passed with an all-hub union
and tokens-only target. This is fixture evidence, not native playback evidence.

Measured CPU/JSON/archive I/O costs: the read-only plan took 2.710 s; the owning
gate wrapper took 2.272 s with 38,531,072 B sampled process-tree private memory.
Real delivery took 14.264 s (14.658 s wrapper), sampled tree private peak
147,869,696 B at 250 ms intervals. The stager's own Windows peak pagefile usage
was 118,603,776 B, excluding the 7-Zip child. No GPU stage or full recompression
was needed. Installed Good1 canvas/audio/duration/registry and all campaign
native softsub-token checks passed in 0.883 s (1.567 s wrapper; 32,538,624 B
sampled tree private). All three Good1 probes used ffmpeg, not the legacy tkhd
fallback. These costs are not game resource measurements.

Evidence: `video_all_campaign_plan_v2.json`, `video_owner_contract_v2.*`,
`video_dependencies_delivery/dependency_report.json`,
`video_dependencies_delivery_command.*` and `video_installed_owner_check.*`
under the lane folder. The earlier read-only plan failure is retained. Delivery
is installed-payload proven for the full referenced set. Run9 below separately
proves Good1a native playback; it does not exercise every delivered movie.

## Runtime observations

### Run 7: native campaign entry

The visible F-copy launch at 2026-10-04 00:27:40 UTC (2026-10-03 19:27 CDT)
used the unchanged installed plugin `6c9ea9b4` and Core `21f1877c`.
The launch/15-second memory guard had a 20-minute deadline and a 2.5 GiB commit
stop threshold. Both bridge frames advanced in a 1.5-second menu freshness
sample before controls were used. Plugin initialization was 12.351 seconds;
`Plugin.Load` completed at process uptime 76.936 seconds, after native bootstrap.

Fresh native Campaign controls opened the profile selector. Capture-only proof
shows existing profile I and empty slots II-IV. A native pilot click selected
slot II; a separate capture shows the Select Campaign dialog with Long Live the
Queen selected. Native Continue accepted the blank/default profile-name field;
no text setter, allowlist change or profile deletion was used. The Player log
then recorded `Saved hub`, but the saved immediate action observation still
reported `mainMenuDecor` / `main_menu`; no saved Run7 bridge observation verifies
StoryHub. Run8's `run8_profiles_initial.png` separately verifies persisted
`PROFILE 2`, zero play time and zero story progress. This changes shared
profile/cloud state under the user's recorded consent. It is profile-persistence
proof, not visually accepted StoryHub or mission gameplay.

Immediately after `Saved hub`, `BhSubtitlesPlayer.Load(ClipInfo[])` repeatedly
threw `NullReferenceException` beneath `BhVideoPlayer.Play`. The final log reports
`Callback registration failed. Increase kMaxCallback` on the video Instantiate
path. PID 46368 ended at 00:35:28 UTC with code -2147483645; the memory
guard did not stop or kill it. The final sample still had 23.924 GiB available
commit. The exact null operand and relationship of the terminal callback failure
to the exception flood are not yet proven; do not suppress subtitles or skip
videos as a repair. The nearby `_test` arena messages are native prewarm, not
evidence that campaign combat started.

The requested post-Continue capture timed out before probe execution. There is
no StoryHub screenshot or mission/map start in this run. Terrain count source
`tools/live_probe_mcp/probes/terrain_counts_25672315.cs` has been independently
checked against the exact F interop, but is not compiled or runtime-proven; its
singleton count does not establish the active-map shader index domain.

Evidence under the lane folder: `run7_process.json`, `run7_memory.jsonl`,
`run7_exit.json`, `Player_run7.log`, `BepInEx_run7.log`,
`run7_menu_observation.json`, `run7_campaign_click.json`,
`run7_profiles_initial.png`, `run7_slot2_click.json`,
`run7_profile_creation.png`, `run7_profile_creation_observation.json`,
`run7_profile_input_components.json` and `run7_profile_continue.json`.
The capture assembly's compile took 5.750 seconds (33 warnings, zero errors;
7.09 seconds for the full bridge call). Its separate compile-process peak RAM
was not measured. It only captures one end-of-frame image, encodes PNG and
destroys the temporary texture; it does not enumerate world/camera DTOs.

### Run 8: exact native video input

The next guarded visible launch began with 29.070 GiB available commit. A fresh
bridge sample advanced both frames, and a separate capture of the selector shows
`PROFILE 2`, zero play time/progress and the Run7 save time. Native Continue used
that existing profile; no new profile was created. The capture compile took
3.16 seconds and the named-method diagnostic compile took 2.92 seconds, each with
33 existing reference warnings and zero errors. Separate compiler peak RAM was
not measured.

The volatile diagnostic adds a void prefix to the exact named
`BhSubtitlesPlayer.Load(Il2CppReferenceArray<ClipInfo>)`, records one invocation,
and lets the original method proceed. At frame 37552 in `storyHub`, it recorded
a nonnull array of length one containing a **null ClipInfo entry**. The subtitle
player instance and its GameObject were nonnull; there was no diagnostic error.
This is runtime proof of malformed native playback input, not a clip-name read:
the null entry has no name, so the exact requested registry key remains unobserved.

Bounded disassembly of the exact current-hash GameAssembly pins Load's 553-byte
body and Play's 522-byte body. Load explicitly null-fails on a null array or null
entry; its sidecar file-read branch is not the observed null-entry failure.
Play checks its subtitle component before calling Load. This supports repairing
the native input's data producer rather than guarding/suppressing subtitle errors.
Extraction wall time and peak RAM were not measured; no full decomp was run.

The installed Good1 StoryHub references `Good1a`, `Good1b` and `Good1c`, but F has
none of their registry rows, videos, sidecars or referenced English subtitle
tokens. The prepared Golden Era payload has all three complete closures. Native
Campaign_Intro/Outro registrations, sidecars and English cue text remain present
and match the available donor data. Good1's firstShowActions is empty; Good1a is
the first mission-node interaction. Thus the missing closure is a definite
delivery defect consistent with the observed null entry, not direct proof of
which key was requested during hub entry.

PID 49968 ended at 00:53:02 UTC with code -2147483645, before the 15-second
guard detected the subtitle exception; `guardStopReason` is null. No profile
cleanup or forced termination was performed. No mission/map/town/combat started.
Evidence: `run8_process.json`, `run8_memory.jsonl`, `run8_exit.json`,
`Player_run8.log`, `BepInEx_run8.log`, `run8_profiles_initial.png`,
`run8_profile2_continue.json`, `run8_video_probe_arm.json`,
`run8_video_inputs.json`, `run8_video_current_body.txt` and
`run8_campaign_video_closure_audit.json` in the lane folder. The closure audit
pins target/donor Core hashes, registry rows, media/sidecar hashes and cue SIDs;
it scanned 23 target StoryHubs containing 85 PlayVideo actions. These are file
and action counts, not a campaign mission count.

### Run 9: native playback and Homecoming selection

The guarded launch at 2026-10-04 01:24:01 UTC began with 28.394 GiB available
commit and the installed video-repair Core `87d1c9e3`. Both fresh menu bridge
frames advanced from 2138 to 2258 over 1.5 seconds. The reviewed volatile probe
compiled in 3.24 s (33 existing reference warnings, zero errors), bound both
observers and armed successfully. Separate compiler peak memory was not measured.
Its unique-signature lookup observer records at most 16 rows and a single V JSON
write; this bounded synchronous diagnostic I/O is a timing risk, not a playback
repair. Exceptions do not escape the Load prefix; failed partial arming removes
only the diagnostic Harmony owner, and a completed observer stops native getter
and allocation work.

Native Campaign and existing Profile2 Continue now reach `storyHub`. At
01:25:38 UTC the loader receives a nonnull one-entry array containing
`Good1a.mp4`; the three observed Good1a/b/c lookups all return named nonnull clips.
The capture shows the movie and readable English subtitle text rather than a
LocKit placeholder. The Player log records native playback ending normally.
The log also reports WindowsMediaFoundation timestamp/color-primaries warnings;
one correct rendered frame does not prove whole-movie audio/timing/color quality.
Run8's exact requested key was not captured and is not retroactively asserted.

A second capture visibly verifies the Homecoming mission dialog and native
Start Mission control. A fresh exact action invokes that control once; this is
mission-launch-request proof, not map readiness or gameplay acceptance. No new
profile or profile deletion was used.

The Player log identifies the loaded file as
`h3_roe_castle_homecoming_raw_translation.map` with the Castle campaign spawn;
this is not the earlier Jebus quickstart. Native `OnScenesLoaded` and a Player
turn-start message occur, but the bridges' last frame is 15698 in `loadingScene`
at 01:28:06 UTC. No fresh map-ready bridge sample or rendered-map capture was
obtained. The 30 memory samples reach 27,804,176,384 B game private memory and
2,297,794,560 B minimum available commit. At 01:31:38 UTC the resource guard
stops this owned process: `available_commit_below_2.5GiB`, exit -1 after the
10-second graceful-close interval and forced termination. These are sampled
maxima/minima, not continuous peaks. Cleanup restored startup headroom but did
not make this map load fit the budget; native mission setup is not playable-map
proof. The terrain-count probe was not dispatched against the stale bridge.

Evidence: `run9_process.json`, `run9_memory.jsonl`,
`run9_menu_bridge_freshness.json`, `run9_campaign_click.json`,
`run9_profile2_continue.json`, `run9_video_probe_arm.json`,
`run9_video_inputs.json`, `run9_video_lookups.json`,
`run9_campaign_capture.png/log`, `run9_campaign_capture_result.json`,
`run9_storyhub_observation.json`, `run9_storyhub_capture.png/log`,
`run9_storyhub_capture_result.json` and `run9_homecoming_start.json` in the lane
folder, plus `run9_exit.json`, `run9_last_bridge_state.json`, `Player_run9.log`
and `BepInEx_run9.log`.
Capture compiles took 3.19 s and 2.65 s respectively, each with 33 warnings
and zero errors; separate compiler memory was not measured.

### Run 10: preview deferral and rendered Homecoming map

The guarded visible launch began at 01:50:36 UTC on 2026-10-04 with 28.034 GiB
available commit, candidate plugin `bafb5515`, repaired Core `87d1c9e3`, and
`homm3NativePreviewStartupDeferral: true`. The current-build pilot registered.
The native log recorded 424 matched `SharedPreviewCreate` calls deferred in
1.3 ms. Fresh bridge observations reached Homecoming; a fresh `worldLight`
frame 18097 and the saved capture show terrain, Castle, HUD, Christian selected,
and the opening story dialog. This proves a rendered campaign map, not successful
first-demand model construction, town, battle, or lifecycle acceptance.

Near the map capture, game-private memory was 10,225,192,960 B (about 9.52 GiB),
with about 19.3 GB available commit. The final 01:58:31 UTC sample was
10,280,861,696 B private (about 9.58 GiB), with 13,948,424,192 B available commit.
These are sampled points, not continuous peaks. The
terrain-count volatile request timed out while pending; the game then exited with
CLR 6 access violation `0xc0000005` at `coreclr.dll+0x1d1fdd`, and the guard did
not stop it. The crash cause is unproven; do not replay the same request. No
first-demand, town, battle or preview-lifecycle acceptance was obtained.

Evidence: `run10_process.json`, `run10_memory.jsonl`, `run10_exit.json`,
`run10_terrain_counts.json`, `run10_crash_events.json`,
`run10_world_capture.png/log/result.json`, `Player_run10.log` and
`BepInEx_run10.log` under `V:/olden_port_work/port_runtime_25672315/`.

### Port relocation: V available, F retained

The 21,748,424,465-byte source tree (227,835 files, 4,131 subdirectories)
finished copying to `V:/olden_port_work/Current Era 25672315 BepInEx` with native
Robocopy. Copy exited 1 as expected for successful copies: all files copied,
zero skipped, mismatched, failed or extra; elapsed time was 462.6 s. The source
on F remains in place. Full native metadata comparison passed with exit 0,
zero required copies, mismatch, failures or extras. At the user's request,
expanded critical-hash verification was stopped and no V startup run was made.
The failed pending terrain-count request was preserved under
`relocation_retired_requests/` outside V's active inbox; that inbox is empty.
At relocation, the V executable was available for user testing but had not yet
been launched. The later user test and focused installed ABI check are recorded
below. No cryptographic whole-tree proof is claimed. Normal installs remain
untouched.

### V presentation refresh: installed and user-tested

Before refresh, the user reported that custom bundles load in combat, while unit
previews and adventure-map meshes were missing and towns rendered black. The
latest post-refresh user test says the port is almost great but hitches about
once per second; no itemized map, preview, town or combat verdict is recorded.
The pre-refresh diagnosis found a stale
`ConfigElementBase<string>.get_id` map path; an exact preview-wrapper pin was not
accepted in the earlier probe. Golden level-67 runtime-catalog hashes differed
from the port-native catalog, suspending camera setup. Native camera extraction
records also had different path IDs; those IDs are not fields in the runtime
catalogs. The shipped source correction removes the stale ID allowlist, and
regenerated catalogs preserve port-native camera provenance. The installed
camera gate now passes; live camera and model rendering are not yet proven.

The source correction removing the stale `ConfigElementBase<string>.get_id`
allowlist is committed as `3e06fce30e`; the town/catalog source milestone is
`50a6be4a69`. Build took 18.03 s; the live interop
check resolved 1,218 references across 139 assemblies, with zero new unresolved
references and nine unchanged allowlisted findings. The focused preview and
config-ID checks pass and independent source review is clear. The broader full
hint gate still reports 47 flat groups and six pre-existing policy findings;
the full validation suite is not claimed as passed.

Deployment receipt
`artifacts/port_current/presentation_refresh_25672315/payload_sync_receipt_d57c81394a474385a22a390faea4d9ce.json`
records 442 rows: 441 replaced and one identical dependency skipped. The installed
delta includes 205 selected unit bundles and 205 manifests, 11 town bundles, 12
native-provenance catalogs, the full import table, and a map-building bundle with
field merge plus Necropolis Capitol yaw correction from 0 to 90 degrees. Five of
six candidate binary files changed. Total source/generated transfer was
7,713,842,506 B and took 63.303 s; sampled PowerShell working-set peak was
144,629,760 B for the parent process only, not the whole host. Core, config and
game-native files were not replaced; normal Golden Era and the retained F copy
were untouched.

All 441 changed receipt rows passed SHA-256 readback; the identical dependency
was skipped. Installed `OfflineUnlockMod.dll` prefix is `02ff3ec6`; the installed
ABI check passes with UnitBundle 1 / TownScene 2. The deploy path now runs the
focused camera-only preflight before town copy with a 60 s timeout; independent
review passed, and the installed gate passed all 12 catalogs against the
port-native camera/settings. The refreshed port camera/settings
match the canonical values, and fresh Golden FOV is
`47.599998474121094`. These are build/deploy, installed-payload and focused
source/catalog proof. The user has launched the refreshed payload, but no
feature-specific startup, map, preview, town or combat acceptance is recorded.

`town_camera_refresh_report.md` records the earlier generated-only extraction
and retarget stage; its statement that nothing had been installed is accurate
for that report's time and is not current deployment evidence. The user owns
feature-level acceptance. The refreshed port is user-tested overall, but the
specific adventure-map, preview, town and combat outcomes remain unrecorded.
The recurring-hitch follow-up is recorded below; no root cause or fix is claimed.

### Post-refresh hitch report and diagnostic flags

Latest V test: the user says "almost great" but reports roughly one-second
hitches. The last 3,000 rows of
`V:/olden_port_work/Current Era 25672315 BepInEx/BepInEx/LogOutput.log` contain
262 `LoadTiming` hitch events: `cityFactory` 148
(median inter-event 0.541 s, median hitch 281 ms), `worldLight` 106 (0.782 s,
279 ms); there were also 548 `AI_HOVER` warnings. Source review found
`Homm3LoadTiming.Update` performs frame,
realtime, scene-name and counter bookkeeping on idle frames, with no object scan,
reflection or file I/O; it logs after stalls of at least 250 ms. This low-cost
observer remains enabled, not a demonstrated cause. AI focus runs three scans
of all loaded `TMP_Text` objects every 30 frames; hover sampling runs every 10
frames with a stationary pointer or every frame when it moves, and revalidates
the world root every 60 frames; the live bridge writes
status and polls every 15 frames. These remain candidates, not proven causes.

With the game stopped, only two optional plugin enable flags were renamed to
`.disabled_perf_20261003_port_hitches`: `homm3_ai_driver.flag` (0 B,
SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`)
and `homm3_live_probe_workbench.flag` (3 B,
`f1b2f662800122bed0ff255693df89c4487fbdcf453d3524a42d4ec20c3d9c04`). The
receipt is `artifacts/port_current/perf_hitch_25672315/diagnostic_disable_receipt.json`.
The unchanged DLL SHA-256 is
`02ff3ec6886fd2b86b3034aee224e1c2f553e17399edf32e5df6bd24f9fa0205`; config
SHA-256 is `474c7ec08aa2e0571296b5a28bb4db1902851e72ad0931df228a50a2dcdf1bcb`.
No rebuild, asset or save writes occurred. The rename took 0.273343 s; sampled PowerShell
working set was 100,229,120 B (one-process sample, not a peak; no GPU stage).
The enabled flags had overridden the false diagnostic settings; renaming them
removes that enable path. The AI-driver JSON
selector is absent and defaults false; the root `OfflineLauncherConfig` is
absent. Cached flags/hosts require a fresh launch to evaluate hitch changes.
Flag disablement is not proof that the hitches are fixed; the user owns that
next-launch check. The sampled log also retains 11 preview-wrapper refusals and
49 texture warnings; this performance cleanup does not resolve or accept those
separate presentation paths.

### Earlier runs

Run 1 used the passed stage-10 Core while the final campaign layer ran separately.
It reached `mainMenuDecor`; both native bridges reported `ready` and advanced
frames in a 1.5-second freshness sample. A fresh native `ai_observe` succeeded.
The game then exited through its observed native Exit to Desktop action before
the final payload was installed. No force-kill or gameplay save was used.

Cold plugin initialization took 55.465 seconds, including 37.731 seconds of
synchronous all-faction city presentation prewarm. Fresh interop generation
preceded that cost. On warm run 2, unchanged plugin initialization took 23.028
seconds. These are different cache conditions, not an A/B proof of a fix.

Run 2 uses the final Core and Story_maps. The native `ai_start_match` resolved
Jebus Outcast / Fortress, not Homecoming. The no-argument AI quickstart is an RMG
skirmish provider, not a campaign launcher: it reads the game-root launcher config
(absent in F), then the plugin settings, which have no launch keys. The similarly
named plugin-local launcher file is inactive. Its Homecoming POC RMG template is
also absent; the existing template resolver silently selects Jebus Outcast in
that case. No config-only change to this provider selects a StoryHub mission.
The next Homecoming attempt must use observed native campaign/mission controls;
its installed SID is `h3_roe_castle_homecoming_raw_translation` in Good1.
The game reached `worldLight`, and a fresh native observation reports
`adventure_map`. The loading-scene interval was 384.763 seconds, with a longest
sampled frame gap of 327.020 seconds. Imported map and UI model setup appears in
that interval, but individual callbacks were not timed; no single callback is
blamed for the entire delay. Native `town_ui_state` responds and confirms no town
is currently open. This proves a generated map loaded, not the campaign mission
or user-visible gameplay.

A volatile rendered-frame probe initially compiled an empty DLL: its project-root
OutputPath caused the SDK's default Compile glob to exclude the source itself.
The repaired adapter builds below `bin` and verifies the requested concrete type
and supported static entrypoint with Mono.Cecil before deployment. A live read-only
probe now resolves and executes successfully. The screenshot probe reaches its
method but fails inside the fresh Unity ScreenCapture wrapper on a missing
`Il2CppSystem.ReadOnlySpan<T>.GetPinnableReference` method. This is a separate
interop issue under investigation; no rendered-screen acceptance is claimed.
Its signature mismatch is also present in the preserved prior interop, so neither
regenerating nor restoring the old cache is a demonstrated repair. A texture-based
capture, PNG encoding and texture disposal succeeded without that string wrapper.
The subsequent one-shot end-of-frame coroutine also saved
`adventure_run2_endframe.png` (2560 x 1440, 4,851,915 bytes). It shows the hero,
resource and town HUD, but the world viewport is skybox rather than visible terrain.
This is a failed visual acceptance check, not playable-map proof. The launch
requested a hidden window, but available run-2 evidence did not independently
establish its actual OS-window visibility. Focus/render lifecycle and camera state
must be checked before attributing the blank viewport to the port's map payload.
Player logs were directed to `Player_run1.log` and `Player_run2.log` in the evidence
folder. The default LocalLow Player.log belonged to an earlier game and is not
evidence for these runs.

Run 2's private memory reached approximately 34.70 GB, versus 9.72 GB sampled
during loading. Host free virtual memory was about 2.71 GB at the later sample.
Those are separated samples, not a measured leak rate or causal attribution.
The successful end-of-frame probe's delayed reply records managed heap 57,970,144
bytes, Unity allocated memory 18,651,118,386 bytes, reserved memory 19,379,658,752
bytes and unused reserved memory 728,540,366 bytes. These counters narrow the
allocation domain but do not identify an asset or callback as its cause.
The copy exited through the fresh native HUD menu, Quit Game and Accept actions;
PID 38148 is gone and the Player log records orderly input/physics shutdown.
No forced termination or save was used. The next run must bound memory growth as
well as validate the visible camera/world state.

## Candidate build

The first isolated candidate compile failed during restore, before C# compilation:
one globally supplied intermediate/restore directory was shared by the plugin and
its OldenAiSim project reference. The simulator restore replaced the assets file,
leaving no netstandard2.1 target for the plugin (NETSDK1005). No DLL was produced
and the live-interop audit did not run. The failed attempt took 5.094 s, with
one-second sampled process-tree peaks of 247,218,176 bytes working set and
169,291,776 bytes private memory. Evidence: `plugin_compile_20261003.log` and its
metrics JSON in the lane folder. The correction must isolate each project's
restore/intermediate output, retain the SDK's project-local obj exclusion, and
preserve reference builds rather than skipping them.

The per-project diagnostic props fixed restore isolation without changing source
exclusions. The next compile reached C# and found nine interoperability errors:
method groups were not convertible directly to the IL2CPP UnityAction properties,
and new strict Newtonsoft loops treated native collection proxies as CLR
enumerables. That attempt took 17.594 s (54 warnings, nine errors; no DLL), with
sampled process-tree peaks of 785,600,512 bytes working set and 677,400,576 bytes
private memory. The fixes use explicit managed-Action conversions and the native
non-generic enumerator/native casts, verified against the fresh F interop. The
subsequent successful build and live-interop audit are recorded below. Evidence:
`plugin_compile_20261003_isolated.log` and its metrics JSON.

Before another runtime attempt, GlobalMemoryStatusEx reported roughly 12 GiB
available commit out of 51.57 GiB; GPU readback showed 12,201 MiB free. A targeted
process audit found a live Fortress town-bench server (PID 45512), not evidence of
a stale process or permission to stop it. Resource ownership was requested on the
shared setup board. No other-agent process was stopped and no pagefile setting
was changed. These readings do not establish full-map resource readiness.

## Installed candidate and run 3

The isolated candidate compiled in 15.125 s (54 warnings, 0 errors); 15 one-second
process-tree samples peaked at 1,243,430,912 bytes working set / 1,004,646,400
bytes private. Live-interop checked 1,219 MemberRefs across 139 assemblies:
10 findings were all pre-existing allowlist entries, with zero new or fixed-but-
still-listed findings; no allowlist entries were added.

- Candidate DLL: 4,767,232 bytes, SHA-256
  `7d919c303f2e8a4ce09187fe25f59ba88ea82c2b0d68efe3b4f8c18213682bbd`.
- `OldenAiSim.dll`: 53,760 bytes, SHA-256
  `deda60673c3c8ad81f4670283550b38c48fde28df33f7f1ac70d0a4bd5a61081`.
- DLL, PDB, ABI sidecar and dependency installed only to the isolated F copy at
  07:48 UTC on 2026-10-03. Installed readback hashes and ABI/source check pass;
  Core remains `21f1877c`. Prior payload is preserved in `payload_backup_run3`.
  Normal Golden Era and vanilla Steam remain untouched.

Run 3 (PID 13100) launched the installed candidate at 07:49 UTC with normal
window style and 1280x720 launch arguments. Escalated Win32 read at 07:52:16
confirmed it visible and foreground (handle 35326148). The default sandbox
cannot inspect window handles, so its zero value is not hidden-window evidence.
Both native bridges were ready and
fresh at the main menu: AI frames 2389->2509 and live-probe 2404->2524. Plugin.Load
took 12.449 s versus 23.028 s on run 2, but cache conditions differed, so this is
not an A/B result. Startup logged the city source preflight accepting 12 configured
full-3D routes with zero legacy decode issues in 125 ms. Patch/factory surfaces
registered; town-hide behavior and map-getter application were not exercised on
a map, and the automatic hover lane had no WORLD-positive sample.

At 07:57:56, available commit was 0.697 GiB of 52.586 GiB; game private memory
was 11.362 GiB, working set 5.034 GiB, and GPU use/free was 10,620/5,376 MiB. No
map was started under that headroom. Native Exit to Desktop succeeded at 07:59:12;
PID 13100 exited orderly. At 08:02 UTC it was absent and 11.596 GiB of 51.570 GiB
commit was available. No run-3 screenshot exists. Run 2's blank viewport remains
a failed visual check, not evidence that visibility caused it or that the
candidate renders the world. The separate eager main-menu 3D prewarm is a
potential memory cost, not a proven cause.
Evidence: `run3_window_startup.json`, `run3_memory_stop.json`, `BepInEx_run3.log`
snapshot and `Player_run3.log` in the lane evidence folder.

## Follow-on candidate

The selected-faction native town-loading change and shared Factory/Bulwark
Unit.Init owner passed independent review. Boundary-only town gate: 168.5 ms (24.12 MiB working set,
16.50 MiB Windows private); NumPy import is deferred from its source-only path.
Factory gate: 149.8 ms / 19.53 MiB RSS; Bulwark: 129.4 ms / 13.86 MiB RSS.
FullValidation policy is unchanged.

The isolated candidate built in 14.500 s (54 warnings, zero errors); 14 one-second
process-tree samples peaked at 1,083,404,288 bytes working set / 858,468,352 bytes
private. Live-interop checked 1,219 MemberRefs across 139 assemblies: 10 findings
were pre-allowlisted, zero new. DLL `6c9ea9b4` and dependency `191b6941` were
installed only to F at 08:39 UTC; readback and ABI/source checks pass, Core is
unchanged. See `plugin_compile_20261003_followon` log/metrics and
`run4_payload_preparation.json`.

Run 4 (PID 46168) launched normally at 08:40:55 UTC with 10.320 GiB available
commit. `Plugin.Load` took 10.832 s. Startup checked metadata/paths for 12 town
catalogs without loading assets, and both Factory and Bulwark registered the shared
consumer; the ownership conflict is gone. This is registration, not combat proof.
`StartMenu` reached `mainMenuDecor` in 12.640 s (longest hitch 1,872 ms). Run 3's
50.028 s shared hitch is not a controlled comparison due to different cache and
process conditions.

Forty-five two-second samples (08:41:48-08:43:17) show game private memory rising
from 5,409,218,560 to 5,674,622,976 bytes and mostly plateauing near 5.292 GiB;
last-sample available commit was 5,374,263,296 bytes. This is below run 3's 11.362
GiB private sample, but conditions differ; logs confirm limited startup scope,
not an A/B result. No campaign, town or battle was started. Town asset retention
and first-town hitch remain untested. Run 4 GPU/VRAM use was not sampled. No native
preview-pool lazy optimization was applied. The follow-on read-only audit below
closes the eager-versus-on-demand control flow, not its measured memory impact.

A separate one-shot DTO/camera/end-frame probe (`59884db7`) compiled in 2.66 s
(34 warnings, zero errors). Bridge request
`79222e18-3164-4176-86bb-d4ffbbb95d93` returned `scheduled` at 08:43:35; the game
crashed about one second later. Windows recorded Application Error 1000 and .NET
Runtime 1023 for PID 46168 (`0xB458`), the F-copy executable: `coreclr.dll` 6.0.722,
offset `0x1d1fdd`, exception `0xc0000005`. No PNG, JSON result or orderly exit
was produced, and the memory guard did not stop it. Timing does not identify the
probe code/API as cause; the crash is a separate diagnostic failure after the
candidate's stable startup. Evidence: `BepInEx_run4.log`,
`run4_startup_memory.json`, `run4_crash_events.json`, run-4 Player/process/build/
payload records and `run4_failed_visual_probe.cs` in the lane evidence folder.

Run 5 (PID 49500, created 09:03:38 UTC) used the same installed candidate. A
separate capture-only probe (`45bdae31`, bridge request `4e14a841-b6c0-46cd-b79a-8dba41218432`)
compiled in 3.19 s (34 warnings, zero errors). Its phase log confirms scheduling,
end-of-frame resume, texture capture, PNG encode/write and texture destruction.
`menu_run5_capture.png` is a valid 2,560 x 1,440 menu image (6,070,837 bytes) despite
the requested 1,280 x 720 launch size. The game remained alive after capture. This
reproduces the earlier direct-byte capture sequence without camera/scene reads,
`.ToArray()` or DTO serialization; it does not locate run 4's crashing operation.
The temporary probe source is preserved in its compiler work directory. Probe
peak memory and GPU/VRAM were not sampled; no resource improvement is attributed
to it. At 09:09:52 UTC an escalated Win32 read confirmed window handle 98177584;
game private memory was 5,633,097,728 bytes and available commit 5,140,566,016 bytes
(single sample, not peak). Evidence: `run5_process.json`, `menu_run5_capture.log`,
`run5_post_capture_memory.json` and the PNG in the lane evidence folder.

The native AI bridge freshly observed and clicked the Campaign button at
09:07:31 UTC (`run5_campaign_act.json`, ok=true). A later observation retained
`mainMenuDecor` / `main_menu`, which initially suggested no transition. That was
not a valid failure inference: scene/mode metadata does not identify the active
additive UI. Run 6's visual check below proves the Campaign profiles screen opens.
No mission/map was started; the prior random-map peak is not safe to assume fits
the remaining commit headroom. No quickstart fallback was used.

Native read-only bridge inspection found the unique Campaign button's click
callback non-null and its availability flag true. Current-hash native body
evidence for `BhNavigationButton.OnPointerClick` dispatches that click slot after
its pointer-event and availability gates; this does not prove handler entry for
the attempted Campaign click. Run 5 then quit through the fresh native Exit to
Desktop action; PID 49500 disappeared and Player.log records orderly network,
physics and input shutdown. The same AI click path therefore works for another
native button, without proving Campaign's callback ran. Evidence:
`run5_campaign_field_Private_*.json`, `run5_exit_act.json`, `run5_native_exit.json`
and `BepInEx_run5.log`.

Run 6 first used native read-only callback inspection, with no callback invocation
or map load. Its live Campaign callback resolves to `Hex.MainMenu.MainMenuNavigationView.pza`,
metadata token `100681261`; the target is non-null, while the multicast delegate's
stored array is null. No callback was invoked by this introspection. These are
exact native `component_member_path` reads, not a guessed click-slot ordering or
UnityEvent listener path. Evidence: `run6_campaign_exact_object.json` and
`run6_campaign_field_Private_Action_0_Method_*.json` in the lane folder. Current-
hash bounded native bodies show this callback's state-transition guard and a
tail-call to `ScProfiles.Open`, not a no-op or direct campaign-session start.

One fresh native Campaign click followed by the separate proven capture-only
probe produced `campaign_run6_capture.png` (2,560 x 1,440, 2,285,406 bytes) at
09:33:49 UTC. Every phase marker completed and PID 51404 stayed alive. The image
shows the native Campaign profile selector: existing Profile 1 plus three empty
slots. The earlier bridge mode/scene classification is not a transition oracle.
No navigation source change is needed for that button. No profile was selected,
created or deleted by our actions. Homecoming mission navigation/load, town and combat remain
unproven. Evidence: `run6_campaign_act.json`, `run6_capture_result.json`, the PNG
and `campaign_run6_capture.log`. Compile: 3.09 s, 34 warnings, zero errors, 173
references. Capture peak memory/GPU use were not sampled. A later single sample
(`run6_profiles_memory.json`) recorded 5,651,009,536 B private and 4,669,411,328 B
available commit. An earlier aggregate GPU sample was 6,508 MiB used / 9,488 MiB
free; it is neither process-attributed nor a peak. Native Exit then closed the
game orderly; no test game or probe compiler remains running.

### Shared-save safety boundary

F isolates the executable/plugin/Core payload, **not userdata**. Run 6 Player.log
lines 436-447 reports cloud-hash reconciliation and reads saves/campaign/prefs
from the normal `LocalLow/Unfrozen/HeroesOldenEra/users/` account directory on C:.
Startup metadata/prefs/cloud activity is not claimed absent; a future agent must
not treat this copy as a disposable save sandbox or activate existing Profile
1's Continue/Load/delete.

After native quit and confirmation that no game writer remained, the complete
local account plus six root metadata files were copied to
`userdata_backup_20261003T094502Z/` in the V lane. Its manifest has 75 files,
16,668,757 B, each verified against before/after source and backup SHA-256.
CPU file I/O/hash work took 1.317 s, peak PowerShell working set 109,539,328 B.
The backup operation wrote no files to C:. Exact local account paths remain in the local
manifest rather than copied into versioned prose. This is a verified **local**
snapshot, not a remote-cloud backup or a tested restore. Profile creation and
mission loading await a save/cloud isolation decision; the user was asked about
keeping saves read-only versus an explicitly accepted disposable-slot test.

Follow-on read-only discovery corrected the earlier Steam checks: both their
account ID and assumed C:/V: install roots were wrong, so those checks are not
absence evidence. The registry identifies the real Steam root on F:. Its exact
account/app subtree contains 15 remote-cache files plus `remotecache.vdf`.
Both campaign profile/save pairs and `prefs/Settings.json` have matching local
and Steam-cache hashes. The app's local config records `synchronized`, and its
last-exit/cache timestamp is 09:43:25 UTC, three seconds after run 6's recorded
native Exit action, not its later PID-gone verification.
This proves matching local Steam-cache data and recorded sync participation,
not the current Cloud UI toggle or the service's current remote contents.

The exact Steam app subtree was copied to
`steam_userdata_backup_20261003T095800Z/`; the manifest records the actual
completion time, **10:19:05 UTC**. All 16 files / 2,096,644 B match source-before,
source-after and backup SHA-256.
Sequential CPU file I/O/hash work took 0.288 s, peak PowerShell working set
104,198,144 B; no GPU work was appropriate. The backup operation changed no source
files or cloud settings. This is another verified local snapshot, **not a
service-side cloud backup or a tested restore**. Exact account paths stay in its
local manifest. No game was running during the snapshot.

The inspected launcher/config paths provide no userdata or cloud-isolation
parameter. Current Unity interop exposes `persistentDataPath` as getter-only;
the matching [Unity 6 API documentation](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Application-persistentDataPath.html)
places Windows data under the user's LocalLow profile. The documented
[Player arguments](https://docs.unity3d.com/6000.0/Documentation/Manual/PlayerCommandLineArguments.html)
provide no data-path override; this does not rule out an unrecovered game-specific
argument parser. [Steam's native per-game Cloud control](https://help.steampowered.com/en/faqs/view/68d2-35ab-09a9-7678)
is an available platform option, not a setting changed or UI-verified here.
A separate Windows user would separate the default LocalLow base, but neither
that nor a separate Steam identity has been established. Disabling Steam Cloud
alone is not proven to disable any separate in-game cloud backend.

### Read-only optimization and observer review

Current-hash native bodies pin `BhUnitPreviews.Start` (token 100666588), its
setup `iic` (100666589), request `iid` (100666590), return `iie` (100666591), and
factory `iih` (100666594). `Start` calls setup; setup registers each config's
queue, creates a preview and enqueues it. Request returns false for an absent
key but creates a preview for an existing empty queue. Return uses the existing
keyed queue. Queue/key registration must be preserved; skipping all setup would
break request/return behavior. A replacement with empty queues was the initial
proposal, not the only supported deferral state. No optimization is installed.

The current wrapper resolves the dictionary field by metadata and dynamically
asks IL2CPP for its offset. Its type/order and native `this+0x30` uses agree, but
there is no independent numeric offset-table proof. Specialized helper bodies
support queue/dictionary operations; absent alias rows mean their exact metadata
tokens are not assigned. Native control-flow evidence does not attribute the
earlier 34.7 GB map process to this pool or establish optimization savings.

The exact 606-byte setup body reads a **pre-existing** dictionary; it must not be
replaced with a newly allocated one. The config key load structurally matches
the inherited string ID field, whose wrapper resolves its offset dynamically.
Enumeration/disposal, null-failure and duplicate-key failure semantics also
need preservation. The ten helper calls previously described as class
initializers receive static slot addresses and perform tagged-slot lazy metadata
initialization; direct user `.cctor` calls are not observed. Hidden loader
callbacks remain unproven. A managed setup replacement remains unimplemented.

A subsequent exact-body audit confirms a native-supported alternative: setup
can enqueue a null construction result. Request dequeues that slot, compares it
to null through Unity object equality, and enters its existing lazy factory path.
Valid demand still succeeds; invalid construction still throws. Other audited
class methods do not consume the keyed queue. This changes the next action from
reimplementing setup to preserving the native body and scoping only construction
deferral. A default-off, current-build source candidate is prepared under
shared-board claim `199a3e6a5e7a40aba7a09f357c14da31`, with strict selector claim
`8b8addf513f8450185c0fe6d010bfdc4`. Thread/native-owner scopes and an explicit demand
scope protect reentrant request construction; cleanup belongs in finalizers.
The owning source gate and linked managed fixture pass 12 cases in 3.14 s,
with sampled fixture-process-tree RSS 241.6 MiB / private estimate 104.0 MiB. This does
not prove Harmony detour coverage or API6 plugin compilation; the package-free
net9 fixture executes the actual helpers, not the game. A config persistence
review also found the histogram tuner erased unrelated mod settings. Its narrow
writer change now merges tuner-owned keys into the active mod JSON, retaining
other overrides and copying a legacy source into the canonical channel on save.
The strict selector and merge share one managed JSON implementation; malformed
input is not repaired or overwritten. The isolated no-deploy compile now passes:
54 warnings / zero errors, 11.42 s MSBuild / 11.983 s wrapper elapsed; live interop checks 1,219 refs
across 139 assemblies with zero new unresolved refs and 10 existing allowlisted
findings. Candidate DLL is `bafb5515f04d56635d21434eac70d71121122162fec513a66ba3545d907d07b7`
under `native_preview_candidate_build/out/`. Compile-only API6 restore succeeded
from V:; no parser DLL is staged. Nine requested-one-second samples show peak
build-tree working set 983,285,760 B / private memory 797,384,704 B, not continuous
or host-wide peaks. The first build's metrics wrapper failed; its logs remain.
Only the output-quota code correction required a second compile: valid near-limit
input must not produce a saved file that its own reader would reject. The actual
helper fixture covers that refusal. No unchanged build was rerun for measurement.
This is build-target proof, not game .NET 6 loading or native detour proof. The
no-deploy build emitted no ABI sidecar; source UnitBundle 1 / TownScene 2 is
unchanged. See
`docs/native_preview_startup_deferral.md`. The installed candidate remains
unchanged, and no game/profile/cloud action accompanied this work.

The AI observer infers broad mode from the active scene, not a frontmost-screen
owner. That explains why the visible Campaign selector still reported
`main_menu`; its `screenId` is a catalog hash, not semantic screen identity.
Action collection recognizes selected button/selectable types, not generic
pointer-handler owners. Empty profile slots' actual component/handler types
remain uninspected, so their missing actions are not attributed to this filter.
Visibility checks do not prove screen intersection or raycast reachability,
and action dispatch does not reraycast its recorded target. A future generic
enhancement needs a pinned active-screen root, bounded candidate discovery and
live hit/owner validation both before publishing and before executing actions;
it must not fabricate profile actions or scan all scene components. No observer,
screen-reader or NVDA code was changed in this review.

### Separate CLR 6 helper check

The committed, linked helper fixture also passed its 12 grouped cases under the
installed **global CLR 6.0.11**, without launching the game. SDK 9.0.304 compiled
the same production scope/JSON helpers for `net6.0`, using the 6.0.36 reference
pack. An explicit restore was required: the first implicit-restore invocation
restored the fixture's declared `net9.0` target, then failed with `NETSDK1005`
because its assets had no `net6.0` target. The corrected restore verified
`net6.0` assets before a `--no-restore` build; no source or framework installation
was changed to make the test pass.

Runtime configuration selects `Microsoft.NETCore.App` 6.0.11 with
`rollForward=Disable`; `dotnet exec --fx-version 6.0.11` and the retained host trace
confirm that exact global framework and CoreCLR path. The test DLL SHA-256 is
`a7d4ae3802d473e78f6e27fba15adc89fb038029587915e71e27b31810f51bc8`.
Commands, stdout/stderr, metrics, runtime-config readback, DLL and host trace are
retained under `V:/olden_port_work/port_runtime_25672315/clr6_helper_review/`.
This closes a helper-level CLR 6 execution gap, **not** the game's bundled 6.0.7
parser/bootstrap, plugin loading, IL2CPP detours, terrain rendering or gameplay.
It is a separate result from the earlier default `net9.0` fixture, not a
replacement or promotion of that evidence.

Measured invocation times: restore 2.919 s, build 5.938 s (5.29 s MSBuild), and
fixture execution 1.395 s, all exit zero; the build reports zero warnings/errors.
One-second process-tree sampling observed maxima of 130,306,048 B working set /
48,738,304 B private for restore; 253,730,816 B / 110,981,120 B for build; and
14,405,632 B / 7,618,560 B for execution. The short execution had only one sample,
so these are sampled observations, not reliable continuous peaks. This is CPU
managed control/JSON testing and SDK compilation, not GPU numerical work. Every
phase had a 120-second guard and all owned processes exited.

The first attempt's SDK stdout reported installing an ASP.NET Core HTTPS
development certificate during first-run initialization. That was an unintended
side effect; the certificate store was not independently verified or altered
afterward. Subsequent commands disabled certificate generation and telemetry.
TEMP, CLI-home, package/cache, build and test outputs were redirected to the V:
lane. No game, F: payload, profile, save or cloud action accompanied the test.

### Map-rendering evidence review

Run 2 was not merely observed during the documented loading phase:
`Player_run2.log` lines 1507-1511 report local/all-player readiness and
`Session.OnGameStarted` at frame 986; line 1549 starts day 1. The failed world
frame was captured at 05:52:48 UTC. This weakens ongoing initial loading as the
explanation, but does not exclude streaming, an incorrect camera or missing
world presentation.

The same log records an actionable owner/order discrepancy immediately after
map generation: lines 643-657 cap `Terrain_BiomParams`, `Terrain_Tilings` and
`Terrain_HeightmapScales` from a requested 32 entries to their previous 16. The
logged writer is `Shader.SetGlobalVectorArray` through `bfd.ff`, not a per-material
setter. The current native index pins that renderer method to token 100672831.
[Unity's Shader API](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Shader.SetGlobalVectorArray.html)
confirms global shader-property ownership; the actual cap is evidenced by the
run's Unity warning, not inferred from the different Material API.

Current `Homm3SwampAutumnTintProof.PrefixRendererConstructor` calls
`EnsureTerrainGlobalVectorArrayCapacity`, which writes those three global arrays
at `GameSymbols.TerrainMaterial.NativePackedMaterialSlotLimit` (16) before the
native constructor. Its postfix separately expands renderer packed-state arrays
to `CustomBiomePackedSlotCapacity` (32). The 16-entry material/shader contract and
32-entry packed-state capacity are deliberately separate in current source;
neither the warning nor the native writer's name proves an unmodified stock
renderer requires 32 shader entries. Do not blindly increase the material limit
or replace a Material instance: neither resolves the demonstrated global owner.
An independent exact-body review of current `ff` at `0x1829436B0` pins three
native global uploads of renderer instance vector arrays at `+0x40`, `+0x50` and
`+0x48`. This supports a packed-array/global-upload interface risk; the precise
field-to-semantic mapping and shader-consumed index domain remain unestablished.
The 16-entry shader declaration is presently a mod-source assumption, not an
independently verified declaration from the current build's shader. Named
artifacts establish `Hex/TerrainMap` creation/existence, not its compiled index
domain; a bounded current `sharedassets0.assets` read found only unrelated
shaders. No large asset-set scan was performed to manufacture that missing proof.

The preseed existed in source before Run 2, but `run2_process.json` pins Core,
not that process's plugin DLL. Its prior global-array value cannot yet be
attributed to the mod, and the warnings do not prove the starfield's cause.
The map-transition lookup validator covers current compacted material rows and
stale-map replacement, not this global write ordering. No terrain repair, new
gate, payload change or game test was made in this review.

The next discriminating runtime observation, once the current resource gate is
met, is a bounded read of the three global-array
lengths and active compacted material-row count. Existing
`volatile_load_probe_assembly` can run a minimal static entry point returning one
short count string; the built-in instance getter commands cannot call these
static Shader methods. No count-only DLL was authored or loaded in this review.
Bridge status `ready` is attachment status, not map readiness; inbox processing
every 15 frames cannot catch the exact constructor/native-write boundary by
polling. A late sample after documented map readiness must be labeled as such.
Immediate post-`ff` timing needs a proven call relation to an existing native
callback or an exact scoped hook; `PrepareMap` postfix alone has not proved that
relation. Do not repeat the failed rich combined camera/DTO probe or reconstruct
all scene components. Keep the existing capture-only frame check separate.
Runtime tests remain in `docs/ingame_check_queue.md`, not a second checklist here.

At 2026-10-03 13:15:16 UTC no game was running. Host committed memory was
43.269 GiB of 51.570 GiB, leaving 8.302 GiB, below the existing 10 GiB startup
guard; this point sample is not a map resource plan. The save/cloud decision
also remains unresolved. No other process was stopped to reclaim memory, and no
game/profile/cloud action was taken.

There are also 869 `FindAllObjectsOfType` errors for `fcb`, at log lines
1508-2438. The current index identifies that class as an `Il2CppSystem.Object`
subclass, not a Unity object; the log supplies no caller stack. Targeted active
plugin inspection found no exact `FindAllObjectsOfType` caller. This is an
unattributed invalid-type finding, not proof that a particular mod scan caused
the errors or hid the terrain.

## Repair work

The following distinguish completed source repairs from pending runtime fixes:

- Campaign LOD extraction previously read the roughly 105 MB archive for every
  member request. The seek reader passed five parity/corruption tests, including
  exact byte-read accounting and incomplete/oversize rejection; Good1.h3c output
  is byte-identical. Warm read cost fell 0.1171 s / 102.01 MiB to 0.01085 s / 0.07
  MiB tracked Python allocation; this is not total RAM or end-to-end timing. Its
  FullValidation target took 2.773 s; standalone validator was 0.537 s / 25.38 MiB
  sampled peak. CPU suits sequential archive/zlib work. Trusted local archives are
  assumed; hostile multi-GB expansion remains unbounded. The 203.907 s spawn phase
  includes other work and is not attributed to this reader.
- Plugin.Load now uses route-aware city file/metadata validation instead of the
  all-faction legacy-art warmup. Owned full-3D routes skip inactive legacy inputs;
  missing configured catalogs fail clearly. Optional music/build-effect audio
  remain optional. Parser parity and animation containment passed review; gate:
  2.072 s, 22.66 MiB working set / 17.05 MiB private peak. This is CPU source/JSON/
  header I/O. Checked-in config has 12 legacy routes versus F's 12 full-3D routes.
  That first candidate left the separate eager main-menu prewarm unchanged;
  the follow-on candidate above replaces it with catalog/file checks.
  Run 3 preflight took 125 ms on the full-3D routes; it did not execute the legacy
  C# metadata/parser branch. That branch remains source/static validated only;
  asset-decode cost and town render are unproven.
- The prior DLL failed hardcoded `UnitViewConfig.rtd` / `BhCityUISession.OnHide`.
  The installed candidate resolves the exact current void/no-argument hide method
  and cached `GameObject` map getter. Native body evidence shows Golden Era's old
  `sec` hint had the wrong owner; current `Method_Public_GameObject_0` matches the
  native body. The remap remains unmapped at zero algorithm confidence; a manual
  Golden Era repair records evidence without rank fallback. Source review,
  build/install and startup registration pass; hook application/behavior on a map
  is untested. Refusal gates remain intact.
- The exact BattleUnitInit.Init symbol remains refused and several law dispatchers
  are unavailable. The first candidate's separate Factory Unit.Init hook conflicted
  with the shared registry, preventing Bulwark registration. The follow-on candidate
  removes that competing owner and registers both shared consumers at startup.
  The original conflict also appears in the historical Golden Era log, so it is
  not attributed to this port. Current scopes pin the exact battle-side
  wrapper and its local-index member; freshness/source gates pass, but local-index
  semantics and gameplay are unproven. The flat-hint audit still reports 47 findings,
  not a passing gate.
- Carry provenance repairs are fixture-validated: missing body evidence blocks
  carry, each live position needs a type check, and manual re-derivation is pending.
  Token-keyed method cores prevent repeated names selecting the wrong body. Review
  and seven tests pass; MSBuild target: 2.684 s / 156.58 MiB peak; standalone
  fixture: 0.620 s / 33.68 MiB, with 7,842,517 bytes tracked Python allocation.
  No expensive matcher/output reran; this is CPU dictionary/evidence work.
- Probe-compiler fake-bridge regression passed in 11.39 s / 750.7 MiB sampled peak;
  FullValidation passed in 3.126 s. It rejects missing types/unsupported entrypoints
  before enqueueing; compilation is not runtime proof.
- A typed live WORLD read proved the two-hop native owner chain to the hover
  service/context; the sampled node was -1. A base Component proxy scan returned
  zero despite the native component existing, so is not absence proof. The reviewed
  source repair pins a unique WORLD root, reads exact properties, retains getter
  failures and invalidates stale roots using scene/liveness checks plus a bounded
  audit. Frame sentinels are guarded; focused validator took 0.114 s. The repair is
  installed, but run 3 had no WORLD-positive sample. Automatic hover remains
  runtime-unproven; -1 is not positive acceptance.

User-visible checks belong only in `docs/ingame_check_queue.md`, under the
explicit current-version test-copy section, not in a second queue here.
