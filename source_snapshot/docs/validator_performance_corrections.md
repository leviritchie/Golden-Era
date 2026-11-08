# Validator performance corrections

Operational contract for validation reuse, local scope and resource reservations.
Source/fixture, sampled CPU/CUDA parity, existing-artifact and isolated build-target
checks passed on 2026-10-02 (workspace local date). No new payload was deployed.
The earlier baseline is
recorded in `docs/validator_performance_audit_20261002.md`; its measurements are
historical evidence, not performance acceptance for later revisions.

## Integrity boundaries

- A town validation invocation verifies the native camera provenance once, then
  checks every catalog against that verified snapshot. Bundles still receive full
  content hashes, read in bounded chunks. No persistent or timestamp trust cache.
- Phase-6 pan coverage defaults to CUDA; `--device cpu` is the explicit reference.
  The fused kernel retains all three aspects, 8192-ray batches, the 4000-step cap,
  the full 16:9 sensitivity negative and its original threshold. There is no
  GPU-error-to-CPU recovery. Invalid scalar/array/ray metadata fails before either
  backend; each catalog uploads its static maps once under a shared reservation.
- A map preflight invocation owns one Core archive/member index and one parsed
  snapshot per unique map path, evicted after its last use. Every signature still runs. Parser failures and
  malformed chunks retain their signature-specific diagnostics; quest counters
  remain independent of the map-data chunk.
- Manifest validation parses the same generator source once. Source and installed
  bundle evidence remain separate, with complete streamed content hashes.
- Delivery validation accepts explicit, exact `--selection NAME.json` values for
  local work. Unknown names or paths fail. Omitting the option retains the strict
  all-selection default; the full-build target never supplies a selection filter.
- GLB patch validation already supports `--unit`; use it for local changes. Its
  default all-unit gate remains intact. The pre-existing royal-griffin stamp
  mismatch is outside this correction.

## Resources

Capacity waits happen before GPU/Unity execution reservations. After acquisition,
an immediate recheck either permits work or releases reservations before any
further wait. These corrections retain the existing RAM/VRAM requirements and safety margins.
A request exceeding physical capacity fails promptly with a diagnostic. A failed
process or memory probe is unknown capacity, never an empty or idle machine.

The existing quick-tier game-running guard uses `launch_guard.py --game-only`
instead of an ignored `tasklist | findstr` exit code. This reuses the strict
process query and refuses unknown state; it performs no GPU/memory/disk work.
No contract sweep was added to the quick tier.

GPU lock contention uses bounded backoff rather than a five-second inventory
query loop. Unity orphan recovery probes each unique claimant PID once per scan
and is rate-limited on the waiter path. Tests use mocked capacity/probes and
isolated locks; they do not establish real workload peaks or runtime scheduling.

Ownership mutations share a nonblocking OS advisory guard. Stale-owner cleanup
rechecks ownership under that guard; release must not remove a successor's lock.
Known contention remains retryable, but an unexpected probe or guard error is a
diagnostic refusal. Existing raise-on-busy cascade callers remain fail-closed.
Native PID probes distinguish OpenProcess access denial (retain the owner) from
a nonexistent PID. Every failed exit-code query refuses without treating the
owner as dead; unexpected API errors no longer become hours of ordinary busy
waiting. A confirmed live process with unavailable creation time remains live,
never stale. Queue orphan inspection finishes its probes before moving any job.
These failure branches are fixture-proven, not reproduced live Win32 failures.

## Build budgets

Every validator/audit process in the plugin project, including embedded payload
readbacks, has a finite MSBuild timeout. Existing 30/60-second limits are retained.
The general ceiling is five minutes; the two existing GPU-heavy contracts
(`ValidateHomm3CsBakeContract` and `ValidateTownZeroStreakContract`) have a separate
35-minute ceiling. These are conservative refusal limits, not measured runtimes
or permission to wait while holding another execution resource. They do not skip
checks or turn failures into success.

