# Unity queue runner

Status: active operational contract for Unity batch jobs (bundle builds, editor probes, editor renders).
Owner: `tools/unity_queue/unity_queue.py` + `tools/unity_queue/unity/UnityQueueDispatcher.cs`.
Gate: `tools/validate_unity_queue_contract.py` (source/static).

**Agents must submit, not launch.** Do not start `Unity.exe -batchmode` yourself, and do not add a new
`unitylock.py run -- Unity.exe ...` call site. Submit a job to the queue (Python `launch()` or the `submit` CLI). The
runner batches queued jobs into one Unity launch per project, runs each job once, and writes a result file for it.
Unity allows one editor per project, and every editor costs RAM and 30-90 s of startup, so separate launches waste
both.

## Why

Before the queue, every agent launched its own batchmode editor through `tools/homm3_vfx/unitylock.py`. That was
serialised, but each job paid a full editor start (domain load, asset database refresh, script compile) and waited
on the lock in a 20-30 s poll. The queue keeps the same single-editor rule (it takes the same lock directory) and
pays the startup once per batch.

## Queue layout

`V:/olden_port_work/unity_queue/` (`UNITY_QUEUE_ROOT` overrides it, for tests only):

| dir | contents |
| --- | --- |
| `pending/` | `<id>.json`, a job waiting for a drain |
| `running/` | a claimed job, with its `claim` (runner pid) and `launchId` |
| `done/`, `failed/` | `<id>.json` (the job), `<id>.result.json` (the result), `<id>.log` (the job's slice of the launch log) |
| `launches/<launchId>/` | `batch.json` (the dispatcher input), `results.jsonl` (one line per finished job), `unity.log`, `host.log`, `launch.json` (cmd, exit code, wall time) |

## Job schema (`unity_queue_job.v1`)

`{kind, executeMethod, args, inputs, outputDir, requester}` plus the launch fields `unity`, `project`, `buildTarget`
and `graphics`, an optional caller `log` path, and `timeoutSeconds`. `args` holds the job's own flags only. A job
that carries `-batchmode`, `-quit`, `-nographics`, `-projectPath`, `-executeMethod`, `-logFile` or `-buildTarget` is
refused, because those flags are launch fields.

**Dedupe key**: sha256 over kind, executeMethod, args, the launch fields, and each input's content sha256. An input
over 512 MB is keyed by size and mtime instead, and a directory by a listing of relative path, size and mtime.
`submit` returns the id of a pending or running job that has the same key instead of queuing a second copy. A
duplicate that raced past that check gets its twin's result (`dedupedInto`). Dedupe only joins *live* jobs. A
finished result is never reused, so a resubmit always rebuilds. At launch time the runner rehashes the inputs. A job
whose inputs changed since submit fails with "inputs changed since submit".

Inputs are what the caller lists. The switched town callers list their spec files (the `-scene3dSpec` /
`-scene3dRender` JSON and the bundle). The staged meshes and textures the spec points at are not hashed. Two live
jobs with the same spec bytes are therefore one build of whatever is staged when it runs.

## Result (`unity_queue_result.v1`)

`status` (`ok` or `failed`), `exitCode` (`UnityQueueExit` code, 1 for an exception, `null` when the job never
reported), `error`, `elapsedSeconds` (inside the editor), `logExcerpt` (the slice's error lines plus its last 60
lines), `outputs` (`relpath -> sha256` for every file under `outputDir` written since the launch started),
`launchId`, `launchLog`, `launchExitCode`, `launchWallSeconds`, `launchJobs`, `jobLog`.

## Usage

Python callers use one call:

```python
uq.launch(kind="town_full3d", method="Homm3TownScene3dBundleBuild.Run", args=["-scene3dSpec", spec],
          project=unity_project, log=out / "unity_bundle.log", inputs=[spec], output_dir=out,
          build_target="StandaloneWindows64", graphics=False, requester="my_tool castle")
# -> result dict; the job's log slice is copied to `log`
```

A caller that already builds a classic `[python unitylock.py run ... --] Unity.exe -batchmode ... -executeMethod M
...` list hands that list to `run_cmd`, which parses it into the same job (`-projectPath`, `-buildTarget`,
`-nographics`, `-executeMethod` and `-logFile` become launch fields, everything else job args; inputs default to the
args that are existing files) and returns a `subprocess.CompletedProcess` look-alike (`.returncode`, `.stdout` = the
job's log slice, `.stderr`):

```python
UNITY_DIRECT = UQ.take_direct_flag()          # pops --unity-direct from sys.argv before argparse sees it
done = UQ.run_cmd(cmd, kind="vfx_lab_build", timeout_s=900, direct=UNITY_DIRECT)
```

CLI:

```
python tools/unity_queue/unity_queue.py submit --kind K --project P --method Ns.Type.Method \
       [--input F ...] [--output-dir D] [--log L] [--build-target T] [--graphics] [--requester R] [--wait] -- <job args>
python tools/unity_queue/unity_queue.py run --once            # drain what is pending, then exit
python tools/unity_queue/unity_queue.py run [--gather 30]     # long-lived drain loop
python tools/unity_queue/unity_queue.py status
python tools/unity_queue/unity_queue.py warmup --project P [--wait]   # cold Library only; see below
```

No daemon is required. `launch()` and `submit --wait` wait for the result. While their job is still pending and no
other drain holds the Unity lock, they drain the queue themselves. That drain takes everything pending, not just
their own job, so jobs queued by other agents in the meantime share the same launch. A long-lived `run` (optionally
with `--gather S`, to collect jobs for S seconds after taking the lock) batches more.

## Runner semantics

1. **Lock.** The runner takes the shared Unity lock, the same directory `unitylock.py` uses
   (`artifacts/homm3_vfx_experiments/_unity.lock`). The queue and any remaining `unitylock` caller therefore never run
   two editors at once. RAM is bounded to one Unity at a time.
2. **Claim.** It claims every pending job by atomic rename into `running/`, then groups the jobs by
   `(unity, project, buildTarget, graphics)`. Each group gets one launch of up to `--max-batch` jobs (default 16).
3. **Preflight, per launch.** The runner runs `memgate --wait 6`, then `launch_guard`, which checks that the game is
   not running, V: free space and RAM/VRAM. It then runs the cold-Library check (below) and checks that no Unity is
   already open on the project, by command line or by a held `Temp/UnityLockfile`. If any check refuses, every job
   in the group fails with the reason.
4. **Launch.** It stages `UnityQueueDispatcher.cs` into `<project>/Assets/Editor/UnityQueue/` (copied only when the
   file differs), then runs `Unity.exe -batchmode -quit [-nographics] -projectPath P [-buildTarget T]
   -executeMethod UnityQueueDispatcher.RunBatch -unityQueueBatch batch.json`.
5. **Dispatch.** The dispatcher invokes each job's static parameterless method in turn. Between jobs it unloads all
   asset bundles and opens an empty scene. A job that throws, or that calls `UnityQueueExit(nonzero)`, is failed
   with its exception, and **the batch continues**. Each finished job appends one line to `results.jsonl`
   immediately.
6. **Crash, compile error or timeout.** Any job without a result line fails with the launch exit code and the
   reason: it started and did not finish (crash), or it never started (compile error or dispatcher failure). The
   timeout is the sum of the jobs' timeouts plus 600 s, after which the runner kills its own Unity child (never the
   game).
7. **Orphans.** A running job whose claiming runner pid is gone fails with "runner pid N died".
8. **Low-disk watch.** While Unity runs, the runner checks the project drive's free space every 30 s. Below 10 GB
   (`UNITY_QUEUE_LOW_DISK_GB`) it prints a loud `UNITY_QUEUE LOW DISK` banner (repeated at most every 5 min) and
   writes `LOW_DISK.flag` (JSON) in the launch dir and in the queue root. It **never kills Unity**; that is the
   user's decision. Delete the queue-root flag once handled.

There is no silent fallback. A refused or failed job is a failed result, and the caller raises or returns nonzero.
To bypass the queue, a switched caller must be given `--unity-direct`. That flag launches through `unitylock` with
a loud `UNITY_QUEUE BYPASS` banner on stderr and produces no queue result.

## Cold or incomplete Library: warm-up first

On 2026-10-05 the unit project's Library was wiped; the next lab job silently reimported the whole project inside its
launch (Library ~100 GB) and filled V: twice. A launch therefore refuses every job on a project whose Library is
cold or incomplete, except the warm-up job:

- **Cold** when `<project>/Library/ArtifactDB` or `SourceAssetDB` is missing, when the wipe marker
  `<project>/.library_wiped` exists, or when the project's most recent `launches/*/unity.log` (matched by the
  `-projectPath` Unity echoes at the top of the log) contains `Rebuilding Library because the asset database could
  not be found` or `Failed to write the asset file` and lacks `Application.AssetDatabase Initial Refresh End`.
