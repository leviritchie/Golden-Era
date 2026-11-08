# Validator And Check Performance Audit

Date: 2026-10-02 (America/Chicago). Classification: point-in-time audit, not an operational contract or an optimization delivery.

**Status:** Source-pinned audit plus bounded execution/profiling of selected checks. No production validator, gate, quality threshold, plugin, bundle or installed file was changed. No full build/deploy, Unity/Blender job or GPU workload was run. Proposed fixes below are **not implemented or performance-proven**.

## Findings In Priority Order

### P1: Resource Waits Hold Shared Capacity, Including A Two-Hour Town Wait

`tools/homm3_town_scene_meshes/town_full3d_gpu.py:124-145` takes a machine GPU slot, then the town GPU lock, then waits for RAM/VRAM for up to 120 minutes. This holds two shared resources while no GPU work is happening. `town_full3d_sdfill.py:51` requests 11 GiB and the gate adds 2.5 GiB. The read-only device snapshot reported 13,526 MiB free (13.209 GiB), below the 13.5 GiB requirement, with 2,470 MiB used on a 16,303 MiB device. The gate cannot pass at that sampled baseline. Headroom can change; this is not a claim that it can never pass on this hardware.

The Unity queue has the same ordering on a shorter scale: `tools/unity_queue/unity_queue.py:469-489` holds the editor lock while `:352-358` invokes `memgate --wait 6`. The older wrapper repeats it in `tools/homm3_vfx/unitylock.py:41-56,66-73`. A low-memory preflight can therefore block unrelated Unity jobs for about six minutes without launching the editor.

Recommended correction: wait for capacity before acquiring shared execution resources, acquire in a consistent order, then perform an immediate resource recheck. If capacity was lost, release and defer/refuse with a diagnostic. Measure the actual workload peak and reconcile the town requirement with available headroom; do not silently reduce the safety margin or quality requirements. Detect clearly infeasible requests without entering a long lock-holding wait. No gate was invoked to reproduce a two-hour stall.

### P1: Town Validation Repeats The Same Native Extraction For Every Catalog

`tools/validate_town_scene3d_contract.py:359-390` hashes native `level67` and `resources.assets`, then re-extracts the same `cityHuman2` camera through UnityPy. `:1747` calls this for each rest-pose catalog. The audit found 12 staged rest-schema catalogs and a 1,076,920,512-byte `resources.assets`: about 12.9 GB of repeated resource-file hashing alone, before repeated extraction and bundle checks.

A single-faction check (`--only homm3_factory`) passed in **33.56 s**, reaching **839.97 MiB OS-reported process peak working set**. The default all-town check was still running at the **60.13 s audit cap**, with **904.64 MiB sampled peak RSS**. The initial sandbox runs failed during a small tempfile fixture before reaching this work; their subsecond durations are not performance results for the town checks. A normal-permissions rerun with scratch on V: produced these measurements.

Recommended correction: verify native provenance and extract the camera once per validator process, then compare every catalog to that single verified snapshot. `:1758-1760` also hashes bundles using `read_bytes()`: stream those hashes to avoid whole-bundle allocations. Keep every catalog comparison and integrity check. A future implementation should demonstrate mutation rejection, unchanged verdicts and the new time/memory profile; no speedup is claimed here.

### P2: Full Map Preflight Reopens Core.zip And Re-parses Each Map

Full installed-map preflight passed twice in **15.56-16.61 s**, versus **0.68-0.69 s** for `--core-only`. Its profiled run passed in 27.66 s, with **120 ZIP openings**, **87 mission loads**, and **783 map-container parses** for 87 maps. ZIP directory loading consumed 19.56 s cumulative in that profiled run; map parsing consumed 5.26 s. Profiling adds overhead, so these are attribution evidence, not ordinary elapsed-time estimates.