On this host's modern .NET MSBuild, timeout handling requests termination of the
tool's process tree. This is best-effort cleanup, not proof that detached,
inaccessible or racing descendants are gone; termination can also add a short
grace period. No custom cancellation subsystem was added. See the
[MSBuild process implementation](https://source.dot.net/Microsoft.Build.Framework/Utilities/ProcessExtensions.cs.html).

The GPU exceptions preserve existing full-tier behavior: CS bake runs its CPU
reference/rekey tests and CUDA parity; town zero-streak runs staged GPU parity and
recipe verification. Their total workload peaks and incremental execution are
not established by this tooling-only correction. A timeout is an explicit failed
validation, not a certificate. They must be measured separately before claiming
whole-full-tier performance acceptance.

The 35-minute town ceiling deliberately stops sooner than the sum of all child
limits (the current 35 recipes plus staged parity could theoretically consume
10.25 hours). It does not establish that every full-tier run will finish within
the ceiling. No staged checks were silently moved out of the full tier to obtain
a passing measurement.

`tools/validate_validator_performance_contract.py` is one full-tier gate for the
lightweight synthetic regressions and XML budgets. It has a 90-second internal
suite budget and a two-minute MSBuild timeout. It does not run installed-art,
Unity, Blender, or GPU parity jobs. CPU use here is source parsing, hashing, I/O
and mocked scheduling, not a substitute for GPU-domain computation.
The contract rejects conditional or ignored executions of its own suite, strict
delivery and game refusal. It pins the game refusal to at most 30 seconds and its
own MSBuild budget to at most two minutes. Fixture scratch is anchored to the
helper's repository on V, with foreign callers and unsafe cleanup refused.

The existing full-tier `ValidateTownScene3dContract` target additionally runs the
complete synthetic CUDA boundary-parity suite first, with a 60-second timeout,
then the all-catalog validator. Both fail the build on error. Sampled staged
parity remains an explicit diagnostic (`test_town_gpu_pan.py --staged-parity`),
not a replacement for production's full ray set. No new contract sweep or CUDA
parity job was added to the quick tier.

The pan backend is a fused Numba CUDA kernel from the installed toolchain. The
existing continuous-field torch terrain kernel has different hit semantics and
cannot replace this discrete coverage check. Reusing its general GPU approach,
not substituting its intersection rules, preserves acceptance. Ray math and dome
classification stay on GPU; CPU is used only for the explicit parity reference,
source/control work and I/O. Reservation covers compute/upload, not bundle I/O.

## Verification

| Check | Before | After | Evidence |
| --- | --- | --- | --- |
| Full map preflight, 87 maps / 17 signatures | 15.56-16.61 s | 2.239-2.240 s | `io_measurements.json` |
| Core-only preflight | 0.684-0.690 s | 0.594-0.597 s | `io_measurements.json` |
| Source manifests | 2.59-2.71 s | 1.408-1.409 s | `io_measurements.json` |
| Installed manifests | 8.02-10.62 s | 7.11-7.92 s | `io_measurements.json` |
| Factory town, full coverage | 33.56 s | 10.36 s | `town_cuda_measurements.json` |
| All 12 towns, full coverage | CPU exceeded 180 s after I/O reuse | CUDA 33.56 s | `town_full_measurements.json`, `town_cuda_measurements.json` |
| Strict delivery, all 37 selections | Earlier normal sample exceeded 30 s | 57.19 s, all pass | `io_measurements.json` |
| Explicit local Griffin selection | Previously forced all-selection sweep | 0.737 s, global checks retained | `io_measurements.json` |
| Full-only performance target, 12 fixture modules | New gate | 9.738 s including MSBuild | `msbuild_performance_postreview_measurements.json` |
| Full-only town target, CUDA parity + all catalogs | New parity plus owning gate | 45.74 s including MSBuild | `msbuild_scene_measurements.json` |

Evidence lives under `artifacts/validator_performance_fixes_20261002/`, with raw
logs. Sequential fresh processes were used, without a cold-cache reset. These
are observations on this host, not a controlled cold-I/O or cold-JIT benchmark.
Only the top-level measured source is hashed before/after by the harness;
transitive code and all assets are not atomically snapshotted. The full delivery
walk remains costly: no same-workload full-sweep speedup is claimed.

Resource measurements: map root OS peak working set fell from about 90 MiB to
72 MiB. Source/installed manifests remained about 128 MiB. Factory root peak fell
from 840 MiB to 686 MiB; all-town CUDA root peak was 692 MiB, with sampled process
tree RSS up to 770 MiB. The final isolated performance target sampled 321 MiB tree RSS;
the town target, including MSBuild/child processes, sampled 933 MiB. RSS is not
host commit. The all-town run observed up to 4143 MiB device-global GPU use; the
owning town target observed 4151 MiB of 16303 MiB total. GPU samples are about two
seconds apart, include desktop/other contexts, and can miss transient peaks;
they are not per-process/context peaks. Known pan device buffers were at most
5.12 MiB in sampled staged parity, excluding driver/JIT/context memory. Pan
admission requests 1 GiB plus the unchanged 2.5 GiB margin and passed on this host.

Exact CPU/CUDA masks matched the synthetic boundary cases and 6144 sampled
classifications across all 12 staged towns. The owning production run then
validated all 15.84 million positive/negative ray classifications, full bundle
hashes and native camera provenance. Independent reviews resolved metadata,
projection, negative-step, lifetime, timeout and build-scope findings. These
prove the validator/artifact checks, not native in-game rendering or gameplay.

No game deploy, Unity rebuild or Blender job occurred. Isolated owning MSBuild
targets passed with deployment disabled; the new target was skipped when
`FullValidationNormalized=false`. This is target wiring proof, not a complete
plugin build or whole-full-tier acceptance. Read-only installed map/manifest
checks concern the existing payload, not a new delivery.
The final lightweight target was rerun after the PID-probe and build-condition
review fixes. The full-ray town measurements preceded those probe-only changes;
ray math was unchanged, so that expensive ray set was not repeated. The final
gate includes the focused lock/probe regressions. Default-tier skip evidence is
retained in `msbuild_default_skip.json`; the large diagnostic raw log stays local.

Remaining owning-gate debt: `validate_unity_queue_contract.py` still refuses the
unrelated ignored Fortress/Inferno preview builders outside the queue. Its
scanner was not relaxed. The GPU-heavy CS-bake/zero-streak full suites were not
run or profiled; the pre-existing GLB stamp mismatch remains outside this lane.
Windows fixture ACL failures in the restricted harness were separated from
assertion failures; final host runs used normal permissions and `TEMP`/`TMP` on V.

Commits: `39e504964b` (map/manifest reuse), `482742e03e` (resource ownership/probes).
The pre-existing untracked mocap script stays untracked; its only working-tree
change delegates to the tracked bounded wait helper. Retained narrow replay
patch and before/after hashes: `mocap_baseline_resource_lock.patch` and its JSON.

## Coordination

Shared-board project: `22d0d675357a48a4a0ac17529c4de3ef`. The implementation
scopes are claimed by the current Codex session for its delegated team. The scope
was posted to Claude's mailbox and existing town-install board. No acknowledgement
had arrived at implementation start; no existing or frozen task was taken over.
Reviewed milestones are pinned to versioned board handoffs. Final town/build
evidence and remaining risks are handed back on the same board. Claude's
concurrent committed TownBench and SD-fill changes were preserved unchanged;
posting a mailbox message is not evidence of a Claude acknowledgement.