- **Whoever wipes a Library must create `<project>/.library_wiped`** (an empty file). A successful warm-up removes it.
- **Warm-up job** (kind `library_warmup`, method sentinel `UnityQueue.LibraryWarmup`, no args): the launch is
  `Unity.exe -batchmode -quit [-nographics] -projectPath P` with no `-executeMethod`. It is `ok` only when Unity exits
  0 and the log has the completed-refresh line. It needs 40 GB free (`UNITY_QUEUE_WARMUP_MIN_FREE_GB`, read by the
  draining process) and has a 6 h job timeout. In a drain, warm-up groups launch before the other jobs on the
  project, so jobs queued behind a warm-up run once it succeeds.

```
python tools/unity_queue/unity_queue.py library-check --project P   # dry: prints the reason, exit 1 when cold
python tools/unity_queue/unity_queue.py warmup --project P --wait   # queue (and drain) the warm-up
```

`--unity-direct` launches get the same cold-Library refusal.

## Making a builder queue-compatible

A Unity method runs under the dispatcher only if its class has the shim below. The dispatcher refuses a class that
lacks it: such a class would read the dispatcher's own command line, or would quit the whole batch with
`EditorApplication.Exit`.

```csharp
static string[] UnityQueueArgs() => AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") as string[] ?? Environment.GetCommandLineArgs();
static void UnityQueueExit(int code)
{
    if (AppDomain.CurrentDomain.GetData("UnityQueue.JobArgs") == null) { EditorApplication.Exit(code); return; }
    if (!(AppDomain.CurrentDomain.GetData("UnityQueue.ExitCode") is int prev && prev != 0)) AppDomain.CurrentDomain.SetData("UnityQueue.ExitCode", code);
}
```