`tools/validate_map_load_preflight_contract.py:90-94,109-114` opens and indexes Core.zip separately for each mission. `tools/map_load_preflight.py:1453-1488` invokes independent signature checks that repeatedly call the gzip/JSON parser in `experiments/campaign_port_poc/port_homecoming_poc.py:458-477`. The garrison checks also reopen Core at `tools/map_load_preflight.py:1129-1130`. ZIP indexing is the larger observed cost; reducing map parses alone would leave it behind.

Recommended correction: one invocation-owned Core reader/member index, plus one parsed container/map-data snapshot per installed map. Pass these snapshots into signature checks and retain signature-specific malformed-input diagnostics. This avoids persistent-cache invalidation risks. Compare the full issue set, including missing/corrupt Core and maps, before measuring the improvement.

The csproj's map-preflight gate (`OfflineUnlockMod.csproj:354`) uses `--core-only`; the full 87-map cost is a standalone/full readiness check, not an ordinary quick-plugin-build cost. Its frequency was not measured, which is why this finding is P2 rather than a release-blocking P1.

### P2: Delivery Integrity Work Is Fleet-Wide Even For A Small Iteration

The def-retarget delivery check exceeded the first 30 s cap, then **passed in 36.30 s under profiling**. The profile shows **37 selections**, **1,370 SHA calls**, and **31.23 s in its hashing helper**. `tools/validate_homm3_def_retarget_delivery_contract.py:425-436` enumerates every selection; `:306-313` hashes each selection's frozen files. Source inspection of 1,335 frozen-input/plan references found no duplicate paths, so memoizing path hashes is not the main solution here.

The GLB patch contract took **22.70 s** to check **272 configs / 4 patched GLBs**. `tools/validate_homm3_glb_patch_contract.py:92-133` also checks every retained base; `tools/homm3_glb_patch/base.py:88-108` hashes its original Blender file and retained artifacts. The command correctly returned an existing `h3_royal_griffin` patch-config/stamp mismatch. That failure is not fixed or classified as a performance regression by this audit.

Recommended correction: use the existing GLB `--unit` scope for touched-unit iterations, and add an explicit selection scope to delivery validation. Keep full unfiltered content-hash checks for releases and explicit fleet acceptance. A scoped pass must identify its scope and must not be reported as whole-fleet acceptance. Do not replace content integrity with mtime/size-only trust.

### P2: Installed Manifest Checks Spend Most Time On Bundles And Repeated Generator Parsing

Source-only manifest validation passed in **2.59-2.71 s**; installed plugin validation passed in **8.02-10.62 s**. The installed profile attributes **6.61 s to two bundle-validation calls**, **3.55 s to 281 `read_bytes` calls**, and **2.63 s to SHA-256**. `tools/validate_custom_faction_manifests.py:1628` materializes entire bundles for hashing.

Another **2.26 s** goes to three AST parses from `load_python_literal_constant` (`:668-689`) through `validate_fortress_core_generator_toa_overlay` (`:691`). The same generator source is parsed to retrieve separate constants. `main` (`:4414-4421`) and `validate_plugin_payload` (`:1896` onward) each invoke bundle validation for source and installed payloads; those two roots need independent integrity evidence and must not be merged blindly.

Recommended correction: parse each generator once per process and stream bundle hashes. For scoped installs, preserve the existing bundle-prefix mechanism and prove which non-bundle checks remain global. Reuse a hash only when the same canonical file is actually being checked within a stable invocation snapshot, not because source/installed filenames match.

### P2: Most Full-Tier Execs Lack A Wall-Clock Bound

The csproj has **153 Validate/Audit targets**, of which **117 are FullValidation-conditioned**, containing **120 Exec tasks** (110 pre-build and 10 post-deploy). **116 of those 120 have no Exec Timeout**. Two more FullValidation-conditioned readbacks sit inside the deploy target. Across all Validate/Audit targets, 150 of 154 Exec tasks lack Timeout. Inventory records exact conditions and commands.

This does not mean the quick tier runs all those checks: it does not. It means a hung subprocess or filesystem scan can leave full validation without a build-level ceiling. Internal timeouts in some Python scripts help only those specific children, not every target. The measured all-town timeout and earlier delivery timeout were audit-imposed limits, not existing build limits.

