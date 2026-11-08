# Claude Rollout Process Handoff (2026-09-27)

This is a time-bound, read-only takeover audit, not a live queue contract. Recheck process identity immediately before any stop or restart. No processes were stopped, builds run, or queue files changed during this audit.

## Current process state

- Windows last booted at 17:03:54 Central on 2026-09-27. The previously reported Worker B PIDs `53304`, `33112`, `43308`, `49296`, `17460`, and `66876` were from about 16:58, before that boot, and none existed at the 18:07 process check. Never reuse those PIDs as stop targets.
- The 18:07 `Win32_Process` command-line check found no `bash`, `blender`, Unity, `HeroesOldenEra`, `ffmpeg`, `run_unit.sh`, `fleet_rebuild.py`, or Worker B queue process. The only Python pair was `blender-mcp` (PIDs `21668` and `22456`, created 18:06:06, parent chain through `blender-mcp.exe` PID `25352`). It is a Codex helper, not the old Worker B queue.
- GPU at 18:07: RTX 5070 Ti, 1,235 MiB of 16,303 MiB used, 0% utilization; no Python/Blender compute process listed. The legacy pose-lane `artifacts/pose_picker_runs/gpu_cascade_global.lock` and `F:/claude_scratch/workerB/PAUSE` were absent. Neither provides queue exclusivity for the DEF retarget rollout.

**Scoped stop recommendation:** none at this snapshot. There is no verified Worker B process to stop. If a queue appears later, identify its current PID, creation time, full command line, and parent/child tree; stop only that verified queue tree, not a recycled PID or Codex MCP helper.

## Interrupted queues and storage

- Worker B's scratch queue scripts are `F:/claude_scratch/workerB/guarded2.sh` and `finish2.sh`; later ad hoc scripts include `L6.sh`. Their helper and logs also live under `F:/claude_scratch/workerB`. They change directory to `/v/games/Olden Era Playtest Tweak`, and `tools/homm3_def_retarget/run_unit.sh` already writes model artifacts under V:. The F: dependency is principally orchestration, helper, and log I/O.
- `F:/claude_scratch/workerB/logs/X1.guard.log` says `X1 done` near 17:02, but concurrent writes garble several lines. `X2.guard.log` ends during rebuilds with Bash fork/resource errors at about 17:02-17:03. `X1.log` also contains fork errors; `X2.log` records a failed fresh-stamp delivery. A crimson couatl run reported `Device or resource busy` on its V: weights file. Do not infer per-unit completion from queue exit or an old output file; audit the unit artifacts and stamps before resuming.
- At the 18:07 audit, `guarded2.sh` checked game state, V: free space, and `memgate.py` before each unit, but had no single-writer lock and continued to later units after a nonzero unit return. At that time `memgate.py` treated `nvidia-smi` failure as 99 GB free VRAM. Those old F: scripts remain historical scratch, not a safe resume path.
- F: is disk 1 `ST1000LM014-1EJ164` (SATA) with 146.1 GB free. V: is disk 2 `CT1000T500SSD8` (NVMe) with 152.5 GB free at 18:07. Move the active small orchestration/helper/log path to V:, leave F: historical scratch untouched, and resume with one explicit writer after inspecting partial outputs. Do not relaunch X1 and X2 in parallel.

## Later source update

The V: source now has `unit_writer.py` (supervisor and assigned child hold separate bytes of one per-unit OS lock; the Job Object kills and drains descendants before normal release) and `launch_guard.py` (game, disk, native RAM, explicit GPU probe, then game recheck). `memgate.py` no longer uses WMI or the 99 GB VRAM fallback. The existing `run_unit.sh`, `fleet_rebuild.py`, emphasis `deliver.py`, and unit-look `gpuslot.py` call the shared guard before Blender launches. Focused tests include a live grandchild terminated on supervisor loss and same-unit lock refusal; this is source/test proof, not a resumed model-build result. At 18:24 the guard correctly refused because the active Golden Era game was running; no Blender job was launched by this update.

## Blender startup blocker (18:50 update)

The isolated ogre build did not reach model code: `V:/Tools/blender-mcp/blender-5.2.2/blender.exe --version` itself exited `3221226505` with `Failed to replace function free in module ucrtbase.dll`. This happened both directly and under the unit writer, including an elevated direct probe. The Blender binary signature is valid and the original ZIP matches its pinned SHA-256. The error text comes from the bundled Intel oneTBB `tbbmalloc_proxy.dll` allocator replacement path, which [aborts rather than leaving a partial replacement](https://github.com/uxlfoundation/oneTBB/blob/v2022.3.0/src/tbbmalloc_proxy/proxy.cpp).

After a fresh launch guard pass, one diagnostic child process with `TBB_MALLOC_DISABLE_REPLACEMENT=1` (set only in that child's environment) returned `Blender 5.2.2 LTS` with exit 0 and empty stderr. A second, short background Blender process under the same child-only setting exited 0; its loaded modules included `C:/Windows/System32/ucrtbase.dll` and Blender's `blender.shared/tbbmalloc_proxy.dll`, `tbbmalloc.dll`, and `tbb12.dll`. That diagnostic process did **not** load the older `ucrtbase.dll` present beside Blender, so that file's version mismatch is not an established cause. The switch identifies the failing startup path; it has not been adopted in the pipeline, and no model build or delivery was retried. The precise reason the allocator patch fails is still unproven. Do not replace DLLs, install runtimes, or set machine-wide environment variables on this evidence. The user is choosing between an explicit per-process allocator setting and further conflict investigation.