Then replace `Environment.GetCommandLineArgs()` with `UnityQueueArgs()`, and `EditorApplication.Exit(c)` with
`UnityQueueExit(c)`. `python tools/unity_queue/apply_shim.py <file.cs> <ClassName> ...` does both edits, keeping
the file's BOM, line endings and indentation. Under the dispatcher, `UnityQueueExit` records the code and *returns*, so it must be the last
statement on its path, as it is in every current builder. A direct launch behaves exactly as before. The shim has
no compile dependency on the dispatcher.

Rules for a job:
- Stage the editor scripts the job needs *before* submitting. The editor compiles once, at launch, so a script a job
  copies in mid-batch is not compiled for that batch.
- Do not rely on static state left by a previous job in the same editor.

Queue-compatible today: every class in `BUILDERS` of `tools/validate_unity_queue_contract.py`. That is the town
`Homm3TownScene3dBundleBuild` (`Run`, `Verify`, `RenderStates`) and `Homm3ConfluxTown3dPreview`; the unit
`BuildCustomUnitBundles`, `Homm3OwnedSkinnedLabBuild`, `ProbeDefRetargetDeliveryBundles`,
`ProbeDisplacementMaskBundles`, `Homm3OwnedSkinnedAttackSlotRemap`, `Homm3FacingProofRig`,
`Homm3BattleSoundPrefabsBuild` and `Homm3BillboardAnimatorBuild`; the `homm3_import` bundle builders (shade shader,
artifact map billboard, artifact meshes, map billboard, dialog portrait, map building meshes, tower city map mesh, UI
portrait, town scene meshes); the previews `UnitVfxPreview`, `BeholderAttackContourV14`,
`Homm3MapBuildingAnimPreview`; and the VFX labs `Homm3VfxLabBuild`, `Homm3VfxLightLab`, `Homm3VolumetricFireLab`,
`Homm3OceanidWaterLab`, `Homm3OceanidLookLab`, `Homm3VanillaStyleVfxLab`.

## Switched callers

| caller | launch helper | kind |
| --- | --- | --- |
| `tools/homm3_town_scene_meshes/stronghold_full3d_scene.py` (all full-3D towns via `--faction` / `TOWN_FULL3D_*`; the castle/rampart/... t2 scripts call it) | `unity()` | `town_full3d` |
| `tools/homm3_town_scene_meshes/build_conflux_full3d_scene.py` | `unity()` | `town_conflux_full3d` |
| `tools/homm3_town_scene_meshes/build_town_scene3d_bundle.py` | `unity_job()` | `town_scene3d_conflux` |
| `tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py` (lab, bundles, probe, displacement probe) | `unity()` | `def_retarget_ship` |

| `tools/homm3_import/remap_owned_attack_slots.py` (remap, bundles, probe) | `unity()` | `attack_slot_remap` |
| the nine `tools/homm3_import/build_homm*_bundle.py` builders (these used to launch Unity with no lock at all) | `UQ.run_cmd()` | one kind per builder, e.g. `map_billboard_bundle` |
| `tools/homm3_import/owned_skinned_facing_proof.py` | `UQ.run_cmd()` | `owned_skinned_facing_proof` |
| `tools/homm3_import/preview_unit_vfx.py`, `run_beholder_attack_contour_v14.py` | `_unity_queue().run_cmd()` | `unit_vfx_preview`, `beholder_attack_contour_v14` |
| `tools/homm3_import/build_homm3_units.sh` (battle sound prefabs, billboard animator, unit bundles) | `unity_queue.py submit --wait` | `homm3_battle_sound_prefabs`, `homm3_billboard_animator`, `homm3_unit_bundles` |
| `tools/homm3_vfx/` `build_vfx_lab.py`, `titan_light_lab.py`, `volfire_unity_lab.py`, `oceanid_unity_lab.py`, `vanilla_style_lab.py` | `UQ.run_cmd()` | `vfx_*` |
| `tools/homm3_map_building_meshes/preview_map_building_anim.py`, `preview_map_building_fx.py` | `UQ.run_cmd()` | `map_building_anim_preview`, `map_building_fx_preview` |
| `tools/homm3_town_scene_meshes/build_conflux_town3d_preview.py` | `UQ.run_cmd()` | `conflux_town3d_preview` |
| `tools/homm3_silhouette_pose_fit/run_stronghold_prebaked_install_overnight.py` (its Unity.exe stages) | `unity_step()` -> `uq.run_cmd()` | `stronghold_prebaked_install` |