Recommended correction: set per-target bounds informed by measured normal cost, with explicit slower audit tiers where needed. Record the failed command and owning scope. Avoid a blanket 30 s limit: the valid single-town check already took 33.56 s, and many checks need optimization before aggressive budgets are reasonable. Do not add another always-on meta-validator just to enforce this report.

### P2: GPU Waiters Probe Too Often And A Probe Failure Can Look Empty

`experiments/homm3_mocap_v2/run_mocap_baseline.py:41-71` can retry lock acquisition every five seconds for 30 minutes. Each retry can run a PowerShell/CIM process inventory through `tools/homm3_silhouette_pose_fit/gpu_cascade_batch_lock.py:85-109,139-153`: up to 360 subprocess probes for one blocked waiter. That inventory ignores the subprocess return code and parses stdout as a process list. The audit environment returned `Access denied` from CIM; that is not evidence of an empty machine.

The atomic global lock still protects cooperating callers. The fail-open risk concerns detection of legacy/uncooperative processes, not a claim that all lock serialization is broken. Recommended correction: preserve unknown/error as a diagnostic refusal, and use owner-aware waits or bounded backoff rather than repeated full inventories. The baseline runner's preparation-before-lock and release-after-inference scope (`:233-265`) is a positive control and should remain narrow.

### P3: Each Unity Submitter Repeats The Same Orphan Probes

`tools/unity_queue/unity_queue.py:185-203,291-304` lets every waiter scan all running job records every five seconds. Each record probes its PID through a separate `tasklist` subprocess (`tools/homm3_vfx/unitylock.py:20-22`), even when a batch's records share the same runner PID. Concurrent submitters multiply this work.

Recommended correction: deduplicate by PID within a scan and rate-limit orphan recovery or make it runner-owned. The inexpensive job-state file check can remain separate. No live-queue overhead was measured because this audit did not submit jobs.

## Measurements And Coverage

Inventory: 187 top-level `tools/{validate,audit,check}*.py` scripts; 155 selected gate definitions including Emit/Refuse; complete source/XML inventory, not complete execution or deep review of every nested test.

Execution: **40 attempts across three sequential suites, 305.06 s total**. Each command had a 30 s or 60 s cap; the audit terminated only its own timed-out processes. Initial argparse mistakes for binary-only and mocap delivery are retained in logs, excluded from cost conclusions; binary-only was rerun with the required project argument and passed. No mocap rollout was selected or accepted.

| Check / Mode | Ordinary Elapsed | Outcome / Memory Evidence |
|---|---:|---|
| Town scene3d, factory only | 33.56 s | Passed; OS peak 839.97 MiB |
| Town scene3d, all staged towns | >60 s | Audit timeout; sampled RSS peak 904.64 MiB |
| GLB patch, all units | 22.70 s | Existing config/stamp mismatch; scoped check available |
| Map preflight, 87 maps | 15.56-16.61 s | Passed both runs; sampled RSS 77-78 MiB |
| Installed manifest | 8.02-10.62 s | Passed both runs; sampled RSS 113-114 MiB |
| GameSymbols hints, Golden Era live interop | 3.58-3.69 s | Passed twice; default shape-cache mode |
| Campaign event policy | 3.30 s | Passed; sampled RSS 129.04 MiB |
| Manifest, source only | 2.59-2.71 s | Passed both runs |
| Town zero-streak, static-only | 3.96 s | Passed with normal permissions; staged/GPU tier not run |
| Map preflight, core only | 0.68-0.69 s | Passed both runs |
| Representative narrow source gates | 0.24-0.59 s | Binary-only, ABI, exact-reference bind, adapter/hook checks passed |
| Def-retarget delivery | >30 s unprofiled | Profiled pass 36.30 s; no ordinary complete timing claimed |