Each of these takes `--unity-direct` as its explicit opt-out. The audio stager `stage_homm3_unit_audio.py` does not
launch Unity; `build_homm3_units.sh` launches the sound-prefab build after it.

Not switched, by design: `tools/homm3_vfx/vanilla_recipes_all.py` holds the `unitylock` lock around a Python
recipe extractor as a file mutex and launches no Unity. Not switched, listed in `LEGACY_UNSWITCHED` with a reason: the
2026-07 `.cmd` / `.ps1` Lane B and town-prefab drivers, the esquire pilot, and two untracked work-in-progress beholder
scripts of another agent. The validator scans `tools/` for any other script that builds a `-batchmode` command line
and fails the build on one it does not know, so a new direct launcher must be switched (or, with a reason, listed).

## Measured

All runs were on 2026-10-01. Records are in `V:/olden_port_work/unity_queue_test/*_summary.json` and
`V:/olden_port_work/unity_queue/launches/*/launch.json`. Wall times are for the Unity launch only.

| project | jobs | one batched launch | two separate launches | saved |
| --- | --- | --- | --- | --- |
| Dungeon `t2_v1` town project (dedicated, built-in modules only) | 2 x `Homm3TownScene3dBundleBuild.Run`, about 55 s of work each | 123.2 s (warm) | 62.3 + 58.1 = 120.4 s | none measurable: noise exceeds the startup cost of about 5-8 s per launch |
| `oldenera_factions` unit project | 2 x `ProbeDefRetargetDeliveryBundles.Run` (h3_troll), about 0.1 s each | 19.6 s | about 18-20 s each (17.6, 20.0 and 20.3 s seen) | about 18-20 s per job folded in, about 48% here |

What this shows:
- **The saving is the editor startup**, paid once per launch instead of once per job. On the big unit project that
  is about 18-20 s per extra job. On a dedicated town project it is only a few seconds, so batching town builds
  saves almost nothing. There the queue's value is serialisation, dedupe and the result files, not wall time.
- The first launch after a builder source changes also pays a script recompile, 68.5 s on the unit project and
  148.5 s for the cold town batch. A batch pays that once instead of once per job.
- The table does not count the time the old `unitylock` path spent polling for a free lock (20-30 s sleeps).
- An identical third submit was deduped onto the first job (`submit` returned that job's id).
- Fail closed: one launch held three jobs, in this order: a broken spec (`UnityQueueExit(1)`), a shim-less method
  (refused as "not queue-compatible"), and a good build. The first two failed with their reasons, and the good build
  still produced its bundle.
- Town bundles are not byte-identical between rebuilds, whether batched or separate (sizes and CRCs differ, the
  `build_report.txt` files are identical). Compare bundle content through the build report or a readback, not the
  sha.

## Proof

Source/static validated (`tools/validate_unity_queue_contract.py`). The live two-job batch, the separate-launch
comparison and the dedupe of an identical third submit ran as recorded under `V:/olden_port_work/unity_queue_test/`.
These are editor batch runs that produced generated artifacts only. Nothing was installed. Changing the shimmed
builder sources also changes `ship_def_retarget_slice` input hashes, so a frozen slice reruns `prepare` before its
next `lab`. The validator runs in the plugin build's full tier (`-p:FullValidation=true`).

Unit lane end to end (2026-10-01): `ship_def_retarget_slice.py prepare` then `lab` on
`castle_griffin_slice_v1.json` went through the queue as job `20261001T150935_def_retarget_ship_9270d7eebd_73ce`.
It waited about 7 minutes behind another agent's queued bundle build on the same project (no second editor), then
ran in launch `20261001T151630_22936_a881` (36.9 s wall, 19.2 s of job work) and the stage completed. Other agents'
`cove_slice_v1` and `dungeon_slice_v1` lab jobs ran through the queue the same afternoon. Generated artifacts only;
no bundles, probe or deploy were run for the griffin.