Hardware observed: Windows 11, Python 3.12, 12 logical CPUs, 31.77 GiB physical RAM; RTX 5070 Ti device snapshot above. Sampling every 100 ms reports live process-tree RSS and OS process peak working set, not host commit or VRAM peaks. Short-lived children/CPU can be missed. Subsecond timings include Python startup and up to one sampling interval of overhead. Disk/OS caches were not reset and other users' processes were not stopped. Profiles and normal timings are kept separate.

Not measured: whole quick/full builds, the C# live-interop checker, generation/diversity audits, complete GPU/parity/certification suites, Unity editor workloads, or in-game behavior. The quick/full split and scoped town/unit modes are already useful; the historical 13-minute full-build figure in `docs/build_validation_tiers.md` was not revalidated here. No game-performance or optimized-pipeline speedup is claimed.

## Evidence And Reproduction

All evidence is in `artifacts/validator_performance_audit_20261002/`: `inventory.json`, three plans, `measure.py`, `measurements.json`, `profiles.json`, `town_measurements.json`, `resource_snapshot.json`, and cited per-command logs. Source hashes are captured before and after each measured top-level script; none changed during its run. This is not an atomic snapshot of every transitive dependency or installed file. HEAD observed during the audit was `7d4a43e3ed0e2ef6c25cefa752c8efdad63cb66a`; the checkout contained unrelated changes and was preserved.

Evidence-retention correction: the later town suite reused two initial raw-log filenames. The initial records' saved tail excerpts still document their fixture failures; they are explicitly marked `log_capture` and saved verbatim as `initial.*.log`. The later raw captures are under `town_measurements.*.log`; the timed-out all-town run emitted no output. The helper now namespaces logs by suite output, preventing that collision. Timing/status records were not altered, and no missing full log was reconstructed or presented as complete. The independent reviewer also checked this repair.

```powershell
python artifacts/validator_performance_audit_20261002/measure.py inventory
python artifacts/validator_performance_audit_20261002/measure.py bench --plan artifacts/validator_performance_audit_20261002/plan.json --timeout-seconds 30 --suite-seconds 360
python artifacts/validator_performance_audit_20261002/measure.py bench --plan artifacts/validator_performance_audit_20261002/profile_plan.json --output profiles.json --timeout-seconds 60 --suite-seconds 180 --workspace-temp
python artifacts/validator_performance_audit_20261002/measure.py bench --plan artifacts/validator_performance_audit_20261002/town_plan.json --output town_measurements.json --timeout-seconds 60 --suite-seconds 150 --workspace-temp
```

The town suite required normal filesystem permissions because managed-sandbox tempfile ACLs failed before assertions. Do not interpret that setup failure as a validator performance pass. The measurement helper is audit-only, requires the already available `psutil`, and is not wired into any build. CPU handles source parsing, filesystem integrity and process observation; no raster/fitting workload was introduced. Retained evidence is under 1 MB; no large C: scratch or asset copies were created.

## Coordination And Resume Boundary

Workboard project: `e2bdf636792e4f6e8c13e90972ae4801`; audit task: `4b8e5ff98e4c4a65be79317288909e92`. A request and preliminary measurements were sent to the registered Claude coordinator, including its existing install-project channel. No response was received during the audit. Posting a message is not a completed Claude roundtrip. No Claude-owned implementation scope was claimed or edited.

Recommended next implementation order: resource-wait ownership and feasibility diagnostics; town invocation-local provenance reuse; one Core reader and one map parse per map; touched-unit/selection integrity scopes; measured target budgets and lower-frequency process probes. Each should preserve verdicts and diagnostics, run only its focused owning checks, and publish before/after elapsed time and peak memory. This report authorizes no silent weakening of acceptance or resumption of unrelated frozen lanes.

Independent review: completed by a separate read-only reviewer. Source pins, measurement totals, proof boundaries and scope were checked; the map finding was downgraded to P2 because the build uses the cheaper core-only mode, cache wording was qualified, and the direct garrison ZIP-reopen citation was added. The reviewer found no unsupported speedup claim or scope drift in the sampled sections. `validate_documentation_contract.py --repo-root .` passed after the audit draft was written. No production optimization has been applied.
